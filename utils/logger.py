# Fix 5 — audit logger used by all cogs that take mod actions.
# Reads log_channel_id from guild settings; silently no-ops if unset.
import discord
from database import db
from utils.embeds import EmbedBuilder
from colors import Color


async def log_action(
    bot: discord.Client,
    guild_id: int,
    title: str,
    description: str,
    color=None,
):
    """Send a mod-action embed to the guild's configured log channel."""
    settings   = await db.get_guild_settings(guild_id)
    channel_id = settings.get("log_channel_id")
    if not channel_id:
        return
    channel = bot.get_channel(channel_id)
    if not channel:
        return
    embed = EmbedBuilder.create(
        title=title,
        description=description,
        color=color or Color.NAVY,
        timestamp=True,
    )
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass
