import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button
import asyncio
from datetime import datetime
import os
import json
import mmh3
import aiohttp
import base64
import json
import hashlib

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
            "You were removed from the voice channel because you didn’t enable "
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
#                     EVENTS
# =====================================================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print("Synced:", len(synced))
    except Exception as e:
        print("Slash command sync failed:", e)


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

@tree.command(name="addpoints", description="Add points to a user’s team.")
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

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        await bot.tree.sync()
        print("Slash commands synced.")
    except Exception as e:
        print("Sync failed:", e)

    # Register persistent views
    # If you have multiple event_names, you must re-add each one manually
    bot.add_view(TeamJoinView("default_event"))

# =====================================================
#                        REMINDER
# =====================================================

import time

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
    now = int(time.time())

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
