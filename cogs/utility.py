import json
import os
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone

from .logging import error_embed, success_embed, info_embed


SNIPE_CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "snipe_cache.json")


def load_snipe_cache() -> dict:
    if os.path.exists(SNIPE_CACHE_PATH):
        try:
            with open(SNIPE_CACHE_PATH, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}


def save_snipe_cache(cache: dict):
    with open(SNIPE_CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)


def set_snipe(channel_id: int, message_data: dict):
    cache = load_snipe_cache()
    cache[str(channel_id)] = message_data
    save_snipe_cache(cache)


def get_snipe(channel_id: int) -> dict | None:
    cache = load_snipe_cache()
    return cache.get(str(channel_id))


def delete_snipe(channel_id: int):
    cache = load_snipe_cache()
    if str(channel_id) in cache:
        del cache[str(channel_id)]
        save_snipe_cache(cache)


class Utility(commands.Cog):
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

    @commands.hybrid_command(name="slowmode", description="Set slowmode for the channel")
    @app_commands.default_permissions(manage_channels=True)
    @commands.has_permissions(manage_channels=True)
    @app_commands.describe(seconds="Slowmode delay in seconds (0-21600, 0 to disable)")
    async def slowmode(self, ctx: commands.Context, seconds: int = 0):
        """Set slowmode for the channel"""
        if seconds < 0 or seconds > 21600:
            await ctx.send(embed=error_embed("Slowmode must be between 0 and 21600 seconds (6 hours)."), ephemeral=True)
            return

        try:
            await ctx.channel.edit(slowmode_delay=seconds)
            if seconds == 0:
                await ctx.send(embed=success_embed("Slowmode disabled."))
            else:
                await ctx.send(embed=success_embed(f"Slowmode set to {seconds} seconds."))
        except discord.Forbidden:
            await ctx.send(embed=error_embed("I don't have permission to change the slowmode."), ephemeral=True)
        except discord.HTTPException as e:
            await ctx.send(embed=error_embed(f"Failed to set slowmode: {e}"), ephemeral=True)

    @slowmode.error
    async def slowmode_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.", ephemeral=True)

    @commands.hybrid_command(name="lockdown", description="Lock the channel (deny @everyone send messages)")
    @app_commands.default_permissions(manage_channels=True)
    @commands.has_permissions(manage_channels=True)
    async def lockdown(self, ctx: commands.Context):
        """Lock the channel (deny @everyone send messages)"""
        try:
            await ctx.channel.set_permissions(
                ctx.guild.default_role,
                send_messages=False,
                add_reactions=False,
            )
            await ctx.send(embed=success_embed(f"Locked {ctx.channel.mention}"))
        except discord.Forbidden:
            await ctx.send(embed=error_embed("I don't have permission to lock this channel."), ephemeral=True)
        except discord.HTTPException as e:
            await ctx.send(embed=error_embed(f"Failed to lock channel: {e}"), ephemeral=True)

    @lockdown.error
    async def lockdown_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.", ephemeral=True)

    @commands.hybrid_command(name="unlock", description="Unlock the channel (allow @everyone send messages)")
    @app_commands.default_permissions(manage_channels=True)
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx: commands.Context):
        """Unlock the channel (allow @everyone send messages)"""
        try:
            await ctx.channel.set_permissions(
                ctx.guild.default_role,
                send_messages=None,
                add_reactions=None,
            )
            await ctx.send(embed=success_embed(f"Unlocked {ctx.channel.mention}"))
        except discord.Forbidden:
            await ctx.send(embed=error_embed("I don't have permission to unlock this channel."), ephemeral=True)
        except discord.HTTPException as e:
            await ctx.send(embed=error_embed(f"Failed to unlock channel: {e}"), ephemeral=True)

    @unlock.error
    async def unlock_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.", ephemeral=True)

    @commands.hybrid_command(name="snipe", description="Snipe the last deleted message in this channel")
    async def snipe(self, ctx: commands.Context):
        """Snipe the last deleted message in this channel"""
        snipe_data = get_snipe(ctx.channel.id)
        
        if not snipe_data:
            await ctx.send(embed=info_embed("Nothing to snipe", "No recently deleted messages in this channel."))
            return

        author_id = snipe_data.get("author_id")
        author_name = snipe_data.get("author_name", "Unknown")
        author_discriminator = snipe_data.get("author_discriminator", "0000")
        author_avatar = snipe_data.get("author_avatar")
        content = snipe_data.get("content", "*No content*")
        timestamp_str = snipe_data.get("timestamp")
        
        try:
            author = await self.bot.fetch_user(author_id)
            author_tag = str(author)
        except discord.NotFound:
            author_tag = f"{author_name}#{author_discriminator}"
        
        embed = discord.Embed(
            description=content,
            color=discord.Color.red(),
        )
        
        if timestamp_str:
            try:
                ts = datetime.fromisoformat(timestamp_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                embed.timestamp = ts
            except ValueError:
                embed.timestamp = discord.utils.utcnow()
        else:
            embed.timestamp = discord.utils.utcnow()
        
        if author_avatar:
            embed.set_author(name=author_tag, icon_url=author_avatar)
        else:
            embed.set_author(name=author_tag)
        
        embed.set_footer(text=f"Deleted in #{ctx.channel.name}")
        
        if snipe_data.get("attachments"):
            attachment_urls = snipe_data["attachments"]
            if attachment_urls:
                embed.add_field(name="Attachments", value="\n".join(attachment_urls), inline=False)
        
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.content:
            return
        
        snipe_data = {
            "content": message.content,
            "author_id": message.author.id,
            "author_name": message.author.name,
            "author_discriminator": message.author.discriminator if hasattr(message.author, 'discriminator') else "0",
            "author_avatar": str(message.author.display_avatar.url) if message.author.display_avatar else None,
            "timestamp": message.created_at.isoformat(),
            "attachments": [attachment.url for attachment in message.attachments] if message.attachments else [],
        }
        
        set_snipe(message.channel.id, snipe_data)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Utility(bot))
