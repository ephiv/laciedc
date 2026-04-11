import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
from io import BytesIO
import json
import os
import random
import textwrap

from PIL import Image, ImageDraw, ImageFont
import matplotlib.pyplot as plt
import numpy as np
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .database import (
    get_potd_settings,
    set_potd_settings,
    get_potd_current,
    set_potd_current,
    add_potd_solve,
    has_solved_potd,
    get_potd_solvers,
    get_attempt_number,
    add_potd_history,
    get_potd_leaderboard,
    update_potd_stats,
    get_potd_stats,
)


PROBLEMS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "problems")
IMAGE_WIDTH = 900
HEADER_COLOR = (30, 58, 95)
TEXT_COLOR = (0, 0, 0)
ACCENT_COLOR = (70, 130, 180)


class POTD(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.scheduler = AsyncIOScheduler()
        self.problems = []
        self.load_problems()

    def load_problems(self):
        self.problems = []
        if not os.path.exists(PROBLEMS_DIR):
            os.makedirs(PROBLEMS_DIR, exist_ok=True)
            return
        
        for filename in os.listdir(PROBLEMS_DIR):
            if filename.endswith('.json'):
                filepath = os.path.join(PROBLEMS_DIR, filename)
                try:
                    with open(filepath, 'r') as f:
                        problem = json.load(f)
                        if self.validate_problem(problem):
                            self.problems.append(problem)
                except (json.JSONDecodeError, IOError):
                    pass

    def validate_problem(self, problem: dict) -> bool:
        required = ['id', 'source', 'type', 'problem', 'answer']
        if not all(key in problem for key in required):
            return False
        if problem['type'] not in ['mcq', 'open', 'parts']:
            return False
        if problem['type'] == 'mcq' and 'options' not in problem:
            return False
        if problem['type'] == 'parts' and 'parts' not in problem:
            return False
        return True

    async def cog_load(self):
        self.scheduler.start()
        for guild_id in self.bot.guilds:
            settings = get_potd_settings(guild_id.id)
            if settings and settings.get('channel_id'):
                self.schedule_potd(guild_id.id)

    async def cog_unload(self):
        self.scheduler.shutdown()

    def schedule_potd(self, guild_id: int):
        settings = get_potd_settings(guild_id)
        if not settings:
            return
        
        hour = settings.get('posting_hour', 9)
        minute = settings.get('posting_minute', 0)
        
        job_id = f'potd_{guild_id}'
        self.scheduler.add_job(
            self.post_potd,
            'cron',
            hour=hour,
            minute=minute,
            timezone='UTC',
            args=[guild_id],
            id=job_id,
            replace_existing=True
        )

    async def post_potd(self, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        
        settings = get_potd_settings(guild_id)
        if not settings or not settings.get('channel_id'):
            return
        
        channel = guild.get_channel(settings['channel_id'])
        if not channel:
            return
        
        previous = get_potd_current(guild_id)
        if previous:
            solvers = get_potd_solvers(previous['problem_id'], guild_id)
            if solvers:
                mentions = []
                for user_id in solvers:
                    member = guild.get_member(user_id)
                    if member:
                        mentions.append(member.mention)
                if mentions:
                    await channel.send(
                        f"✅ {', '.join(mentions)} solved yesterday's problem!"
                    )
            else:
                await channel.send("😢 No one solved yesterday's problem.")
        
        if not self.problems:
            await channel.send("No problems available!")
            return
        
        problem = random.choice(self.problems)
        attempt = 1
        
        image = await self.render_problem_image(problem, attempt)
        
        file = discord.File(fp=image, filename='problem.png')
        await channel.send(file=file)
        
        set_potd_current(guild_id, problem['id'], attempt)
        add_potd_history(guild_id, problem['id'], attempt)

    async def render_problem_image(self, problem: dict, attempt: int = 1) -> BytesIO:
        img_width = IMAGE_WIDTH
        padding = 40
        line_height = 30
        header_height = 80
        footer_height = 30
        
        estimated_height = header_height + padding * 3
        estimated_height += len(textwrap.wrap(problem['problem'], 85)) * line_height
        
        if problem.get('parts'):
            estimated_height += len(problem['parts']) * line_height + padding
        
        if problem.get('diagram'):
            estimated_height += 300
        
        estimated_height += footer_height
        
        img_height = max(400, estimated_height)
        
        img = Image.new('RGB', (img_width, img_height), 'white')
        draw = ImageDraw.Draw(img)
        
        try:
            font_large = ImageFont.truetype("arial.ttf", 24)
            font_medium = ImageFont.truetype("arial.ttf", 18)
            font_small = ImageFont.truetype("arial.ttf", 16)
        except:
            font_large = ImageFont.load_default()
            font_medium = ImageFont.load_default()
            font_small = ImageFont.load_default()
        
        draw.rectangle([0, 0, img_width, header_height], fill=HEADER_COLOR)
        
        title = "PROBLEM OF THE DAY"
        draw.text(
            (img_width // 2, 25),
            title,
            fill='white',
            font=font_large,
            anchor='mm'
        )
        
        source_text = f"Problem #{problem['id']} | {problem.get('source', 'Unknown')}"
        draw.text(
            (img_width // 2, 55),
            source_text,
            fill=(200, 200, 200),
            font=font_small,
            anchor='mm'
        )
        
        if attempt > 1:
            attempt_text = f"(Retake #{attempt})"
            draw.text(
                (img_width // 2, 75),
                attempt_text,
                fill=(255, 200, 100),
                font=font_small,
                anchor='mm'
            )
        
        y_offset = header_height + padding
        
        wrapped = textwrap.wrap(problem['problem'], 85)
        for line in wrapped:
            draw.text((padding, y_offset), line, fill=TEXT_COLOR, font=font_medium)
            y_offset += line_height
        
        y_offset += padding // 2
        
        if problem.get('type') == 'parts' and problem.get('parts'):
            for part in problem['parts']:
                part_wrapped = textwrap.wrap(part, 83)
                for line in part_wrapped:
                    draw.text((padding + 20, y_offset), line, fill=TEXT_COLOR, font=font_medium)
                    y_offset += line_height
                y_offset += 5
        
        if problem.get('type') == 'mcq' and problem.get('options'):
            for i, option in enumerate(problem['options']):
                draw.text((padding + 20, y_offset), option, fill=TEXT_COLOR, font=font_medium)
                y_offset += line_height
            y_offset += padding // 2
        
        if problem.get('diagram'):
            y_offset += padding
            diagram_img = await self.render_diagram(problem['diagram'])
            if diagram_img:
                img.paste(diagram_img, (padding, y_offset))
                y_offset += diagram_img.height + padding
        
        draw_time = f"Posted: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        draw.text(
            (img_width // 2, img_height - 15),
            draw_time,
            fill=(150, 150, 150),
            font=font_small,
            anchor='mm'
        )
        
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        return buffer

    async def render_diagram(self, diagram: dict) -> Image.Image:
        if diagram.get('type') == 'matplotlib':
            code = diagram.get('code', '')
            try:
                plt.clf()
                exec(code, {'plt': plt, 'np': np})
                
                buf = BytesIO()
                plt.savefig(buf, format='PNG', bbox_inches='tight', dpi=100)
                plt.close()
                buf.seek(0)
                return Image.open(buf)
            except Exception:
                return None
        return None

    async def cog_app_command_error(
        self, inter: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.errors.CommandInvokeError):
            error = error.original
        
        if isinstance(error, (commands.MissingPermissions, app_commands.errors.MissingPermissions)):
            try:
                await inter.response.send_message("You don't have permission.", ephemeral=True)
            except discord.InteractionResponded:
                await inter.followup.send("You don't have permission.", ephemeral=True)
        else:
            try:
                await inter.response.send_message("An error occurred.", ephemeral=True)
            except discord.InteractionResponded:
                await inter.followup.send("An error occurred.", ephemeral=True)

    @app_commands.command(name="potd", description="POTD management commands")
    @app_commands.default_permissions(administrator=True)
    async def potd(self, inter: discord.Interaction):
        pass

    @app_commands.command(name="potd_setchannel", description="Set POTD channel")
    @app_commands.describe(channel="Channel for POTD posts")
    async def potd_setchannel(self, inter: discord.Interaction, channel: discord.TextChannel):
        set_potd_settings(inter.guild_id, channel_id=channel.id)
        self.schedule_potd(inter.guild_id)
        await inter.response.send_message(f"POTD channel set to {channel.mention}")

    @app_commands.command(name="potd_settime", description="Set POTD posting time (UTC)")
    @app_commands.describe(hour="Hour (0-23)", minute="Minute (0-59)")
    async def potd_settime(self, inter: discord.Interaction, hour: int, minute: int):
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            await inter.response.send_message("Invalid time. Hour: 0-23, Minute: 0-59", ephemeral=True)
            return
        
        set_potd_settings(inter.guild_id, posting_hour=hour, posting_minute=minute)
        self.schedule_potd(inter.guild_id)
        await inter.response.send_message(f"POTD time set to {hour:02d}:{minute:02d} UTC")

    @app_commands.command(name="potd_preview", description="Preview current problem")
    async def potd_preview(self, inter: discord.Interaction):
        if not self.problems:
            await inter.response.send_message("No problems loaded!", ephemeral=True)
            return
        
        await inter.response.defer()
        
        problem = random.choice(self.problems)
        attempt = get_attempt_number(problem['id'], inter.guild_id) + 1
        
        image = await self.render_problem_image(problem, attempt)
        file = discord.File(fp=image, filename='problem_preview.png')
        
        await inter.followup.send(file=file)

    @app_commands.command(name="potd_post", description="Post POTD immediately")
    async def potd_post(self, inter: discord.Interaction):
        settings = get_potd_settings(inter.guild_id)
        if not settings or not settings.get('channel_id'):
            await inter.response.send_message("No channel set! Use /potd_setchannel first.", ephemeral=True)
            return
        
        await inter.response.defer()
        
        previous = get_potd_current(inter.guild_id)
        if previous:
            solvers = get_potd_solvers(previous['problem_id'], inter.guild_id)
            if solvers:
                mentions = [f"<@{uid}>" for uid in solvers]
                await inter.followup.send(f"✅ {', '.join(mentions)} solved the previous problem!")
            else:
                await inter.followup.send("😢 No one solved the previous problem.")
        
        if not self.problems:
            await inter.followup.send("No problems available!")
            return
        
        problem = random.choice(self.problems)
        attempt = 1
        
        image = await self.render_problem_image(problem, attempt)
        file = discord.File(fp=image, filename='problem.png')
        
        await inter.followup.send(file=file)
        
        set_potd_current(inter.guild_id, problem['id'], attempt)
        add_potd_history(inter.guild_id, problem['id'], attempt)

    @app_commands.command(name="potd_submit", description="Submit your answer")
    @app_commands.describe(answer="Your answer")
    async def potd_submit(self, inter: discord.Interaction, *, answer: str):
        current = get_potd_current(inter.guild_id)
        if not current:
            await inter.response.send_message("No active problem!", ephemeral=True)
            return
        
        problem_id = current['problem_id']
        
        if has_solved_potd(inter.user.id, inter.guild_id, problem_id):
            await inter.response.send_message("You already solved this problem!", ephemeral=True)
            return
        
        correct_answer = None
        for p in self.problems:
            if p['id'] == problem_id:
                correct_answer = p.get('answer', '').lower().strip()
                break
        
        is_correct = False
        if correct_answer:
            user_answer = answer.lower().strip()
            if user_answer == correct_answer:
                is_correct = True
        
        if is_correct:
            add_potd_solve(inter.user.id, inter.guild_id, problem_id)
            update_potd_stats(inter.user.id, inter.guild_id)
            increment_potd_solves(inter.user.id, inter.guild_id, problem_id)
            await inter.response.send_message(
                f"✅ Correct! Your answer: \"{answer}\"",
                ephemeral=True
            )
        else:
            await inter.response.send_message(
                f"❌ Incorrect. Your answer: \"{answer}\"\nYou can try again until the next problem.",
                ephemeral=True
            )

    @app_commands.command(name="potd_stats", description="View POTD stats")
    @app_commands.describe(member="Member to check (optional)")
    async def potd_stats(self, inter: discord.Interaction, member: discord.Member = None):
        if member is None:
            member = inter.user
        
        stats = get_potd_stats(member.id, inter.guild_id)
        
        if not stats:
            await inter.response.send_message(
                f"{member.display_name} hasn't solved any problems yet!",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title=f"POTD Stats - {member.display_name}",
            color=member.color
        )
        embed.add_field(name="Total Solves", value=stats.get('total_solves', 0), inline=True)
        embed.add_field(name="Current Streak", value=stats.get('current_streak', 0), inline=True)
        embed.add_field(name="Best Streak", value=stats.get('best_streak', 0), inline=True)
        
        await inter.response.send_message(embed=embed)

    @app_commands.command(name="potd_leaderboard", description="View POTD leaderboard")
    async def potd_leaderboard(self, inter: discord.Interaction):
        leaderboard = get_potd_leaderboard(inter.guild_id, 10)
        
        if not leaderboard:
            await inter.response.send_message("No stats yet!")
            return
        
        medals = ["🥇", "🥈", "🥉"]
        
        lines = []
        for i, entry in enumerate(leaderboard):
            user_id = entry['user_id']
            member = inter.guild.get_member(user_id)
            name = member.display_name if member else f"User {user_id}"
            
            if i < 3:
                lines.append(f"{medals[i]} {name} - {entry['total_solves']} solves")
            else:
                lines.append(f"{i + 1}. {name} - {entry['total_solves']} solves")
        
        embed = discord.Embed(
            title="POTD Leaderboard",
            description="\n".join(lines),
            color=discord.Color.gold()
        )
        
        await inter.response.send_message(embed=embed)

    @app_commands.command(name="potd_add", description="Add a problem")
    @app_commands.describe(problem="Problem JSON")
    async def potd_add(self, inter: discord.Interaction, *, problem: str):
        try:
            data = json.loads(problem)
        except json.JSONDecodeError:
            await inter.response.send_message("Invalid JSON format!", ephemeral=True)
            return
        
        if not self.validate_problem(data):
            await inter.response.send_message(
                "Invalid problem format! Required: id, source, type, problem, answer",
                ephemeral=True
            )
            return
        
        filepath = os.path.join(PROBLEMS_DIR, f"{data['id']}.json")
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            
            self.load_problems()
            await inter.response.send_message(f"Problem '{data['id']}' added!")
        except IOError as e:
            await inter.response.send_message(f"Failed to save: {e}", ephemeral=True)

    @app_commands.command(name="potd_list", description="List all problems")
    async def potd_list(self, inter: discord.Interaction):
        if not self.problems:
            await inter.response.send_message("No problems available!")
            return
        
        lines = [f"Total: {len(self.problems)} problems\n"]
        for p in self.problems:
            lines.append(f"- [{p['id']}] {p.get('source', 'Unknown')} ({p.get('difficulty', 'N/A')})")
        
        await inter.response.send_message("```\n" + "\n".join(lines) + "```")

    @app_commands.command(name="potd_status", description="Show POTD settings")
    async def potd_status(self, inter: discord.Interaction):
        settings = get_potd_settings(inter.guild_id)
        
        embed = discord.Embed(
            title="POTD Settings",
            color=discord.Color.blue()
        )
        
        if settings and settings.get('channel_id'):
            channel = inter.guild.get_channel(settings['channel_id'])
            embed.add_field(name="Channel", value=channel.mention if channel else "Unknown", inline=True)
        else:
            embed.add_field(name="Channel", value="Not set", inline=True)
        
        hour = (settings or {}).get('posting_hour', 9)
        minute = (settings or {}).get('posting_minute', 0)
        embed.add_field(name="Posting Time", value=f"{hour:02d}:{minute:02d} UTC", inline=True)
        
        current = get_potd_current(inter.guild_id)
        if current:
            embed.add_field(name="Current Problem", value=current['problem_id'], inline=True)
        else:
            embed.add_field(name="Current Problem", value="None", inline=True)
        
        embed.add_field(name="Problems Loaded", value=str(len(self.problems)), inline=True)
        
        await inter.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(POTD(bot))
