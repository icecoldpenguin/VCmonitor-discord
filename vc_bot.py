from dotenv import load_dotenv
load_dotenv()

import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Button
import asyncio
from datetime import datetime, time, timedelta
import os
import json
import mmh3
import aiohttp
import base64
import json
import hashlib
import time as time_module
import pytz
from typing import Literal

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
# Structure: { "user_id": { "enabled": bool, "journal_thread_id": int, "last_reminder_sent": "ISO_timestamp" } }

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
#                      EMBEDS
# =====================================================

def make_initial_kick_embed(member, vc):
    embed = discord.Embed(
        title="Voice Enforcement Notice",
        description=(
            f"Hey {member.mention},\n\n"
            "You were removed from the voice channel because you didn't enable "
            "**camera or stream** within the allowed time."
        ),
        color=0xF97316
    )
    embed.timestamp = datetime.utcnow()
    return embed

def make_reminder_embed(member, vc):
    embed = discord.Embed(
        title="Reminder: Turn On Stream / Camera",
        description=(
            f"{member.mention}, you turned off your **stream/camera**.\n\n"
            "Please re-enable it within **3 minutes**, or you may be removed."
        ),
        color=0x22C55E
    )
    embed.timestamp = datetime.utcnow()
    return embed

def make_post_stream_kick_embed(member, vc):
    embed = discord.Embed(
        title="You Were Removed From the Voice Channel",
        description=(
            f"{member.mention}, you were removed because your "
            "**stream/camera stayed off** after the reminder period."
        ),
        color=0xEF4444
    )
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

    # stable hash
    def stable_hash(member: discord.Member):
        key = f"{event_name}:{member.id}".encode()
        return int(hashlib.sha256(key).hexdigest(), 16)

    # sort
    sorted_members = sorted(humans, key=lambda m: stable_hash(m))

    half = len(sorted_members) // 2
    team_x = sorted_members[:half]
    team_y = sorted_members[half:]

    # --- IMPORTANT FIX: remove BOTH roles from ALL users first ---
    for m in humans:
        try:
            await m.remove_roles(team_x_role, team_y_role, reason="Rebalancing teams")
        except:
            pass

    # assign correctly
    for m in team_x:
        await m.add_roles(team_x_role, reason="Balanced deterministic assignment")

    for m in team_y:
        await m.add_roles(team_y_role, reason="Balanced deterministic assignment")

    return len(team_x), len(team_y)

def pick_team_for_user(user_id: int, event_name: str) -> str:
    """
    Deterministic 50/50 assignment:
    team = SHA256(event_name + user_id) % 2
    """
    key = f"{event_name}:{user_id}".encode()
    h = int(hashlib.sha256(key).hexdigest(), 16)
    return "A" if (h % 2 == 0) else "B"

TEAM_X_ROLE = 1444727473643327581
TEAM_Y_ROLE = 1444727513489215641

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

@tasks.loop(minutes=5)
async def check_journal_reminders():
    """Check every 5 minutes if it's between 9 PM and 9:30 PM IST and send reminders"""
    
    # Get current time in IST
    ist = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(ist)
    
    # Check if it's between 9:00 PM and 9:30 PM IST (gives us a 30-minute window)
    if 21 <= now_ist.hour < 22 or (now_ist.hour == 21 and now_ist.minute <= 30):
        print(f"[JOURNAL] Checking for journal reminders at {now_ist.strftime('%I:%M %p IST')}")
        
        # Get today's date in IST (just the date part)
        today_date = now_ist.date()
        
        # Calculate 24 hours ago in UTC for message checking
        twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
        
        # Check if we need to send reminders
        for user_id, data in list(journal_data.items()):
            # Skip if reminders disabled
            if not data.get("enabled", False):
                continue
            
            # Get the journal thread ID
            journal_thread_id = data.get("journal_thread_id")
            if not journal_thread_id:
                print(f"[JOURNAL] User {user_id} has no journal thread set, skipping")
                continue
            
            # Check if we already sent a reminder today
            last_reminder_str = data.get("last_reminder_sent")
            if last_reminder_str:
                try:
                    last_reminder_utc = datetime.fromisoformat(last_reminder_str.replace('Z', '+00:00'))
                    if last_reminder_utc.tzinfo is None:
                        last_reminder_utc = pytz.utc.localize(last_reminder_utc)
                    last_reminder_ist = last_reminder_utc.astimezone(ist)
                    
                    # If we already sent a reminder today, skip
                    if last_reminder_ist.date() == today_date:
                        print(f"[JOURNAL] Already sent reminder to {user_id} today")
                        continue
                except Exception as e:
                    print(f"[JOURNAL] Error parsing last_reminder for {user_id}: {e}")
            
            # Check if user posted in their journal thread in the last 24 hours
            needs_reminder = False
            
            try:
                # Get the journal thread
                thread = bot.get_channel(int(journal_thread_id))
                
                # If not in cache, try to fetch it
                if not thread:
                    try:
                        thread = await bot.fetch_channel(int(journal_thread_id))
                    except:
                        print(f"[JOURNAL] Cannot find thread {journal_thread_id} for user {user_id}")
                        continue
                
                # Check if it's actually a thread
                if not isinstance(thread, discord.Thread):
                    print(f"[JOURNAL] Channel {journal_thread_id} is not a thread for user {user_id}")
                    continue
                
                # Search for messages from this user in the last 24 hours
                has_posted = False
                async for message in thread.history(limit=200, after=twenty_four_hours_ago):
                    if message.author.id == int(user_id):
                        has_posted = True
                        print(f"[JOURNAL] User {user_id} posted in thread at {message.created_at}")
                        break
                
                if not has_posted:
                    needs_reminder = True
                    print(f"[JOURNAL] User {user_id} has NOT posted in the last 24 hours")
                else:
                    print(f"[JOURNAL] User {user_id} has posted in the last 24 hours, no reminder needed")
                    
            except discord.Forbidden:
                print(f"[JOURNAL] No permission to read thread {journal_thread_id}")
                continue
            except Exception as e:
                print(f"[JOURNAL] Error checking messages for user {user_id}: {e}")
                continue
            
            if needs_reminder:
                try:
                    user = await bot.fetch_user(int(user_id))
                    
                    # Get thread name for the reminder
                    thread_mention = f"<#{journal_thread_id}>" if thread else "your journal thread"
                    
                    embed = discord.Embed(
                        title="📔 Journal Reminder",
                        description=(
                            f"Hey! It looks like you haven't posted in {thread_mention} in the last 24 hours.\n\n"
                            "Take a moment to reflect on your day and write down your thoughts! 💭"
                        ),
                        color=0x5865F2,
                        timestamp=datetime.utcnow()
                    )
                    
                    await user.send(embed=embed)
                    
                    # Mark that we sent a reminder
                    journal_data[user_id]["last_reminder_sent"] = datetime.utcnow().isoformat()
                    save_journal_data(journal_data)
                    
                    print(f"[JOURNAL] ✅ Sent reminder to user {user_id}")
                    
                except discord.Forbidden:
                    print(f"[JOURNAL] ❌ Cannot DM user {user_id}")
                except Exception as e:
                    print(f"[JOURNAL] ❌ Error sending reminder to {user_id}: {e}")
        
        print(f"[JOURNAL] Finished checking reminders")


# =====================================================
#                     EVENTS
# =====================================================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    
    # Start the journal reminder task
    if not check_journal_reminders.is_running():
        check_journal_reminders.start()
        print("[JOURNAL] Journal reminder task started")
    
    try:
        synced = await bot.tree.sync()
        print("Synced:", len(synced))
    except Exception as e:
        print("Slash command sync failed:", e)
    
    # Register persistent views
    bot.add_view(TeamJoinView("default_event"))


@bot.event
async def on_voice_state_update(member, before, after):
    # Leaving monitored VC
    if before.channel and before.channel.id in MONITORED_VC_IDS:
        if not after.channel or after.channel.id not in MONITORED_VC_IDS:
            if member.id in initial_checks:
                initial_checks[member.id].cancel()
                initial_checks.pop(member.id)

            if member.id in post_stream_checks:
                for t in post_stream_checks[member.id].values():
                    t.cancel()
                post_stream_checks.pop(member.id)

    # Joining monitored VC
    if after.channel and after.channel.id in MONITORED_VC_IDS and not before.channel:
        if not has_required_activity(member):
            task = asyncio.create_task(initial_check_task(member, after.channel.id))
            initial_checks[member.id] = task

    before_active = before.self_stream or before.self_video if before else False
    after_active = after.self_stream or after.self_video if after else False

    # Turned ON stream/cam
    if not before_active and after_active:
        if member.id in initial_checks:
            initial_checks[member.id].cancel()
            initial_checks.pop(member.id)

        if member.id in post_stream_checks:
            for t in post_stream_checks[member.id].values():
                t.cancel()
            post_stream_checks.pop(member.id)

    # Turned OFF stream/cam
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
#              JOURNAL REMINDER COMMANDS
# =====================================================

@tree.command(name="remindjournal", description="Enable/disable daily journal reminders at 9 PM IST")
@app_commands.describe(
    enable="True to enable reminders, False to disable",
    journal_thread="The thread where you post your journal entries (right-click thread > Copy ID)"
)
async def remindjournal(interaction: discord.Interaction, enable: bool, journal_thread: str = None):
    user_id = str(interaction.user.id)
    
    if enable:
        # Must provide a thread ID when enabling
        if not journal_thread:
            return await interaction.response.send_message(
                "❌ You must specify a journal thread ID when enabling reminders!\n\n"
                "**How to get your thread ID:**\n"
                "1. Right-click on your journal thread\n"
                "2. Click 'Copy ID' (you need Developer Mode enabled)\n"
                "3. Use the command: `/remindjournal enable:True journal_thread:YOUR_THREAD_ID`\n\n"
                "**Enable Developer Mode:** User Settings > App Settings > Advanced > Developer Mode",
                ephemeral=True
            )
        
        # Validate thread ID
        try:
            thread_id = int(journal_thread)
        except ValueError:
            return await interaction.response.send_message(
                "❌ Invalid thread ID! Please provide a valid numeric thread ID.",
                ephemeral=True
            )
        
        # Try to fetch the thread to verify it exists
        try:
            thread = bot.get_channel(thread_id)
            if not thread:
                thread = await bot.fetch_channel(thread_id)
            
            # Verify it's actually a thread
            if not isinstance(thread, discord.Thread):
                return await interaction.response.send_message(
                    "❌ That ID is not a thread! Please provide a valid thread ID.",
                    ephemeral=True
                )
            
            thread_name = thread.name
            
        except discord.NotFound:
            return await interaction.response.send_message(
                "❌ Thread not found! Make sure the thread ID is correct and the bot has access to it.",
                ephemeral=True
            )
        except discord.Forbidden:
            return await interaction.response.send_message(
                "❌ I don't have permission to access that thread!",
                ephemeral=True
            )
        except Exception as e:
            return await interaction.response.send_message(
                f"❌ Error accessing thread: {e}",
                ephemeral=True
            )
        
        # Enable reminders for this user
        journal_data[user_id] = {
            "enabled": True,
            "journal_thread_id": thread_id,
            "last_reminder_sent": None
        }
        
        save_journal_data(journal_data)
        
        await interaction.response.send_message(
            f"✅ Journal reminders enabled!\n\n"
            f"**Monitoring thread:** {thread_name} (<#{thread_id}>)\n"
            f"**Reminder time:** 9:00 PM IST daily\n\n"
            f"You'll receive a reminder if you haven't posted in your journal thread "
            f"in the last 24 hours.",
            ephemeral=True
        )
    else:
        # Disable reminders
        if user_id in journal_data:
            journal_data[user_id]["enabled"] = False
            save_journal_data(journal_data)
        
        await interaction.response.send_message(
            "❌ Journal reminders disabled.",
            ephemeral=True
        )


@tree.command(name="journalstatus", description="Check your journal reminder settings")
async def journalstatus(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    
    if user_id not in journal_data:
        return await interaction.response.send_message(
            "You don't have journal reminders set up yet!\n\n"
            "**To set up:**\n"
            "1. Right-click on your journal thread\n"
            "2. Click 'Copy ID'\n"
            "3. Run: `/remindjournal enable:True journal_thread:YOUR_THREAD_ID`",
            ephemeral=True
        )
    
    data = journal_data[user_id]
    
    embed = discord.Embed(
        title="📔 Your Journal Reminder Settings",
        color=0x5865F2
    )
    
    embed.add_field(
        name="Status",
        value="✅ Enabled" if data.get("enabled") else "❌ Disabled",
        inline=True
    )
    
    thread_id = data.get("journal_thread_id")
    if thread_id:
        # Try to get thread name
        try:
            thread = bot.get_channel(int(thread_id))
            if not thread:
                thread = await bot.fetch_channel(int(thread_id))
            thread_display = f"{thread.name} (<#{thread_id}>)"
        except:
            thread_display = f"<#{thread_id}>"
        
        embed.add_field(
            name="Journal Thread",
            value=thread_display,
            inline=True
        )
    
    last_reminder = data.get("last_reminder_sent")
    if last_reminder:
        try:
            reminder_dt = datetime.fromisoformat(last_reminder.replace('Z', '+00:00'))
            embed.add_field(
                name="Last Reminder Sent",
                value=f"<t:{int(reminder_dt.timestamp())}:R>",
                inline=False
            )
        except:
            pass
    
    # Check if they've posted in the last 24 hours
    if thread_id and data.get("enabled"):
        try:
            thread = bot.get_channel(int(thread_id))
            if not thread:
                thread = await bot.fetch_channel(int(thread_id))
            
            if thread and isinstance(thread, discord.Thread):
                twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
                has_posted = False
                
                async for message in thread.history(limit=200, after=twenty_four_hours_ago):
                    if message.author.id == interaction.user.id:
                        has_posted = True
                        embed.add_field(
                            name="Recent Activity",
                            value=f"✅ You posted <t:{int(message.created_at.timestamp())}:R>",
                            inline=False
                        )
                        break
                
                if not has_posted:
                    embed.add_field(
                        name="Recent Activity",
                        value="❌ No posts in the last 24 hours",
                        inline=False
                    )
        except:
            pass
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


# =====================================================
#              LAST STAND GAME COMMANDS
# =====================================================

@tree.command(name="laststand_start", description="Start a new Last Stand game")
@app_commands.describe(starting_lives="Number of lives each player starts with (default: 3)")
async def laststand_start(interaction: discord.Interaction, starting_lives: int = 3):
    global last_stand_data
    
    # Check permission
    if not any(role.id in ALLOWED_ROLES for role in interaction.user.roles):
        return await interaction.response.send_message("You cannot use this command.", ephemeral=True)
    
    if last_stand_data["active"]:
        return await interaction.response.send_message("A game is already active! End it first with `/laststand_end`", ephemeral=True)
    
    last_stand_data = {
        "active": True,
        "players": {},
        "starting_lives": starting_lives,
        "pom_logs": []
    }
    save_last_stand(last_stand_data)
    
    embed = discord.Embed(
        title="🎯 LAST STAND - Game Started!",
        description=(
            f"A new Last Stand game has begun!\n\n"
            f"**Starting Lives:** {starting_lives}\n\n"
            "**How to Play:**\n"
            "• Join with `/laststand_join`\n"
            "• Log defensive poms: `/laststand_defend poms:4`\n"
            "• Attack others: `/laststand_attack target:@user poms:3`\n"
            "• View status: `/laststand_status`\n\n"
            "**Rules:**\n"
            "• Each defensive pom blocks one incoming attack pom\n"
            "• You can't use the same pom to attack and defend\n"
            "• When your lives reach 0, you're eliminated\n"
            "• Last one standing wins!"
        ),
        color=0xFF0000
    )
    
    await interaction.response.send_message(embed=embed)


@tree.command(name="laststand_join", description="Join the active Last Stand game")
async def laststand_join(interaction: discord.Interaction):
    global last_stand_data
    
    if not last_stand_data["active"]:
        return await interaction.response.send_message("No active game! Start one with `/laststand_start`", ephemeral=True)
    
    user_id = str(interaction.user.id)
    
    if user_id in last_stand_data["players"]:
        return await interaction.response.send_message("You're already in the game!", ephemeral=True)
    
    last_stand_data["players"][user_id] = {
        "name": interaction.user.display_name,
        "lives": last_stand_data["starting_lives"],
        "defense_poms": 0,
        "eliminated": False
    }
    save_last_stand(last_stand_data)
    
    await interaction.response.send_message(
        f"✅ {interaction.user.mention} joined the game with **{last_stand_data['starting_lives']} lives**!",
        ephemeral=False
    )


@tree.command(name="laststand_defend", description="Log defensive poms to block attacks")
@app_commands.describe(poms="Number of poms to add to your defense")
async def laststand_defend(interaction: discord.Interaction, poms: int):
    global last_stand_data
    
    if not last_stand_data["active"]:
        return await interaction.response.send_message("No active game!", ephemeral=True)
    
    user_id = str(interaction.user.id)
    
    if user_id not in last_stand_data["players"]:
        return await interaction.response.send_message("You're not in the game! Join with `/laststand_join`", ephemeral=True)
    
    player = last_stand_data["players"][user_id]
    
    if player["eliminated"]:
        return await interaction.response.send_message("You've been eliminated!", ephemeral=True)
    
    if poms <= 0:
        return await interaction.response.send_message("Poms must be positive!", ephemeral=True)
    
    player["defense_poms"] += poms
    
    last_stand_data["pom_logs"].append({
        "type": "defend",
        "user_id": user_id,
        "user_name": interaction.user.display_name,
        "poms": poms,
        "timestamp": datetime.utcnow().isoformat()
    })
    
    save_last_stand(last_stand_data)
    
    await interaction.response.send_message(
        f"🛡️ {interaction.user.mention} added **{poms} defensive poms**! Total defense: **{player['defense_poms']}**",
        ephemeral=False
    )


@tree.command(name="laststand_attack", description="Attack another player with poms")
@app_commands.describe(
    target="The player to attack",
    poms="Number of poms to use in the attack"
)
async def laststand_attack(interaction: discord.Interaction, target: discord.Member, poms: int):
    global last_stand_data
    
    if not last_stand_data["active"]:
        return await interaction.response.send_message("No active game!", ephemeral=True)
    
    attacker_id = str(interaction.user.id)
    target_id = str(target.id)
    
    if attacker_id not in last_stand_data["players"]:
        return await interaction.response.send_message("You're not in the game!", ephemeral=True)
    
    if target_id not in last_stand_data["players"]:
        return await interaction.response.send_message("Target is not in the game!", ephemeral=True)
    
    if attacker_id == target_id:
        return await interaction.response.send_message("You can't attack yourself!", ephemeral=True)
    
    attacker = last_stand_data["players"][attacker_id]
    target_player = last_stand_data["players"][target_id]
    
    if attacker["eliminated"]:
        return await interaction.response.send_message("You've been eliminated!", ephemeral=True)
    
    if target_player["eliminated"]:
        return await interaction.response.send_message("That player is already eliminated!", ephemeral=True)
    
    if poms <= 0:
        return await interaction.response.send_message("Poms must be positive!", ephemeral=True)
    
    # Process attack with defense
    remaining_poms = poms
    blocked_poms = 0
    
    if target_player["defense_poms"] > 0:
        blocked_poms = min(remaining_poms, target_player["defense_poms"])
        target_player["defense_poms"] -= blocked_poms
        remaining_poms -= blocked_poms
    
    # Apply damage
    damage = remaining_poms
    target_player["lives"] -= damage
    
    # Check if eliminated
    if target_player["lives"] <= 0:
        target_player["lives"] = 0
        target_player["eliminated"] = True
    
    last_stand_data["pom_logs"].append({
        "type": "attack",
        "attacker_id": attacker_id,
        "attacker_name": interaction.user.display_name,
        "target_id": target_id,
        "target_name": target.display_name,
        "poms": poms,
        "blocked": blocked_poms,
        "damage": damage,
        "timestamp": datetime.utcnow().isoformat()
    })
    
    save_last_stand(last_stand_data)
    
    # Create response
    response = f"⚔️ {interaction.user.mention} attacked {target.mention} with **{poms} poms**!\n\n"
    
    if blocked_poms > 0:
        response += f"🛡️ **{blocked_poms}** poms blocked by defense!\n"
    
    if damage > 0:
        response += f"💥 **{damage}** damage dealt!\n"
    
    response += f"\n{target.mention} now has **{target_player['lives']} lives** remaining"
    
    if target_player["eliminated"]:
        response += "\n\n💀 **ELIMINATED!**"
        
        # Check if game is over
        alive_players = [p for p in last_stand_data["players"].values() if not p["eliminated"]]
        if len(alive_players) == 1:
            winner_id = [uid for uid, p in last_stand_data["players"].items() if not p["eliminated"]][0]
            winner = last_stand_data["players"][winner_id]
            response += f"\n\n🏆 **GAME OVER!** {winner['name']} wins with **{winner['lives']} lives** remaining!"
    
    await interaction.response.send_message(response, ephemeral=False)


@tree.command(name="laststand_status", description="View the current game status")
async def laststand_status(interaction: discord.Interaction):
    global last_stand_data
    
    if not last_stand_data["active"]:
        return await interaction.response.send_message("No active game!", ephemeral=True)
    
    if not last_stand_data["players"]:
        return await interaction.response.send_message("No players have joined yet!", ephemeral=True)
    
    embed = discord.Embed(
        title="🎯 LAST STAND - Current Status",
        color=0xFF0000
    )
    
    alive_players = []
    eliminated_players = []
    
    for user_id, player in last_stand_data["players"].items():
        status = f"**{player['name']}**\n"
        status += f"❤️ Lives: {player['lives']}\n"
        status += f"🛡️ Defense: {player['defense_poms']}\n"
        
        if player["eliminated"]:
            eliminated_players.append(status)
        else:
            alive_players.append(status)
    
    if alive_players:
        embed.add_field(
            name=f"🟢 Alive ({len(alive_players)})",
            value="\n".join(alive_players),
            inline=False
        )
    
    if eliminated_players:
        embed.add_field(
            name=f"💀 Eliminated ({len(eliminated_players)})",
            value="\n".join(eliminated_players),
            inline=False
        )
    
    await interaction.response.send_message(embed=embed)


@tree.command(name="laststand_end", description="End the current Last Stand game")
async def laststand_end(interaction: discord.Interaction):
    global last_stand_data
    
    # Check permission
    if not any(role.id in ALLOWED_ROLES for role in interaction.user.roles):
        return await interaction.response.send_message("You cannot use this command.", ephemeral=True)
    
    if not last_stand_data["active"]:
        return await interaction.response.send_message("No active game!", ephemeral=True)
    
    # Find winner if any
    alive_players = [(uid, p) for uid, p in last_stand_data["players"].items() if not p["eliminated"]]
    
    embed = discord.Embed(
        title="🎯 LAST STAND - Game Ended",
        color=0xFF0000
    )
    
    if len(alive_players) == 1:
        winner_id, winner = alive_players[0]
        embed.description = f"🏆 **Winner:** {winner['name']}\n**Lives Remaining:** {winner['lives']}"
    else:
        embed.description = "Game ended with multiple survivors or no clear winner."
    
    last_stand_data = {
        "active": False,
        "players": {},
        "starting_lives": 3,
        "pom_logs": []
    }
    save_last_stand(last_stand_data)
    
    await interaction.response.send_message(embed=embed)


# =====================================================
#                     INVITE COMMAND
# =====================================================

@tree.command(name="invite", description="Invite a user to your current voice channel")
async def invite_user(interaction, user: discord.Member):
    inviter = interaction.user

    if not inviter.voice or not inviter.voice.channel:
        return await interaction.response.send_message(
            "You must be in a VC to invite someone.", ephemeral=True
        )

    vc = inviter.voice.channel

    embed = discord.Embed(
        title="VC Invitation",
        description=f"{inviter.mention} invited you to join **{vc.name}**\n\nClick here: <#{vc.id}>",
        color=0x5865F2
    )
    embed.timestamp = datetime.utcnow()

    try:
        await user.send(embed=embed)
        await interaction.response.send_message(
            f"Sent an invite to {user.mention}!", ephemeral=False
        )
    except:
        await interaction.response.send_message(
            "User cannot be DMed.", ephemeral=False
        )


ALLOWED_ROLES = {
    1438159005846605926,
    1423663604070223913,
    1420803949312610384
}

@tree.command(name="addpoints", description="Add points to a user's team.")
async def addpoints(interaction: discord.Interaction, user: discord.Member, points: int):

    # Permission check
    if not any(role.id in ALLOWED_ROLES for role in interaction.user.roles):
        return await interaction.response.send_message("You cannot use this command.", ephemeral=True)

    # Determine the user's team using your mmh3 logic
    team_name = calculate_team(user.id)  # You already have this logic earlier

    # Load current points
    pts = await get_team_points()

    if team_name == "X":
        pts["X"] += points
    else:
        pts["Y"] += points

    # Save back to GitHub
    await set_team_points(pts["X"], pts["Y"])

    await interaction.response.send_message(
        f"Added **{points}** points to **Team {team_name}**!\n\n"
        f"New totals — X: `{pts['X']}`, Y: `{pts['Y']}`"
    )


@tree.command(name="viewteampoints", description="View current X/Y team scores.")
async def viewteampoints(interaction: discord.Interaction):
    pts = await get_team_points()

    embed = discord.Embed(
        title="Team Scores",
        color=0x5865F2
    )
    embed.add_field(name="Team X", value=f"**{pts['X']}**", inline=True)
    embed.add_field(name="Team Y", value=f"**{pts['Y']}**", inline=True)

    await interaction.response.send_message(embed=embed)

async def assign_team_role(member: discord.Member):
    team = calculate_team(member.id)

    x_role = member.guild.get_role(TEAM_X_ROLE)
    y_role = member.guild.get_role(TEAM_Y_ROLE)

    # remove both roles in case user switches
    try:
        await member.remove_roles(x_role, y_role)
    except:
        pass

    if team == "X":
        await member.add_roles(x_role)
        return "X"
    else:
        await member.add_roles(y_role)
        return "Y"

@tree.command(name="assignteams", description="Assign perfectly balanced teams deterministically.")
@app_commands.describe(event_name="Name of the event used in hashing")
async def assignteams(interaction: discord.Interaction, event_name: str):

    TEAM_X_ROLE = 1443554800405975091
    TEAM_Y_ROLE = 1443555914534617168

    await interaction.response.send_message("Assigning teams... This may take a few seconds.", ephemeral=True)

    x_count, y_count = await assign_balanced_teams(
        interaction.guild,
        event_name,
        TEAM_X_ROLE,
        TEAM_Y_ROLE
    )

    await interaction.followup.send(
        f"Teams assigned!\n"
        f"**Team X:** {x_count} members\n"
        f"**Team Y:** {y_count} members"
    )

EVENT_CHANNEL_ID = 1424749944882991114
EVENT_VC_ID = 1438178530620866581

class TeamJoinButton(Button):
    def __init__(self, event_name: str):
        super().__init__(
            label="Join Event",
            style=discord.ButtonStyle.blurple,
            custom_id=f"jointeam_{event_name}"   # persists
        )
        self.event_name = event_name

    async def callback(self, interaction: discord.Interaction):

        guild = interaction.guild
        member = interaction.user
        
        # Roles
        x_role = guild.get_role(TEAM_X_ROLE)
        y_role = guild.get_role(TEAM_Y_ROLE)

        # Already assigned?
        if x_role in member.roles or y_role in member.roles:
            return await interaction.response.send_message(
                "You already have a team!", ephemeral=True
            )

        # Pick deterministic team
        team = pick_team_for_user(member.id, self.event_name)

        if team == "A":
            await member.add_roles(x_role)
        else:
            await member.add_roles(y_role)

        await interaction.response.send_message(
            f"You have been assigned to **Team {team}**!",
            ephemeral=True
        )

class TeamJoinView(View):
    def __init__(self, event_name: str):
        super().__init__(timeout=None)  # persistent forever
        self.add_item(TeamJoinButton(event_name))

@tree.command(name="assignteamembed", description="Post a join-event embed with team auto assignment button.")
@app_commands.describe(event_name="Name of the event used for hashing")
async def assignteamembed(interaction: discord.Interaction, event_name: str):

    embed = discord.Embed(
        title="Join The Event!",
        description=(
            "Click the button below to join the event.\n\n"
            "You will automatically be assigned to **Team A** or **Team B** "
            f"based on a secure per-event hash.\n\n"
            f"**Event:** `{event_name}`"
        ),
        color=0x5865F2
    )

    await interaction.response.send_message(
        "Team assignment panel created!",
        ephemeral=True
    )

    await interaction.channel.send(
        embed=embed,
        view=TeamJoinView(event_name)
    )

# =====================================================
#                        REMINDER
# =====================================================

EVENT_CHANNEL_ID = 1424749944882991114
EVENT_VC_ID = 1438178530620866581

@tree.command(name="reminder", description="Schedule a reminder for a specific timestamp.")
async def reminder(
    interaction: discord.Interaction,
    reminder_about: str,
    timestamp: int
):
    """
    /reminder reminder_about:"Study Session" timestamp:1700000000
    -> Bot waits until that timestamp - 600 seconds (10 min)
    -> Sends event reminder message
    """

    # CURRENT TIME
    now = int(time_module.time())

    # We want reminder 10 minutes BEFORE the timestamp
    reminder_time = timestamp - 600  # 600 sec = 10 min

    if reminder_time <= now:
        return await interaction.response.send_message(
            "That timestamp is too soon or already passed!",
            ephemeral=True
        )

    wait_seconds = reminder_time - now

    await interaction.response.send_message(
        f"Reminder scheduled! I will send it **10 minutes before** <t:{timestamp}:F>.",
        ephemeral=True
    )

    async def reminder_task():
        await asyncio.sleep(wait_seconds)

        channel = interaction.guild.get_channel(EVENT_CHANNEL_ID)
        if channel is None:
            print("[REMINDER] Error: channel not found.")
            return

        msg = (
            "@everyone\n"
            "**🔔 EVENT REMINDER**\n"
            f"{reminder_about} will start in **10 minutes**, hop in on <#{EVENT_VC_ID}>.\n\n"
            f"Event time: <t:{timestamp}:F>"
        )

        try:
            await channel.send(msg)
            print(f"[REMINDER] Sent reminder for timestamp {timestamp}")
        except Exception as e:
            print(f"[REMINDER ERROR] {e}")

    asyncio.create_task(reminder_task())
    
# =====================================================
#                   RENDER WEB SERVER
# =====================================================

from aiohttp import web

async def start_webserver():
    app = web.Application()
    app.add_routes([web.get("/", lambda r: web.Response(text="Bot Alive"))])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 10000)
    await site.start()
    print("Heartbeat running")

# ------------------- GITHUB PERSISTENCE LAYER -----------------------

GH_TOKEN = os.getenv("GH_TOKEN")
GH_OWNER = os.getenv("GH_REPO_OWNER")
GH_REPO = os.getenv("GH_REPO_NAME")
GH_FILE = os.getenv("GH_POINTS_FILE_PATH")

GH_API_BASE = f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_FILE}"

# store SHA so updates work correctly
points_file_sha = None  


async def github_get_points():
    """Load points.json from GitHub or create it if missing."""
    global points_file_sha

    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(GH_API_BASE, headers=headers) as r:
            if r.status == 200:
                data = await r.json()
                points_file_sha = data["sha"]  # required for updating files later

                content = base64.b64decode(data["content"]).decode()
                try:
                    points = json.loads(content)
                    return points
                except:
                    return {"X": 0, "Y": 0}

            else:
                # File does not exist → create default one
                print("[GITHUB] points.json missing → creating new one...")
                await github_update_points({"X": 0, "Y": 0})
                return {"X": 0, "Y": 0}


async def github_update_points(points_dict):
    """Save updated points.json to GitHub."""
    global points_file_sha

    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    content_bytes = json.dumps(points_dict, indent=4).encode()
    encoded = base64.b64encode(content_bytes).decode()

    payload = {
        "message": "update team points",
        "content": encoded,
        "sha": points_file_sha
    }

    async with aiohttp.ClientSession() as session:
        async with session.put(GH_API_BASE, headers=headers, json=payload) as r:
            if r.status in [200, 201]:
                resp = await r.json()
                points_file_sha = resp["content"]["sha"]
                print("[GITHUB] Points updated successfully.")
            else:
                print("[GITHUB] Failed to update points:", r.status)
                print(await r.text())

async def get_team_points():
    """Loads the X/Y team scores from GitHub."""
    return await github_get_points()


async def set_team_points(x_points, y_points):
    """Writes the new values back to GitHub."""
    await github_update_points({"X": x_points, "Y": y_points})

# ================= CODEFORCES CHANNEL UPDATER =================

import aiohttp
import base64
import json
import os
import discord
from discord.ext import tasks
from discord import app_commands

# ---------- CONFIG ----------
CODEFORCES_API = "https://codeforces.com/api/contest.list"

GH_CF_FILE = os.getenv("GH_CF_FILE_PATH")
GH_OWNER = os.getenv("GH_REPO_OWNER")
GH_REPO = os.getenv("GH_REPO_NAME")
GH_TOKEN = os.getenv("GH_TOKEN")
GH_LC_FILE = os.getenv("GH_LC_FILE_PATH")
GH_LC_API = f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_LC_FILE}"

GH_CF_API = f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_CF_FILE}"

cf_file_sha = None


# ---------- GITHUB STORAGE ----------
async def github_get_cf_data():
    global cf_file_sha

    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(GH_CF_API, headers=headers) as r:
            text = await r.text()

            # ---------- FILE EXISTS ----------
            if r.status == 200:
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    raise RuntimeError(
                        f"GitHub returned invalid JSON (200):\n{text}"
                    )

                cf_file_sha = data["sha"]

                try:
                    content = base64.b64decode(data["content"]).decode()
                    return json.loads(content)
                except Exception:
                    # file exists but is empty/corrupt → reset safely
                    default = {
                        "channels": [],
                        "last_contest_id": None
                    }
                    await github_set_cf_data(default)
                    return default

            # ---------- FILE DOES NOT EXIST ----------
            if r.status == 404:
                default = {
                    "channels": [],
                    "last_contest_id": None
                }
                await github_set_cf_data(default)
                return default

            # ---------- ANY OTHER RESPONSE ----------
            raise RuntimeError(
                f"GitHub GET failed ({r.status})\n{text}"
            )

async def github_set_cf_data(data_dict):
    global cf_file_sha

    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    encoded = base64.b64encode(
        json.dumps(data_dict, indent=4).encode()
    ).decode()

    payload = {
        "message": "update codeforces state",
        "content": encoded
    }

    if cf_file_sha:
        payload["sha"] = cf_file_sha

    async with aiohttp.ClientSession() as session:
        async with session.put(GH_CF_API, headers=headers, json=payload) as r:

            if r.status not in (200, 201):
                text = await r.text()
                raise RuntimeError(
                    f"GitHub PUT failed ({r.status})\n{text}"
                )

            resp = await r.json()
            cf_file_sha = resp["content"]["sha"]

# ================= LEETCODE STORAGE =================

lc_file_sha = None


async def github_get_lc_data():
    global lc_file_sha

    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(GH_LC_API, headers=headers) as r:
            text = await r.text()

            if r.status == 200:
                data = json.loads(text)
                lc_file_sha = data["sha"]
                content = base64.b64decode(data["content"]).decode()
                return json.loads(content)

            if r.status == 404:
                default = {
                    "channels": [],
                    "last_question_slug": None
                }
                await github_set_lc_data(default)
                return default

            raise RuntimeError(f"GitHub LC GET failed ({r.status})\n{text}")


async def github_set_lc_data(data_dict):
    global lc_file_sha

    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    encoded = base64.b64encode(
        json.dumps(data_dict, indent=4).encode()
    ).decode()

    payload = {
        "message": "update leetcode state",
        "content": encoded
    }

    if lc_file_sha:
        payload["sha"] = lc_file_sha

    async with aiohttp.ClientSession() as session:
        async with session.put(GH_LC_API, headers=headers, json=payload) as r:
            if r.status not in (200, 201):
                raise RuntimeError(await r.text())

            resp = await r.json()
            lc_file_sha = resp["content"]["sha"]


# ---------- HELPERS ----------
def parse_contest_type(name: str):
    name = name.lower()
    if "div. 1" in name:
        return "Div. 1"
    if "div. 2" in name:
        return "Div. 2"
    if "educational" in name:
        return "Educational"
    if "global" in name:
        return "Global"
    return "Rated"


def format_duration(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}:{m:02d} hours"


def registration_link(contest_id: int):
    return f"https://codeforces.com/contestRegistration/{contest_id}"


async def fetch_contests():
    async with aiohttp.ClientSession() as session:
        async with session.get(CODEFORCES_API) as r:
            data = await r.json()
            return data["result"]


# ---------- WATCHER ----------
def cf_dbg(tag, msg):
    print(f"[CODEFORCES:{tag}] {msg}")

@tasks.loop(minutes=1)
async def codeforces_watcher():
    cf_dbg("START", "Watcher tick started")

    try:
        cf_data = await github_get_cf_data()
        cf_dbg("STATE", f"Loaded GitHub state: {cf_data}")

        contests = await fetch_contests()
        cf_dbg("FETCH", f"Fetched {len(contests)} contests")

        upcoming = [c for c in contests if c["phase"] == "BEFORE"]
        cf_dbg("FILTER", f"Upcoming contests: {len(upcoming)}")

        if not upcoming:
            cf_dbg("SKIP", "No upcoming contests")
            return

        upcoming.sort(key=lambda c: c["startTimeSeconds"])
        contest = upcoming[0]

        cf_dbg(
            "CONTEST",
            f"Next contest: {contest['name']} (id={contest['id']})"
        )

        if cf_data["last_contest_id"] == contest["id"]:
            cf_dbg("SKIP", "Contest already posted")
            return

        embed = discord.Embed(
            title="🏆 Team Codeforcers",
            description=(
                f"**{contest['name']}**\n\n"
                "⚡ One-click registration."
            ),
            color=0x1f8b4c
        )

        embed.add_field(
            name="📌 Type",
            value=parse_contest_type(contest["name"]),
            inline=True
        )

        embed.add_field(
            name="🕒 Starts",
            value=f"<t:{contest['startTimeSeconds']}:F>",
            inline=True
        )

        embed.add_field(
            name="⏳ Duration",
            value=format_duration(contest["durationSeconds"]),
            inline=True
        )

        embed.add_field(
            name="📝 Register Here",
            value=registration_link(contest["id"]),
            inline=False
        )

        embed.set_footer(text="Telugu Study Buddies")

        posted = False
        cf_dbg("CHANNELS", f"Posting to channels: {cf_data['channels']}")

        for ch_id in cf_data["channels"]:
            cf_dbg("CHANNEL", f"Trying channel ID {ch_id}")

            channel = bot.get_channel(ch_id)
            if not channel:
                cf_dbg("CHANNEL", f"Channel {ch_id} not found in cache")
                continue

            await channel.send(embed=embed)
            cf_dbg("POST", f"Posted to #{channel.name}")
            posted = True

        if posted:
            cf_data["last_contest_id"] = contest["id"]
            await github_set_cf_data(cf_data)
            cf_dbg("STATE", f"Updated last_contest_id -> {contest['id']}")
        else:
            cf_dbg("WARNING", "Nothing posted — state NOT updated")

    except Exception as e:
        cf_dbg("ERROR", repr(e))

LEETCODE_GRAPHQL = "https://leetcode.com/graphql"

LEETCODE_DAILY_QUERY = {
    "query": """
    query questionOfToday {
      activeDailyCodingChallengeQuestion {
        date
        link
        question {
          title
          titleSlug
          difficulty
          questionId
        }
      }
    }
    """
}

async def fetch_leetcode_daily():
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; DiscordBot/1.0)",
        "Referer": "https://leetcode.com",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(LEETCODE_GRAPHQL, json=LEETCODE_DAILY_QUERY) as r:
            text = await r.text()

            print("[LEETCODE:RAW]", text[:500])  # PRINT RAW RESPONSE (first 500 chars)

            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                raise RuntimeError("LeetCode did not return JSON")

            if "data" not in data:
                raise RuntimeError(
                    f"LeetCode GraphQL error response: {data}"
                )

            challenge = data["data"].get("activeDailyCodingChallengeQuestion")
            if not challenge:
                raise RuntimeError("No daily challenge found")

            return challenge

def dbg(tag, msg):
    print(f"[LEETCODE:{tag}] {msg}")

@tasks.loop(minutes=10)
async def leetcode_watcher():
    dbg("START", "Watcher tick started")

    try:
        lc_data = await github_get_lc_data()
        dbg("STATE", f"Loaded GitHub state: {lc_data}")

        daily = await fetch_leetcode_daily()
        dbg("FETCH", f"Fetched daily payload: {daily}")

        q = daily["question"]
        slug = q["titleSlug"]
        dbg("QUESTION", f"Today's slug = {slug}")

        if lc_data["last_question_slug"] == slug:
            dbg("SKIP", "Slug already posted, skipping")
            return

        embed = discord.Embed(
            title="🧠 LeetCode Daily Challenge",
            description=f"**{q['title']}**",
            color=0xf89f1b
        )
        
        embed.add_field(
            name="🆔 Problem ID",
            value=q["questionId"],
            inline=True
        )
        
        embed.add_field(
            name="⚡ Difficulty",
            value=q["difficulty"],
            inline=True
        )
        
        embed.add_field(
            name="🕒 Date",
            value=daily["date"],
            inline=True
        )
        
        embed.add_field(
            name="📝 Solve Here",
            value=f"https://leetcode.com{daily['link']}",
            inline=False
        )
        
        embed.set_footer(text="Telugu Study Buddies • Daily LeetCode")


        posted = False

        dbg("CHANNELS", f"Posting to channels: {lc_data['channels']}")

        for ch_id in lc_data["channels"]:
            dbg("CHANNEL", f"Trying channel ID {ch_id}")

            channel = bot.get_channel(ch_id)

            if channel is None:
                dbg("CHANNEL", f"Channel {ch_id} NOT in cache")
                continue

            dbg("CHANNEL", f"Channel found: {channel.name}")
            await channel.send(embed=embed)
            dbg("POST", f"Posted to #{channel.name}")
            posted = True

        if posted:
            lc_data["last_question_slug"] = slug
            await github_set_lc_data(lc_data)
            dbg("STATE", f"Updated last_question_slug -> {slug}")
        else:
            dbg("WARNING", "Nothing posted — state NOT updated")

    except Exception as e:
        dbg("ERROR", repr(e))

@leetcode_watcher.before_loop
async def before_leetcode():
    await bot.wait_until_ready()
    print("[LEETCODE] Bot ready, watcher will start")

# ---------- SLASH COMMAND ----------
@bot.tree.command(name="setup", description="Setup automated competitive programming updates")
@app_commands.describe(
    update_type="Type of updates",
    channel="Channel to send updates"
)
@app_commands.choices(update_type=[
    app_commands.Choice(name="Codeforces", value="codeforces"),
    app_commands.Choice(name="LeetCode", value="leetcode"),
])
async def setup(
    interaction: discord.Interaction,
    update_type: app_commands.Choice[str],
    channel: discord.TextChannel
):
    await interaction.response.defer(ephemeral=True)

    try:
        if update_type.value == "codeforces":
            cf_data = await github_get_cf_data()

            if channel.id not in cf_data["channels"]:
                cf_data["channels"].append(channel.id)
                await github_set_cf_data(cf_data)

            if not codeforces_watcher.is_running():
                codeforces_watcher.start()

            await interaction.followup.send(
                f"✅ **Codeforces updates enabled** in {channel.mention}"
            )

        elif update_type.value == "leetcode":
            print("[SETUP:LC] Setup started")
        
            lc_data = await github_get_lc_data()
            print("[SETUP:LC] Loaded state:", lc_data)
        
            if channel.id not in lc_data["channels"]:
                lc_data["channels"].append(channel.id)
                await github_set_lc_data(lc_data)
                print(f"[SETUP:LC] Added channel {channel.id}")
        
            if not leetcode_watcher.is_running():
                leetcode_watcher.start()
                print("[SETUP:LC] Watcher started")
            else:
                print("[SETUP:LC] Watcher already running")
        
            await interaction.followup.send(
                f"✅ **LeetCode updates enabled** in {channel.mention}"
            )


    except Exception as e:
        await interaction.followup.send(
            f"❌ Setup failed:\n```{type(e).__name__}: {e}```"
        )

# =====================================================
#                     MAIN ENTRY
# =====================================================

async def main():
    asyncio.create_task(start_webserver())
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
