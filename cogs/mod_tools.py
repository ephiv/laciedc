import discord
from discord.ext import commands
from utils.embeds import EmbedBuilder


class ModTools(commands.Cog):
    """Manual moderation commands for channel and message management."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------------ #
    #  !purge                                                              #
    # ------------------------------------------------------------------ #

    @commands.command(name="purge", description="Bulk-delete messages in the current channel")
    @commands.has_permissions(manage_messages=True)
    async def purge(self, ctx: commands.Context, amount: int, member: discord.Member = None):
        if not 1 <= amount <= 1000:
            await ctx.send(embed=EmbedBuilder.error(
                "Invalid Amount", "Amount must be between **1** and **1000**."
            ))
            return

        await ctx.message.delete()

        check   = (lambda m: m.author == member) if member else None
        deleted = await ctx.channel.purge(limit=amount, check=check)

        desc = f"Deleted **{len(deleted)}** message(s)"
        if member:
            desc += f" from {member.mention}"
        desc += f" in {ctx.channel.mention}."

        await ctx.send(embed=EmbedBuilder.success("Purge Complete", desc), delete_after=5)

    # ------------------------------------------------------------------ #
    #  !slowmode                                                           #
    # ------------------------------------------------------------------ #

    @commands.command(name="slowmode", description="Set or remove the slowmode delay for this channel")
    @commands.has_permissions(manage_channels=True)
    async def slowmode(self, ctx: commands.Context, seconds: int):
        if not 0 <= seconds <= 21600:
            await ctx.send(embed=EmbedBuilder.error(
                "Invalid Duration", "Seconds must be between **0** (off) and **21600** (6 hours)."
            ))
            return

        await ctx.channel.edit(slowmode_delay=seconds)

        if seconds == 0:
            embed = EmbedBuilder.success(
                "Slowmode Disabled",
                f"Slowmode has been removed from {ctx.channel.mention}.",
            )
        else:
            embed = EmbedBuilder.success(
                "Slowmode Enabled",
                f"Members in {ctx.channel.mention} may send one message every **{seconds}s**.",
            )
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------ #
    #  !lock / !unlock                                                     #
    # ------------------------------------------------------------------ #

    @commands.command(name="lock", description="Prevent @everyone from sending messages here")
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx: commands.Context):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        if overwrite.send_messages is False:
            await ctx.send(embed=EmbedBuilder.warning(
                "Already Locked", f"{ctx.channel.mention} is already locked."
            ))
            return

        overwrite.send_messages = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.send(embed=EmbedBuilder.warning(
            "Channel Locked",
            f"{ctx.channel.mention} has been locked. Only staff can send messages.",
        ))

    @commands.command(name="unlock", description="Restore @everyone's ability to send messages here")
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx: commands.Context):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        if overwrite.send_messages is not False:
            await ctx.send(embed=EmbedBuilder.info(
                "Not Locked", f"{ctx.channel.mention} is not currently locked."
            ))
            return

        overwrite.send_messages = None  # Revert to role/server default
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.send(embed=EmbedBuilder.success(
            "Channel Unlocked",
            f"{ctx.channel.mention} is now open for everyone.",
        ))

    # ------------------------------------------------------------------ #
    #  Error handler                                                       #
    # ------------------------------------------------------------------ #

    @purge.error
    @slowmode.error
    @lock.error
    @unlock.error
    async def _error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            perm = "Manage Messages" if ctx.command.name == "purge" else "Manage Channels"
            await ctx.send(embed=EmbedBuilder.error(
                "Permission Denied", f"You need **{perm}** permission to do that."
            ))
        elif isinstance(error, commands.MissingRequiredArgument):
            usages = {
                "purge":    "!purge <amount> [@member]",
                "slowmode": "!slowmode <seconds>",
            }
            usage = usages.get(ctx.command.name, f"!{ctx.command.name}")
            await ctx.send(embed=EmbedBuilder.error("Missing Argument", f"Usage: `{usage}`"))
        elif isinstance(error, commands.BadArgument):
            await ctx.send(embed=EmbedBuilder.error(
                "Invalid Argument", "Please check your input and try again."
            ))


async def setup(bot: commands.Bot):
    await bot.add_cog(ModTools(bot))
