import discord
from discord.ext import commands
from database import db
from utils.embeds import EmbedBuilder
from colors import Color as ColorPalette


class Appeals(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pending_appeals = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if not isinstance(message.author, discord.Member):
            return

        if not message.guild:
            for guild in self.bot.guilds:
                ban_info = await db.get_active_ban(guild.id, message.author.id)
                if ban_info:
                    await self.handle_appeal(message, ban_info, guild)
                    return

    async def handle_appeal(self, message: discord.Message, ban_info: dict, guild: discord.Guild):
        await db.add_appeal(
            guild.id,
            message.author.id,
            ban_info["id"],
            message.content
        )

        embed = EmbedBuilder.info(
            "Appeal Submitted",
            f"Your appeal for **{guild.name}** has been submitted.\n"
            f"A moderator will review it shortly.\n\n"
            f"Original ban reason: {ban_info['reason']}"
        )
        await message.author.send(embed=embed)

    @commands.command(name="appeals", description="View pending appeals")
    @commands.has_permissions(ban_members=True)
    async def list_appeals(self, ctx):
        appeals = await db.get_pending_appeals(ctx.guild.id)

        if not appeals:
            embed = EmbedBuilder.info(
                "No Pending Appeals",
                "There are no pending appeals."
            )
            await ctx.send(embed=embed)
            return

        fields = [
            {
                "name": f"Appeal #{a['id']}",
                "value": f"User: <@{a['user_id']}>\nReason: {a['ban_reason']}\nMessage: {a['message'][:100]}...",
                "inline": False,
            }
            for a in appeals[:10]
        ]

        embed = EmbedBuilder.create(
            title=f"📝 Pending Appeals ({len(appeals)})",
            color=ColorPalette.BLUE_GRAY,
            fields=fields,
        )
        await ctx.send(embed=embed)

    @commands.command(name="appeal", description="View or review an appeal")
    @commands.has_permissions(ban_members=True)
    async def review_appeal(self, ctx, appeal_id: int, action: str = None):
        if not action:
            appeal = await db.get_appeal(appeal_id)
            if not appeal:
                embed = EmbedBuilder.error("Appeal Not Found", f"Appeal #{appeal_id} not found.")
                await ctx.send(embed=embed)
                return

            fields = [
                {"name": "User", "value": f"<@{appeal['user_id']}>", "inline": True},
                {"name": "Status", "value": appeal['status'].capitalize(), "inline": True},
                {"name": "Ban Reason", "value": appeal['ban_reason'], "inline": False},
                {"name": "Appeal Message", "value": appeal['message'], "inline": False},
                {"name": "Submitted", "value": appeal['created_at'].strftime('%Y-%m-%d %H:%M'), "inline": True},
            ]

            if appeal['reviewed_at']:
                fields.append(
                    {"name": "Reviewed", "value": appeal['reviewed_at'].strftime('%Y-%m-%d %H:%M'), "inline": True}
                )

            embed = EmbedBuilder.create(
                title=f"📝 Appeal #{appeal_id}",
                color=ColorPalette.BLUE_GRAY,
                fields=fields,
            )
            await ctx.send(embed=embed)
            return

        action = action.lower()
        if action not in ["approve", "deny"]:
            embed = EmbedBuilder.error(
                "Invalid Action",
                "Use `!appeal <id> approve` or `!appeal <id> deny`"
            )
            await ctx.send(embed=embed)
            return

        appeal = await db.get_appeal(appeal_id)
        if not appeal:
            embed = EmbedBuilder.error("Appeal Not Found", f"Appeal #{appeal_id} not found.")
            await ctx.send(embed=embed)
            return

        if appeal['status'] != "pending":
            embed = EmbedBuilder.error(
                "Already Processed",
                f"This appeal is already **{appeal['status']}**"
            )
            await ctx.send(embed=embed)
            return

        await db.update_appeal(appeal_id, action, ctx.author.id)
        await db.deactivate_ban(appeal['ban_id'])

        user = self.bot.get_user(appeal['user_id'])

        if action == "approve":
            try:
                await ctx.guild.unban(user, reason="Appeal approved")
            except:
                pass

            if user:
                embed = EmbedBuilder.success(
                    "✅ Appeal Approved",
                    f"Your ban in **{ctx.guild.name}** has been lifted!\n"
                    f"You are now welcome to rejoin the server."
                )
                try:
                    await user.send(embed=embed)
                except:
                    pass

            embed = EmbedBuilder.success(
                "Appeal Approved",
                f"Appeal #{appeal_id} approved. User has been unbanned."
            )
        else:
            if user:
                embed = EmbedBuilder.error(
                    "❌ Appeal Denied",
                    f"Your appeal in **{ctx.guild.name}** has been denied.\n"
                    f"Reason: The moderation team has reviewed your case."
                )
                try:
                    await user.send(embed=embed)
                except:
                    pass

            embed = EmbedBuilder.warning(
                "Appeal Denied",
                f"Appeal #{appeal_id} denied."
            )

        await ctx.send(embed=embed)

    @list_appeals.error
    @review_appeal.error
    async def error_handler(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            embed = EmbedBuilder.error(
                "Permission Denied",
                "You need **Ban Members** permission to use this command."
            )
            await ctx.send(embed=embed)
        elif isinstance(error, commands.MissingRequiredArgument):
            embed = EmbedBuilder.error(
                "Missing Argument",
                f"Usage: `!{ctx.command.name}` or `!{ctx.command.name} <id> <action>`"
            )
            await ctx.send(embed=embed)
        elif isinstance(error, commands.BadArgument):
            embed = EmbedBuilder.error(
                "Invalid Argument",
                "The provided argument is invalid."
            )
            await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Appeals(bot))