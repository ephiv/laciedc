import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta

from .database import (
    add_infraction,
    get_infraction_count,
)
from .logging import (
    mod_log_embed,
    send_mod_log,
    InfractionType,
    error_embed,
    success_embed,
    info_embed,
)


async def can_act_on_member(moderator: discord.Member, target: discord.Member) -> bool:
    if moderator.id == moderator.guild.owner_id:
        return True
    if moderator.top_role <= target.top_role:
        return False
    if target.guild_permissions.administrator:
        return False
    return True


class DurationTransformer(app_commands.Transformer):
    async def transform(self, inter: discord.Interaction, value: str) -> timedelta | None:
        if not value:
            return None
        
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
        try:
            if value[-1].lower() in multipliers:
                seconds = int(value[:-1]) * multipliers[value[-1].lower()]
                return timedelta(seconds=seconds)
            else:
                seconds = int(value)
                return timedelta(seconds=seconds)
        except (ValueError, KeyError):
            raise app_commands.TransformError("Invalid duration. Use: 30, 30s, 5m, 1h, 1d, 1w")


role_group = app_commands.Group(name="role", description="Role management", guild_only=True)


class UserManagement(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.tree.add_command(role_group)

    async def cog_app_command_error(
        self, inter: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.errors.CommandInvokeError):
            error = error.original
        
        if isinstance(error, (commands.MissingPermissions, app_commands.errors.MissingPermissions)):
            try:
                await inter.response.send_message("You don't have permission to use this command.", ephemeral=True)
            except discord.InteractionResponded:
                await inter.followup.send("You don't have permission to use this command.", ephemeral=True)
        else:
            try:
                await inter.response.send_message(f"An error occurred: {error}", ephemeral=True)
            except discord.InteractionResponded:
                await inter.followup.send(f"An error occurred: {error}", ephemeral=True)

    @commands.hybrid_command(name="timeout", description="Timeout a member using Discord's native timeout")
    @app_commands.default_permissions(moderate_members=True)
    @commands.has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to timeout", duration="Duration (e.g., 5m, 1h, 1d)")
    async def timeout(
        self, ctx: commands.Context, member: discord.Member, duration: str = None, *, reason: str = None
    ):
        """Timeout a member using Discord's native timeout feature"""
        if not await can_act_on_member(ctx.author, member):
            await ctx.send(embed=error_embed("You cannot timeout this member (same or higher role)."), ephemeral=True)
            return

        if ctx.author == member:
            await ctx.send(embed=error_embed("You cannot timeout yourself."), ephemeral=True)
            return

        if member.is_timed_out():
            await ctx.send(embed=error_embed(f"{member} is already timed out."), ephemeral=True)
            return

        if not duration:
            await ctx.send(embed=error_embed("Please provide a duration (e.g., 5m, 1h, 1d)."), ephemeral=True)
            return

        delta = self._parse_duration(duration)
        if not delta:
            await ctx.send(embed=error_embed("Invalid duration. Use: 30, 30s, 5m, 1h, 1d, 1w"), ephemeral=True)
            return

        if delta.total_seconds() > 2419200:
            await ctx.send(embed=error_embed("Timeout cannot exceed 28 days."), ephemeral=True)
            return

        reason_text = reason or "No reason provided"
        until = discord.utils.utcnow() + delta

        try:
            await member.timeout(until, reason=reason_text)
        except discord.Forbidden:
            await ctx.send(embed=error_embed("I don't have permission to timeout this member."), ephemeral=True)
            return

        add_infraction(member.id, ctx.guild.id, "timeout", ctx.author.id, f"{reason_text} | Duration: {duration}")

        embed = mod_log_embed(
            InfractionType.TIMEOUT, member, ctx.author, reason_text, duration
        )
        await ctx.send(embed=success_embed(f"Timed out {member} for {duration}"))
        await send_mod_log(ctx.guild, embed)

    @timeout.error
    async def timeout_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.", ephemeral=True)

    @commands.hybrid_command(name="untimeout", description="Remove timeout from a member")
    @app_commands.default_permissions(moderate_members=True)
    @commands.has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to remove timeout from")
    async def untimeout(self, ctx: commands.Context, member: discord.Member, *, reason: str = None):
        """Remove timeout from a member"""
        if not member.is_timed_out():
            await ctx.send(embed=error_embed(f"{member} is not timed out."), ephemeral=True)
            return

        reason_text = reason or "No reason provided"

        try:
            await member.timeout(None, reason=reason_text)
        except discord.Forbidden:
            await ctx.send(embed=error_embed("I don't have permission to remove timeout."), ephemeral=True)
            return

        add_infraction(member.id, ctx.guild.id, "untimeout", ctx.author.id, reason_text)

        embed = mod_log_embed(
            InfractionType.UNTIMEOUT, member, ctx.author, reason_text
        )
        await ctx.send(embed=success_embed(f"Removed timeout from {member}"))
        await send_mod_log(ctx.guild, embed)

    @untimeout.error
    async def untimeout_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.", ephemeral=True)

    @role_group.command(name="add", description="Add a role to a member")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(member="The member", role="The role to add")
    async def role_add(self, inter: discord.Interaction, member: discord.Member, role: discord.Role):
        """Add a role to a member"""
        if inter.user.id != inter.guild.owner_id and inter.user.top_role <= role:
            await inter.response.send_message("You cannot add a role that is higher or equal to your highest role.", ephemeral=True)
            return

        if role in member.roles:
            await inter.response.send_message(f"{member} already has the {role.mention} role.", ephemeral=True)
            return

        if inter.guild.me.top_role <= role:
            await inter.response.send_message("I cannot add a role that is higher or equal to my highest role.", ephemeral=True)
            return

        try:
            await member.add_roles(role, reason=f"Added by {inter.user}")
        except discord.Forbidden:
            await inter.response.send_message("I don't have permission to add this role.", ephemeral=True)
            return

        await inter.response.send_message(embed=success_embed(f"Added {role.mention} to {member.mention}"))

    @role_group.command(name="remove", description="Remove a role from a member")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(member="The member", role="The role to remove")
    async def role_remove(self, inter: discord.Interaction, member: discord.Member, role: discord.Role):
        """Remove a role from a member"""
        if inter.user.id != inter.guild.owner_id and inter.user.top_role <= role:
            await inter.response.send_message("You cannot remove a role that is higher or equal to your highest role.", ephemeral=True)
            return

        if role not in member.roles:
            await inter.response.send_message(f"{member} doesn't have the {role.mention} role.", ephemeral=True)
            return

        try:
            await member.remove_roles(role, reason=f"Removed by {inter.user}")
        except discord.Forbidden:
            await inter.response.send_message("I don't have permission to remove this role.", ephemeral=True)
            return

        await inter.response.send_message(embed=success_embed(f"Removed {role.mention} from {member.mention}"))

    @commands.hybrid_command(name="userinfo", description="Get information about a user")
    @app_commands.describe(member="The member to get info about (defaults to you)")
    async def userinfo(self, ctx: commands.Context, member: discord.Member = None):
        """Get information about a user"""
        if member is None:
            member = ctx.author

        account_age = discord.utils.utcnow() - member.created_at.replace(tzinfo=timezone.utc)
        account_days = account_age.days
        
        embed = discord.Embed(
            title=str(member),
            color=member.color,
            timestamp=discord.utils.utcnow()
        )
        
        embed.set_thumbnail(url=member.display_avatar.url if member.display_avatar else None)
        
        embed.add_field(name="ID", value=member.id, inline=True)
        embed.add_field(name="Nickname", value=member.nick or "None", inline=True)
        
        if isinstance(member, discord.Member) and member.joined_at:
            join_age = discord.utils.utcnow() - member.joined_at.replace(tzinfo=timezone.utc)
            embed.add_field(name="Joined Server", value=f"{join_age.days} days ago", inline=True)
            embed.add_field(name="Join Date", value=discord.utils.format_dt(member.joined_at, style="F"), inline=True)
        
        embed.add_field(name="Account Created", value=f"{account_days} days ago", inline=True)
        embed.add_field(name="Account Age", value=discord.utils.format_dt(member.created_at, style="F"), inline=True)
        
        roles = [role.mention for role in member.roles[1:]]
        if roles:
            embed.add_field(
                name=f"Roles ({len(roles)})",
                value=" ".join(roles) if len(roles) <= 10 else " ".join(roles[:10]) + f" ... ({len(roles) - 10} more)",
                inline=False
            )
        else:
            embed.add_field(name="Roles", value="None", inline=False)
        
        warn_count = get_infraction_count(member.id, ctx.guild.id, "warn")
        total_infraction_count = get_infraction_count(member.id, ctx.guild.id)
        
        status_text = []
        if member.bot:
            status_text.append("Bot")
        if isinstance(member, discord.Member):
            if member.is_timed_out():
                status_text.append("Timed Out")
        
        status_str = ", ".join(status_text) if status_text else "Active"
        embed.add_field(name="Status", value=status_str, inline=True)
        embed.add_field(name="Warnings", value=warn_count, inline=True)
        embed.add_field(name="Total Infractions", value=total_infraction_count, inline=True)
        
        if member.premium_since:
            embed.add_field(name="Server Booster Since", value=discord.utils.format_dt(member.premium_since, style="F"), inline=True)

        await ctx.send(embed=embed)

    def _parse_duration(self, duration: str) -> timedelta | None:
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
        try:
            if duration[-1].lower() in multipliers:
                seconds = int(duration[:-1]) * multipliers[duration[-1].lower()]
                return timedelta(seconds=seconds)
            else:
                seconds = int(duration)
                return timedelta(seconds=seconds)
        except (ValueError, KeyError):
            return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UserManagement(bot))
