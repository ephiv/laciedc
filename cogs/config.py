import discord
from discord.ext import commands
from database import db
from utils.embeds import EmbedBuilder
from colors import Color


def _parse_bool(value: str) -> bool:
    if value.lower() in ("on", "true", "yes", "1", "enable", "enabled"):
        return True
    if value.lower() in ("off", "false", "no", "0", "disable", "disabled"):
        return False
    raise commands.BadArgument(f"`{value}` is not a valid on/off value.")


class Config(commands.Cog):
    """Prefix-command interface for per-guild bot configuration."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------------ #
    #  !config — show or configure                                         #
    # ------------------------------------------------------------------ #

    @commands.group(
        name="config",
        description="View or change server configuration",
        invoke_without_command=True,
    )
    @commands.has_permissions(manage_guild=True)
    async def config_cmd(self, ctx: commands.Context):
        """Show all current settings when no subcommand is given."""
        s = await db.get_guild_settings(ctx.guild.id)

        def toggle(v: bool) -> str:
            return "✅ on" if v else "❌ off"

        fields = [
            {"name": "Auto-Mod",          "value": toggle(s["auto_mod_enabled"]),               "inline": True},
            {"name": "Max Warnings",      "value": str(s["max_warns"]),                          "inline": True},
            {"name": "Warn Action",       "value": s["warn_action"].capitalize(),                "inline": True},
            {"name": "Profanity Filter",  "value": toggle(s["filter_profanity"]),                "inline": True},
            {"name": "Spam Filter",       "value": toggle(s["filter_spam"]),                     "inline": True},
            {"name": "Invite Filter",     "value": toggle(s["filter_invites"]),                  "inline": True},
            {"name": "Link Filter",       "value": toggle(s["filter_links"]),                    "inline": True},
            {"name": "Caps Filter",       "value": toggle(s["filter_caps"]),                     "inline": True},
            {"name": "Mention Filter",    "value": toggle(s["filter_mentions"]),                 "inline": True},
            {"name": "Caps Threshold",    "value": f"{s['caps_threshold']}% uppercase",         "inline": True},
            {"name": "Mention Threshold", "value": f"{s['mention_threshold']} mentions",        "inline": True},
            {"name": "Spam Threshold",    "value": f"{s['spam_threshold']} identical messages", "inline": True},
        ]
        embed = EmbedBuilder.create(
            title="⚙️ Server Configuration",
            color=Color.NAVY,
            fields=fields,
        )
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------ #
    #  Subcommands                                                         #
    # ------------------------------------------------------------------ #

    @config_cmd.command(name="automod", description="Toggle auto-moderation on or off")
    async def config_automod(self, ctx: commands.Context, state: str):
        enabled = _parse_bool(state)
        await db.update_guild_setting(ctx.guild.id, "auto_mod_enabled", enabled)
        word = "enabled" if enabled else "disabled"
        await ctx.send(embed=EmbedBuilder.success(
            "Auto-Mod Updated", f"Auto-moderation is now **{word}**."
        ))

    @config_cmd.command(name="maxwarns", description="Set how many warnings trigger an action (1–10)")
    async def config_maxwarns(self, ctx: commands.Context, number: int):
        if not 1 <= number <= 10:
            await ctx.send(embed=EmbedBuilder.error(
                "Out of Range", "Number must be between **1** and **10**."
            ))
            return
        await db.update_guild_setting(ctx.guild.id, "max_warns", number)
        await ctx.send(embed=EmbedBuilder.success(
            "Max Warnings Updated", f"Action will be taken after **{number}** warning(s)."
        ))

    @config_cmd.command(name="warnaction", description="Set action at max warnings: timeout / kick / ban")
    async def config_warnaction(self, ctx: commands.Context, action: str):
        action = action.lower()
        if action not in ("timeout", "kick", "ban"):
            await ctx.send(embed=EmbedBuilder.error(
                "Invalid Action", "Choose one of: `timeout`, `kick`, `ban`."
            ))
            return
        await db.update_guild_setting(ctx.guild.id, "warn_action", action)
        await ctx.send(embed=EmbedBuilder.success(
            "Warn Action Updated", f"Users who hit max warnings will be **{action}**ned."
        ))

    @config_cmd.command(name="filter", description="Toggle a content filter on or off")
    async def config_filter(self, ctx: commands.Context, name: str, state: str):
        valid = ("profanity", "spam", "invites", "links", "caps", "mentions")
        if name not in valid:
            await ctx.send(embed=EmbedBuilder.error(
                "Invalid Filter",
                f"Valid filters: {', '.join(f'`{v}`' for v in valid)}",
            ))
            return
        enabled = _parse_bool(state)
        await db.update_guild_setting(ctx.guild.id, f"filter_{name}", enabled)
        word = "enabled" if enabled else "disabled"
        await ctx.send(embed=EmbedBuilder.success(
            "Filter Updated", f"The **{name}** filter is now **{word}**."
        ))

    @config_cmd.command(name="threshold", description="Adjust a filter threshold")
    async def config_threshold(self, ctx: commands.Context, type: str, value: int):
        bounds: dict[str, tuple[int, int, str, str]] = {
            "caps":    (10, 90, "caps_threshold",    "% uppercase letters"),
            "mention": (2,  20, "mention_threshold", "mentions"),
            "spam":    (2,  10, "spam_threshold",    "identical messages"),
        }
        if type not in bounds:
            await ctx.send(embed=EmbedBuilder.error(
                "Invalid Type",
                f"Valid types: {', '.join(f'`{k}`' for k in bounds)}",
            ))
            return
        lo, hi, db_key, unit = bounds[type]
        if not lo <= value <= hi:
            await ctx.send(embed=EmbedBuilder.error(
                "Out of Range", f"**{type}** threshold must be between **{lo}** and **{hi}**."
            ))
            return
        await db.update_guild_setting(ctx.guild.id, db_key, value)
        await ctx.send(embed=EmbedBuilder.success(
            "Threshold Updated", f"**{type.capitalize()}** threshold set to **{value}** {unit}."
        ))

    # ------------------------------------------------------------------ #
    #  Error handler                                                       #
    # ------------------------------------------------------------------ #

    @config_cmd.error
    async def config_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=EmbedBuilder.error(
                "Permission Denied", "You need **Manage Server** permission."
            ))
        elif isinstance(error, commands.BadArgument):
            await ctx.send(embed=EmbedBuilder.error("Bad Argument", str(error)))

    # Subcommand errors inherit from the group error handler in discord.py,
    # but explicit handlers here catch MissingRequiredArgument per-subcommand.
    async def cog_command_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingRequiredArgument):
            usage_map = {
                "automod":     "!config automod <on/off>",
                "maxwarns":    "!config maxwarns <1–10>",
                "warnaction":  "!config warnaction <timeout/kick/ban>",
                "filter":      "!config filter <name> <on/off>",
                "threshold":   "!config threshold <caps/mention/spam> <value>",
            }
            usage = usage_map.get(ctx.command.name, f"!{ctx.command.qualified_name}")
            await ctx.send(embed=EmbedBuilder.error("Missing Argument", f"Usage: `{usage}`"))
        elif isinstance(error, commands.BadArgument):
            await ctx.send(embed=EmbedBuilder.error("Bad Argument", str(error)))


async def setup(bot: commands.Bot):
    await bot.add_cog(Config(bot))
