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
# Structure: { "user_id": { "enabled": bool, "last_post": "ISO_timestamp" } }

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

@tasks.loop(minutes=1)
async def check_journal_reminders():
    """Check every minute if it's 9 PM IST and send reminders"""
    
    # Get current time in IST
    ist = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(ist)
    
    # Check if it's 9:00 PM IST (we check if minute is 0 to send once)
    if now_ist.hour == 21 and now_ist.minute == 0:
        print(f"[JOURNAL] It's 9 PM IST - checking for reminders...")
        
        # Calculate yesterday 9 PM IST threshold
        yesterday_9pm = now_ist - timedelta(days=1)
        
        for user_id, data in journal_data.items():
            # Skip if reminders disabled
            if not data.get("enabled", False):
                continue
            
            # Check if user posted since yesterday 9 PM
            last_post_str = data.get("last_post")
            
            needs_reminder = False
            
            if last_post_str is None:
                # Never posted
                needs_reminder = True
            else:
                try:
                    # Parse last post time and convert to IST
                    last_post_utc = datetime.fromisoformat(last_post_str.replace('Z', '+00:00'))
                    if last_post_utc.tzinfo is None:
                        last_post_utc = pytz.utc.localize(last_post_utc)
                    last_post_ist = last_post_utc.astimezone(ist)
                    
                    # If last post was before yesterday 9 PM, send reminder
                    if last_post_ist < yesterday_9pm:
                        needs_reminder = True
                except Exception as e:
                    print(f"[JOURNAL] Error parsing timestamp for {user_id}: {e}")
                    needs_reminder = True
            
            if needs_reminder:
                try:
                    user = await bot.fetch_user(int(user_id))
                    
                    embed = discord.Embed(
                        title="📔 Journal Reminder",
                        description=(
                            "Hey! It looks like you haven't posted in your journal today.\n\n"
                            "Take a moment to reflect on your day and write down your thoughts! 💭\n\n"
                            "Use `/journalpost` after you've updated your journal."
                        ),
                        color=0x5865F2,
                        timestamp=datetime.utcnow()
                    )
                    
                    await user.send(embed=embed)
                    print(f"[JOURNAL] Sent reminder to user {user_id}")
                    
                except discord.Forbidden:
                    print(f"[JOURNAL] Cannot DM user {user_id}")
                except Exception as e:
                    print(f"[JOURNAL] Error sending reminder to {user_id}: {e}")
        
        print(f"[JOURNAL] Finished sending reminders")


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
@app_commands.describe(enable="True to enable reminders, False to disable")
async def remindjournal(interaction: discord.Interaction, enable: bool):
    user_id = str(interaction.user.id)
    
    if enable:
        # Enable reminders for this user
        if user_id not in journal_data:
            journal_data[user_id] = {
                "enabled": True,
                "last_post": None
            }
        else:
            journal_data[user_id]["enabled"] = True
        
        save_journal_data(journal_data)
        
        await interaction.response.send_message(
            "✅ Journal reminders enabled! You'll receive a reminder at **9:00 PM IST** "
            "if you haven't posted in your journal that day.\n\n"
            "Use `/journalpost` to mark that you've posted today.",
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


@tree.command(name="journalpost", description="Mark that you've posted in your journal today")
async def journalpost(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    
    if user_id not in journal_data:
        journal_data[user_id] = {
            "enabled": False,
            "last_post": datetime.utcnow().isoformat()
        }
    else:
        journal_data[user_id]["last_post"] = datetime.utcnow().isoformat()
    
    save_journal_data(journal_data)
    
    await interaction.response.send_message(
        "✅ Marked as posted! You won't receive a reminder today.",
        ephemeral=True
    )


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


# =====================================================
#                     MAIN ENTRY
# =====================================================

async def main():
    asyncio.create_task(start_webserver())
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
