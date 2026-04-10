import os
import logging
from dotenv import load_dotenv

import discord

load_dotenv()

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", 0))

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    if GUILD_ID:
        guild = client.get_guild(GUILD_ID)
        if guild:
            print(f"Connected to guild: {guild.name}")


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return


client.run(TOKEN)
