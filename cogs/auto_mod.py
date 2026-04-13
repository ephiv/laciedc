import re
import hashlib
import discord
from discord.ext import commands
from datetime import datetime, timezone
from database import db
from utils.embeds import EmbedBuilder
from colors import Color as ColorPalette

PROFANITY_LIST = {
    "fuck", "shit", "damn", "bitch", "ass", "bastard", "cunt", "dick", "piss",
    "crap", "hell", "damn", "arse", "bollocks", "bugger", "crikey", "rubbish",
    "retard", "idiot", "stupid", "dumb", "moron", "imbecile", "fool", "loser",
}

INVITE_REGEX = re.compile(
    r"(discord\.gg|discordapp\.com/invite)/[a-zA-Z0-9]+", re.IGNORECASE
)

URL_REGEX = re.compile(
    r"https?://[^\s]+", re.IGNORECASE
)


class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.spam_cache = {}

    async def cog_load(self):
        print("AutoMod cog loaded")

    async def get_settings(self, guild_id: int) -> dict:
        return await db.get_guild_settings(guild_id)

    async def check_profanity(self, message: str) -> bool:
        words = message.lower().split()
        return any(word in PROFANITY_LIST for word in words)

    async def check_caps(self, message: str, threshold: int) -> bool:
        if len(message) < 10:
            return False
        letters = [c for c in message if c.isalpha()]
        if not letters:
            return False
        caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        return caps_ratio >= (threshold / 100)

    async def check_spam(self, guild_id: int, user_id: int, message: str) -> bool:
        msg_hash = hashlib.md5(message.encode()).hexdigest()

        key = (guild_id, user_id)
        if key not in self.spam_cache:
            self.spam_cache[key] = []

        self.spam_cache[key].append(msg_hash)

        if len(self.spam_cache[key]) >= 3:
            self.spam_cache[key] = self.spam_cache[key][-3:]
            return True

        return False

    async def check_invites(self, message: str) -> bool:
        return bool(INVITE_REGEX.search(message))

    async def check_links(self, message: str) -> bool:
        return bool(URL_REGEX.search(message))

    async def check_mentions(self, message: str, threshold: int) -> bool:
        mention_count = message.count("@everyone") + message.count("@here")
        mention_count += len(re.findall(r"<@!?\d+>", message))
        return mention_count >= threshold

    async def handle_violation(
        self, member: discord.Member, reason: str, severity: str = "medium"
    ):
        guild = member.guild
        settings = await self.get_settings(guild.id)

        if not settings["auto_mod_enabled"]:
            return

        warn_count = await db.get_warn_count(guild.id, member.id)
        max_warns = settings["max_warns"]
        warn_action = settings["warn_action"]

        await db.add_warn(guild.id, member.id, reason, severity)

        embed = EmbedBuilder.warning(
            "⚠️ Warning Issued",
            f"You have received a warning in **{guild.name}**\n"
            f"Reason: {reason}\n"
            f"Warnings: {warn_count + 1}/{max_warns}"
        )
        try:
            await member.send(embed=embed)
        except:
            pass

        if warn_count + 1 >= max_warns:
            if warn_action == "timeout":
                timeout_duration = discord.utils.utcnow() + datetime.timedelta(minutes=30)
                await member.timeout(timeout_duration, reason="Max warnings reached")
            elif warn_action == "kick":
                try:
                    await member.kick(reason="Max warnings reached")
                except:
                    pass
            elif warn_action == "ban":
                try:
                    await member.ban(reason="Max warnings reached")
                    ban_id = await db.add_ban(guild.id, member.id, "Max warnings reached", 0)
                    await self.send_ban_dm(member, guild)
                except:
                    pass

            await db.clear_warns(guild.id, member.id)

    async def send_ban_dm(self, member: discord.Member, guild: discord.Guild):
        embed = EmbedBuilder.create(
            title="🚫 You Have Been Banned",
            description=f"You have been banned from **{guild.name}**.\n\n"
                        f"You may submit an appeal by replying to this message.\n"
                        f"Explain why you believe your ban should be lifted.",
            color=ColorPalette.BURGUNDY,
            timestamp=False,
        )
        try:
            await member.send(embed=embed)
        except:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if not message.guild:
            return

        settings = await self.get_settings(message.guild.id)
        if not settings["auto_mod_enabled"]:
            return

        member = message.author
        content = message.content
        guild = message.guild

        if settings["filter_profanity"] and await self.check_profanity(content):
            await message.delete()
            await self.handle_violation(member, "Profanity", "low")
            return

        if settings["filter_spam"] and await self.check_spam(message.guild.id, member.id, content):
            await message.delete()
            await self.handle_violation(member, "Spam", "medium")
            return

        if settings["filter_caps"] and await self.check_caps(content, settings["caps_threshold"]):
            await message.delete()
            await self.handle_violation(member, "Excessive caps", "low")
            return

        if settings["filter_invites"] and await self.check_invites(content):
            await message.delete()
            await self.handle_violation(member, "Discord invite link", "medium")
            return

        if settings["filter_links"] and await self.check_links(content):
            await message.delete()
            await self.handle_violation(member, "Links not allowed", "medium")
            return

        if settings["filter_mentions"] and await self.check_mentions(content, settings["mention_threshold"]):
            await message.delete()
            await self.handle_violation(member, "Excessive mentions", "medium")
            return

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        settings = await self.get_settings(member.guild.id)
        if not settings["auto_mod_enabled"]:
            return

        account_age = datetime.now(timezone.utc) - member.created_at
        if account_age.days < 7:
            embed = EmbedBuilder.warning(
                "⚠️ New Account Warning",
                f"**{member}** joined with an account less than 7 days old.\n"
                f"Account created: {member.created_at.strftime('%Y-%m-%d')}"
            )
            try:
                await member.send(
                    f"⚠️ Welcome to **{member.guild.name}**! "
                    f"Your account is very new. Please read the rules carefully."
                )
            except:
                pass

    @commands.command(name="warnings", description="Check user's warnings")
    @commands.has_permissions(manage_messages=True)
    async def warnings(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        warns = await db.get_warns(ctx.guild.id, member.id)

        if not warns:
            embed = EmbedBuilder.info(
                "No Warnings",
                f"**{member}** has no warnings."
            )
            await ctx.send(embed=embed)
            return

        fields = [
            {
                "name": f"Warning #{i+1}",
                "value": f"Reason: {w['reason']}\nSeverity: {w['severity']}\n{w['created_at'].strftime('%Y-%m-%d %H:%M')}",
                "inline": False,
            }
            for i, w in enumerate(warns)
        ]

        embed = EmbedBuilder.create(
            title=f"⚠️ Warnings for {member}",
            color=ColorPalette.PLUM,
            fields=fields[:10],
        )
        await ctx.send(embed=embed)

    @commands.command(name="clear-warnings", description="Clear user's warnings")
    @commands.has_permissions(manage_messages=True)
    async def clear_warnings(self, ctx, member: discord.Member):
        await db.clear_warns(ctx.guild.id, member.id)
        embed = EmbedBuilder.success(
            "Warnings Cleared",
            f"All warnings for **{member}** have been cleared."
        )
        await ctx.send(embed=embed)

    @warnings.error
    @clear_warnings.error
    async def error_handler(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            embed = EmbedBuilder.error("Permission Denied", "You don't have permission to use this command.")
            await ctx.send(embed=embed)
        elif isinstance(error, commands.MemberNotFound):
            embed = EmbedBuilder.error("Member Not Found", "The specified member could not be found.")
            await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(AutoMod(bot))