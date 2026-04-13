import io
import base64
import asyncio
import discord
from discord.ext import commands
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from utils.embeds import EmbedBuilder
from colors import Color as ColorPalette


FILTERS = {
    "grayscale": lambda img: ImageOps.grayscale(img),
    "sepia": lambda img: ImageOps.colorize(
        ImageOps.grayscale(img),
        (255, 240, 190),
        (96, 64, 32),
    ),
    "blur": lambda img: img.filter(ImageFilter.GaussianBlur(5)),
    "sharpen": lambda img: img.filter(ImageFilter.SHARPEN),
    "invert": lambda img: ImageOps.invert(img.convert("RGB")),
    "mirror": lambda img: ImageOps.mirror(img),
    "flip": lambda img: ImageOps.flip(img),
}


def deep_fry(image: Image.Image) -> Image.Image:
    rgb_img = image.convert("RGB")
    enhancer = ImageEnhance.Color(rgb_img)
    img = enhancer.enhance(2.5)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=1, optimize=False)
    buffer.seek(0)
    return Image.open(buffer)


def ascii_art(image: Image.Image, width: int = 80) -> str:
    aspect_ratio = image.height / image.width
    new_height = int(width * aspect_ratio * 0.5)
    img = image.resize((width, new_height))
    img = img.convert("L")

    chars = "`^\",:;Il!i><~+*?bao%#@"
    chars = chars[::-1]

    pixels = list(img.getdata())
    ascii_img = []

    for i in range(0, len(pixels), width):
        row = pixels[i : i + width]
        ascii_row = [chars[int(pixel / 256 * len(chars))] for pixel in row]
        ascii_img.append("".join(ascii_row))

    return "```\n" + "\n".join(ascii_img) + "\n```"


def extract_colors(image: Image.Image, num_colors: int = 5) -> list:
    img = image.convert("RGB")
    img = img.resize((100, 100))
    img = img.convert("P", palette=Image.ADAPTIVE, colors=num_colors)
    img = img.convert("RGB")

    colors = img.getpalette()[: num_colors * 3]
    hex_colors = []

    for i in range(0, len(colors), 3):
        r, g, b = colors[i : i + 3]
        hex_colors.append(f"#{r:02x}{g:02x}{b:02x}")

    return hex_colors


class Images(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.processing = set()

    async def get_image_from_message(
        self, message: discord.Message, user_or_attachment
    ) -> Image.Image | None:
        if isinstance(user_or_attachment, discord.Attachment):
            attachment = user_or_attachment
        elif isinstance(user_or_attachment, discord.Member):
            user = user_or_attachment
            if user.avatar:
                url = user.display_avatar.url
            else:
                return None
        else:
            if message.attachments:
                attachment = message.attachments[0]
            else:
                return None

        if "attachment" in locals():
            if not attachment.content_type.startswith("image"):
                return None

            url = attachment.url

        try:
            async with self.bot.http.session.get(url) as response:
                if response.status != 200:
                    return None
                data = await response.read()
                return Image.open(io.BytesIO(data))
        except:
            return None

    async def process_image(
        self, image: Image.Image, filter_name: str
    ) -> io.BytesIO:
        if filter_name == "deepfry":
            result = deep_fry(image)
        else:
            filter_func = FILTERS.get(filter_name)
            if not filter_func:
                raise ValueError(f"Unknown filter: {filter_name}")
            result = filter_func(image)

        buffer = io.BytesIO()
        result.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    @commands.command(name="filter", description="Apply filter to image")
    @commands.has_permissions(manage_messages=True)
    async def apply_filter(self, ctx, filter_name: str, member: discord.Member = None):
        if ctx.message.id in self.processing:
            embed = EmbedBuilder.error(
                "Already Processing",
                "Please wait for the current image to finish."
            )
            await ctx.send(embed=embed)
            return

        if filter_name not in FILTERS and filter_name != "deepfry":
            embed = EmbedBuilder.error(
                "Invalid Filter",
                f"Available: {', '.join(FILTERS.keys())}, deepfry"
            )
            await ctx.send(embed=embed)
            return

        self.processing.add(ctx.message.id)

        try:
            image = await self.get_image_from_message(
                ctx.message, member or ctx.message.attachments[0] if ctx.message.attachments else member
            )

            if not image:
                embed = EmbedBuilder.error(
                    "No Image Found",
                    "Attach an image or mention a user."
                )
                await ctx.send(embed=embed)
                return

            buffer = await self.process_image(image, filter_name)

            file = discord.File(buffer, filename=f"{filter_name}.png")
            await ctx.send(file=file)

        except Exception as e:
            embed = EmbedBuilder.error("Error", str(e))
            await ctx.send(embed=embed)
        finally:
            self.processing.discard(ctx.message.id)

    @commands.command(name="ascii", description="Convert image to ASCII art")
    @commands.has_permissions(manage_messages=True)
    async def ascii_convert(
        self, ctx, width: int = 80, member: discord.Member = None
    ):
        if not 20 <= width <= 150:
            embed = EmbedBuilder.error(
                "Invalid Width",
                "Width must be between 20 and 150."
            )
            await ctx.send(embed=embed)
            return

        image = await self.get_image_from_message(
            ctx.message, member or ctx.message.attachments[0] if ctx.message.attachments else member
        )

        if not image:
            embed = EmbedBuilder.error(
                "No Image Found",
                "Attach an image or mention a user."
            )
            await ctx.send(embed=embed)
            return

        try:
            ascii_str = ascii_art(image, width)
            await ctx.send(ascii_str)
        except Exception as e:
            embed = EmbedBuilder.error("Error", str(e))
            await ctx.send(embed=embed)

    @commands.command(name="colors", description="Extract dominant colors")
    @commands.has_permissions(manage_messages=True)
    async def extract_color_palette(
        self, ctx, num_colors: int = 5, member: discord.Member = None
    ):
        if not 1 <= num_colors <= 10:
            embed = EmbedBuilder.error(
                "Invalid Number",
                "Number must be between 1 and 10."
            )
            await ctx.send(embed=embed)
            return

        image = await self.get_image_from_message(
            ctx.message, member or ctx.message.attachments[0] if ctx.message.attachments else member
        )

        if not image:
            embed = EmbedBuilder.error(
                "No Image Found",
                "Attach an image or mention a user."
            )
            await ctx.send(embed=embed)
            return

        try:
            colors = extract_colors(image, num_colors)

            fields = [
                {"name": f"Color {i+1}", "value": color, "inline": True}
                for i, color in enumerate(colors)
            ]

            embed = EmbedBuilder.create(
                title="🎨 Dominant Colors",
                color=ColorPalette.BLUE_GRAY,
                fields=fields,
            )

            await ctx.send(embed=embed)

        except Exception as e:
            embed = EmbedBuilder.error("Error", str(e))
            await ctx.send(embed=embed)

    @apply_filter.error
    @ascii_convert.error
    @extract_color_palette.error
    async def error_handler(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            embed = EmbedBuilder.error(
                "Permission Denied",
                "You need **Manage Messages** permission."
            )
            await ctx.send(embed=embed)
        elif isinstance(error, commands.MissingRequiredArgument):
            embed = EmbedBuilder.error(
                "Missing Argument",
                f"Usage: `!{ctx.command.name} <filter> [member/attachment]`"
            )
            await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Images(bot))