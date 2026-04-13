import re
import discord
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque
from database import db
from utils.embeds import EmbedBuilder
from colors import Color


# ------------------------------------------------------------------ #
#  Filter patterns                                                     #
# ------------------------------------------------------------------ #

PROFANITY: set[str] = {
    "fuck", "shit", "bitch", "cunt", "dick", "piss", "arse",
    "bollocks", "retard", "idiot", "moron", "imbecile",
}

INVITE_RE = re.compile(r"(discord\.gg|discordapp\.com/invite)/\w+", re.IGNORECASE)
URL_RE    = re.compile(r"https?://\S+", re.IGNORECASE)
MENTION_RE = re.compile(r"<@!?\d+>")


# ------------------------------------------------------------------ #
#  Escalation table                                                    #
# (warn_count after the new warn → action)                            #
# ------------------------------------------------------------------ #
#
#   1st warn  →  DM warning only
#   2nd warn  →  5-minute timeout
#   3rd warn  →  Kick
#   ≥ max     →  Permanent ban + clears warns
#
# ------------------------------------------------------------------ #


class AutoMod(commands.Cog):
    """
    Listens to every message in every guild and automatically detects:
      - profanity, spam, excessive caps, Discord invite links, external
        links, and mass-mentions.

    Violations are deleted and warned. Punishments escalate with each
    successive warning a user accumulates.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # (guild_id, user_id) → deque of (content, utc_timestamp)
        self._spam_cache: dict[tuple[int, int], deque] = defaultdict(
            lambda: deque(maxlen=20)
        )

    # ------------------------------------------------------------------ #
    #  Checks (all synchronous — no I/O needed)                           #
    # ------------------------------------------------------------------ #

    def _is_profanity(self, text: str) -> bool:
        words = re.sub(r"[^a-z ]", "", text.lower()).split()
        return any(w in PROFANITY for w in words)

    def _is_excessive_caps(self, text: str, threshold: int) -> bool:
        letters = [c for c in text if c.isalpha()]
        if len(letters) < 10:           # ignore very short messages
            return False
        ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        return ratio * 100 >= threshold

    def _is_spam(self, guild_id: int, user_id: int, content: str, threshold: int) -> bool:
        """True if the same message content appears ≥ threshold times in 5 seconds."""
        now = datetime.now(timezone.utc)
        cache = self._spam_cache[(guild_id, user_id)]
        cache.append((content, now))

        cutoff = now - timedelta(seconds=5)
        recent_identical = sum(
            1 for msg, ts in cache
            if ts >= cutoff and msg == content
        )
        return recent_identical >= threshold

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

    # ------------------------------------------------------------------ #
    #  Escalation                                                          #
    # ------------------------------------------------------------------ #

    async def _escalate(
        self,
        member: discord.Member,
        guild: discord.Guild,
        warn_count: int,
        max_warns: int,
    ):
        """Apply the appropriate punishment for the given warn count."""
        try:
            if warn_count == 2:
                until = discord.utils.utcnow() + timedelta(minutes=5)
                await member.timeout(until, reason="Auto-mod: 2nd warning — 5-minute timeout")

            elif warn_count == 3:
                await member.kick(reason="Auto-mod: 3rd warning — kicked from server")

            elif warn_count >= max_warns:
                # Send the ban DM before banning so the message can reach them
                await self._send_ban_dm(member, guild)
                await member.ban(
                    reason="Auto-mod: max warnings reached — permanent ban",
                    delete_message_days=0,
                )
                await db.add_ban(
                    guild.id, member.id,
                    "Auto-mod: max warnings reached",
                    self.bot.user.id,
                )
                await db.clear_warns(guild.id, member.id)

        except discord.Forbidden:
            pass   # Bot lacks hierarchy or permissions; fail silently

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

    # ------------------------------------------------------------------ #
    #  Violation handler                                                   #
    # ------------------------------------------------------------------ #

    async def _handle_violation(
        self,
        message: discord.Message,
        reason: str,
        severity: str = "medium",
    ):
        """Delete the offending message, issue a warning, and escalate."""
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

        # Notify the user via DM
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

        await self._escalate(member, guild, warn_count, max_warns)

    # ------------------------------------------------------------------ #
    #  Message listener                                                    #
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bots and DMs
        if message.author.bot or not message.guild:
            return

        # Moderators and admins are exempt
        if message.author.guild_permissions.manage_messages:
            return

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

    # ------------------------------------------------------------------ #
    #  Member join — new account warning                                   #
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

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

    # ------------------------------------------------------------------ #
    #  Moderator commands                                                  #
    # ------------------------------------------------------------------ #

    @commands.command(name="warnings", description="View a member's active warnings")
    @commands.has_permissions(manage_messages=True)
    async def warnings(self, ctx: commands.Context, member: discord.Member = None):
        target = member or ctx.author
        warns  = await db.get_warns(ctx.guild.id, target.id)

        if not warns:
            await ctx.send(embed=EmbedBuilder.info(
                "No Warnings",
                f"**{target}** has no active warnings.",
            ))
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
        embed = EmbedBuilder.create(
            title=f"⚠️ Warnings — {target}",
            color=Color.PLUM,
            fields=fields,
        )
        await ctx.send(embed=embed)

    @commands.command(name="clearwarnings", description="Clear all warnings for a member")
    @commands.has_permissions(manage_messages=True)
    async def clear_warnings(self, ctx: commands.Context, member: discord.Member):
        await db.clear_warns(ctx.guild.id, member.id)
        await ctx.send(embed=EmbedBuilder.success(
            "Warnings Cleared",
            f"All warnings for **{member}** have been removed.",
        ))

    @warnings.error
    @clear_warnings.error
    async def _error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=EmbedBuilder.error(
                "Permission Denied", "You need **Manage Messages** permission."
            ))
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send(embed=EmbedBuilder.error(
                "Member Not Found", "That member could not be found in this server."
            ))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=EmbedBuilder.error(
                "Missing Argument", f"Usage: `!{ctx.command.name} @member`"
            ))


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMod(bot))
