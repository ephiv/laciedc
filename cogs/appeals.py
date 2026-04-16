import asyncpg
import discord
from discord.ext import commands
from database import db
from utils.embeds import EmbedBuilder
from utils.logger import log_action
from colors import Color


class Appeals(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── DM listener — appeal intake ───────────────────────────────────── #

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is not None:
            return

        user = message.author
        try:
            for guild in self.bot.guilds:
                ban_info = await db.get_active_ban(guild.id, user.id)
                if not ban_info:
                    continue

                pending = await db.get_pending_appeals(guild.id)
                already_pending = any(
                    a["user_id"] == user.id and a["ban_id"] == ban_info["id"]
                    for a in pending
                )
                if already_pending:
                    await user.send(embed=EmbedBuilder.warning(
                        "Appeal Already Pending",
                        f"You already have an open appeal for **{guild.name}**.\n"
                        "Please wait for a moderator to review it.",
                    ))
                    return

                await db.add_appeal(guild.id, user.id, ban_info["id"], message.content)
                await user.send(embed=EmbedBuilder.info(
                    "Appeal Submitted",
                    f"Your appeal for **{guild.name}** has been received.\n"
                    f"**Original ban reason:** {ban_info['reason']}\n\n"
                    "A moderator will review your case shortly.",
                ))
                return

        except asyncpg.PostgresError:
            pass

    # ── !appeals — list pending ───────────────────────────────────────── #

    @commands.command(name="appeals", description="List all pending ban appeals for this server")
    @commands.has_permissions(ban_members=True)
    async def list_appeals(self, ctx: commands.Context):
        appeals = await db.get_pending_appeals(ctx.guild.id)

        if not appeals:
            await ctx.send(embed=EmbedBuilder.info("No Pending Appeals", "There are no appeals awaiting review."))
            return

        fields = [
            {
                "name": f"Appeal #{a['id']}",
                "value": (
                    f"**User:** <@{a['user_id']}>\n"
                    f"**Ban reason:** {a['ban_reason']}\n"
                    f"**Message:** {a['message'][:150]}{'…' if len(a['message']) > 150 else ''}"
                ),
                "inline": False,
            }
            for a in appeals[:10]
        ]
        embed = EmbedBuilder.create(
            title=f"📋 Pending Appeals ({len(appeals)})",
            color=Color.BLUE_GRAY,
            fields=fields,
        )
        await ctx.send(embed=embed)

    # ── !appeal <id> [approve|deny] ───────────────────────────────────── #

    @commands.command(name="appeal", description="View or action a specific appeal")
    @commands.has_permissions(ban_members=True)
    async def review_appeal(self, ctx: commands.Context, appeal_id: int, action: str = None):
        appeal = await db.get_appeal(appeal_id)

        # Fix 3 — guild boundary: moderators can only touch appeals from their own guild.
        # Using the same "not found" message for both cases avoids leaking
        # the existence of other guilds' appeals.
        if not appeal or appeal["guild_id"] != ctx.guild.id:
            await ctx.send(embed=EmbedBuilder.error(
                "Not Found", f"no appeal exists with id **#{appeal_id}** in this server."
            ))
            return

        # ── View mode ────────────────────────────────────────────────── #
        if action is None:
            fields = [
                {"name": "User",           "value": f"<@{appeal['user_id']}>",                          "inline": True},
                {"name": "Status",         "value": appeal["status"].capitalize(),                       "inline": True},
                {"name": "Ban Reason",     "value": appeal["ban_reason"],                                "inline": False},
                {"name": "Appeal Message", "value": appeal["message"],                                   "inline": False},
                {"name": "Submitted",      "value": appeal["created_at"].strftime("%Y-%m-%d %H:%M UTC"), "inline": True},
            ]
            if appeal["reviewed_at"]:
                fields.append({
                    "name":   "Reviewed",
                    "value":  appeal["reviewed_at"].strftime("%Y-%m-%d %H:%M UTC"),
                    "inline": True,
                })
            embed = EmbedBuilder.create(
                title=f"📋 Appeal #{appeal_id}", color=Color.BLUE_GRAY, fields=fields
            )
            await ctx.send(embed=embed)
            return

        # ── Decision mode ─────────────────────────────────────────────── #
        action = action.lower()
        if action not in ("approve", "deny"):
            await ctx.send(embed=EmbedBuilder.error(
                "Invalid Action", "Use `!appeal <id> approve` or `!appeal <id> deny`."
            ))
            return

        if appeal["status"] != "pending":
            await ctx.send(embed=EmbedBuilder.error(
                "Already Reviewed",
                f"Appeal **#{appeal_id}** has already been **{appeal['status']}**.",
            ))
            return

        await db.update_appeal(appeal_id, action, ctx.author.id)
        user = self.bot.get_user(appeal["user_id"])

        if action == "approve":
            await db.deactivate_ban(appeal["ban_id"])
            try:
                await ctx.guild.unban(
                    discord.Object(id=appeal["user_id"]),
                    reason=f"appeal #{appeal_id} approved by {ctx.author}",
                )
            except (discord.NotFound, discord.HTTPException):
                pass

            if user:
                try:
                    await user.send(embed=EmbedBuilder.success(
                        "Appeal Approved",
                        f"Your ban appeal for **{ctx.guild.name}** has been **approved**.\n"
                        "You are welcome to rejoin the server.",
                    ))
                except discord.HTTPException:
                    pass

            # Fix 5 — log the decision
            await log_action(self.bot, ctx.guild.id, "📋 appeal approved",
                f"appeal **#{appeal_id}** approved by {ctx.author.mention}.\n"
                f"user <@{appeal['user_id']}> was unbanned.",
                Color.NAVY)

            await ctx.send(embed=EmbedBuilder.success(
                "Appeal Approved",
                f"appeal **#{appeal_id}** approved — <@{appeal['user_id']}> has been unbanned.",
            ))

        else:  # deny
            if user:
                try:
                    await user.send(embed=EmbedBuilder.error(
                        "Appeal Denied",
                        f"Your ban appeal for **{ctx.guild.name}** has been **denied**.",
                    ))
                except discord.HTTPException:
                    pass

            await log_action(self.bot, ctx.guild.id, "📋 appeal denied",
                f"appeal **#{appeal_id}** denied by {ctx.author.mention}.",
                Color.PLUM)

            await ctx.send(embed=EmbedBuilder.warning(
                "Appeal Denied", f"appeal **#{appeal_id}** has been denied."
            ))

    # ── Error handler ─────────────────────────────────────────────────── #

    @list_appeals.error
    @review_appeal.error
    async def _cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=EmbedBuilder.error("Permission Denied", "You need **Ban Members** permission."))
        elif isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument)):
            await ctx.send(embed=EmbedBuilder.error(
                "Invalid Usage",
                "Usage: `!appeals` · `!appeal <id>` · `!appeal <id> approve/deny`",
            ))

    async def cog_command_error(self, ctx: commands.Context, error):
        # Fix 7 — handle DB failures gracefully
        err = getattr(error, "original", error)
        if isinstance(err, asyncpg.PostgresError):
            await ctx.send(embed=EmbedBuilder.error(
                "Database Error", "a database error occurred. please try again in a moment."
            ))


async def setup(bot: commands.Bot):
    await bot.add_cog(Appeals(bot))
