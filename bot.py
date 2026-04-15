import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from discord import Embed, Intents
from discord.ext import commands
from dotenv import load_dotenv

from colors import Color
from database import db
from utils.watcher import start_watcher

load_dotenv()

intents = Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

_observer = None  # file-watcher handle, stopped on shutdown


def _discover_cogs() -> list[str]:
    """Return cog extension names for every .py file in cogs/."""
    return sorted(
        f"cogs.{p.stem}"
        for p in Path("cogs").glob("*.py")
        if p.stem != "__init__"
    )


async def _load_cogs():
    for cog in _discover_cogs():
        try:
            await bot.load_extension(cog)
            print(f"  ✓ {cog}")
        except Exception as exc:
            print(f"  ✗ {cog}: {exc}")


# ------------------------------------------------------------------ #
#  Startup                                                             #
# ------------------------------------------------------------------ #

@bot.event
async def on_ready():
    global _observer

    print(f"\nLogged in as {bot.user} (ID: {bot.user.id})")
    print(f"Guilds: {len(bot.guilds)}\n")

    await db.connect()
    print("Database connected\n")

    print("Loading cogs:")
    await _load_cogs()

    await bot.tree.sync()
    print("\nSlash commands synced\n")

    _observer = start_watcher(bot, asyncio.get_event_loop())
    print("\nBot is ready.")


@bot.event
async def on_guild_join(guild):
    await db.get_guild_settings(guild.id)
    print(f"Joined guild: {guild.name} ({guild.id})")


@bot.event
async def on_guild_remove(guild):
    print(f"Left guild: {guild.name} ({guild.id})")


# ------------------------------------------------------------------ #
#  Commands                                                            #
# ------------------------------------------------------------------ #

@bot.command(name="ping", description="Check bot latency")
async def ping(ctx):
    import time
    start = time.perf_counter()
    msg   = await ctx.send("Pinging…")
    rtt   = (time.perf_counter() - start) * 1000

    embed = Embed(title="🏓 Pong!", color=Color.GRAY, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Roundtrip", value=f"{rtt:.0f}ms", inline=True)
    embed.add_field(name="API",       value=f"{bot.latency * 1000:.0f}ms", inline=True)
    await msg.edit(content=None, embed=embed)


@bot.command(name="reload", description="Reload all currently loaded cogs")
@commands.is_owner()
async def reload_cogs(ctx):
    loaded = [ext for ext in bot.extensions if ext.startswith("cogs.")]
    lines  = []
    for cog in sorted(loaded):
        try:
            await bot.reload_extension(cog)
            lines.append(f"✅ `{cog}`")
        except Exception as exc:
            lines.append(f"❌ `{cog}` — {exc}")

    embed = Embed(
        title="🔄 Reloaded",
        description="\n".join(lines) or "no cogs loaded",
        color=Color.GRAY,
    )
    await ctx.send(embed=embed)


@reload_cogs.error
async def reload_error(ctx, error):
    if isinstance(error, commands.NotOwner):
        await ctx.send("only the bot owner can use this command.", delete_after=5)


# ------------------------------------------------------------------ #
#  Entry point                                                         #
# ------------------------------------------------------------------ #

async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("Error: DISCORD_TOKEN not set in .env")
        raise SystemExit(1)

    try:
        async with bot:
            await bot.start(token)
    finally:
        if _observer:
            _observer.stop()
            _observer.join()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
