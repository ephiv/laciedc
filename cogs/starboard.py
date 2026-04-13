import json
import discord
from discord.ext import commands
from database import db
from utils.embeds import EmbedBuilder
from colors import Color as ColorPalette


class Starboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_settings(self, guild_id: int) -> dict:
        settings = await db.get_guild_settings(guild_id)
        
        emoji_weights = settings.get("emoji_weights")
        if isinstance(emoji_weights, str):
            emoji_weights = json.loads(emoji_weights)
        elif emoji_weights is None:
            emoji_weights = {"⭐": 1, "✨": 2}
        
        return {
            "channel_id": settings.get("starboard_channel_id"),
            "threshold": settings.get("starboard_threshold", 5),
            "emoji_weights": emoji_weights,
        }

    async def calculate_score(
        self, message: discord.Message, emoji_weights: dict
    ) -> int:
        total = 0
        for reaction in message.reactions:
            async for user in reaction.users():
                emoji = str(reaction.emoji)
                weight = emoji_weights.get(emoji, 0)
                if reaction.count > 0:
                    total += weight * reaction.count
        return total

    async def send_to_starboard(
        self, message: discord.Message, settings: dict
    ):
        channel = message.guild.get_channel(settings["channel_id"])
        if not channel:
            return

        embed = discord.Embed(
            description=message.content,
            color=ColorPalette.GRAY,
            timestamp=message.created_at,
        )
        embed.set_author(
            name=message.author.display_name,
            icon_url=message.author.display_avatar.url,
        )
        embed.set_footer(text=f"#{message.channel.name}")

        if message.attachments:
            attachment = message.attachments[0]
            if attachment.content_type and attachment.content_type.startswith("image"):
                embed.set_image(url=attachment.url)

        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if user.bot:
            return

        message = reaction.message
        if not message.guild:
            return

        settings = await self.get_settings(message.guild.id)
        if not settings["channel_id"]:
            return

        emoji = str(reaction.emoji)
        emoji_weights = settings["emoji_weights"]
        
        if emoji not in emoji_weights:
            return

        score = await self.calculate_score(message, emoji_weights)
        
        if score >= settings["threshold"]:
            await self.send_to_starboard(message, settings)

@commands.command(name="starboard", description="Configure starboard")
    @commands.has_permissions(manage_channels=True)
    async def configure_starboard(self, ctx, channel: discord.TextChannel = None):
        print(f"Starboard command called by {ctx.author} in {ctx.guild}")
        await ctx.send("Testing - starboard command works!")

    @commands.command(name="starboard-weights", description="Set emoji weights")
    @commands.has_permissions(manage_channels=True)
    async def set_weights(self, ctx, *, weights: str):
        try:
            emoji_weights = json.loads(weights)
        except:
            embed = EmbedBuilder.error(
                "Invalid Format",
                "Use JSON: `{'⭐': 1, '✨': 2}`"
            )
            await ctx.send(embed=embed)
            return

        await db.update_guild_setting(
            ctx.guild.id, "emoji_weights", json.dumps(emoji_weights)
        )

        embed = EmbedBuilder.success(
            "Weights Updated",
            f"Emoji weights set to: {weights}"
        )
        await ctx.send(embed=embed)

    @configure_starboard.error
    @set_weights.error
    async def error_handler(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            embed = EmbedBuilder.error(
                "Permission Denied",
                "You need **Manage Channels** permission."
            )
            await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Starboard(bot))