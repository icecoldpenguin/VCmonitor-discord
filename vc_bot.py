import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
import asyncio
from datetime import datetime, time, timedelta
import os
import json
import aiohttp
import base64
import hashlib
import time as time_module
import pytz

# ================== CONFIG ==================
TOKEN = os.getenv("TOKEN")

MONITORED_VC_IDS = {
    1422274947291676672
}

INITIAL_WAIT_SECONDS = 120
REMINDER_WAIT_SECONDS = 120
KICK_WAIT_AFTER_REMINDER = 180

# ============ TEAM POINT SYSTEM CONFIG =============
ALLOWED_ROLES = {
    1438159005846605926,
    1423663604070223913,
    1420803949312610384
}

TEAM_X_ROLE = 1440768904204124302
TEAM_Y_ROLE = 1440769096760168498

# ============ STREAKBOARD CONFIG =============
STREAKBOARD_FILE = "streakboard.json"

def load_streakboard():
    try:
        with open(STREAKBOARD_FILE, "r") as f:
            return json.load(f)
    except:
        return {
            "season_start": datetime.utcnow().isoformat(),
            "season_number": 1,
            "players": {}
        }

def save_streakboard(data):
    with open(STREAKBOARD_FILE, "w") as f:
        json.dump(data, f, indent=4)

streakboard_data = load_streakboard()

# points.json loader/saver
def load_points():
    try:
        with open("points.json", "r") as f:
            return json.load(f)
    except:
        return {"X": 0, "Y": 0}

def save_points():
    with open("points.json", "w") as f:
        json.dump(team_points, f, indent=4)

team_points = load_points()

# ============ LAST STAND GAME CONFIG =============
LAST_STAND_FILE = "last_stand_game.json"

def load_last_stand():
    try:
        with open(LAST_STAND_FILE, "r") as f:
            return json.load(f)
    except:
        return {
            "active": False,
            "players": {},
            "starting_lives": 3,
            "pom_logs": []
        }

def save_last_stand(data):
    with open(LAST_STAND_FILE, "w") as f:
        json.dump(data, f, indent=4)

last_stand_data = load_last_stand()

# ============ JOURNAL REMINDER CONFIG =============
JOURNAL_FILE = "journal_reminders.json"

def load_journal_data():
    try:
        with open(JOURNAL_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_journal_data(data):
    with open(JOURNAL_FILE, "w") as f:
        json.dump(data, f, indent=4)

journal_data = load_journal_data()

# =====================================================

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True
intents.messages = True
intents.dm_messages = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Track user monitoring tasks
initial_checks = {}
post_stream_checks = {}

print("TOKEN LOADED?:", TOKEN is not None)

# =====================================================
#                      DM HELPER
# =====================================================
async def safe_dm(member: discord.Member, embed: discord.Embed):
    try:
        await member.send(embed=embed)
        print(f"[DM] Sent DM to {member}")
    except discord.Forbidden:
        print(f"[DM] Cannot DM {member}")
    except Exception as e:
        print(f"[DM] Error:", e)


# =====================================================
#                   MODERN EMBEDS
# =====================================================

def make_initial_kick_embed(member, vc):
    embed = discord.Embed(
        title="⚠️ Voice Channel Enforcement",
        description=f"Hey {member.mention}! 👋\n\nYou were removed from **{vc.name}** because camera or stream wasn't enabled within the required timeframe.",
        color=0xF59E0B
    )
    embed.add_field(
        name="📌 What happened?",
        value="All members must enable camera 📷 or stream 🖥️ to stay in monitored voice channels.",
        inline=False
    )
    embed.set_footer(text="Need help? Contact a moderator")
    embed.timestamp = datetime.utcnow()
    return embed

def make_reminder_embed(member, vc):
    embed = discord.Embed(
        title="⏰ Friendly Reminder",
        description=f"{member.mention}, your stream/camera was turned off in **{vc.name}**",
        color=0x10B981
    )
    embed.add_field(
        name="⚡ Action Required",
        value="Please re-enable your **camera 📷** or **stream 🖥️** within the next **3 minutes**",
        inline=False
    )
    embed.add_field(
        name="⚠️ Warning",
        value="Failure to comply may result in removal from the voice channel",
        inline=False
    )
    embed.set_footer(text="Automated Voice Channel Monitor")
    embed.timestamp = datetime.utcnow()
    return embed

def make_post_stream_kick_embed(member, vc):
    embed = discord.Embed(
        title="🚫 Removed from Voice Channel",
        description=f"{member.mention}, you were disconnected from **{vc.name}**",
        color=0xEF4444
    )
    embed.add_field(
        name="💡 Reason",
        value="Camera/stream remained disabled after the reminder period",
        inline=False
    )
    embed.add_field(
        name="🔄 Rejoin",
        value="You can rejoin once you're ready to enable camera or stream",
        inline=False
    )
    embed.set_footer(text="Voice Channel Compliance System")
    embed.timestamp = datetime.utcnow()
    return embed

# =====================================================
#                 HELPER FUNCTIONS
# =====================================================

def has_required_activity(member):
    if not member.voice:
        return False
    vs = member.voice
    return vs.self_stream or vs.self_video

async def assign_balanced_teams(guild: discord.Guild, event_name: str, team_x_role_id: int, team_y_role_id: int):
    team_x_role = guild.get_role(team_x_role_id)
    team_y_role = guild.get_role(team_y_role_id)

    humans = [m for m in guild.members if not m.bot]

    def stable_hash(member: discord.Member):
        key = f"{event_name}:{member.id}".encode()
        return int(hashlib.sha256(key).hexdigest(), 16)

    sorted_members = sorted(humans, key=lambda m: stable_hash(m))

    half = len(sorted_members) // 2
    team_x = sorted_members[:half]
    team_y = sorted_members[half:]

    for m in humans:
        try:
            await m.remove_roles(team_x_role, team_y_role, reason="Rebalancing teams")
        except:
            pass

    for m in team_x:
        await m.add_roles(team_x_role, reason="Balanced deterministic assignment")

    for m in team_y:
        await m.add_roles(team_y_role, reason="Balanced deterministic assignment")

    return len(team_x), len(team_y)

def pick_team_for_user(user_id: int, event_name: str) -> str:
    key = f"{event_name}:{user_id}".encode()
    h = int(hashlib.sha256(key).hexdigest(), 16)
    return "A" if (h % 2 == 0) else "B"

def calculate_team(user_id: int) -> str:
    """Simple hash-based team assignment"""
    return "X" if (user_id % 2 == 0) else "Y"

TEAM_X_ROLE_ALT = 1444727473643327581
TEAM_Y_ROLE_ALT = 1444727513489215641

# =====================================================
#                 BACKGROUND TASKS
# =====================================================

async def initial_check_task(member, vc_id):
    await asyncio.sleep(INITIAL_WAIT_SECONDS)
    
    mem = member.guild.get_member(member.id)
    if not mem or not mem.voice or mem.voice.channel.id != vc_id:
        return

    if has_required_activity(mem):
        return

    embed = make_initial_kick_embed(mem, mem.voice.channel)
    await safe_dm(mem, embed)

    try:
        await mem.move_to(None, reason="No cam/stream after initial window")
    except Exception as e:
        print("[MOVE ERROR]", e)


async def post_stream_reminder_task(member, vc_id):
    await asyncio.sleep(REMINDER_WAIT_SECONDS)

    mem = member.guild.get_member(member.id)
    if not mem or not mem.voice or mem.voice.channel.id != vc_id:
        return

    if has_required_activity(mem):
        return

    embed = make_reminder_embed(mem, mem.voice.channel)
    await safe_dm(mem, embed)


async def post_stream_kick_task(member, vc_id):
    await asyncio.sleep(KICK_WAIT_AFTER_REMINDER)

    mem = member.guild.get_member(member.id)
    if not mem or not mem.voice or mem.voice.channel.id != vc_id:
        return

    if has_required_activity(mem):
        return

    embed = make_post_stream_kick_embed(mem, mem.voice.channel)
    await safe_dm(mem, embed)

    try:
        await mem.move_to(None, reason="Did not turn cam/stream back on")
    except Exception as e:
        print("[MOVE ERROR]", e)


# =====================================================
#              JOURNAL REMINDER BACKGROUND TASK
# =====================================================

@tasks.loop(minutes=1)
async def check_journal_reminders():
    ist = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(ist)
    
    if now_ist.hour == 21 and now_ist.minute == 0:
        print(f"[JOURNAL] It's 9 PM IST - checking for reminders...")
        
        yesterday_9pm = now_ist - timedelta(days=1)
        
        for user_id, data in journal_data.items():
            if not data.get("enabled", False):
                continue
            
            last_post_str = data.get("last_post")
            needs_reminder = False
            
            if last_post_str is None:
                needs_reminder = True
            else:
                try:
                    last_post_utc = datetime.fromisoformat(last_post_str.replace('Z', '+00:00'))
                    if last_post_utc.tzinfo is None:
                        last_post_utc = pytz.utc.localize(last_post_utc)
                    last_post_ist = last_post_utc.astimezone(ist)
                    
                    if last_post_ist < yesterday_9pm:
                        needs_reminder = True
                except Exception as e:
                    print(f"[JOURNAL] Error parsing timestamp for {user_id}: {e}")
                    needs_reminder = True
            
            if needs_reminder:
                try:
                    user = await bot.fetch_user(int(user_id))
                    
                    embed = discord.Embed(
                        title="📔 Daily Journal Reminder",
                        description="Hey there! It looks like you haven't posted in your journal today. 🌙",
                        color=0x8B5CF6
                    )
                    embed.add_field(
                        name="✨ Take a moment to reflect",
                        value="Writing down your thoughts helps you grow and process your day!",
                        inline=False
                    )
                    embed.add_field(
                        name="📝 What to do",
                        value="After updating your journal, use `/journalpost` to mark it complete.",
                        inline=False
                    )
                    embed.set_footer(text="Daily journaling builds character 💪")
                    embed.timestamp = datetime.utcnow()
                    
                    await user.send(embed=embed)
                    print(f"[JOURNAL] Sent reminder to user {user_id}")
                    
                except discord.Forbidden:
                    print(f"[JOURNAL] Cannot DM user {user_id}")
                except Exception as e:
                    print(f"[JOURNAL] Error sending reminder to {user_id}: {e}")
        
        print(f"[JOURNAL] Finished sending reminders")


# =====================================================
#              STREAKBOARD DAILY CHECK
# =====================================================

@tasks.loop(hours=24)
async def check_streaks_daily():
    """Check at midnight UTC if players completed their tasks"""
    global streakboard_data
    
    print("[STREAKBOARD] Running daily streak check...")
    
    current_time = datetime.utcnow()
    
    for user_id, player_data in streakboard_data["players"].items():
        if not player_data.get("streak_active", False):
            continue
        
        last_completion = player_data.get("last_completion")
        
        if last_completion:
            last_time = datetime.fromisoformat(last_completion)
            hours_since = (current_time - last_time).total_seconds() / 3600
            
            if hours_since > 24:
                player_data["streak"] = 0
                player_data["streak_active"] = False
                print(f"[STREAKBOARD] Streak broken for user {user_id}")
                
                try:
                    user = await bot.fetch_user(int(user_id))
                    embed = discord.Embed(
                        title="💔 Streak Broken",
                        description="Your streak has been reset because you didn't complete your tasks within 24 hours.",
                        color=0xEF4444
                    )
                    embed.add_field(
                        name="🔄 Start Again",
                        value="Use `/streak_start` to define new tasks and begin a fresh streak!",
                        inline=False
                    )
                    embed.set_footer(text="Don't give up! Every day is a new opportunity")
                    embed.timestamp = datetime.utcnow()
                    await user.send(embed=embed)
                except:
                    pass
    
    save_streakboard(streakboard_data)


# =====================================================
#                     EVENTS
# =====================================================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    
    if not check_journal_reminders.is_running():
        check_journal_reminders.start()
        print("[JOURNAL] Journal reminder task started")
    
    if not check_streaks_daily.is_running():
        check_streaks_daily.start()
        print("[STREAKBOARD] Daily streak check started")
    
    try:
        synced = await bot.tree.sync()
        print("Synced:", len(synced))
    except Exception as e:
        print("Slash command sync failed:", e)
    
    bot.add_view(TeamJoinView("default_event"))


@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel and before.channel.id in MONITORED_VC_IDS:
        if not after.channel or after.channel.id not in MONITORED_VC_IDS:
            if member.id in initial_checks:
                initial_checks[member.id].cancel()
                initial_checks.pop(member.id)

            if member.id in post_stream_checks:
                for t in post_stream_checks[member.id].values():
                    t.cancel()
                post_stream_checks.pop(member.id)

    if after.channel and after.channel.id in MONITORED_VC_IDS and not before.channel:
        if not has_required_activity(member):
            task = asyncio.create_task(initial_check_task(member, after.channel.id))
            initial_checks[member.id] = task

    before_active = before.self_stream or before.self_video if before else False
    after_active = after.self_stream or after.self_video if after else False

    if not before_active and after_active:
        if member.id in initial_checks:
            initial_checks[member.id].cancel()
            initial_checks.pop(member.id)

        if member.id in post_stream_checks:
            for t in post_stream_checks[member.id].values():
                t.cancel()
            post_stream_checks.pop(member.id)

    if before_active and not after_active:
        if after.channel and after.channel.id in MONITORED_VC_IDS:
            if member.id in post_stream_checks:
                for t in post_stream_checks[member.id].values():
                    t.cancel()
                post_stream_checks.pop(member.id)

            reminder = asyncio.create_task(post_stream_reminder_task(member, after.channel.id))
            kick = asyncio.create_task(post_stream_kick_task(member, after.channel.id))
            post_stream_checks[member.id] = {"reminder": reminder, "kick": kick}


# =====================================================
#              STREAKBOARD COMMANDS
# =====================================================

class TaskModal(Modal, title="Define Your Daily Tasks"):
    task_input = TextInput(
        label="Enter your tasks (one per line)",
        style=discord.TextStyle.paragraph,
        placeholder="Morning workout\nRead 30 pages\nMeditate 10 minutes\nCode for 2 hours",
        required=True,
        max_length=500
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        tasks = [t.strip() for t in self.task_input.value.split('\n') if t.strip()]
        
        if len(tasks) == 0:
            return await interaction.response.send_message("❌ You must define at least one task!", ephemeral=True)
        
        user_id = str(interaction.user.id)
        
        if user_id not in streakboard_data["players"]:
            streakboard_data["players"][user_id] = {
                "streak": 0,
                "tasks": tasks,
                "last_completion": None,
                "streak_active": False,
                "username": interaction.user.display_name
            }
        else:
            streakboard_data["players"][user_id]["tasks"] = tasks
        
        save_streakboard(streakboard_data)
        
        tasks_formatted = "\n".join([f"• {task}" for task in tasks])
        
        embed = discord.Embed(
            title="✅ Tasks Defined Successfully!",
            description="Your daily tasks have been set. Complete them all to maintain your streak! 🔥",
            color=0x10B981
        )
        embed.add_field(
            name="📋 Your Daily Tasks",
            value=tasks_formatted,
            inline=False
        )
        embed.add_field(
            name="⚡ Next Steps",
            value="Use `/streak_complete` when you finish all tasks today!",
            inline=False
        )
        embed.set_footer(text="Consistency is key to success")
        embed.timestamp = datetime.utcnow()
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="streak_start", description="Start or restart your streak by defining daily tasks")
async def streak_start(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    
    if user_id in streakboard_data["players"]:
        player = streakboard_data["players"][user_id]
        if player.get("streak_active", False) and player.get("streak", 0) > 0:
            return await interaction.response.send_message(
                "❌ You already have an active streak! Use `/streak_view` to see your progress.",
                ephemeral=True
            )
    
    await interaction.response.send_modal(TaskModal())


@tree.command(name="streak_addtask", description="Add a new task to your active streak")
@app_commands.describe(task="The task to add to your daily routine")
async def streak_addtask(interaction: discord.Interaction, task: str):
    user_id = str(interaction.user.id)
    
    if user_id not in streakboard_data["players"]:
        return await interaction.response.send_message(
            "❌ You don't have a streak yet! Use `/streak_start` to begin.",
            ephemeral=True
        )
    
    player = streakboard_data["players"][user_id]
    
    if task in player["tasks"]:
        return await interaction.response.send_message("❌ This task already exists!", ephemeral=True)
    
    player["tasks"].append(task)
    save_streakboard(streakboard_data)
    
    embed = discord.Embed(
        title="✅ Task Added!",
        description=f"Successfully added: **{task}**",
        color=0x10B981
    )
    embed.add_field(
        name="📝 Total Tasks",
        value=f"You now have **{len(player['tasks'])}** daily tasks",
        inline=False
    )
    embed.set_footer(text="Remember: You can't remove tasks during an active streak")
    embed.timestamp = datetime.utcnow()
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="streak_complete", description="Mark all your tasks as complete for today")
async def streak_complete(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    
    if user_id not in streakboard_data["players"]:
        return await interaction.response.send_message(
            "❌ You don't have any tasks defined! Use `/streak_start` to begin.",
            ephemeral=True
        )
    
    player = streakboard_data["players"][user_id]
    
    if len(player["tasks"]) == 0:
        return await interaction.response.send_message(
            "❌ You need to define tasks first! Use `/streak_start`.",
            ephemeral=True
        )
    
    player["streak"] += 1
    player["last_completion"] = datetime.utcnow().isoformat()
    player["streak_active"] = True
    player["username"] = interaction.user.display_name
    
    save_streakboard(streakboard_data)
    
    streak_emoji = "🔥" * min(player["streak"], 10)
    
    embed = discord.Embed(
        title="🎉 Tasks Completed!",
        description=f"Amazing work, {interaction.user.mention}! All tasks completed for today.",
        color=0xF59E0B
    )
    embed.add_field(
        name=f"{streak_emoji} Current Streak",
        value=f"**{player['streak']} days**",
        inline=True
    )
    embed.add_field(
        name="📅 Last Completion",
        value=f"<t:{int(datetime.utcnow().timestamp())}:R>",
        inline=True
    )
    embed.add_field(
        name="💪 Keep Going!",
        value="Don't forget to complete your tasks tomorrow to maintain the streak!",
        inline=False
    )
    embed.set_footer(text="Consistency builds excellence")
    embed.timestamp = datetime.utcnow()
    
    await interaction.response.send_message(embed=embed)


@tree.command(name="streak_view", description="View your current streak and tasks")
async def streak_view(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    
    if user_id not in streakboard_data["players"]:
        embed = discord.Embed(
            title="📊 No Streak Found",
            description="You haven't started tracking your streak yet!",
            color=0x6B7280
        )
        embed.add_field(
            name="🚀 Get Started",
            value="Use `/streak_start` to define your daily tasks and begin your journey!",
            inline=False
        )
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    player = streakboard_data["players"][user_id]
    
    streak_emoji = "🔥" * min(max(player["streak"], 1), 10)
    status = "✅ Active" if player.get("streak_active") else "⏸️ Inactive"
    
    embed = discord.Embed(
        title=f"{streak_emoji} Your Streak",
        description=f"**Status:** {status}",
        color=0xF59E0B if player.get("streak_active") else 0x6B7280
    )
    embed.add_field(
        name="📈 Current Streak",
        value=f"**{player['streak']} days**",
        inline=True
    )
    
    if player.get("last_completion"):
        last_time = datetime.fromisoformat(player["last_completion"])
        embed.add_field(
            name="⏰ Last Completion",
            value=f"<t:{int(last_time.timestamp())}:R>",
            inline=True
        )
    
    tasks_formatted = "\n".join([f"• {task}" for task in player["tasks"]])
    embed.add_field(
        name="📋 Daily Tasks",
        value=tasks_formatted if tasks_formatted else "*No tasks defined*",
        inline=False
    )
    
    embed.set_footer(text=f"Season {streakboard_data['season_number']}")
    embed.timestamp = datetime.utcnow()
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="streakboard", description="View the global streakboard leaderboard")
async def streakboard(interaction: discord.Interaction):
    players = streakboard_data["players"]
    
    active_players = {
        uid: data for uid, data in players.items()
        if data.get("streak_active") and data.get("streak", 0) > 0
    }
    
    if not active_players:
        embed = discord.Embed(
            title="🏆 Streakboard",
            description="No active streaks yet! Be the first to start one with `/streak_start`",
            color=0x6B7280
        )
        embed.set_footer(text=f"Season {streakboard_data['season_number']}")
        return await interaction.response.send_message(embed=embed)
    
    sorted_players = sorted(
        active_players.items(),
        key=lambda x: x[1]["streak"],
        reverse=True
    )
    
    leaderboard_text = ""
    medals = ["🥇", "🥈", "🥉"]
    
    for idx, (uid, data) in enumerate(sorted_players[:10]):
        medal = medals[idx] if idx < 3 else f"**{idx + 1}.**"
        username = data.get("username", "Unknown")
        streak = data["streak"]
        fire = "🔥" * min(streak // 5 + 1, 5)
        
        leaderboard_text += f"{medal} **{username}** — {streak} days {fire}\n"
    
    embed = discord.Embed(
        title="🏆 Streakboard Leaderboard",
        description=leaderboard_text,
        color=0xF59E0B
    )
    
    season_start = datetime.fromisoformat(streakboard_data["season_start"])
    embed.add_field(
        name="📅 Current Season",
        value=f"Season {streakboard_data['season_number']} • Started <t:{int(season_start.timestamp())}:R>",
        inline=False
    )
    embed.add_field(
        name="👥 Active Streakers",
        value=f"**{len(active_players)}** players maintaining streaks",
        inline=True
    )
    
    if sorted_players:
        longest = max(sorted_players, key=lambda x: x[1]["streak"])
        embed.add_field(
            name="🔥 Longest Streak",
            value=f"**{longest[1]['streak']} days** by {longest[1].get('username', 'Unknown')}",
            inline=True
        )
    
    embed.set_footer(text="Keep up the momentum! 💪")
    embed.timestamp = datetime.utcnow()
    
    await interaction.response.send_message(embed=embed)


@tree.command(name="streak_reset_season", description="[ADMIN] Reset the season and all streaks")
async def streak_reset_season(interaction: discord.Interaction):
    if not any(role.id in ALLOWED_ROLES for role in interaction.user.roles):
        return await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
    
    global streakboard_data
    
    old_season = streakboard_data["season_number"]
    
    streakboard_data = {
        "season_start": datetime.utcnow().isoformat(),
        "season_number": old_season + 1,
        "players": {}
    }
    
    save_streakboard(streakboard_data)
    
    embed = discord.Embed(
        title="🔄 New Season Started!",
        description=f"Season {old_season} has ended. Welcome to **Season {streakboard_data['season_number']}**!",
        color=0x8B5CF6
    )
    embed.add_field(
        name="✨ Fresh Start",
        value="All streaks have been reset. Time to build new habits and chase new goals!",
        inline=False
    )
    embed.add_field(
        name="🚀 Get Started",
        value="Use `/streak_start` to begin your journey in the new season!",
        inline=False
    )
    embed.set_footer(text="New season, new opportunities")
    embed.timestamp = datetime.utcnow()
    
    await interaction.response.send_message(embed=embed)

# =====================================================
#              JOURNAL REMINDER COMMANDS (CONTINUED)
# =====================================================

@tree.command(name="remindjournal", description="Enable/disable daily journal reminders at 9 PM IST")
@app_commands.describe(enable="True to enable reminders, False to disable")
async def remindjournal(interaction: discord.Interaction, enable: bool):
    user_id = str(interaction.user.id)

    if user_id not in journal_data:
        journal_data[user_id] = {
            "enabled": False,
            "last_post": None
        }

    journal_data[user_id]["enabled"] = enable
    save_journal_data(journal_data)

    status = "enabled ✅" if enable else "disabled ❌"

    embed = discord.Embed(
        title="📔 Journal Reminder Updated",
        description=f"Daily journal reminders have been **{status}**.",
        color=0x10B981 if enable else 0xEF4444
    )
    embed.add_field(
        name="⏰ Reminder Time",
        value="Every day at **9:00 PM IST**",
        inline=False
    )
    embed.set_footer(text="Consistency compounds over time")
    embed.timestamp = datetime.utcnow()

    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="journalpost", description="Mark today's journal as completed")
async def journalpost(interaction: discord.Interaction):
    user_id = str(interaction.user.id)

    if user_id not in journal_data:
        journal_data[user_id] = {
            "enabled": True,
            "last_post": None
        }

    journal_data[user_id]["last_post"] = datetime.utcnow().isoformat()
    save_journal_data(journal_data)

    embed = discord.Embed(
        title="📝 Journal Logged",
        description="Great job! Today's journal entry has been marked as complete. 🌙",
        color=0x8B5CF6
    )
    embed.add_field(
        name="🔥 Momentum",
        value="Show up again tomorrow. Small wins build big discipline.",
        inline=False
    )
    embed.set_footer(text="Reflection sharpens the mind")
    embed.timestamp = datetime.utcnow()

    await interaction.response.send_message(embed=embed, ephemeral=True)


# =====================================================
#              TEAM JOIN VIEW (BUTTON UI)
# =====================================================

class TeamJoinView(View):
    def __init__(self, event_name: str):
        super().__init__(timeout=None)
        self.event_name = event_name

    @discord.ui.button(label="Join Team X", style=discord.ButtonStyle.primary, custom_id="join_team_x")
    async def join_x(self, interaction: discord.Interaction, button: Button):
        team = pick_team_for_user(interaction.user.id, self.event_name)
        role = interaction.guild.get_role(TEAM_X_ROLE_ALT if team == "A" else TEAM_Y_ROLE_ALT)

        await interaction.user.add_roles(role, reason="Team join via button")

        embed = discord.Embed(
            title="⚔️ Team Assigned",
            description=f"You have been placed in **{role.name}**",
            color=0x3B82F6
        )
        embed.set_footer(text="Balanced & deterministic assignment")
        embed.timestamp = datetime.utcnow()

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Join Team Y", style=discord.ButtonStyle.secondary, custom_id="join_team_y")
    async def join_y(self, interaction: discord.Interaction, button: Button):
        team = pick_team_for_user(interaction.user.id, self.event_name)
        role = interaction.guild.get_role(TEAM_Y_ROLE_ALT if team == "A" else TEAM_X_ROLE_ALT)

        await interaction.user.add_roles(role, reason="Team join via button")

        embed = discord.Embed(
            title="⚔️ Team Assigned",
            description=f"You have been placed in **{role.name}**",
            color=0x6366F1
        )
        embed.set_footer(text="Balanced & deterministic assignment")
        embed.timestamp = datetime.utcnow()

        await interaction.response.send_message(embed=embed, ephemeral=True)


# =====================================================
#              LAST STAND GAME COMMANDS
# =====================================================

@tree.command(name="laststand_start", description="[ADMIN] Start a Last Stand challenge")
async def laststand_start(interaction: discord.Interaction, lives: int = 3):
    if not any(role.id in ALLOWED_ROLES for role in interaction.user.roles):
        return await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)

    last_stand_data.update({
        "active": True,
        "players": {},
        "starting_lives": lives,
        "pom_logs": []
    })

    save_last_stand(last_stand_data)

    embed = discord.Embed(
        title="🔥 Last Stand Started",
        description=f"Survival challenge is live! Everyone starts with **{lives} lives**.",
        color=0xEF4444
    )
    embed.set_footer(text="Stay disciplined or get eliminated")
    embed.timestamp = datetime.utcnow()

    await interaction.response.send_message(embed=embed)


@tree.command(name="laststand_join", description="Join the active Last Stand challenge")
async def laststand_join(interaction: discord.Interaction):
    if not last_stand_data.get("active", False):
        return await interaction.response.send_message("❌ No active Last Stand game.", ephemeral=True)

    uid = str(interaction.user.id)

    if uid in last_stand_data["players"]:
        return await interaction.response.send_message("❌ You already joined.", ephemeral=True)

    last_stand_data["players"][uid] = {
        "lives": last_stand_data["starting_lives"],
        "username": interaction.user.display_name
    }

    save_last_stand(last_stand_data)

    embed = discord.Embed(
        title="🛡️ Joined Last Stand",
        description=f"You have **{last_stand_data['starting_lives']} lives**. Stay sharp.",
        color=0xF59E0B
    )
    embed.set_footer(text="One mistake can cost everything")
    embed.timestamp = datetime.utcnow()

    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="laststand_fail", description="[ADMIN] Remove a life from a player")
@app_commands.describe(user="User who failed")
async def laststand_fail(interaction: discord.Interaction, user: discord.Member):
    if not any(role.id in ALLOWED_ROLES for role in interaction.user.roles):
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)

    uid = str(user.id)

    if uid not in last_stand_data["players"]:
        return await interaction.response.send_message("❌ User not in Last Stand.", ephemeral=True)

    last_stand_data["players"][uid]["lives"] -= 1

    lives = last_stand_data["players"][uid]["lives"]

    if lives <= 0:
        del last_stand_data["players"][uid]
        result = "☠️ Eliminated"
    else:
        result = f"💔 {lives} lives remaining"

    save_last_stand(last_stand_data)

    embed = discord.Embed(
        title="⚠️ Last Stand Update",
        description=f"**{user.display_name}** → {result}",
        color=0xEF4444
    )
    embed.set_footer(text="Pressure reveals discipline")
    embed.timestamp = datetime.utcnow()

    await interaction.response.send_message(embed=embed)


# =====================================================
#              BOT RUN
# =====================================================

bot.run(TOKEN)
