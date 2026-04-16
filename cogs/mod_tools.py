import asyncpg
import discord
from discord.ext import commands
from utils.embeds import EmbedBuilder
from utils.logger import log_action
from colors import Color


class ModTools(commands.Cog):
    """Manual moderation commands for channel and message management."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── !purge ────────────────────────────────────────────────────────── #

    @commands.command(name="purge")
    @commands.has_permissions(manage_messages=True)
    async def purge(self, ctx: commands.Context, amount: int, member: discord.Member = None):
        if not 1 <= amount <= 1000:
            await ctx.send(embed=EmbedBuilder.error("Invalid Amount", "Amount must be between **1** and **1000**."))
            return

        await ctx.message.delete()
        check   = (lambda m: m.author == member) if member else None
        deleted = await ctx.channel.purge(limit=amount, check=check)

        desc = f"deleted **{len(deleted)}** message(s)"
        if member:
            desc += f" from {member.mention}"
        desc += f" in {ctx.channel.mention}."

        # Fix 5 — audit log
        await log_action(self.bot, ctx.guild.id, "🧹 messages purged",
            f"{ctx.author.mention} {desc}", Color.NAVY)

        await ctx.send(embed=EmbedBuilder.success("Purge Complete", desc), delete_after=5)

    # ── !slowmode ─────────────────────────────────────────────────────── #

    @commands.command(name="slowmode")
    @commands.has_permissions(manage_channels=True)
    async def slowmode(self, ctx: commands.Context, seconds: int):
        if not 0 <= seconds <= 21600:
            await ctx.send(embed=EmbedBuilder.error(
                "Invalid Duration", "Seconds must be between **0** (off) and **21600** (6 hours)."
            ))
            return

        await ctx.channel.edit(slowmode_delay=seconds)

        if seconds == 0:
            embed = EmbedBuilder.success("Slowmode Disabled", f"Slowmode removed from {ctx.channel.mention}.")
            log_desc = f"{ctx.author.mention} disabled slowmode in {ctx.channel.mention}."
        else:
            embed = EmbedBuilder.success(
                "Slowmode Enabled",
                f"Members in {ctx.channel.mention} may send one message every **{seconds}s**.",
            )
            log_desc = f"{ctx.author.mention} set slowmode to **{seconds}s** in {ctx.channel.mention}."

        await log_action(self.bot, ctx.guild.id, "⏱️ slowmode changed", log_desc, Color.BLUE_GRAY)
        await ctx.send(embed=embed)

    # ── !lock / !unlock ───────────────────────────────────────────────── #

    @commands.command(name="lock")
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx: commands.Context):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        if overwrite.send_messages is False:
            await ctx.send(embed=EmbedBuilder.warning("Already Locked", f"{ctx.channel.mention} is already locked."))
            return

        overwrite.send_messages = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)

        await log_action(self.bot, ctx.guild.id, "🔒 channel locked",
            f"{ctx.author.mention} locked {ctx.channel.mention}.", Color.PLUM)
        await ctx.send(embed=EmbedBuilder.warning(
            "Channel Locked", f"{ctx.channel.mention} has been locked. only staff can send messages."
        ))

    @commands.command(name="unlock")
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx: commands.Context):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        if overwrite.send_messages is not False:
            await ctx.send(embed=EmbedBuilder.info("Not Locked", f"{ctx.channel.mention} is not currently locked."))
            return

        overwrite.send_messages = None
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)

        await log_action(self.bot, ctx.guild.id, "🔓 channel unlocked",
            f"{ctx.author.mention} unlocked {ctx.channel.mention}.", Color.NAVY)
        await ctx.send(embed=EmbedBuilder.success(
            "Channel Unlocked", f"{ctx.channel.mention} is now open for everyone."
        ))

    # ── Error handler ─────────────────────────────────────────────────── #

    @purge.error
    @slowmode.error
    @lock.error
    @unlock.error
    async def _cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            perm = "Manage Messages" if ctx.command.name == "purge" else "Manage Channels"
            await ctx.send(embed=EmbedBuilder.error("Permission Denied", f"You need **{perm}** permission."))
        elif isinstance(error, commands.MissingRequiredArgument):
            usages = {"purge": "!purge <amount> [@member]", "slowmode": "!slowmode <seconds>"}
            await ctx.send(embed=EmbedBuilder.error(
                "Missing Argument", f"Usage: `{usages.get(ctx.command.name, f'!{ctx.command.name}')}`"
            ))
        elif isinstance(error, commands.BadArgument):
            await ctx.send(embed=EmbedBuilder.error("Invalid Argument", "Please check your input and try again."))

    async def cog_command_error(self, ctx: commands.Context, error):
        # Fix 7
        err = getattr(error, "original", error)
        if isinstance(err, asyncpg.PostgresError):
            await ctx.send(embed=EmbedBuilder.error(
                "Database Error", "a database error occurred. please try again in a moment."
            ))


async def setup(bot: commands.Bot):
    await bot.add_cog(ModTools(bot))
