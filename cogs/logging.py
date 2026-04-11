import discord
from datetime import datetime, timezone
from enum import Enum


class InfractionType(Enum):
    WARN = "warn"
    MUTE = "mute"
    UNMUTE = "unmute"
    KICK = "kick"
    BAN = "ban"
    UNBAN = "unban"
    TIMEOUT = "timeout"
    UNTIMEOUT = "untimeout"


class EmbedColors:
    WARN = 0xFFA500
    MUTE = 0x9B59B6
    UNMUTE = 0x2ECC71
    KICK = 0xF39C12
    BAN = 0xE74C3C
    UNBAN = 0x2ECC71
    TIMEOUT = 0x9B59B6
    UNTIMEOUT = 0x2ECC71
    AUTOMOD = 0x3498DB
    ERROR = 0xE74C3C


INFRACTION_COLORS = {
    InfractionType.WARN: EmbedColors.WARN,
    InfractionType.MUTE: EmbedColors.MUTE,
    InfractionType.UNMUTE: EmbedColors.UNMUTE,
    InfractionType.KICK: EmbedColors.KICK,
    InfractionType.BAN: EmbedColors.BAN,
    InfractionType.UNBAN: EmbedColors.UNBAN,
    InfractionType.TIMEOUT: EmbedColors.TIMEOUT,
    InfractionType.UNTIMEOUT: EmbedColors.UNTIMEOUT,
}


def get_action_emoji(action: InfractionType) -> str:
    emojis = {
        InfractionType.WARN: "\u26a0\ufe0f",
        InfractionType.MUTE: "\ud83d\udd07",
        InfractionType.UNMUTE: "\ud83d\udd0a",
        InfractionType.KICK: "\ud83d\udc62",
        InfractionType.BAN: "\ud83d\udeab",
        InfractionType.UNBAN: "\ud83d\udfe2",
        InfractionType.TIMEOUT: "\u23f1\ufe0f",
        InfractionType.UNTIMEOUT: "\u23f1\ufe0f",
    }
    return emojis.get(action, "\u2728")


def mod_log_embed(
    action: InfractionType,
    member: discord.Member | discord.User,
    moderator: discord.Member | discord.User,
    reason: str = None,
    duration: str = None,
    bot: discord.Client = None
) -> discord.Embed:
    emoji = get_action_emoji(action)
    color = INFRACTION_COLORS.get(action, EmbedColors.ERROR)
    
    action_text = action.value.capitalize()
    embed = discord.Embed(
        title=f"{emoji} Member {action_text}",
        color=color,
        timestamp=datetime.now(timezone.utc)
    )
    
    if isinstance(member, discord.Member):
        embed.set_thumbnail(url=member.display_avatar.url if member.display_avatar else None)
        user_display = f"{member} ({member.id})"
    else:
        user_display = f"{member} ({member.id})"
    
    embed.add_field(name="User", value=user_display, inline=True)
    embed.add_field(name="Moderator", value=moderator.mention if isinstance(moderator, discord.Member) else str(moderator), inline=True)
    
    if reason:
        embed.add_field(name="Reason", value=reason, inline=False)
    
    if duration:
        embed.add_field(name="Duration", value=duration, inline=True)
    
    return embed


def automod_embed(
    action_type: str,
    member: discord.Member,
    reason: str,
    bot: discord.Client = None
) -> discord.Embed:
    embed = discord.Embed(
        title=f"\ud83d\udeab Auto-Moderation: {action_type}",
        color=EmbedColors.AUTOMOD,
        timestamp=datetime.now(timezone.utc)
    )
    
    if isinstance(member, discord.Member):
        embed.set_thumbnail(url=member.display_avatar.url if member.display_avatar else None)
    
    embed.add_field(name="User", value=f"{member} ({member.id})", inline=True)
    embed.add_field(name="Action", value=reason, inline=True)
    
    return embed


def error_embed(description: str) -> discord.Embed:
    return discord.Embed(
        title="\u274c Error",
        description=description,
        color=EmbedColors.ERROR
    )


def success_embed(description: str) -> discord.Embed:
    return discord.Embed(
        title="\u2705 Success",
        description=description,
        color=EmbedColors.UNMUTE
    )


def info_embed(title: str, description: str) -> discord.Embed:
    return discord.Embed(
        title=title,
        description=description,
        color=0x3498DB
    )


async def send_mod_log(guild: discord.Guild, embed: discord.Embed, log_channel_id: int = None):
    if not log_channel_id:
        from .database import get_settings
        settings = get_settings(guild.id)
        log_channel_id = settings.get("log_channel_id") if settings else None
    
    if not log_channel_id:
        return
    
    channel = guild.get_channel(log_channel_id)
    if channel:
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass


async def send_automod_log(guild: discord.Guild, embed: discord.Embed):
    from .database import get_settings
    settings = get_settings(guild.id)
    log_channel_id = settings.get("log_channel_id") if settings else None
    
    if log_channel_id:
        channel = guild.get_channel(log_channel_id)
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                pass


async def setup(bot):
    pass
