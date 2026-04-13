import discord
from discord import Embed
from discord.ext import commands
from colors import Color


# ------------------------------------------------------------------ #
#  Category definitions                                                #
# Each dict becomes one page. Order here = navigation order.          #
# ------------------------------------------------------------------ #

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
        "emoji":       "⚙️",
        "color":       Color.BLUE_GRAY,
        "description": "warning system and filter configuration.\nrequires **manage messages** for warn commands, **manage server** for `/config`.",
        "commands": [
            ("!warnings [@user]",    "view a member's active warnings"),
            ("!clearwarnings @user", "clear all warnings for a member"),
        ],
        "slash": [
            ("/config show",                         "display current server settings"),
            ("/config automod <on/off>",              "toggle auto-moderation on or off"),
            ("/config maxwarns <1–10>",               "set warning count before action"),
            ("/config warnaction <timeout/kick/ban>", "set the action taken at max warns"),
            ("/config filter <type> <on/off>",        "toggle a specific content filter"),
            ("/config threshold <type> <value>",      "adjust a filter's sensitivity"),
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
        "emoji":       "🤖",
        "color":       Color.GRAY,
        "description": "core bot commands.",
        "commands": [
            ("!ping",   "check roundtrip and api latency"),
            ("!reload", "reload all cogs — owner only"),
            ("!help",   "show this menu"),
        ],
    },
]


# ------------------------------------------------------------------ #
#  Embed builders                                                      #
# ------------------------------------------------------------------ #

def _home_embed(bot: commands.Bot) -> Embed:
    embed = Embed(
        title="laciedc — help",
        description=(
            "a discord bot with auto-moderation, manual mod tools, and a ban appeal system.\n"
            "use the menu below or the arrows to browse categories.\n\u200b"
        ),
        color=Color.NAVY,
    )
    for cat in CATEGORIES:
        cmd_count = len(cat["commands"]) + len(cat.get("slash", []))
        embed.add_field(
            name=f"{cat['emoji']} {cat['label']}",
            value=f"{cat['description'].splitlines()[0]}\n`{cmd_count} command{'s' if cmd_count != 1 else ''}`",
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

    prefix_lines = "\n".join(
        f"`{usage}` — {desc}" for usage, desc in cat["commands"]
    )
    embed.add_field(name="prefix commands", value=prefix_lines, inline=False)

    if cat.get("slash"):
        slash_lines = "\n".join(
            f"`{usage}` — {desc}" for usage, desc in cat["slash"]
        )
        embed.add_field(name="\u200b\nslash commands", value=slash_lines, inline=False)

    embed.set_footer(text=f"page {page} of {total}")
    return embed


def _build_embeds(bot: commands.Bot) -> list[Embed]:
    total = len(CATEGORIES)
    embeds = [_home_embed(bot)]
    for i, cat in enumerate(CATEGORIES, start=1):
        embeds.append(_category_embed(cat, i, total))
    return embeds


# ------------------------------------------------------------------ #
#  View                                                                #
# ------------------------------------------------------------------ #

class HelpView(discord.ui.View):
    def __init__(self, embeds: list[Embed], author_id: int):
        super().__init__(timeout=120)
        self.embeds    = embeds
        self.page      = 0
        self.author_id = author_id
        self.message: discord.Message | None = None

        # Prev button
        self._prev = discord.ui.Button(
            emoji="◀",
            style=discord.ButtonStyle.secondary,
            row=0,
            disabled=True,
        )
        self._prev.callback = self._on_prev
        self.add_item(self._prev)

        # Next button
        self._next = discord.ui.Button(
            emoji="▶",
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        self._next.callback = self._on_next
        self.add_item(self._next)

        # Category select
        options = [discord.SelectOption(label="overview", value="0", emoji="🏠", default=True)]
        for i, cat in enumerate(CATEGORIES, start=1):
            options.append(discord.SelectOption(
                label=cat["label"].lower(),
                value=str(i),
                emoji=cat["emoji"],
            ))
        self._select = discord.ui.Select(
            placeholder="jump to a category…",
            options=options,
            row=1,
        )
        self._select.callback = self._on_select
        self.add_item(self._select)

    # ── Sync button/select state to current page ─────────────────── #

    def _sync(self):
        self._prev.disabled = self.page == 0
        self._next.disabled = self.page == len(self.embeds) - 1
        for opt in self._select.options:
            opt.default = opt.value == str(self.page)

    # ── Guard: only the original invoker may interact ─────────────── #

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "this menu isn't yours.", ephemeral=True
            )
            return False
        return True

    # ── Disable controls when the view times out ──────────────────── #

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    # ── Callbacks ─────────────────────────────────────────────────── #

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


# ------------------------------------------------------------------ #
#  Cog                                                                 #
# ------------------------------------------------------------------ #

class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self._cache: list[Embed] | None = None  # rebuilt on reload

    def _get_embeds(self) -> list[Embed]:
        if self._cache is None:
            self._cache = _build_embeds(self.bot)
        return self._cache

    @commands.command(name="help", description="Show the help menu")
    async def help(self, ctx: commands.Context):
        embeds = self._get_embeds()
        view   = HelpView(embeds, ctx.author.id)
        view.message = await ctx.send(embed=embeds[0], view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))