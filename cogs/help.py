import discord
from discord import Embed
from discord.ext import commands
from colors import Color


CATEGORIES = [
    {
        "label":       "Moderation",
        "emoji":       "🛡️",
        "color":       Color.NAVY,
        "description": "manual tools for channel and message management.\nrequires **manage messages** or **manage channels**.",
        "commands": [
            ("!purge <amount> [@user]", "bulk-delete messages in this channel"),
            ("!slowmode <seconds>",     "set slowmode delay — `0` to disable"),
            ("!lock",                   "prevent @everyone from sending messages"),
            ("!unlock",                 "restore @everyone message permissions"),
        ],
    },
    {
        "label":       "Auto-Mod",
        "emoji":       "🤖",
        "color":       Color.PLUM,
        "description": "automatic moderation and escalating warn system.\nrequires **manage messages** for warn commands.",
        "commands": [
            ("!warnings [@user]",    "view a member's active warnings"),
            ("!clearwarnings @user", "clear all warnings for a member"),
        ],
    },
    {
        "label":       "Config",
        "emoji":       "⚙️",
        "color":       Color.BLUE_GRAY,
        "description": "per-server configuration.\nrequires **manage server**.",
        "commands": [
            ("!config",                               "show current server settings"),
            ("!config automod <on/off>",              "toggle auto-moderation"),
            ("!config maxwarns <1–10>",               "set warning count before action"),
            ("!config warnaction <timeout/kick/ban>", "set action at max warnings"),
            ("!config filter <type> <on/off>",        "toggle a content filter"),
            ("!config threshold <type> <value>",      "adjust a filter's sensitivity"),
            ("!config logchannel [#channel]",         "set (or clear) the mod-action log channel"),
        ],
    },
    {
        "label":       "Images",
        "emoji":       "🖼️",
        "color":       Color.GRAY,
        "description": "image filters, generation, and utilities.\navailable to all members.",
        "commands": [
            ("!filter <filter> [@user]", "apply a filter to an image or avatar"),
            ("!ascii [width] [@user]",   "convert an image to ascii art"),
            ("!colors [num] [@user]",    "extract dominant colors from an image"),
            ("!quote",                   "generate a quote card — reply to a message"),
            ("!avatar [@user]",          "show a user's full-size avatar"),
        ],
    },
    {
        "label":       "Starboard",
        "emoji":       "⭐",
        "color":       Color.BLUE_GRAY,
        "description": "reposts highly-starred messages to a dedicated channel.\nrequires **manage channels** to configure.",
        "commands": [
            ("!starboard",                   "show current starboard settings"),
            ("!starboard channel #channel",  "set the starboard channel"),
            ("!starboard threshold <n>",     "set the star count required"),
            ('!starboard emojis {"⭐": 1}',  "set emoji weights as json"),
        ],
    },
    {
        "label":       "Appeals",
        "emoji":       "📋",
        "color":       Color.PLUM,
        "description": "review ban appeals submitted by banned users via dm.\nrequires **ban members**.",
        "commands": [
            ("!appeals",             "list all pending ban appeals"),
            ("!appeal <id>",         "view details of a specific appeal"),
            ("!appeal <id> approve", "approve the appeal and unban the user"),
            ("!appeal <id> deny",    "deny the appeal"),
        ],
    },
    {
        "label":       "General",
        "emoji":       "✨",
        "color":       Color.GRAY,
        "description": "core bot commands.",
        "commands": [
            ("!ping",   "check roundtrip and api latency"),
            ("!reload", "reload all cogs — owner only"),
            ("!help",   "show this menu"),
        ],
    },
]


def _home_embed(bot: commands.Bot) -> Embed:
    embed = Embed(
        title="laciedc — help",
        description=(
            "a discord moderation bot with auto-mod, image tools, and a starboard.\n"
            "use the menu below or the arrows to browse categories.\n\u200b"
        ),
        color=Color.NAVY,
    )
    for cat in CATEGORIES:
        count = len(cat["commands"])
        embed.add_field(
            name=f"{cat['emoji']} {cat['label']}",
            value=f"{cat['description'].splitlines()[0]}\n`{count} command{'s' if count != 1 else ''}`",
            inline=True,
        )
    embed.set_footer(text=f"{len(bot.guilds)} guild{'s' if len(bot.guilds) != 1 else ''} · prefix: !")
    return embed


def _category_embed(cat: dict, page: int, total: int) -> Embed:
    embed = Embed(
        title=f"{cat['emoji']} {cat['label']}",
        description=cat["description"] + "\n\u200b",
        color=cat["color"],
    )
    lines = "\n".join(f"`{usage}` — {desc}" for usage, desc in cat["commands"])
    embed.add_field(name="commands", value=lines, inline=False)
    embed.set_footer(text=f"page {page} of {total}")
    return embed


def _build_embeds(bot: commands.Bot) -> list[Embed]:
    total  = len(CATEGORIES)
    embeds = [_home_embed(bot)]
    for i, cat in enumerate(CATEGORIES, start=1):
        embeds.append(_category_embed(cat, i, total))
    return embeds


class HelpView(discord.ui.View):
    def __init__(self, embeds: list[Embed], author_id: int):
        super().__init__(timeout=120)
        self.embeds    = embeds
        self.page      = 0
        self.author_id = author_id
        self.message: discord.Message | None = None

        self._prev          = discord.ui.Button(emoji="◀", style=discord.ButtonStyle.secondary, row=0, disabled=True)
        self._prev.callback = self._on_prev
        self.add_item(self._prev)

        self._next          = discord.ui.Button(emoji="▶", style=discord.ButtonStyle.secondary, row=0)
        self._next.callback = self._on_next
        self.add_item(self._next)

        options = [discord.SelectOption(label="overview", value="0", emoji="🏠", default=True)]
        for i, cat in enumerate(CATEGORIES, start=1):
            options.append(discord.SelectOption(label=cat["label"].lower(), value=str(i), emoji=cat["emoji"]))
        self._select          = discord.ui.Select(placeholder="jump to a category…", options=options, row=1)
        self._select.callback = self._on_select
        self.add_item(self._select)

    def _sync(self):
        self._prev.disabled = self.page == 0
        self._next.disabled = self.page == len(self.embeds) - 1
        for opt in self._select.options:
            opt.default = opt.value == str(self.page)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("this menu isn't yours.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def _on_prev(self, interaction: discord.Interaction):
        self.page -= 1
        self._sync()
        await interaction.response.edit_message(embed=self.embeds[self.page], view=self)

    async def _on_next(self, interaction: discord.Interaction):
        self.page += 1
        self._sync()
        await interaction.response.edit_message(embed=self.embeds[self.page], view=self)

    async def _on_select(self, interaction: discord.Interaction):
        self.page = int(self._select.values[0])
        self._sync()
        await interaction.response.edit_message(embed=self.embeds[self.page], view=self)


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self._cache: list[Embed] | None = None

    def _get_embeds(self) -> list[Embed]:
        if self._cache is None:
            self._cache = _build_embeds(self.bot)
        return self._cache

    @commands.command(name="help")
    async def help(self, ctx: commands.Context):
        embeds       = self._get_embeds()
        view         = HelpView(embeds, ctx.author.id)
        view.message = await ctx.send(embed=embeds[0], view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
