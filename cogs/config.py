import discord
from discord import app_commands
from discord.ext import commands
from database import db
from utils.embeds import EmbedBuilder
from colors import Color


class Config(commands.Cog):
    """Slash-command interface for per-guild bot configuration."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    config_group = app_commands.Group(
        name="config",
        description="Server configuration",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # ------------------------------------------------------------------ #
    #  /config show                                                        #
    # ------------------------------------------------------------------ #

    @config_group.command(name="show", description="Display the current server configuration")
    async def show(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        s = await db.get_guild_settings(interaction.guild.id)

        def toggle(v: bool) -> str:
            return "✅ On" if v else "❌ Off"

        fields = [
            {"name": "Auto-Mod",         "value": toggle(s["auto_mod_enabled"]),              "inline": True},
            {"name": "Max Warnings",     "value": str(s["max_warns"]),                         "inline": True},
            {"name": "Warn Action",      "value": s["warn_action"].capitalize(),               "inline": True},
            {"name": "Profanity Filter", "value": toggle(s["filter_profanity"]),               "inline": True},
            {"name": "Spam Filter",      "value": toggle(s["filter_spam"]),                    "inline": True},
            {"name": "Invite Filter",    "value": toggle(s["filter_invites"]),                 "inline": True},
            {"name": "Link Filter",      "value": toggle(s["filter_links"]),                   "inline": True},
            {"name": "Caps Filter",      "value": toggle(s["filter_caps"]),                    "inline": True},
            {"name": "Mention Filter",   "value": toggle(s["filter_mentions"]),                "inline": True},
            {"name": "Caps Threshold",   "value": f"{s['caps_threshold']}% uppercase",        "inline": True},
            {"name": "Mention Threshold","value": f"{s['mention_threshold']} mentions",       "inline": True},
            {"name": "Spam Threshold",   "value": f"{s['spam_threshold']} identical messages","inline": True},
        ]

        embed = EmbedBuilder.create(
            title="⚙️ Server Configuration",
            color=Color.NAVY,
            fields=fields,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------ #
    #  /config automod                                                     #
    # ------------------------------------------------------------------ #

    @config_group.command(name="automod", description="Enable or disable auto-moderation")
    @app_commands.describe(enabled="Turn auto-mod on or off")
    async def automod(self, interaction: discord.Interaction, enabled: bool):
        await db.update_guild_setting(interaction.guild.id, "auto_mod_enabled", enabled)
        state = "enabled" if enabled else "disabled"
        embed = EmbedBuilder.success("Auto-Mod Updated", f"Auto-moderation is now **{state}**.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------ #
    #  /config maxwarns                                                    #
    # ------------------------------------------------------------------ #

    @config_group.command(name="maxwarns", description="Set how many warnings trigger an action")
    @app_commands.describe(number="Number of warnings before action (1–10)")
    async def maxwarns(
        self,
        interaction: discord.Interaction,
        number: app_commands.Range[int, 1, 10],
    ):
        await db.update_guild_setting(interaction.guild.id, "max_warns", number)
        embed = EmbedBuilder.success("Max Warnings Updated", f"Action will be taken after **{number}** warning(s).")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------ #
    #  /config warnaction                                                  #
    # ------------------------------------------------------------------ #

    @config_group.command(name="warnaction", description="Set the action taken when max warnings are reached")
    @app_commands.describe(action="What to do when a user hits max warnings")
    @app_commands.choices(action=[
        app_commands.Choice(name="Timeout (30 min)", value="timeout"),
        app_commands.Choice(name="Kick",              value="kick"),
        app_commands.Choice(name="Ban",               value="ban"),
    ])
    async def warnaction(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
    ):
        await db.update_guild_setting(interaction.guild.id, "warn_action", action.value)
        embed = EmbedBuilder.success("Warn Action Updated", f"Users who reach max warnings will be **{action.name}**.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------ #
    #  /config filter                                                      #
    # ------------------------------------------------------------------ #

    @config_group.command(name="filter", description="Enable or disable a specific content filter")
    @app_commands.describe(name="Which filter to change", enabled="Turn the filter on or off")
    @app_commands.choices(name=[
        app_commands.Choice(name="Profanity", value="profanity"),
        app_commands.Choice(name="Spam",      value="spam"),
        app_commands.Choice(name="Invites",   value="invites"),
        app_commands.Choice(name="Links",     value="links"),
        app_commands.Choice(name="Caps",      value="caps"),
        app_commands.Choice(name="Mentions",  value="mentions"),
    ])
    async def filter(
        self,
        interaction: discord.Interaction,
        name: app_commands.Choice[str],
        enabled: bool,
    ):
        await db.update_guild_setting(interaction.guild.id, f"filter_{name.value}", enabled)
        state = "enabled" if enabled else "disabled"
        embed = EmbedBuilder.success("Filter Updated", f"The **{name.name}** filter is now **{state}**.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------ #
    #  /config threshold                                                   #
    # ------------------------------------------------------------------ #

    THRESHOLD_BOUNDS: dict[str, tuple[int, int, str]] = {
        "caps":    (10, 90, "caps_threshold",    "% uppercase letters to trigger"),
        "mention": (2,  20, "mention_threshold", "mentions to trigger"),
        "spam":    (2,  10, "spam_threshold",    "identical messages to trigger"),
    }

    @config_group.command(name="threshold", description="Adjust a filter's sensitivity threshold")
    @app_commands.describe(filter="Which threshold to adjust", value="New threshold value")
    @app_commands.choices(filter=[
        app_commands.Choice(name="Caps (% uppercase)",          value="caps"),
        app_commands.Choice(name="Mentions (count)",            value="mention"),
        app_commands.Choice(name="Spam (identical messages)",   value="spam"),
    ])
    async def threshold(
        self,
        interaction: discord.Interaction,
        filter: app_commands.Choice[str],
        value: int,
    ):
        min_v, max_v, db_key, unit = self.THRESHOLD_BOUNDS[filter.value]

        if not min_v <= value <= max_v:
            embed = EmbedBuilder.error(
                "Out of Range",
                f"**{filter.name}** threshold must be between **{min_v}** and **{max_v}**.",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await db.update_guild_setting(interaction.guild.id, db_key, value)
        embed = EmbedBuilder.success(
            "Threshold Updated",
            f"**{filter.name}** threshold set to **{value}** {unit}.",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Config(bot))
