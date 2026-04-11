import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
from collections import defaultdict
from typing import Optional
import re
import asyncio

from .database import (
    get_guild_settings,
    update_settings,
    get_word_blacklist,
    add_word_to_blacklist,
    remove_word_from_blacklist,
    get_link_whitelist,
    add_domain_to_whitelist,
    remove_domain_from_whitelist,
    add_infraction,
)
from .logging import automod_embed, send_automod_log, success_embed, info_embed, error_embed


automod_group = app_commands.Group(name="automod", description="Auto-moderation settings", guild_only=True)


class SpamTracker:
    def __init__(self):
        self.messages = defaultdict(list)

    def add_message(self, user_id: int, channel_id: int, timestamp: datetime):
        key = (user_id, channel_id)
        self.messages[key].append(timestamp)
        self._cleanup(key)

    def get_message_count(self, user_id: int, channel_id: int, seconds: int = 3) -> int:
        key = (user_id, channel_id)
        self._cleanup(key)
        return len(self.messages[key])

    def _cleanup(self, key):
        now = datetime.now(timezone.utc)
        cutoff = datetime.timestamp(now) - 3
        self.messages[key] = [
            ts for ts in self.messages[key]
            if datetime.timestamp(ts) > cutoff
        ]

    def clear_user(self, user_id: int, channel_id: int):
        key = (user_id, channel_id)
        if key in self.messages:
            del self.messages[key]


spam_tracker = SpamTracker()


def contains_url(content: str) -> bool:
    url_pattern = re.compile(
        r'https?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)',
        re.IGNORECASE
    )
    return bool(url_pattern.search(content))


def is_url_whitelisted(url: str, whitelist: list[str]) -> bool:
    url_lower = url.lower()
    for domain in whitelist:
        if domain in url_lower:
            return True
    return False


def contains_blacklisted_word(content: str, blacklist: list[str]) -> tuple[bool, list[str]]:
    content_lower = content.lower()
    found = [word for word in blacklist if word in content_lower]
    return len(found) > 0, found


class Automod(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.tree.add_command(automod_group)

    async def cog_app_command_error(
        self, inter: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.errors.CommandInvokeError):
            error = error.original
        
        if isinstance(error, (commands.MissingPermissions, app_commands.errors.MissingPermissions)):
            try:
                await inter.response.send_message("You don't have permission to use this command.", ephemeral=True)
            except discord.InteractionResponded:
                await inter.followup.send("You don't have permission to use this command.", ephemeral=True)
        else:
            try:
                await inter.response.send_message(f"An error occurred: {error}", ephemeral=True)
            except discord.InteractionResponded:
                await inter.followup.send(f"An error occurred: {error}", ephemeral=True)

    @automod_group.command(name="status", description="Show current auto-mod settings")
    async def automod_status(self, inter: discord.Interaction):
        """Show current auto-mod settings"""
        settings = get_guild_settings(inter.guild.id)
        
        embed = discord.Embed(
            title="Auto-Moderation Settings",
            color=discord.Color.blue()
        )
        
        enabled = bool(settings.get("automod_enabled", 1))
        embed.add_field(name="Enabled", value="Yes" if enabled else "No", inline=True)
        embed.add_field(name="Spam Threshold", value=settings.get("spam_threshold", 5), inline=True)
        embed.add_field(name="Mention Threshold", value=settings.get("mention_threshold", 3), inline=True)
        embed.add_field(name="Link Blocking", value="Enabled" if settings.get("link_blocking_enabled", 1) else "Disabled", inline=True)
        
        word_blacklist = get_word_blacklist(inter.guild.id)
        word_count = len(word_blacklist)
        embed.add_field(name="Blacklisted Words", value=str(word_count), inline=True)
        
        link_whitelist = get_link_whitelist(inter.guild.id)
        whitelist_count = len(link_whitelist)
        embed.add_field(name="Whitelisted Domains", value=str(whitelist_count) if whitelist_count > 0 else "None", inline=True)
        
        if word_count > 0:
            words_preview = ", ".join(word_blacklist[:10])
            if word_count > 10:
                words_preview += f" ... (+{word_count - 10} more)"
            embed.add_field(name="Words (preview)", value=words_preview, inline=False)
        
        if whitelist_count > 0:
            domains_preview = ", ".join(link_whitelist[:5])
            if whitelist_count > 5:
                domains_preview += f" ... (+{whitelist_count - 5} more)"
            embed.add_field(name="Whitelisted (preview)", value=domains_preview, inline=False)
        
        await inter.response.send_message(embed=embed)

    @automod_group.command(name="toggle", description="Toggle auto-mod on/off")
    @app_commands.default_permissions(administrator=True)
    async def automod_toggle(self, inter: discord.Interaction):
        """Toggle auto-mod on/off"""
        settings = get_guild_settings(inter.guild.id)
        current = bool(settings.get("automod_enabled", 1))
        new_value = 0 if current else 1
        
        update_settings(inter.guild.id, automod_enabled=new_value)
        
        status = "enabled" if new_value else "disabled"
        await inter.response.send_message(embed=success_embed(f"Auto-mod {status}."))

    @automod_group.command(name="linksblock", description="Toggle link blocking on/off")
    @app_commands.default_permissions(administrator=True)
    async def automod_links_toggle(self, inter: discord.Interaction):
        """Toggle link blocking on/off"""
        settings = get_guild_settings(inter.guild.id)
        current = bool(settings.get("link_blocking_enabled", 1))
        new_value = 0 if current else 1
        
        update_settings(inter.guild.id, link_blocking_enabled=new_value)
        
        status = "enabled" if new_value else "disabled"
        await inter.response.send_message(embed=success_embed(f"Link blocking {status}."))

    words_group = app_commands.Group(name="words", description="Word filter settings", parent=automod_group)
    
    @words_group.command(name="add", description="Add a word to the blacklist")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(word="The word to blacklist")
    async def word_add(self, inter: discord.Interaction, word: str):
        """Add a word to the blacklist"""
        added = add_word_to_blacklist(inter.guild.id, word)
        
        if added:
            await inter.response.send_message(embed=success_embed(f"Added '{word}' to the blacklist."))
        else:
            await inter.response.send_message(embed=info_embed("Already Blacklisted", f"'{word}' is already in the blacklist."))

    @words_group.command(name="remove", description="Remove a word from the blacklist")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(word="The word to remove")
    async def word_remove(self, inter: discord.Interaction, word: str):
        """Remove a word from the blacklist"""
        removed = remove_word_from_blacklist(inter.guild.id, word)
        
        if removed:
            await inter.response.send_message(embed=success_embed(f"Removed '{word}' from the blacklist."))
        else:
            await inter.response.send_message(embed=info_embed("Not Found", f"'{word}' is not in the blacklist."))

    @words_group.command(name="list", description="List all blacklisted words")
    async def word_list(self, inter: discord.Interaction):
        """List all blacklisted words"""
        words = get_word_blacklist(inter.guild.id)
        
        if not words:
            await inter.response.send_message(embed=info_embed("Blacklist Empty", "No words in the blacklist."))
            return
        
        embed = discord.Embed(
            title="Blacklisted Words",
            color=discord.Color.orange()
        )
        
        words_text = "\n".join(f"- {word}" for word in sorted(words))
        embed.description = words_text
        embed.set_footer(text=f"Total: {len(words)} words")
        
        await inter.response.send_message(embed=embed)

    links_group = app_commands.Group(name="links", description="Link whitelist settings", parent=automod_group)

    @links_group.command(name="allow", description="Add a domain to the link whitelist")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(domain="The domain to whitelist (e.g., youtube.com)")
    async def link_allow(self, inter: discord.Interaction, domain: str):
        """Add a domain to the link whitelist"""
        added = add_domain_to_whitelist(inter.guild.id, domain)
        
        if added:
            await inter.response.send_message(embed=success_embed(f"Added '{domain}' to the link whitelist."))
        else:
            await inter.response.send_message(embed=info_embed("Already Whitelisted", f"'{domain}' is already in the whitelist."))

    @links_group.command(name="disallow", description="Remove a domain from the link whitelist")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(domain="The domain to remove")
    async def link_disallow(self, inter: discord.Interaction, domain: str):
        """Remove a domain from the link whitelist"""
        removed = remove_domain_from_whitelist(inter.guild.id, domain)
        
        if removed:
            await inter.response.send_message(embed=success_embed(f"Removed '{domain}' from the whitelist."))
        else:
            await inter.response.send_message(embed=info_embed("Not Found", f"'{domain}' is not in the whitelist."))

    @links_group.command(name="list", description="List all whitelisted domains")
    async def link_list(self, inter: discord.Interaction):
        """List all whitelisted domains"""
        domains = get_link_whitelist(inter.guild.id)
        
        if not domains:
            await inter.response.send_message(embed=info_embed("Whitelist Empty", "No domains in the whitelist."))
            return
        
        embed = discord.Embed(
            title="Whitelisted Domains",
            color=discord.Color.green()
        )
        
        domains_text = "\n".join(f"- {domain}" for domain in sorted(domains))
        embed.description = domains_text
        embed.set_footer(text=f"Total: {len(domains)} domains")
        
        await inter.response.send_message(embed=embed)

    config_group = app_commands.Group(name="config", description="Auto-mod configuration", parent=automod_group)

    @config_group.command(name="spam", description="Set spam threshold (messages per 3 seconds)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(count="Number of messages before spam trigger (1-20)")
    async def config_spam(self, inter: discord.Interaction, count: int):
        """Set spam threshold"""
        if count < 1 or count > 20:
            await inter.response.send_message(embed=error_embed("Spam threshold must be between 1 and 20."), ephemeral=True)
            return
        
        update_settings(inter.guild.id, spam_threshold=count)
        await inter.response.send_message(embed=success_embed(f"Spam threshold set to {count} messages per 3 seconds."))

    @config_group.command(name="mentions", description="Set mention spam threshold")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(count="Number of mentions before trigger (1-50)")
    async def config_mentions(self, inter: discord.Interaction, count: int):
        """Set mention spam threshold"""
        if count < 1 or count > 50:
            await inter.response.send_message(embed=error_embed("Mention threshold must be between 1 and 50."), ephemeral=True)
            return
        
        update_settings(inter.guild.id, mention_threshold=count)
        await inter.response.send_message(embed=success_embed(f"Mention spam threshold set to {count} mentions."))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        
        if message.author.guild_permissions.manage_messages:
            return
        
        settings = get_guild_settings(message.guild.id)
        
        if not settings.get("automod_enabled", 1):
            return
        
        user_id = message.author.id
        channel_id = message.channel.id
        content = message.content
        
        spam_count = settings.get("spam_threshold", 5)
        mention_count = settings.get("mention_threshold", 3)
        link_blocking = settings.get("link_blocking_enabled", 1)
        
        spam_tracker.add_message(user_id, channel_id, datetime.now(timezone.utc))
        recent_count = spam_tracker.get_message_count(user_id, channel_id, seconds=3)
        
        if recent_count >= spam_count:
            try:
                await message.delete()
                await message.channel.send(
                    f"{message.author.mention} Stop spamming!",
                    delete_after=3
                )
                
                muted_role = discord.utils.get(message.guild.roles, name="Muted")
                if muted_role and muted_role not in message.author.roles:
                    await message.author.add_roles(muted_role, reason="Auto-mute for spam")
                    
                    asyncio.create_task(self._auto_unmute(message.author, muted_role, 300))
                
                add_infraction(user_id, message.guild.id, "mute", self.bot.user.id, f"Auto-muted for spam ({recent_count} msgs in 3s)")
                
                embed = automod_embed("Spam Detected", message.author, f"Sent {recent_count} messages in 3 seconds. Auto-muted for 5 minutes.")
                await send_automod_log(message.guild, embed)
                
                spam_tracker.clear_user(user_id, channel_id)
            except discord.Forbidden:
                pass
            return
        
        if link_blocking and contains_url(content):
            whitelist = get_link_whitelist(message.guild.id)
            
            url_match = re.search(r'https?://[^\s]+', content)
            if url_match:
                url = url_match.group()
                if not is_url_whitelisted(url, whitelist):
                    try:
                        await message.delete()
                        
                        embed = automod_embed("Link Blocked", message.author, "Posted a link not in the whitelist")
                        await send_automod_log(message.guild, embed)
                    except discord.Forbidden:
                        pass
                    return
        
        mentions_in_message = len(message.mentions) + len(message.role_mentions)
        if mentions_in_message >= mention_count:
            try:
                await message.delete()
                
                add_infraction(user_id, message.guild.id, "warn", self.bot.user.id, f"Auto-warned for mention spam ({mentions_in_message} mentions)")
                
                embed = automod_embed("Mention Spam", message.author, f"Sent a message with {mentions_in_message} mentions")
                await send_automod_log(message.guild, embed)
            except discord.Forbidden:
                pass
            return
        
        word_blacklist = get_word_blacklist(message.guild.id)
        if word_blacklist:
            has_blacklisted, found_words = contains_blacklisted_word(content, word_blacklist)
            if has_blacklisted:
                try:
                    await message.delete()
                    
                    embed = automod_embed("Word Filter", message.author, f"Message contained blacklisted word(s): {', '.join(found_words)}")
                    await send_automod_log(message.guild, embed)
                except discord.Forbidden:
                    pass
                return

    async def _auto_unmute(self, member: discord.Member, muted_role: discord.Role, delay_seconds: int):
        await asyncio.sleep(delay_seconds)
        try:
            if muted_role in member.roles:
                await member.remove_roles(muted_role, reason="Auto-unmute after spam mute duration")
        except discord.Forbidden:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Automod(bot))
