import json
import discord
from discord.ext import commands
from database import db
from utils.embeds import EmbedBuilder
from colors import Color


# Star yellow — distinct from the bot's color palette
_STAR_COLOR = 0xFFAC33


class Starboard(commands.Cog):
    """
    Reposts highly-starred messages to a dedicated starboard channel.

    - The score for a message is: sum(emoji_weight × reaction_count)
      for every tracked emoji.
    - A message is posted exactly once when its score first hits the
      threshold.  Further reactions update the star count in the footer
      of the already-posted starboard entry.
    - Removing stars edits the footer count downward (but never deletes
      the post — once a message makes the board it stays).
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Settings helpers ──────────────────────────────────────────────── #

    async def _settings(self, guild_id: int) -> dict:
        s = await db.get_guild_settings(guild_id)
        raw = s.get("emoji_weights") or '{"⭐": 1}'
        try:
            weights = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            weights = {"⭐": 1}
        return {
            "channel_id": s.get("starboard_channel_id"),
            "threshold":  s.get("starboard_threshold") or 5,
            "weights":    weights,
        }

    def _score(self, message: discord.Message, weights: dict) -> int:
        total = 0
        for reaction in message.reactions:
            w = weights.get(str(reaction.emoji), 0)
            if w:
                total += reaction.count * w
        return total

    # ── Embed builder ─────────────────────────────────────────────────── #

    def _build_embed(self, message: discord.Message, score: int) -> discord.Embed:
        embed = discord.Embed(
            description=message.content or "",
            color=_STAR_COLOR,
            timestamp=message.created_at,
        )
        embed.set_author(
            name=message.author.display_name,
            icon_url=message.author.display_avatar.url,
        )
        embed.add_field(
            name="source",
            value=f"[jump to message]({message.jump_url}) in {message.channel.mention}",
            inline=False,
        )

        # Attach the first image if present
        for att in message.attachments:
            if att.content_type and att.content_type.startswith("image/"):
                embed.set_image(url=att.url)
                break

        embed.set_footer(text=f"⭐ {score} · #{message.channel.name}")
        return embed

    # ── Starboard post lifecycle ──────────────────────────────────────── #

    async def _post(
        self,
        sb_channel: discord.TextChannel,
        message: discord.Message,
        score: int,
        guild_id: int,
    ):
        """Post a message to the starboard for the first time."""
        embed  = self._build_embed(message, score)
        sb_msg = await sb_channel.send(embed=embed)
        await db.add_starboard_post(guild_id, message.id, message.channel.id, sb_msg.id)

    async def _update(
        self,
        sb_channel: discord.TextChannel,
        sb_msg_id: int,
        message: discord.Message,
        score: int,
    ):
        """Edit an existing starboard post to reflect the current score."""
        try:
            sb_msg = await sb_channel.fetch_message(sb_msg_id)
        except discord.NotFound:
            return

        embed = self._build_embed(message, score)
        await sb_msg.edit(embed=embed)

    # ── Reaction listeners ───────────────────────────────────────────── #

    async def _handle_reaction(self, reaction: discord.Reaction, user: discord.User):
        if user.bot or not reaction.message.guild:
            return

        message  = reaction.message
        guild_id = message.guild.id
        settings = await self._settings(guild_id)

        if not settings["channel_id"]:
            return
        if str(reaction.emoji) not in settings["weights"]:
            return

        # Fetch fresh message so reaction counts are accurate
        try:
            message = await message.channel.fetch_message(message.id)
        except discord.HTTPException:
            return

        score = self._score(message, settings["weights"])

        sb_channel = message.guild.get_channel(settings["channel_id"])
        if not sb_channel:
            return

        # Don't allow starring messages posted in the starboard itself
        if message.channel.id == settings["channel_id"]:
            return

        existing = await db.get_starboard_post(guild_id, message.id)

        if existing:
            await self._update(sb_channel, existing["starboard_message_id"], message, score)
        elif score >= settings["threshold"]:
            await self._post(sb_channel, message, score, guild_id)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        await self._handle_reaction(reaction, user)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction: discord.Reaction, user: discord.User):
        await self._handle_reaction(reaction, user)

    # ── !starboard command group ─────────────────────────────────────── #

    @commands.group(
        name="starboard",
        description="Configure the starboard",
        invoke_without_command=True,
    )
    @commands.has_permissions(manage_channels=True)
    async def starboard_cmd(self, ctx: commands.Context):
        """Show current starboard settings."""
        settings = await self._settings(ctx.guild.id)

        channel_val = (
            f"<#{settings['channel_id']}>"
            if settings["channel_id"]
            else "not set — use `!starboard channel #channel`"
        )
        weights_fmt = ", ".join(
            f"{e} × {w}" for e, w in settings["weights"].items()
        )

        fields = [
            {"name": "Channel",         "value": channel_val,            "inline": False},
            {"name": "Threshold",       "value": str(settings["threshold"]), "inline": True},
            {"name": "Emoji Weights",   "value": weights_fmt,            "inline": True},
        ]
        embed = EmbedBuilder.create(
            title="⭐ Starboard Settings",
            color=Color.BLUE_GRAY,
            fields=fields,
        )
        await ctx.send(embed=embed)

    @starboard_cmd.command(name="channel", description="Set (or clear) the starboard channel")
    async def sb_channel(
        self, ctx: commands.Context, channel: discord.TextChannel = None
    ):
        value = channel.id if channel else None
        await db.update_guild_setting(ctx.guild.id, "starboard_channel_id", value)
        if channel:
            await ctx.send(embed=EmbedBuilder.success(
                "Starboard Channel Set", f"Starboard posts will go to {channel.mention}."
            ))
        else:
            await ctx.send(embed=EmbedBuilder.success(
                "Starboard Disabled", "Starboard channel cleared — no messages will be posted."
            ))

    @starboard_cmd.command(name="threshold", description="Set the star count needed to be posted")
    async def sb_threshold(self, ctx: commands.Context, number: int):
        if not 1 <= number <= 100:
            await ctx.send(embed=EmbedBuilder.error(
                "Out of Range", "Threshold must be between **1** and **100**."
            ))
            return
        await db.update_guild_setting(ctx.guild.id, "starboard_threshold", number)
        await ctx.send(embed=EmbedBuilder.success(
            "Threshold Updated",
            f"Messages need **{number}** star(s) to appear on the starboard.",
        ))

    @starboard_cmd.command(name="emojis", description='Set emoji weights as JSON e.g. {"⭐":1,"✨":2}')
    async def sb_emojis(self, ctx: commands.Context, *, weights: str):
        try:
            parsed = json.loads(weights)
            if not isinstance(parsed, dict) or not parsed:
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            await ctx.send(embed=EmbedBuilder.error(
                "Invalid Format",
                'Provide valid JSON, e.g. `{"⭐": 1, "✨": 2}`',
            ))
            return

        await db.update_guild_setting(ctx.guild.id, "emoji_weights", json.dumps(parsed))
        formatted = ", ".join(f"{e} × {w}" for e, w in parsed.items())
        await ctx.send(embed=EmbedBuilder.success(
            "Emoji Weights Updated", f"Tracking: {formatted}"
        ))

    # ── Error handler ─────────────────────────────────────────────────── #

    async def cog_command_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=EmbedBuilder.error(
                "Permission Denied", "You need **Manage Channels** permission."
            ))
        elif isinstance(error, commands.ChannelNotFound):
            await ctx.send(embed=EmbedBuilder.error(
                "Channel Not Found", "That channel could not be found."
            ))
        elif isinstance(error, commands.BadArgument):
            await ctx.send(embed=EmbedBuilder.error("Invalid Argument", str(error)))
        elif isinstance(error, commands.MissingRequiredArgument):
            usage = {
                "threshold": "!starboard threshold <number>",
                "emojis":    '!starboard emojis {"⭐": 1, "✨": 2}',
            }.get(ctx.command.name, "!starboard")
            await ctx.send(embed=EmbedBuilder.error("Missing Argument", f"Usage: `{usage}`"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Starboard(bot))
