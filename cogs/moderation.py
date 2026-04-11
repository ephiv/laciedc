import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from datetime import datetime, timedelta, timezone

from .database import (
    add_infraction,
    get_infraction_history,
    get_infraction_count,
    clear_warnings,
    get_settings,
    update_settings,
    get_guild_settings,
)
from .logging import (
    mod_log_embed,
    send_mod_log,
    InfractionType,
    error_embed,
    success_embed,
    info_embed,
)


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


async def get_or_create_muted_role(guild: discord.Guild) -> discord.Role:
    settings = get_settings(guild.id)
    muted_role_id = settings.get("muted_role_id") if settings else None
    
    if muted_role_id:
        muted_role = guild.get_role(muted_role_id)
        if muted_role:
            return muted_role
    
    muted_role = await guild.create_role(
        name="Muted",
        color=discord.Color.grey(),
        reason="Creating Muted role for moderation bot"
    )
    
    for channel in guild.channels:
        try:
            await channel.set_permissions(
                muted_role,
                send_messages=False,
                add_reactions=False,
                speak=False,
            )
        except discord.Forbidden:
            pass
    
    update_settings(guild.id, muted_role_id=muted_role.id)
    return muted_role


async def can_act_on_member(moderator: discord.Member, target: discord.Member) -> bool:
    if moderator.id == moderator.guild.owner_id:
        return True
    if moderator.top_role <= target.top_role:
        return False
    if target.guild_permissions.administrator:
        return False
    return True


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

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

    @commands.hybrid_command(name="kick", description="Kick a member from the server")
    @app_commands.default_permissions(kick_members=True)
    @commands.has_permissions(kick_members=True)
    @app_commands.describe(member="The member to kick", reason="Reason for kicking")
    async def kick(
        self, ctx: commands.Context, member: discord.Member, *, reason: str = None
    ):
        """Kick a member from the server"""
        if not await can_act_on_member(ctx.author, member):
            await ctx.send(embed=error_embed("You cannot kick this member (same or higher role)."), ephemeral=True)
            return

        if ctx.author == member:
            await ctx.send(embed=error_embed("You cannot kick yourself."), ephemeral=True)
            return

        reason_text = reason or "No reason provided"
        
        try:
            await member.kick(reason=reason_text)
        except discord.Forbidden:
            await ctx.send(embed=error_embed("I don't have permission to kick this member."), ephemeral=True)
            return

        add_infraction(member.id, ctx.guild.id, "kick", ctx.author.id, reason_text)

        embed = mod_log_embed(
            InfractionType.KICK, member, ctx.author, reason_text
        )
        await ctx.send(embed=success_embed(f"Kicked {member}"))
        await send_mod_log(ctx.guild, embed)

    @kick.error
    async def kick_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.", ephemeral=True)

    @commands.hybrid_command(name="ban", description="Ban a member from the server")
    @app_commands.default_permissions(ban_members=True)
    @commands.has_permissions(ban_members=True)
    @app_commands.describe(member="The member to ban", reason="Reason for banning")
    async def ban(
        self, ctx: commands.Context, member: discord.Member, *, reason: str = None
    ):
        """Ban a member from the server"""
        if not await can_act_on_member(ctx.author, member):
            await ctx.send(embed=error_embed("You cannot ban this member (same or higher role)."), ephemeral=True)
            return

        if ctx.author == member:
            await ctx.send(embed=error_embed("You cannot ban yourself."), ephemeral=True)
            return

        reason_text = reason or "No reason provided"
        
        try:
            await member.ban(reason=reason_text, delete_message_days=0)
        except discord.Forbidden:
            await ctx.send(embed=error_embed("I don't have permission to ban this member."), ephemeral=True)
            return

        add_infraction(member.id, ctx.guild.id, "ban", ctx.author.id, reason_text)

        embed = mod_log_embed(
            InfractionType.BAN, member, ctx.author, reason_text
        )
        await ctx.send(embed=success_embed(f"Banned {member}"))
        await send_mod_log(ctx.guild, embed)

    @ban.error
    async def ban_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.", ephemeral=True)

    @commands.hybrid_command(name="unban", description="Unban a user from the server")
    @app_commands.default_permissions(ban_members=True)
    @commands.has_permissions(ban_members=True)
    @app_commands.describe(user="The user to unban (mention or ID)")
    async def unban(self, ctx: commands.Context, user: discord.User):
        """Unban a user from the server"""
        try:
            await ctx.guild.fetch_ban(user)
        except discord.NotFound:
            await ctx.send(embed=error_embed(f"{user} is not banned."), ephemeral=True)
            return

        try:
            await ctx.guild.unban(user, reason=f"Unbanned by {ctx.author}")
        except discord.Forbidden:
            await ctx.send(embed=error_embed("I don't have permission to unban this user."), ephemeral=True)
            return

        add_infraction(user.id, ctx.guild.id, "unban", ctx.author.id, "Unbanned")

        embed = mod_log_embed(
            InfractionType.UNBAN, user, ctx.author, "Unbanned"
        )
        await ctx.send(embed=success_embed(f"Unbanned {user}"))
        await send_mod_log(ctx.guild, embed)

    @unban.error
    async def unban_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.", ephemeral=True)

    @commands.hybrid_command(name="mute", description="Mute a member using a role")
    @app_commands.default_permissions(manage_roles=True)
    @commands.has_permissions(manage_roles=True)
    @app_commands.describe(member="The member to mute", duration="Duration (e.g., 5m, 1h, 1d)")
    async def mute(
        self,
        ctx: commands.Context,
        member: discord.Member,
        duration: str = None,
        *,
        reason: str = None,
    ):
        """Mute a member using a role"""
        if not await can_act_on_member(ctx.author, member):
            await ctx.send(embed=error_embed("You cannot mute this member (same or higher role)."), ephemeral=True)
            return

        if ctx.author == member:
            await ctx.send(embed=error_embed("You cannot mute yourself."), ephemeral=True)
            return

        muted_role = await get_or_create_muted_role(ctx.guild)

        if muted_role in member.roles:
            await ctx.send(embed=error_embed(f"{member} is already muted."), ephemeral=True)
            return

        try:
            await member.add_roles(muted_role, reason=f"Muted by {ctx.author}: {reason or 'No reason'}")
        except discord.Forbidden:
            await ctx.send(embed=error_embed("I don't have permission to add the muted role."), ephemeral=True)
            return

        reason_text = reason or "No reason provided"
        duration_text = duration or "Indefinite"
        
        add_infraction(member.id, ctx.guild.id, "mute", ctx.author.id, f"{reason_text} | Duration: {duration_text}")

        embed = mod_log_embed(
            InfractionType.MUTE, member, ctx.author, reason_text, duration_text
        )
        await ctx.send(embed=success_embed(f"Muted {member} for {duration_text}"))
        await send_mod_log(ctx.guild, embed)

        if duration:
            await asyncio.sleep(self._parse_duration(duration))
            if muted_role in member.roles:
                try:
                    await member.remove_roles(muted_role, reason="Mute duration expired")
                    await ctx.guild.get_channel(ctx.channel.id).send(
                        f"{member} has been unmuted (duration expired)."
                    )
                except discord.Forbidden:
                    pass

    @mute.error
    async def mute_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.", ephemeral=True)

    @commands.hybrid_command(name="unmute", description="Unmute a member")
    @app_commands.default_permissions(manage_roles=True)
    @commands.has_permissions(manage_roles=True)
    @app_commands.describe(member="The member to unmute")
    async def unmute(self, ctx: commands.Context, member: discord.Member, *, reason: str = None):
        """Unmute a member"""
        muted_role = await get_or_create_muted_role(ctx.guild)

        if muted_role not in member.roles:
            await ctx.send(embed=error_embed(f"{member} is not muted."), ephemeral=True)
            return

        try:
            await member.remove_roles(muted_role, reason=f"Unmuted by {ctx.author}: {reason or 'No reason'}")
        except discord.Forbidden:
            await ctx.send(embed=error_embed("I don't have permission to remove the muted role."), ephemeral=True)
            return

        reason_text = reason or "No reason provided"
        
        embed = mod_log_embed(
            InfractionType.UNMUTE, member, ctx.author, reason_text
        )
        await ctx.send(embed=success_embed(f"Unmuted {member}"))
        await send_mod_log(ctx.guild, embed)

    @unmute.error
    async def unmute_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.", ephemeral=True)

    @commands.hybrid_command(name="warn", description="Warn a member")
    @app_commands.default_permissions(moderate_members=True)
    @commands.has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to warn", reason="Reason for warning")
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str):
        """Warn a member"""
        if not await can_act_on_member(ctx.author, member):
            await ctx.send(embed=error_embed("You cannot warn this member (same or higher role)."), ephemeral=True)
            return

        if ctx.author == member:
            await ctx.send(embed=error_embed("You cannot warn yourself."), ephemeral=True)
            return

        add_infraction(member.id, ctx.guild.id, "warn", ctx.author.id, reason)

        embed = mod_log_embed(
            InfractionType.WARN, member, ctx.author, reason
        )
        
        warnings_count = get_infraction_count(member.id, ctx.guild.id, "warn")
        await ctx.send(
            embed=success_embed(f"Warned {member}. They now have {warnings_count} warning(s).")
        )
        await send_mod_log(ctx.guild, embed)

    @warn.error
    async def warn_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.", ephemeral=True)

    @commands.hybrid_command(name="warnings", description="View a member's warnings")
    @app_commands.default_permissions(moderate_members=True)
    @commands.has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to check warnings for")
    async def warnings(self, ctx: commands.Context, member: discord.Member):
        """View a member's warnings"""
        history = get_infraction_history(member.id, ctx.guild.id)
        warnings = [w for w in history if w["type"] == "warn"]
        
        if not warnings:
            await ctx.send(embed=info_embed(f"Warnings for {member}", f"{member} has no warnings."))
            return

        embed = discord.Embed(
            title=f"Warnings for {member}",
            color=discord.Color.orange()
        )
        
        for i, warning in enumerate(warnings[:10], 1):
            moderator = ctx.guild.get_member(warning["moderator_id"])
            mod_name = moderator.mention if moderator else f"<@{warning['moderator_id']}>"
            timestamp = datetime.fromisoformat(warning["created_at"]).strftime("%Y-%m-%d %H:%M")
            embed.add_field(
                name=f"Warning #{i}",
                value=f"**Reason:** {warning['reason']}\n**By:** {mod_name}\n**At:** {timestamp}",
                inline=False
            )
        
        total = len(warnings)
        if total > 10:
            embed.set_footer(text=f"Showing 10 of {total} warnings")
        
        await ctx.send(embed=embed)

    @warnings.error
    async def warnings_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.", ephemeral=True)

    @commands.hybrid_command(name="clearwarnings", description="Clear all warnings for a member")
    @app_commands.default_permissions(administrator=True)
    @commands.has_permissions(administrator=True)
    @app_commands.describe(member="The member to clear warnings for")
    async def clearwarnings(self, ctx: commands.Context, member: discord.Member):
        """Clear all warnings for a member"""
        deleted = clear_warnings(member.id, ctx.guild.id)
        
        if deleted > 0:
            await ctx.send(embed=success_embed(f"Cleared {deleted} warning(s) for {member}."))
        else:
            await ctx.send(embed=info_embed("No Warnings", f"{member} had no warnings to clear."))

    @clearwarnings.error
    async def clearwarnings_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.", ephemeral=True)

    @commands.hybrid_command(name="history", description="View a member's full infraction history")
    @app_commands.default_permissions(moderate_members=True)
    @commands.has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to check history for")
    async def history(self, ctx: commands.Context, member: discord.Member):
        """View a member's full infraction history"""
        history = get_infraction_history(member.id, ctx.guild.id)
        
        if not history:
            await ctx.send(embed=info_embed(f"History for {member}", f"{member} has no infractions."))
            return

        embed = discord.Embed(
            title=f"Infraction History for {member}",
            color=discord.Color.blue()
        )
        
        type_emojis = {
            "warn": "\u26a0\ufe0f",
            "mute": "\ud83d\udd07",
            "unmute": "\ud83d\udd0a",
            "kick": "\ud83d\udc62",
            "ban": "\ud83d\udeab",
            "unban": "\ud83d\udfe2",
            "timeout": "\u23f1\ufe0f",
            "untimeout": "\u23f1\ufe0f",
        }
        
        for i, infraction in enumerate(history[:15], 1):
            emoji = type_emojis.get(infraction["type"], "\u2728")
            moderator = ctx.guild.get_member(infraction["moderator_id"])
            mod_name = moderator.mention if moderator else f"<@{infraction['moderator_id']}>"
            timestamp = datetime.fromisoformat(infraction["created_at"]).strftime("%Y-%m-%d %H:%M")
            reason = infraction["reason"] or "No reason"
            
            embed.add_field(
                name=f"{emoji} {infraction['type'].capitalize()} #{i}",
                value=f"**Reason:** {reason}\n**By:** {mod_name}\n**At:** {timestamp}",
                inline=False
            )
        
        total = len(history)
        if total > 15:
            embed.set_footer(text=f"Showing 15 of {total} infractions")
        
        await ctx.send(embed=embed)

    @history.error
    async def history_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.", ephemeral=True)

    @commands.hybrid_command(name="setmodlog", description="Set the mod log channel")
    @app_commands.default_permissions(administrator=True)
    @commands.has_permissions(administrator=True)
    @app_commands.describe(channel="The channel for mod logs")
    async def setmodlog(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the mod log channel"""
        update_settings(ctx.guild.id, log_channel_id=channel.id)
        await ctx.send(embed=success_embed(f"Mod log channel set to {channel.mention}"))

    @setmodlog.error
    async def setmodlog_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.", ephemeral=True)

    def _parse_duration(self, duration: str) -> int:
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
        try:
            if duration[-1].lower() in multipliers:
                return int(duration[:-1]) * multipliers[duration[-1].lower()]
            else:
                return int(duration)
        except (ValueError, KeyError):
            return 300


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
