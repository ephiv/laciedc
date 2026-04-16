import re
import unicodedata
import asyncpg
import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque
from database import db
from utils.embeds import EmbedBuilder
from utils.logger import log_action
from colors import Color


# ── Filter patterns ────────────────────────────────────────────────────── #

PROFANITY: set[str] = {
    "fuck", "shit", "bitch", "cunt", "dick", "piss", "arse",
    "bollocks", "retard", "idiot", "moron", "imbecile",
}

INVITE_RE  = re.compile(r"(discord\.gg|discordapp\.com/invite)/\w+", re.IGNORECASE)
URL_RE     = re.compile(r"https?://\S+", re.IGNORECASE)

# Fix 8 — leet-speak normalisation
_LEET: dict[str, str] = {
    "0": "o", "1": "i", "3": "e", "4": "a",
    "5": "s", "7": "t", "@": "a", "$": "s", "!": "i",
}
_STRIP_RE = re.compile(r"[^a-z0-9@$!]")


class AutoMod(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # (guild_id, user_id) → deque of (content, utc_timestamp)
        self._spam_cache: dict[tuple[int, int], deque] = defaultdict(
            lambda: deque(maxlen=20)
        )

    async def cog_load(self):
        # Fix 9 — start pruning task after the cog is loaded into a running bot
        self._prune_spam_cache.start()

    def cog_unload(self):
        # Cancel the task cleanly on hot-reload so it doesn't linger
        self._prune_spam_cache.cancel()

    # ── Fix 9 — prune stale spam-cache dict entries every 10 minutes ──── #

    @tasks.loop(minutes=10)
    async def _prune_spam_cache(self):
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=30)
        stale  = [
            k for k, dq in self._spam_cache.items()
            if not dq or dq[-1][1] < cutoff
        ]
        for k in stale:
            del self._spam_cache[k]

    # ── Checks ────────────────────────────────────────────────────────── #

    # Fix 8 — normalise before matching so "f4ck", "f.u.c.k", "ſhit" are caught
    def _normalise(self, text: str) -> str:
        text = unicodedata.normalize("NFKD", text)
        text = text.encode("ascii", errors="ignore").decode()
        text = text.lower()
        text = _STRIP_RE.sub("", text)
        return "".join(_LEET.get(c, c) for c in text)

    def _is_profanity(self, text: str) -> bool:
        normalised = self._normalise(text)
        if any(word in normalised for word in PROFANITY):
            return True
        return any(w in PROFANITY for w in text.lower().split())

    def _is_excessive_caps(self, text: str, threshold: int) -> bool:
        letters = [c for c in text if c.isalpha()]
        if len(letters) < 10:
            return False
        ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        return ratio * 100 >= threshold

    def _is_spam(self, guild_id: int, user_id: int, content: str, threshold: int) -> bool:
        now   = datetime.now(timezone.utc)
        cache = self._spam_cache[(guild_id, user_id)]
        cache.append((content, now))
        cutoff = now - timedelta(seconds=5)
        return sum(1 for msg, ts in cache if ts >= cutoff and msg == content) >= threshold

    def _has_invite(self, text: str) -> bool:
        return bool(INVITE_RE.search(text))

    def _has_external_link(self, text: str) -> bool:
        return bool(URL_RE.search(text))

    def _has_excessive_mentions(self, message: discord.Message, threshold: int) -> bool:
        count = (
            len(message.mentions)
            + len(message.role_mentions)
            + message.content.count("@everyone")
            + message.content.count("@here")
        )
        return count >= threshold

    # ── Fix 4 — escalation now reads warn_action for the terminal step ── #

    async def _escalate(
        self,
        member: discord.Member,
        guild: discord.Guild,
        warn_count: int,
        settings: dict,
    ):
        max_warns   = settings["max_warns"]
        warn_action = settings["warn_action"]  # "timeout" | "kick" | "ban"

        try:
            if warn_count >= max_warns:
                # Terminal action — respects the configured warn_action setting
                if warn_action == "timeout":
                    until = discord.utils.utcnow() + timedelta(minutes=30)
                    await member.timeout(until, reason="auto-mod: max warnings reached")
                    await log_action(self.bot, guild.id, "⏱️ member timed out",
                        f"**{member}** (`{member.id}`) timed out 30 min.\n**reason:** max warnings reached",
                        Color.PLUM)
                elif warn_action == "kick":
                    await member.kick(reason="auto-mod: max warnings reached")
                    await log_action(self.bot, guild.id, "👢 member kicked",
                        f"**{member}** (`{member.id}`) was kicked.\n**reason:** max warnings reached",
                        Color.BURGUNDY)
                else:  # "ban" (default)
                    await self._send_ban_dm(member, guild)
                    await member.ban(
                        reason="auto-mod: max warnings reached",
                        delete_message_days=0,
                    )
                    await db.add_ban(
                        guild.id, member.id,
                        "auto-mod: max warnings reached",
                        self.bot.user.id,
                    )
                    await log_action(self.bot, guild.id, "🔨 member banned",
                        f"**{member}** (`{member.id}`) was permanently banned.\n**reason:** max warnings reached",
                        Color.BURGUNDY)
                await db.clear_warns(guild.id, member.id)

            elif warn_count == 2:
                # Intermediate step — always a 5-min timeout regardless of warn_action
                until = discord.utils.utcnow() + timedelta(minutes=5)
                await member.timeout(until, reason="auto-mod: 2nd warning — 5-minute timeout")
                await log_action(self.bot, guild.id, "⏱️ member timed out",
                    f"**{member}** (`{member.id}`) timed out 5 min.\n**reason:** 2nd auto-mod warning",
                    Color.PLUM)

            elif warn_count == 3 and max_warns > 3:
                # Intermediate kick only if max_warns leaves room above warn 3
                await member.kick(reason="auto-mod: 3rd warning — kicked from server")
                await log_action(self.bot, guild.id, "👢 member kicked",
                    f"**{member}** (`{member.id}`) was kicked.\n**reason:** 3rd auto-mod warning",
                    Color.BURGUNDY)

        except discord.Forbidden:
            pass

    async def _send_ban_dm(self, member: discord.Member, guild: discord.Guild):
        embed = EmbedBuilder.create(
            title="🚫 You Have Been Banned",
            description=(
                f"You have been permanently banned from **{guild.name}**.\n\n"
                "If you believe this was a mistake, you can appeal by sending "
                "a direct message to this bot with your explanation."
            ),
            color=Color.BURGUNDY,
            timestamp=False,
        )
        try:
            await member.send(embed=embed)
        except discord.HTTPException:
            pass

    # ── Violation handler ─────────────────────────────────────────────── #

    async def _handle_violation(
        self,
        message: discord.Message,
        reason: str,
        severity: str = "medium",
    ):
        member = message.author
        guild  = message.guild

        try:
            await message.delete()
        except discord.HTTPException:
            pass

        await db.add_warn(guild.id, member.id, reason, severity)
        warn_count = await db.get_warn_count(guild.id, member.id)
        settings   = await db.get_guild_settings(guild.id)
        max_warns  = settings["max_warns"]

        embed = EmbedBuilder.warning(
            "Warning Received",
            f"You were warned in **{guild.name}**.\n"
            f"**Reason:** {reason}\n"
            f"**Warnings:** {warn_count} / {max_warns}",
        )
        try:
            await member.send(embed=embed)
        except discord.HTTPException:
            pass

        await log_action(self.bot, guild.id, "⚠️ warning issued",
            f"**{member}** (`{member.id}`) was warned.\n"
            f"**reason:** {reason}\n**count:** {warn_count}/{max_warns}",
            Color.PLUM)

        # Fix 4 — pass full settings so _escalate can read warn_action
        await self._escalate(member, guild, warn_count, settings)

    # ── Message listener ──────────────────────────────────────────────── #

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.author.guild_permissions.manage_messages:
            return

        try:
            settings = await db.get_guild_settings(message.guild.id)
            if not settings["auto_mod_enabled"]:
                return

            content   = message.content
            guild_id  = message.guild.id
            author_id = message.author.id

            if settings["filter_profanity"] and self._is_profanity(content):
                await self._handle_violation(message, "Profanity", "low")
                return
            if settings["filter_spam"] and self._is_spam(guild_id, author_id, content, settings["spam_threshold"]):
                await self._handle_violation(message, "Spam", "medium")
                return
            if settings["filter_caps"] and self._is_excessive_caps(content, settings["caps_threshold"]):
                await self._handle_violation(message, "Excessive caps", "low")
                return
            if settings["filter_invites"] and self._has_invite(content):
                await self._handle_violation(message, "Discord invite link", "medium")
                return
            if settings["filter_links"] and self._has_external_link(content):
                await self._handle_violation(message, "Unauthorized external link", "medium")
                return
            if settings["filter_mentions"] and self._has_excessive_mentions(message, settings["mention_threshold"]):
                await self._handle_violation(message, "Excessive mentions", "high")
                return

        except asyncpg.PostgresError:
            pass  # DB hiccup — don't crash the listener, silently skip

    # ── Member join ───────────────────────────────────────────────────── #

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        try:
            settings = await db.get_guild_settings(member.guild.id)
            if not settings["auto_mod_enabled"]:
                return
            age = datetime.now(timezone.utc) - member.created_at
            if age.days < 7:
                try:
                    await member.send(
                        f"⚠️ Welcome to **{member.guild.name}**! "
                        "Your account is very new — please read the server rules carefully."
                    )
                except discord.HTTPException:
                    pass
        except asyncpg.PostgresError:
            pass

    # ── Moderator commands ────────────────────────────────────────────── #

    @commands.command(name="warnings", description="View a member's active warnings")
    @commands.has_permissions(manage_messages=True)
    async def warnings(self, ctx: commands.Context, member: discord.Member = None):
        target = member or ctx.author
        warns  = await db.get_warns(ctx.guild.id, target.id)

        if not warns:
            await ctx.send(embed=EmbedBuilder.info("No Warnings", f"**{target}** has no active warnings."))
            return

        fields = [
            {
                "name": f"Warning #{i + 1}",
                "value": (
                    f"**Reason:** {w['reason']}\n"
                    f"**Severity:** {w['severity'].capitalize()}\n"
                    f"**Date:** {w['created_at'].strftime('%Y-%m-%d %H:%M UTC')}"
                ),
                "inline": False,
            }
            for i, w in enumerate(warns[:10])
        ]
        embed = EmbedBuilder.create(title=f"⚠️ Warnings — {target}", color=Color.PLUM, fields=fields)
        await ctx.send(embed=embed)

    @commands.command(name="clearwarnings", description="Clear all warnings for a member")
    @commands.has_permissions(manage_messages=True)
    async def clear_warnings(self, ctx: commands.Context, member: discord.Member):
        await db.clear_warns(ctx.guild.id, member.id)
        await ctx.send(embed=EmbedBuilder.success(
            "Warnings Cleared", f"All warnings for **{member}** have been removed."
        ))

    # ── Error handler ─────────────────────────────────────────────────── #

    @warnings.error
    @clear_warnings.error
    async def _cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=EmbedBuilder.error("Permission Denied", "You need **Manage Messages** permission."))
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send(embed=EmbedBuilder.error("Member Not Found", "That member could not be found."))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=EmbedBuilder.error("Missing Argument", f"Usage: `!{ctx.command.name} @member`"))

    async def cog_command_error(self, ctx: commands.Context, error):
        # Fix 7 — unwrap CommandInvokeError to check for DB errors
        err = getattr(error, "original", error)
        if isinstance(err, asyncpg.PostgresError):
            await ctx.send(embed=EmbedBuilder.error(
                "Database Error", "a database error occurred. please try again in a moment."
            ))


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMod(bot))
