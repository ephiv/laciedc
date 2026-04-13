import discord
from discord.ext import commands
from utils.embeds import EmbedBuilder
from colors import Color as ColorPalette


class ModTools(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="purge", description="Delete messages")
    @commands.has_permissions(manage_messages=True)
    async def purge(self, ctx, amount: int, member: discord.Member = None):
        if amount < 1 or amount > 1000:
            embed = EmbedBuilder.error(
                "Invalid Amount",
                "Amount must be between 1 and 1000"
            )
            await ctx.send(embed=embed)
            return

        if member:
            def check(m):
                return m.author.id == member.id

            deleted = await ctx.channel.purge(limit=amount, check=check)
            count = len(deleted)
        else:
            deleted = await ctx.channel.purge(limit=amount)
            count = len(deleted)

        embed = EmbedBuilder.success(
            "Messages Deleted",
            f"Deleted **{count}** message(s)" + (f" from {member.mention}" if member else "")
        )
        await ctx.send(embed=embed, delete_after=5)

    @commands.command(name="slowmode", description="Set channel slowmode")
    @commands.has_permissions(manage_channels=True)
    async def slowmode(self, ctx, seconds: int):
        if seconds < 0 or seconds > 21600:
            embed = EmbedBuilder.error(
                "Invalid Duration",
                "Seconds must be between 0 and 21600 (6 hours)"
            )
            await ctx.send(embed=embed)
            return

        await ctx.channel.edit(slowmode_delay=seconds)

        if seconds == 0:
            embed = EmbedBuilder.success(
                "Slowmode Disabled",
                f"Slowmode has been disabled in {ctx.channel.mention}"
            )
        else:
            embed = EmbedBuilder.success(
                "Slowmode Enabled",
                f"Slowmode set to **{seconds}** seconds in {ctx.channel.mention}"
            )
        await ctx.send(embed=embed)

    @commands.command(name="lock", description="Lock the current channel")
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx):
        channel = ctx.channel

        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)

        embed = EmbedBuilder.warning(
            "Channel Locked",
            f"{channel.mention} has been locked. Only staff can send messages."
        )
        await ctx.send(embed=embed)

    @commands.command(name="unlock", description="Unlock the current channel")
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx):
        channel = ctx.channel

        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)

        embed = EmbedBuilder.success(
            "Channel Unlocked",
            f"{channel.mention} has been unlocked."
        )
        await ctx.send(embed=embed)

    @purge.error
    @slowmode.error
    @lock.error
    @unlock.error
    async def error_handler(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            perm = "Manage Messages" if ctx.command.name == "purge" else "Manage Channels"
            embed = EmbedBuilder.error(
                "Permission Denied",
                f"You need **{perm}** permission to use this command."
            )
            await ctx.send(embed=embed)
        elif isinstance(error, commands.MissingRequiredArgument):
            embed = EmbedBuilder.error(
                "Missing Argument",
                f"Usage: `!{ctx.command.name} {ctx.command.usage}`"
            )
            await ctx.send(embed=embed)
        elif isinstance(error, commands.BadArgument):
            embed = EmbedBuilder.error(
                "Invalid Argument",
                "The provided argument is invalid."
            )
            await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(ModTools(bot))