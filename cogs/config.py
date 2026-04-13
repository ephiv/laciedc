from discord import app_commands
from discord.ext import commands
from database import db
from utils.embeds import EmbedBuilder
from colors import Color as ColorPalette


class Config(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    config_group = app_commands.Group(name="config", description="Server configuration")

    @config_group.command(name="show", description="Show current server settings")
    async def show_config(self, interaction):
        await interaction.response.defer()
        settings = await db.get_guild_settings(interaction.guild.id)

        fields = [
            {"name": "Auto-Mod", "value": f"{'Enabled' if settings['auto_mod_enabled'] else 'Disabled'}", "inline": True},
            {"name": "Max Warns", "value": str(settings['max_warns']), "inline": True},
            {"name": "Warn Action", "value": settings['warn_action'].capitalize(), "inline": True},
            {"name": "Profanity Filter", "value": str(settings['filter_profanity']), "inline": True},
            {"name": "Spam Filter", "value": str(settings['filter_spam']), "inline": True},
            {"name": "Invite Filter", "value": str(settings['filter_invites']), "inline": True},
            {"name": "Link Filter", "value": str(settings['filter_links']), "inline": True},
            {"name": "Caps Filter", "value": str(settings['filter_caps']), "inline": True},
            {"name": "Mention Filter", "value": str(settings['filter_mentions']), "inline": True},
            {"name": "Caps Threshold", "value": f"{settings['caps_threshold']}%", "inline": True},
            {"name": "Mention Threshold", "value": str(settings['mention_threshold']), "inline": True},
            {"name": "Spam Threshold", "value": str(settings['spam_threshold']), "inline": True},
        ]

        embed = EmbedBuilder.create(
            title="⚙️ Server Configuration",
            color=ColorPalette.NAVY,
            fields=fields,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @config_group.command(name="auto-mod", description="Toggle auto-mod on/off")
    @app_commands.describe(state="Enable or disable auto-mod")
    async def toggle_auto_mod(self, interaction, state: bool):
        await db.update_guild_setting(interaction.guild.id, "auto_mod_enabled", state)
        embed = EmbedBuilder.success(
            "Auto-Mod Toggled",
            f"Auto-mod is now **{'enabled' if state else 'disabled'}**"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @config_group.command(name="max-warns", description="Set max warnings before action")
    @app_commands.describe(number="Number of warns (1-10)")
    async def set_max_warns(self, interaction, number: int):
        if not 1 <= number <= 10:
            embed = EmbedBuilder.error("Invalid Value", "Number must be between 1 and 10")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await db.update_guild_setting(interaction.guild.id, "max_warns", number)
        embed = EmbedBuilder.success(
            "Max Warns Updated",
            f"Max warns set to **{number}**"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @config_group.command(name="warn-action", description="Set action on max warns")
    @app_commands.describe(action="Action to take (timeout/kick/ban)")
    async def set_warn_action(self, interaction, action: str):
        if action not in ["timeout", "kick", "ban"]:
            embed = EmbedBuilder.error("Invalid Action", "Action must be: timeout, kick, or ban")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await db.update_guild_setting(interaction.guild.id, "warn_action", action)
        embed = EmbedBuilder.success(
            "Warn Action Updated",
            f"Action on max warns set to **{action}**"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @config_group.command(name="filter", description="Toggle a specific filter")
    @app_commands.describe(filter="Filter to toggle", state="Enable or disable")
    async def toggle_filter(self, interaction, filter: str, state: bool):
        valid_filters = [
            "profanity", "spam", "invites", "links", "caps", "mentions"
        ]
        if filter not in valid_filters:
            embed = EmbedBuilder.error(
                "Invalid Filter",
                f"Valid filters: {', '.join(valid_filters)}"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await db.update_guild_setting(
            interaction.guild.id, f"filter_{filter}", state
        )
        embed = EmbedBuilder.success(
            "Filter Updated",
            f"**{filter.capitalize()}** filter is now **{'enabled' if state else 'disabled'}**"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @config_group.command(name="threshold", description="Set filter threshold")
    @app_commands.describe(type="Threshold type (caps/mention/spam)", value="Threshold value")
    async def set_threshold(self, interaction, type: str, value: int):
        valid_thresholds = {
            "caps": (5, 50),
            "mention": (2, 20),
            "spam": (2, 10),
        }

        if type not in valid_thresholds:
            embed = EmbedBuilder.error(
                "Invalid Type",
                f"Valid types: {', '.join(valid_thresholds.keys())}"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        min_val, max_val = valid_thresholds[type]
        if not min_val <= value <= max_val:
            embed = EmbedBuilder.error(
                "Invalid Value",
                f"Value must be between {min_val} and {max_val}"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await db.update_guild_setting(
            interaction.guild.id, f"{type}_threshold", value
        )
        embed = EmbedBuilder.success(
            "Threshold Updated",
            f"**{type.capitalize()}** threshold set to **{value}**"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Config(bot))