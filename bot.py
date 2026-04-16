import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
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

_observer = None  # file-watcher handle, stopped on shutdown


def _discover_cogs() -> list[str]:
    """Return extension names for every .py file in cogs/."""
    return sorted(
        f"cogs.{p.stem}"
        for p in Path("cogs").glob("*.py")
        if p.stem != "__init__"
    )


async def _load_cogs(bot: commands.Bot):
    for cog in _discover_cogs():
        try:
            await bot.load_extension(cog)
            print(f"  ✓ {cog}")
        except Exception as exc:
            print(f"  ✗ {cog}: {exc}")


# Fix 2 — subclass bot so setup_hook() can be overridden.
# setup_hook() runs exactly once before the first connection and is
# never re-triggered on reconnect, unlike on_ready().
class LacieDC(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self):
        global _observer

        await db.connect()
        print("database connected\n")

        print("loading cogs:")
        await _load_cogs(self)
        print()

        # Fix 6 — asyncio.get_running_loop() instead of get_event_loop().
        # get_running_loop() is always correct inside an async context;
        # get_event_loop() is deprecated in Python 3.10+ and raises in 3.12+.
        _observer = start_watcher(self, asyncio.get_running_loop())


bot = LacieDC()


# ------------------------------------------------------------------ #
#  Events                                                              #
# ------------------------------------------------------------------ #

@bot.event
async def on_ready():
    # on_ready is now lightweight — only fires for status reporting.
    # All one-time init has moved to setup_hook() above.
    print(f"logged in as {bot.user} ({bot.user.id})")
    print(f"guilds: {len(bot.guilds)}")
    print("bot is ready.")


@bot.event
async def on_guild_join(guild):
    await db.get_guild_settings(guild.id)
    print(f"joined guild: {guild.name} ({guild.id})")


@bot.event
async def on_guild_remove(guild):
    print(f"left guild: {guild.name} ({guild.id})")


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
    loaded = sorted(ext for ext in bot.extensions if ext.startswith("cogs."))
    lines  = []
    for cog in loaded:
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
        print("error: DISCORD_TOKEN not set in .env")
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
