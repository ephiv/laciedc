import os
import asyncio
from datetime import datetime, timezone
from dotenv import load_dotenv
from discord import Intents, Embed
from discord.ext import commands

from colors import Color
from database import db
from utils.embeds import EmbedBuilder


load_dotenv()

intents = Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


async def load_cogs():
    cogs = ["cogs.config", "cogs.auto_mod", "cogs.mod_tools", "cogs.appeals"]
    for cog in cogs:
        try:
            await bot.load_extension(cog)
            print(f"Loaded {cog}")
        except Exception as e:
            print(f"Failed to load {cog}: {e}")


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    print(f"Guilds: {len(bot.guilds)}")

    await db.connect()
    print("Database connected")

    await load_cogs()
    print("Cogs loaded")

    await bot.tree.sync()
    print("Slash commands synced")


@bot.event
async def on_guild_join(guild):
    await db.get_guild_settings(guild.id)
    print(f"Joined guild: {guild.name} (ID: {guild.id})")


@bot.event
async def on_guild_remove(guild):
    print(f"Left guild: {guild.name} (ID: {guild.id})")


@bot.command(name="ping", description="Check bot latency and status")
async def ping(ctx):
    import time

    start_time = time.perf_counter()
    msg = await ctx.send("Pinging...")
    end_time = time.perf_counter()
    latency_ms = (end_time - start_time) * 1000

    embed = Embed(
        title="🏓 Pong!",
        color=Color.GRAY,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="Latency", value=f"{latency_ms:.2f}ms", inline=True)
    embed.add_field(name="API Latency", value=f"{round(bot.latency * 1000)}ms", inline=True)

    await msg.edit(content=None, embed=embed)


@bot.command(name="reload", description="Reload a cog")
@commands.is_owner()
async def reload(ctx, cog: str):
    try:
        await bot.reload_extension(f"cogs.{cog}")
        embed = EmbedBuilder.success("Cog Reloaded", f"**{cog}** has been reloaded.")
    except Exception as e:
        embed = EmbedBuilder.error("Reload Failed", str(e))
    await ctx.send(embed=embed)


@reload.error
async def reload_error(ctx, error):
    if isinstance(error, commands.NotOwner):
        embed = EmbedBuilder.error("Permission Denied", "Only the bot owner can use this command.")
        await ctx.send(embed=embed)


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("Error: DISCORD_TOKEN not found in .env file")
        exit(1)

    try:
        await bot.start(token)
    except KeyboardInterrupt:
        await db.close()
        await bot.close()


if __name__ == "__main__":
    asyncio.run(main())