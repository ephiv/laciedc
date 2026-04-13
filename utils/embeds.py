from discord import Embed
from datetime import datetime, timezone
from colors import Color as ColorPalette


class EmbedBuilder:
    @staticmethod
    def create(
        title: str = None,
        description: str = None,
        color=None,
        fields: list = None,
        footer: str = None,
        timestamp: bool = True,
    ):
        embed = Embed(
            title=title,
            description=description,
            color=color or ColorPalette.GRAY,
            timestamp=datetime.now(timezone.utc) if timestamp else None,
        )

        if fields:
            for field in fields:
                embed.add_field(
                    name=field.get("name", ""),
                    value=field.get("value", ""),
                    inline=field.get("inline", False),
                )

        if footer:
            embed.set_footer(text=footer)

        return embed

    @staticmethod
    def error(title: str = "Error", description: str = None):
        return EmbedBuilder.create(
            title=f"❌ {title}",
            description=description,
            color=ColorPalette.BURGUNDY,
        )

    @staticmethod
    def success(title: str = "Success", description: str = None):
        return EmbedBuilder.create(
            title=f"✅ {title}",
            description=description,
            color=ColorPalette.NAVY,
        )

    @staticmethod
    def info(title: str = "Info", description: str = None):
        return EmbedBuilder.create(
            title=f"ℹ️ {title}",
            description=description,
            color=ColorPalette.BLUE_GRAY,
        )

    @staticmethod
    def warning(title: str = "Warning", description: str = None):
        return EmbedBuilder.create(
            title=f"⚠️ {title}",
            description=description,
            color=ColorPalette.PLUM,
        )