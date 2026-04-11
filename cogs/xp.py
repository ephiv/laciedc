import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import random

from .database import (
    get_xp_data,
    add_xp,
    update_xp_level,
    increment_message_count,
    update_last_daily_bonus,
    update_voice_seconds,
    set_xp_excluded,
    get_xp_leaderboard,
    get_user_rank,
    set_level_role,
    get_level_role,
    get_all_level_roles,
    get_user_total_xp,
    create_xp_data,
    get_level_role_config,
)


MESSAGE_XP_MIN = 10
MESSAGE_XP_MAX = 25
MESSAGE_COOLDOWN_SECONDS = 30
VOICE_XP_PER_MINUTE = 5
VOICE_MAX_XP_PER_SESSION = 150
DAILY_BONUS_XP = 50

message_cooldowns = defaultdict(dict)
voice_sessions = {}


def calculate_level(xp: int) -> int:
    return int((xp / 100) ** 0.5)


def xp_for_level(level: int) -> int:
    return level ** 2 * 100


def xp_progress(xp: int) -> tuple[int, int, int]:
    level = calculate_level(xp)
    current_level_xp = xp_for_level(level)
    next_level_xp = xp_for_level(level + 1)
    xp_in_level = xp - current_level_xp
    xp_needed = next_level_xp - current_level_xp
    return (xp_in_level, xp_needed, level)


def create_progress_bar(progress: float, length: int = 10) -> str:
    filled = int(progress * length)
    empty = length - filled
    return "\u2588" * filled + "\u2591" * empty


levelup_group = app_commands.Group(name="levelup", description="Level role management", guild_only=True)


LEVEL_COLORS = [
    0xFFFFFF,  # White
    0xC0C0C0,  # Silver
    0xFFD700,  # Gold
    0xFF8C00,  # Dark Orange
    0xFF4500,  # Orange Red
    0xDC143C,  # Crimson
    0x8B0000,  # Dark Red
    0xFF1493,  # Deep Pink
    0x9932CC,  # Dark Orchid
    0x4169E1,  # Royal Blue
]

COLOR_NAMES = [
    "White", "Silver", "Gold", "Orange", "Orange Red",
    "Crimson", "Dark Red", "Pink", "Purple", "Blue"
]


class XP(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.tree.add_command(levelup_group)

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

    @commands.hybrid_command(name="rank", description="Show your or another user's rank and XP")
    @app_commands.describe(member="The member to check (defaults to you)")
    async def rank(self, ctx: commands.Context, member: discord.Member = None):
        """Show your or another user's rank and XP"""
        if member is None:
            member = ctx.author

        xp_data = get_xp_data(member.id, ctx.guild.id)
        
        if not xp_data or xp_data.get("xp", 0) == 0:
            await ctx.send(
                embed=discord.Embed(
                    title=f"{member}'s Rank",
                    description="This user hasn't earned any XP yet!",
                    color=member.color
                ).set_thumbnail(url=member.display_avatar.url if member.display_avatar else None)
            )
            return

        xp = xp_data["xp"]
        xp_in_level, xp_needed, level = xp_progress(xp)
        rank, _ = get_user_rank(member.id, ctx.guild.id)
        total_users = get_user_total_xp(ctx.guild.id)
        
        progress = xp_in_level / xp_needed if xp_needed > 0 else 1.0
        progress_bar = create_progress_bar(progress)
        
        embed = discord.Embed(
            title=f"{member}'s Rank",
            color=member.color,
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url if member.display_avatar else None)
        
        embed.add_field(name="Level", value=f"**{level}**", inline=True)
        embed.add_field(name="XP", value=f"**{xp:,}**", inline=True)
        embed.add_field(name="Server Rank", value=f"**#{rank}** of {total_users}", inline=True)
        
        embed.add_field(
            name="Progress",
            value=f"{progress_bar} `{xp_in_level:,} / {xp_needed:,} XP`",
            inline=False
        )
        
        embed.add_field(
            name="Stats",
            value=f"Messages: {xp_data.get('messages_sent', 0):,}\nVoice: {xp_data.get('voice_seconds', 0) // 60:,} min",
            inline=True
        )
        
        next_level_xp = xp_for_level(level + 1)
        embed.set_footer(text=f"Next level: {next_level_xp - xp:,} XP needed")
        
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="leaderboard", description="Show the server XP leaderboard")
    async def leaderboard(self, ctx: commands.Context):
        """Show the server XP leaderboard"""
        leaderboard_data = get_xp_leaderboard(ctx.guild.id, 10)
        
        if not leaderboard_data:
            await ctx.send(embed=discord.Embed(
                title="Leaderboard",
                description="No XP data yet. Start chatting to earn XP!",
                color=discord.Color.blue()
            ))
            return
        
        medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
        
        embed = discord.Embed(
            title=f"Leaderboard - {ctx.guild.name}",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )
        
        description_lines = []
        for i, entry in enumerate(leaderboard_data):
            user_id = entry["user_id"]
            xp = entry["xp"]
            level = calculate_level(xp)
            
            try:
                user = ctx.guild.get_member(user_id)
                if user:
                    name = user.display_name
                else:
                    user_obj = await self.bot.fetch_user(user_id)
                    name = user_obj.name
            except discord.NotFound:
                name = f"Unknown User"
            
            if i < 3:
                medal = medals[i]
                description_lines.append(f"{medal} **{name}** - Level {level} ({xp:,} XP)")
            else:
                description_lines.append(f"{i + 1}. **{name}** - Level {level} ({xp:,} XP)")
        
        embed.description = "\n".join(description_lines)
        embed.set_footer(text=f"Showing top {len(leaderboard_data)} users")
        
        await ctx.send(embed=embed)

    @levelup_group.command(name="add", description="Add a role reward for reaching a level")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(level="The level required", role="The role to give")
    async def levelup_add(self, inter: discord.Interaction, level: int, role: discord.Role):
        """Add a role reward for reaching a level"""
        if level < 1:
            await inter.response.send_message("Level must be at least 1.", ephemeral=True)
            return
        
        if inter.guild.me.top_role <= role:
            await inter.response.send_message("I cannot assign a role higher or equal to my highest role.", ephemeral=True)
            return
        
        set_level_role(inter.guild.id, level, role.id)
        
        await inter.response.send_message(
            embed=discord.Embed(
                title="Level Role Added",
                description=f"When users reach level {level}, they will receive {role.mention}.",
                color=discord.Color.green()
            )
        )

    @levelup_group.command(name="remove", description="Remove a level role reward")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(level="The level to remove the reward from")
    async def levelup_remove(self, inter: discord.Interaction, level: int):
        """Remove a level role reward"""
        removed = remove_level_role(inter.guild.id, level)
        
        if removed:
            await inter.response.send_message(
                embed=discord.Embed(
                    title="Level Role Removed",
                    description=f"Removed the role reward for level {level}.",
                    color=discord.Color.orange()
                )
            )
        else:
            await inter.response.send_message(
                embed=discord.Embed(
                    title="Not Found",
                    description=f"No role reward exists for level {level}.",
                    color=discord.Color.red()
                )
            )

    @levelup_group.command(name="list", description="List all level role rewards")
    async def levelup_list(self, inter: discord.Interaction):
        """List all level role rewards"""
        level_roles = get_all_level_roles(inter.guild.id)
        
        if not level_roles:
            await inter.response.send_message(
                embed=discord.Embed(
                    title="Level Roles",
                    description="No level roles configured yet.",
                    color=discord.Color.blue()
                )
            )
            return
        
        embed = discord.Embed(
            title="Level Role Rewards",
            color=discord.Color.blue()
        )
        
        lines = []
        for entry in level_roles:
            level = entry["level"]
            role_id = entry["role_id"]
            role = inter.guild.get_role(role_id)
            role_mention = role.mention if role else f"<@&{role_id}>"
            lines.append(f"Level {level}: {role_mention}")
        
        embed.description = "\n".join(lines)
        
        await inter.response.send_message(embed=embed)

    @commands.hybrid_command(name="xpexclude", description="Exclude a user from XP")
    @app_commands.default_permissions(administrator=True)
    @commands.has_permissions(administrator=True)
    @app_commands.describe(member="The member to exclude")
    async def xpexclude(self, ctx: commands.Context, member: discord.Member):
        """Exclude a user from XP tracking"""
        set_xp_excluded(member.id, ctx.guild.id, True)
        
        await ctx.send(
            embed=discord.Embed(
                title="User Excluded",
                description=f"{member.mention} will no longer earn XP.",
                color=discord.Color.orange()
            )
        )

    @xpexclude.error
    async def xpexclude_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.", ephemeral=True)

    @commands.hybrid_command(name="xpinclude", description="Re-include a user in XP")
    @app_commands.default_permissions(administrator=True)
    @commands.has_permissions(administrator=True)
    @app_commands.describe(member="The member to re-include")
    async def xpinclude(self, ctx: commands.Context, member: discord.Member):
        """Re-include a user in XP tracking"""
        set_xp_excluded(member.id, ctx.guild.id, False)
        
        await ctx.send(
            embed=discord.Embed(
                title="User Included",
                description=f"{member.mention} can now earn XP again.",
                color=discord.Color.green()
            )
        )

    @xpinclude.error
    async def xpinclude_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        
        xp_data = get_xp_data(message.author.id, message.guild.id)
        
        if xp_data and xp_data.get("is_excluded", 0):
            return
        
        user_id = message.author.id
        guild_id = message.guild.id
        channel_id = message.channel.id
        
        now = datetime.now(timezone.utc)
        last_message = message_cooldowns[guild_id].get((user_id, channel_id))
        
        if last_message and (now - last_message).total_seconds() < MESSAGE_COOLDOWN_SECONDS:
            return
        
        message_cooldowns[guild_id][(user_id, channel_id)] = now
        
        xp_amount = random.randint(MESSAGE_XP_MIN, MESSAGE_XP_MAX)
        
        xp_data = add_xp(user_id, guild_id, xp_amount)
        increment_message_count(user_id, guild_id)
        
        last_daily = xp_data.get("last_daily_bonus")
        if last_daily:
            last_daily_dt = datetime.fromisoformat(last_daily) if isinstance(last_daily, str) else last_daily
            if last_daily_dt.tzinfo:
                last_daily_dt = last_daily_dt.replace(tzinfo=None)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
            if last_daily_dt < today_start:
                add_xp(user_id, guild_id, DAILY_BONUS_XP)
                update_last_daily_bonus(user_id, guild_id)
                try:
                    await message.channel.send(
                        f"\U0001f389 {message.author.mention} earned a daily bonus of {DAILY_BONUS_XP} XP!",
                        delete_after=5
                    )
                except discord.Forbidden:
                    pass
        else:
            update_last_daily_bonus(user_id, guild_id)
        
        await self.check_level_up(message.author, message.guild, xp_data)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        if member.bot or not member.guild:
            return
        
        xp_data = get_xp_data(member.id, member.guild.id)
        if xp_data and xp_data.get("is_excluded", 0):
            return
        
        user_id = member.id
        guild_id = member.guild.id
        
        if before.channel is None and after.channel is not None:
            voice_sessions[user_id] = {
                "guild_id": guild_id,
                "channel_id": after.channel.id,
                "start_time": datetime.now(timezone.utc)
            }
        
        elif before.channel is not None and after.channel is None:
            if user_id in voice_sessions:
                session = voice_sessions[user_id]
                if session["guild_id"] == guild_id:
                    elapsed = (datetime.now(timezone.utc) - session["start_time"]).total_seconds()
                    
                    xp_to_add = min(int(elapsed / 60) * VOICE_XP_PER_MINUTE, VOICE_MAX_XP_PER_SESSION)
                    
                    if xp_to_add > 0:
                        add_xp(user_id, guild_id, xp_to_add)
                        update_voice_seconds(user_id, guild_id, int(elapsed))
                        
                        xp_data = get_xp_data(user_id, guild_id)
                        await self.check_level_up(member, member.guild, xp_data)
                
                del voice_sessions[user_id]
        
        elif before.channel != after.channel:
            if user_id in voice_sessions:
                session = voice_sessions[user_id]
                if session["guild_id"] == guild_id and session["channel_id"] == before.channel.id:
                    elapsed = (datetime.now(timezone.utc) - session["start_time"]).total_seconds()
                    
                    xp_to_add = min(int(elapsed / 60) * VOICE_XP_PER_MINUTE, VOICE_MAX_XP_PER_SESSION)
                    
                    if xp_to_add > 0:
                        add_xp(user_id, guild_id, xp_to_add)
                        update_voice_seconds(user_id, guild_id, int(elapsed))
                        
                        xp_data = get_xp_data(user_id, guild_id)
                        await self.check_level_up(member, member.guild, xp_data)
                    
                    voice_sessions[user_id] = {
                        "guild_id": guild_id,
                        "channel_id": after.channel.id,
                        "start_time": datetime.now(timezone.utc)
                    }

    async def check_level_up(self, member: discord.Member, guild: discord.Guild, xp_data: dict):
        if not xp_data:
            return
        
        xp = xp_data["xp"]
        old_level = xp_data.get("level", 0)
        new_level = calculate_level(xp)
        
        if new_level > old_level:
            update_xp_level(member.id, guild.id, xp, new_level)
            
            role_id = get_level_role(guild.id, new_level)
            if not role_id:
                config = get_level_role_config(guild.id, new_level)
                if config and config.get("created_role_id"):
                    role_id = config["created_role_id"]
            
            if role_id:
                role = guild.get_role(role_id)
                if role and role not in member.roles:
                    try:
                        await member.add_roles(role, reason=f"Reached level {new_level}")
                    except discord.Forbidden:
                        pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(XP(bot))
