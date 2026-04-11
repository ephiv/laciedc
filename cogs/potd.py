import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
from io import BytesIO
import json
import os
import random
import textwrap
import asyncio
import aiohttp

from PIL import Image, ImageDraw, ImageFont
import matplotlib.pyplot as plt
import numpy as np
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import watchfiles

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
    increment_potd_solves,
)


PROBLEMS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "problems")
IMAGE_WIDTH = 900
HEADER_COLOR = (30, 58, 95)
TEXT_COLOR = (0, 0, 0)
ACCENT_COLOR = (70, 130, 180)
LATEX_FONT_SIZE = 18


def render_latex_to_image(latex: str, fontsize: int = LATEX_FONT_SIZE) -> Image.Image:
    """Render LaTeX expression to a PIL Image using matplotlib mathtext."""
    fig = plt.figure(figsize=(len(latex) * 0.12 + 0.3, 0.6))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.text(0.5, 0.5, f'${latex}$', fontsize=fontsize, ha='center', va='center',
            usetex=False, transform=ax.transAxes)
    ax.axis('off')
    
    buf = BytesIO()
    fig.savefig(buf, format='PNG', dpi=150, transparent=True, bbox_inches='tight',
                facecolor='none', edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert('RGBA')


def parse_latex_in_text(text: str, fontsize: int = LATEX_FONT_SIZE) -> list:
    """Parse text and return list of (text_chunk, latex_image_or_None) tuples."""
    import re
    parts = []
    pattern = r'(\$+)(.*?)(\$+)'
    last_end = 0
    
    for match in re.finditer(pattern, text, re.DOTALL):
        before = text[last_end:match.start()]
        if before:
            parts.append((before, None))
        
        latex_content = match.group(2)
        delimiter = match.group(1)
        
        if len(delimiter) == 1:
            try:
                img = render_latex_to_image(latex_content, fontsize)
                parts.append(('', img))
            except Exception:
                parts.append(('$'+latex_content+'$', None))
        elif len(delimiter) >= 2:
            try:
                img = render_latex_to_image(latex_content, fontsize + 4)
                parts.append(('', img))
            except Exception:
                parts.append(('$$'+latex_content+'$$', None))
        
        last_end = match.end()
    
    remaining = text[last_end:]
    if remaining:
        parts.append((remaining, None))
    
    return parts


class POTD(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.scheduler = AsyncIOScheduler()
        self.problems = []
        self.problems_changed = False
        self.watcher_task = None
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
        self.watcher_task = asyncio.create_task(self.watch_problems())
        for guild_id in self.bot.guilds:
            settings = get_potd_settings(guild_id.id)
            if settings and settings.get('channel_id'):
                self.schedule_potd(guild_id.id)

    async def cog_unload(self):
        self.scheduler.shutdown()
        if self.watcher_task:
            self.watcher_task.cancel()
            try:
                await self.watcher_task
            except asyncio.CancelledError:
                pass

    async def watch_problems(self):
        try:
            async for changes in watchfiles.awatch(PROBLEMS_DIR, raise_interrupt=False):
                self.load_problems()
                self.problems_changed = True
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

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
        
        if self.problems_changed:
            await channel.send("Problems have been updated!")
            self.problems_changed = False
        
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
        footer_padding = 50
        
        try:
            font_large = ImageFont.truetype("arial.ttf", 24)
            font_medium = ImageFont.truetype("arial.ttf", 18)
            font_small = ImageFont.truetype("arial.ttf", 16)
        except:
            font_large = ImageFont.load_default()
            font_medium = ImageFont.load_default()
            font_small = ImageFont.load_default()
        
        wrapped = textwrap.wrap(problem['problem'], 85)
        problem_lines = len(wrapped)
        
        parts_lines = 0
        if problem.get('type') == 'parts' and problem.get('parts'):
            for part in problem['parts']:
                parts_lines += len(textwrap.wrap(part, 83))
        
        mcq_lines = 0
        if problem.get('type') == 'mcq' and problem.get('options'):
            mcq_lines = len(problem['options'])
        
        diagram_img = None
        if problem.get('diagram'):
            diagram_img = await self.render_diagram(problem['diagram'])
        
        content_height = (
            header_height + padding +
            problem_lines * line_height +
            (padding // 2) +
            parts_lines * line_height +
            (len(problem.get('parts', [])) * 5 if problem.get('parts') else 0) +
            mcq_lines * line_height +
            (padding // 2 if mcq_lines else 0) +
            (padding * 2 + (diagram_img.height if diagram_img else 0)) +
            footer_padding
        )
        
        img_height = max(400, content_height)
        
        img = Image.new('RGB', (img_width, img_height), 'white')
        draw = ImageDraw.Draw(img)
        
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
        
        for line in wrapped:
            parts = parse_latex_in_text(line)
            x_pos = padding
            line_max_height = line_height
            for text_part, latex_img in parts:
                if latex_img:
                    img.paste(latex_img, (x_pos, y_offset - line_height + 8), latex_img)
                    x_pos += latex_img.width + 2
                    line_max_height = max(line_max_height, latex_img.height + 12)
                elif text_part:
                    draw.text((x_pos, y_offset), text_part, fill=TEXT_COLOR, font=font_medium)
                    x_pos += font_medium.getbbox(text_part)[2] - font_medium.getbbox(text_part)[0]
            y_offset += max(line_height, line_max_height)
        
        y_offset += padding // 2
        
        if problem.get('type') == 'parts' and problem.get('parts'):
            for part in problem['parts']:
                part_wrapped = textwrap.wrap(part, 83)
                for line in part_wrapped:
                    parts = parse_latex_in_text(line)
                    x_pos = padding + 20
                    line_max_height = line_height
                    for text_part, latex_img in parts:
                        if latex_img:
                            img.paste(latex_img, (x_pos, y_offset - line_height + 8), latex_img)
                            x_pos += latex_img.width + 2
                            line_max_height = max(line_max_height, latex_img.height + 12)
                        elif text_part:
                            draw.text((x_pos, y_offset), text_part, fill=TEXT_COLOR, font=font_medium)
                            x_pos += font_medium.getbbox(text_part)[2] - font_medium.getbbox(text_part)[0]
                    y_offset += max(line_height, line_max_height)
                y_offset += 5
        
        if problem.get('type') == 'mcq' and problem.get('options'):
            for option in problem['options']:
                parts = parse_latex_in_text(option)
                x_pos = padding + 20
                line_max_height = line_height
                for text_part, latex_img in parts:
                    if latex_img:
                        img.paste(latex_img, (x_pos, y_offset - line_height + 8), latex_img)
                        x_pos += latex_img.width + 2
                        line_max_height = max(line_max_height, latex_img.height + 12)
                    elif text_part:
                        draw.text((x_pos, y_offset), text_part, fill=TEXT_COLOR, font=font_medium)
                        x_pos += font_medium.getbbox(text_part)[2] - font_medium.getbbox(text_part)[0]
                y_offset += max(line_height, line_max_height)
            y_offset += padding // 2
        
        if diagram_img:
            y_offset += padding
            if diagram_img.mode == 'RGBA':
                img.paste(diagram_img, (padding, y_offset), diagram_img)
            else:
                img.paste(diagram_img, (padding, y_offset))
            y_offset += diagram_img.height + padding
        
        draw_time = f"Posted: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        draw.text(
            (img_width // 2, y_offset + 15),
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
        diagram_type = diagram.get('type', '').lower()
        
        if diagram_type == 'matplotlib':
            code = diagram.get('code', '')
            try:
                plt.clf()
                exec(code, {'plt': plt, 'np': np})
                
                buf = BytesIO()
                plt.savefig(buf, format='PNG', bbox_inches='tight', dpi=100)
                plt.close()
                buf.seek(0)
                return Image.open(buf).convert('RGBA')
            except Exception:
                return None
        
        elif diagram_type == 'latex':
            latex_code = diagram.get('code', '')
            try:
                plt.clf()
                fig = plt.figure(figsize=(diagram.get('width', 8), diagram.get('height', 2)))
                ax = fig.add_axes([0, 0, 1, 1])
                ax.text(0.5, 0.5, latex_code, fontsize=diagram.get('fontsize', 20),
                        ha='center', va='center', usetex=False)
                ax.axis('off')
                
                buf = BytesIO()
                plt.savefig(buf, format='PNG', bbox_inches='tight', dpi=150, transparent=True)
                plt.close()
                buf.seek(0)
                return Image.open(buf).convert('RGBA')
            except Exception:
                return None
        
        elif diagram_type == 'image':
            filepath = diagram.get('path', '')
            try:
                if not os.path.isabs(filepath):
                    filepath = os.path.join(PROBLEMS_DIR, filepath)
                return Image.open(filepath).convert('RGBA')
            except Exception:
                return None
        
        elif diagram_type == 'url':
            url = diagram.get('url', '')
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.read()
                            return Image.open(BytesIO(data)).convert('RGBA')
            except Exception:
                return None
            return None
        
        return None

    async def cog_app_command_error(
        self, inter: discord.Interaction, error: app_commands.AppCommandError
    ):
        import traceback
        if isinstance(error, app_commands.errors.CommandInvokeError):
            error = error.original
        
        if isinstance(error, (commands.MissingPermissions, app_commands.errors.MissingPermissions)):
            try:
                await inter.response.send_message("You don't have permission.", ephemeral=True)
            except discord.InteractionResponded:
                await inter.followup.send("You don't have permission.", ephemeral=True)
        else:
            err_msg = f"An error occurred: {type(error).__name__}: {error}"
            print(err_msg)
            traceback.print_exc()
            try:
                await inter.response.send_message(err_msg, ephemeral=True)
            except discord.InteractionResponded:
                await inter.followup.send(err_msg, ephemeral=True)

    @app_commands.command(name="potd", description="View POTD help and available commands")
    async def potd(self, inter: discord.Interaction):
        embed = discord.Embed(
            title="POTD Commands",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="For Users",
            value="`/potd_submit` - Submit your answer\n`/potd_stats` - View your stats\n`/potd_leaderboard` - View leaderboard",
            inline=False
        )
        embed.add_field(
            name="For Admins",
            value="`/potd_setchannel` - Set POTD channel\n`/potd_settime` - Set posting time\n`/potd_post` - Post now\n`/potd_preview` - Preview problem\n`/potd_status` - View settings\n`/potd_list` - List problems\n`/potd_add` - Add problem",
            inline=False
        )
        await inter.response.send_message(embed=embed, ephemeral=True)

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

    @app_commands.command(name="potd_preview", description="Preview the sample problem")
    async def potd_preview(self, inter: discord.Interaction):
        sample = None
        for p in self.problems:
            if p['id'] == 'sample_001':
                sample = p
                break
        
        if not sample:
            await inter.response.send_message("Sample problem not found!", ephemeral=True)
            return
        
        await inter.response.defer()
        
        image = await self.render_problem_image(sample, 1)
        file = discord.File(fp=image, filename='sample_problem.png')
        
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
        
        content = "\n".join(lines)
        if len(content) > 1990:
            await inter.response.send_message(
                f"Problem list too long. Showing {len(self.problems)} problems.",
                ephemeral=True
            )
            for i in range(0, len(lines), 25):
                chunk = lines[i:i+25]
                msg = "```\n" + "\n".join(chunk) + "```"
                if i == 0:
                    await inter.followup.send(msg)
                else:
                    await inter.channel.send(msg)
        else:
            await inter.response.send_message("```\n" + content + "```")

    @app_commands.command(name="potd_reload", description="Reload problems from disk")
    async def potd_reload(self, inter: discord.Interaction):
        count = len(self.problems)
        self.load_problems()
        new_count = len(self.problems)
        self.problems_changed = False
        await inter.response.send_message(
            f"Reloaded problems. ({count} → {new_count})",
            ephemeral=True
        )

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
