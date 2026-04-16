import io
import asyncio
import textwrap
import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
from utils.embeds import EmbedBuilder
from colors import Color


# ── Fonts ─────────────────────────────────────────────────────────────── #

_SERIF      = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
_SERIF_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
_SANS       = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


# ── Filter registry ───────────────────────────────────────────────────── #

def _pixelate(img: Image.Image) -> Image.Image:
    small = img.resize((img.width // 10, img.height // 10), Image.NEAREST)
    return small.resize((img.width, img.height), Image.NEAREST)


FILTERS: dict[str, callable] = {
    "grayscale": lambda img: ImageOps.grayscale(img).convert("RGB"),
    "sepia":     lambda img: ImageOps.colorize(
                     ImageOps.grayscale(img), (255, 240, 190), (96, 64, 32)
                 ),
    "blur":      lambda img: img.filter(ImageFilter.GaussianBlur(5)),
    "sharpen":   lambda img: img.filter(ImageFilter.SHARPEN),
    "invert":    lambda img: ImageOps.invert(img.convert("RGB")),
    "mirror":    lambda img: ImageOps.mirror(img),
    "flip":      lambda img: ImageOps.flip(img),
    "edge":      lambda img: img.filter(ImageFilter.FIND_EDGES).convert("RGB"),
    "emboss":    lambda img: img.filter(ImageFilter.EMBOSS).convert("RGB"),
    "pixelate":  _pixelate,
    "deepfry":   None,  # handled separately
}


def _deep_fry(img: Image.Image) -> Image.Image:
    img = ImageEnhance.Color(img.convert("RGB")).enhance(2.5)
    img = ImageEnhance.Contrast(img).enhance(2.0)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=1)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


# ── ASCII art ─────────────────────────────────────────────────────────── #

_ASCII_CHARS = "`^\",:;Il!i><~+_-?bao%#@"[::-1]


def _ascii_art(img: Image.Image, width: int = 80) -> str:
    h = int(width * (img.height / img.width) * 0.5)
    img = img.resize((width, h)).convert("L")
    pixels = list(img.getdata())
    rows = [
        "".join(
            _ASCII_CHARS[int(p / 256 * len(_ASCII_CHARS))]
            for p in pixels[i : i + width]
        )
        for i in range(0, len(pixels), width)
    ]
    return "```\n" + "\n".join(rows) + "\n```"


# ── Color palette extraction ──────────────────────────────────────────── #

def _extract_colors(img: Image.Image, n: int = 5) -> list[str]:
    img = img.convert("RGB").resize((100, 100))
    img = img.convert("P", palette=Image.ADAPTIVE, colors=n).convert("RGB")
    palette = img.getpalette()[: n * 3]
    return [
        f"#{palette[i]:02x}{palette[i+1]:02x}{palette[i+2]:02x}"
        for i in range(0, len(palette), 3)
    ]


# ── Quote card ────────────────────────────────────────────────────────── #

_BG      = (18, 18, 30)
_ACCENT  = (100, 130, 200)
_TEXT_C  = (230, 230, 240)
_MUTED   = (140, 145, 170)
_QUOTE_C = (55, 65, 110)

_BAR_W  = 8
_PAD    = 52
_CARD_W = 800


def _make_quote_card(text: str, author: str) -> io.BytesIO:
    font_body   = _font(_SERIF,      30)
    font_author = _font(_SANS,       20)
    font_big_q  = _font(_SERIF_BOLD, 90)

    lines   = textwrap.wrap(f'"{text}"', width=42) or ['""']
    line_h  = 40
    card_h  = max(260, 90 + len(lines) * line_h + 80)

    img  = Image.new("RGB", (_CARD_W, card_h), _BG)
    draw = ImageDraw.Draw(img)

    # accent bar + decorative opening quote
    draw.rectangle([0, 0, _BAR_W - 1, card_h], fill=_ACCENT)
    draw.text((_BAR_W + _PAD - 10, 8), "\u201c", font=font_big_q, fill=_QUOTE_C)

    # body text
    y = 88
    for line in lines:
        draw.text((_BAR_W + _PAD, y), line, font=font_body, fill=_TEXT_C)
        y += line_h

    # divider + author
    draw.line([_BAR_W + _PAD, y + 12, _BAR_W + _PAD + 100, y + 12],
              fill=_ACCENT, width=2)
    draw.text((_BAR_W + _PAD, y + 22), f"\u2014 {author}", font=font_author, fill=_MUTED)

    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


# ── Cog ──────────────────────────────────────────────────────────────── #

class Images(commands.Cog):
    """Image manipulation and generation tools."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._processing: set[int] = set()  # author IDs currently being processed

    # ── Image resolution helper ──────────────────────────────────────── #

    async def _fetch(self, url: str) -> Image.Image | None:
        try:
            async with self.bot.http.session.get(url) as resp:
                if resp.status != 200:
                    return None
                return Image.open(io.BytesIO(await resp.read()))
        except Exception:
            return None

    async def _resolve(
        self, ctx: commands.Context, member: discord.Member | None
    ) -> Image.Image | None:
        """
        Resolution priority:
          1. Mentioned member's avatar
          2. Attachment on the command message
          3. Attachment on the replied-to message
        """
        if member:
            return await self._fetch(member.display_avatar.url)

        if ctx.message.attachments:
            att = ctx.message.attachments[0]
            if att.content_type and att.content_type.startswith("image/"):
                return await self._fetch(att.url)

        if ctx.message.reference:
            ref = ctx.message.reference.resolved
            if isinstance(ref, discord.Message) and ref.attachments:
                att = ref.attachments[0]
                if att.content_type and att.content_type.startswith("image/"):
                    return await self._fetch(att.url)

        return None

    def _lock(self, ctx: commands.Context) -> bool:
        """Returns False if the user is already processing an image."""
        if ctx.author.id in self._processing:
            return False
        self._processing.add(ctx.author.id)
        return True

    def _unlock(self, ctx: commands.Context):
        self._processing.discard(ctx.author.id)

    # ── !filter ─────────────────────────────────────────────────────── #

    @commands.command(name="filter", description="Apply a filter to an image")
    async def apply_filter(
        self, ctx: commands.Context, filter_name: str, member: discord.Member = None
    ):
        filter_name = filter_name.lower()
        if filter_name not in FILTERS:
            names = ", ".join(f"`{k}`" for k in FILTERS)
            await ctx.send(embed=EmbedBuilder.error("Unknown Filter", f"Available: {names}"))
            return

        if not self._lock(ctx):
            await ctx.send(embed=EmbedBuilder.warning(
                "Processing", "Please wait for your current image to finish."
            ))
            return

        try:
            image = await self._resolve(ctx, member)
            if not image:
                await ctx.send(embed=EmbedBuilder.error(
                    "No Image", "Attach an image, mention a user, or reply to an image message."
                ))
                return

            async with ctx.typing():
                loop = asyncio.get_running_loop()
                fn   = (lambda i: _deep_fry(i)) if filter_name == "deepfry" \
                       else FILTERS[filter_name]
                result = await loop.run_in_executor(None, fn, image.convert("RGB"))

                buf = io.BytesIO()
                result.save(buf, "PNG")
                buf.seek(0)

            await ctx.send(file=discord.File(buf, filename=f"{filter_name}.png"))
        finally:
            self._unlock(ctx)

    # ── !ascii ──────────────────────────────────────────────────────── #

    @commands.command(name="ascii", description="Convert an image to ASCII art")
    async def ascii_convert(
        self, ctx: commands.Context, width: int = 60, member: discord.Member = None
    ):
        if not 20 <= width <= 100:
            await ctx.send(embed=EmbedBuilder.error(
                "Invalid Width", "Width must be between **20** and **100**."
            ))
            return

        image = await self._resolve(ctx, member)
        if not image:
            await ctx.send(embed=EmbedBuilder.error(
                "No Image", "Attach an image, mention a user, or reply to an image message."
            ))
            return

        async with ctx.typing():
            result = await asyncio.get_running_loop().run_in_executor(
                None, _ascii_art, image, width
            )

        if len(result) > 2000:
            await ctx.send(embed=EmbedBuilder.warning(
                "Too Large", "Try a smaller width — the output exceeds Discord's character limit."
            ))
            return

        await ctx.send(result)

    # ── !colors ─────────────────────────────────────────────────────── #

    @commands.command(name="colors", description="Extract dominant colors from an image")
    async def extract_colors(
        self, ctx: commands.Context, num: int = 5, member: discord.Member = None
    ):
        if not 1 <= num <= 10:
            await ctx.send(embed=EmbedBuilder.error(
                "Invalid Number", "Number of colors must be between **1** and **10**."
            ))
            return

        image = await self._resolve(ctx, member)
        if not image:
            await ctx.send(embed=EmbedBuilder.error(
                "No Image", "Attach an image, mention a user, or reply to an image message."
            ))
            return

        async with ctx.typing():
            colors = await asyncio.get_running_loop().run_in_executor(
                None, _extract_colors, image, num
            )

        fields = [
            {"name": f"Color {i + 1}", "value": c, "inline": True}
            for i, c in enumerate(colors)
        ]
        embed = EmbedBuilder.create(
            title="🎨 Dominant Colors",
            color=Color.BLUE_GRAY,
            fields=fields,
        )
        await ctx.send(embed=embed)

    # ── !quote ──────────────────────────────────────────────────────── #

    @commands.command(name="quote", description="Generate a quote card from a replied message")
    async def quote(self, ctx: commands.Context):
        ref = ctx.message.reference
        if not ref or not isinstance(ref.resolved, discord.Message):
            await ctx.send(embed=EmbedBuilder.error(
                "No Reply",
                "Reply to a message with `!quote` to turn it into a quote card.",
            ))
            return

        source = ref.resolved
        text   = source.content.strip()

        if not text:
            await ctx.send(embed=EmbedBuilder.error(
                "Empty Message", "The message you replied to has no text content."
            ))
            return

        if len(text) > 300:
            await ctx.send(embed=EmbedBuilder.error(
                "Too Long",
                "Quote text must be 300 characters or fewer. "
                "Try replying to a shorter message.",
            ))
            return

        author_str = f"{source.author.display_name} • #{source.channel.name}"

        async with ctx.typing():
            buf = await asyncio.get_running_loop().run_in_executor(
                None, _make_quote_card, text, author_str
            )

        await ctx.send(file=discord.File(buf, filename="quote.png"))

    # ── !avatar ─────────────────────────────────────────────────────── #

    @commands.command(name="avatar", description="Show a user's full-size avatar")
    async def avatar(self, ctx: commands.Context, member: discord.Member = None):
        target = member or ctx.author
        embed = EmbedBuilder.create(
            title=f"{target.display_name}'s avatar",
            color=Color.BLUE_GRAY,
        )
        embed.set_image(url=target.display_avatar.with_size(1024).url)
        await ctx.send(embed=embed)

    # ── Error handler ─────────────────────────────────────────────────#

    async def cog_command_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MemberNotFound):
            await ctx.send(embed=EmbedBuilder.error(
                "Member Not Found", "That user could not be found in this server."
            ))
        elif isinstance(error, commands.BadArgument):
            await ctx.send(embed=EmbedBuilder.error("Invalid Argument", str(error)))
        elif isinstance(error, commands.MissingRequiredArgument):
            usage = {
                "filter": "!filter <filter> [@user]",
                "ascii":  "!ascii [width] [@user]",
                "colors": "!colors [num] [@user]",
                "quote":  "!quote (reply to a message)",
                "avatar": "!avatar [@user]",
            }.get(ctx.command.name, f"!{ctx.command.name}")
            await ctx.send(embed=EmbedBuilder.error("Missing Argument", f"Usage: `{usage}`"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Images(bot))
