import os
import logging
from dotenv import load_dotenv

import discord
from discord.ext import commands

load_dotenv()

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", 0))
PREFIX = os.getenv("BOT_PREFIX", "!")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
intents.messages = True
intents.voice_states = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if GUILD_ID:
        guild = bot.get_guild(GUILD_ID)
        if guild:
            print(f"Connected to guild: {guild.name}")
    
    await bot.tree.sync()
    print("Slash commands synced")


@bot.command(name="sync")
@commands.is_owner()
async def sync(inter: commands.Context):
    """Sync slash commands (owner only)"""
    synced = await inter.bot.tree.sync()
    await inter.send(f"Synced {len(synced)} commands globally")


@bot.command(name="syncguild")
@commands.is_owner()
async def sync_guild(inter: commands.Context, guild_id: int):
    """Sync slash commands for a specific guild (owner only)"""
    guild = bot.get_guild(guild_id)
    if not guild:
        await inter.send("Guild not found.")
        return
    
    synced = await bot.tree.sync(guild=discord.Object(id=guild_id))
    await inter.send(f"Synced {len(synced)} commands for {guild.name}")


async def load_cogs():
    cogs_to_load = [
        "cogs.database",
        "cogs.logging",
        "cogs.moderation",
        "cogs.utility",
        "cogs.usermanagement",
        "cogs.automod",
        "cogs.xp",
        "cogs.potd",
    ]
    
    for cog in cogs_to_load:
        try:
            await bot.load_extension(cog)
            print(f"Loaded {cog}")
        except Exception as e:
            print(f"Failed to load {cog}: {e}")


async def main():
    async with bot:
        await load_cogs()
        await bot.start(TOKEN)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
