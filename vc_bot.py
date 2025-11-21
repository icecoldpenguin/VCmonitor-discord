import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from datetime import datetime
import os
import json
import mmh3
import aiohttp
import base64
import json

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

def calculate_team(user_id: int):
    key = f"events_of_tsb:{user_id}"
    hashed = mmh3.hash(key, 0)
    result = hashed % 10000
    
    if result < 5000:
        return "X"
    else:
        return "Y"


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

@tree.command(name="assigntoteam", description="Assign a user to their deterministic team via hashing.")
async def assign_to_team(interaction: discord.Interaction, user: discord.Member):

    # Only staff can do this — optional check
    if not any(role.id in ALLOWED_ROLES for role in interaction.user.roles):
        return await interaction.response.send_message("You cannot use this.", ephemeral=True)

    team = await assign_team_role(user)

    await interaction.response.send_message(
        f"{user.mention} has been assigned to **Team {team}** (via mmh3 hashing)."
    )
@tree.command(name="assigntall", description="Assign deterministic X/Y team roles to all humans in the server.")
async def assigntall(interaction: discord.Interaction):

    # Permission check — same as your addpoints perms
    if not any(role.id in ALLOWED_ROLES for role in interaction.user.roles):
        return await interaction.response.send_message(
            "You don't have permission to use this.", ephemeral=True
        )

    await interaction.response.send_message(
        "Starting bulk team assignment... This may take a moment.", ephemeral=False
    )

    guild = interaction.guild
    assigned_x = 0
    assigned_y = 0

    for member in guild.members:
        # Skip bots
        if member.bot:
            continue

        # Assign role based on consistent hashing
        team = await assign_team_role(member)

        if team == "X":
            assigned_x += 1
        else:
            assigned_y += 1

        # safety delay to avoid rate limits
        await asyncio.sleep(0.1)

    await interaction.followup.send(
        f"✅ Finished assigning teams!\n\n"
        f"**Team X:** {assigned_x} members\n"
        f"**Team Y:** {assigned_y} members"
    )

EVENT_CHANNEL_ID = 1424749944882991114
EVENT_VC_ID = 1438178530620866581

# =====================================================
#                        REMINDER
# =====================================================

@tree.command(name="reminder", description="Schedule an event reminder to send in the future.")
async def reminder(
    interaction: discord.Interaction,
    reminder_about: str,
    time: int
):
    """
    /reminder reminder_about:"Movie Night" time:30
    → After 30 mins:
         @everyone
         🔔EVENT REMINDER
         Movie Night will start in 10 minutes...
    """

    await interaction.response.send_message(
        f"Reminder set! I’ll remind everyone in **{time} minutes**.",
        ephemeral=True
    )

    # Background sleeper task
    async def reminder_task():
        await asyncio.sleep(time * 60)

        channel = interaction.guild.get_channel(EVENT_CHANNEL_ID)
        if channel is None:
            print("[REMINDER] Failed: Channel not found.")
            return

        embed = discord.Embed(
            title="🔔 EVENT REMINDER",
            description=(
                f"**{reminder_about}** will start in **10 minutes**!\n\n"
                f"Join the VC here: <#{EVENT_VC_ID}>"
            ),
            color=0xF5C542
        )
        embed.set_footer(text=f"Requested by {interaction.user}")
        embed.timestamp = datetime.utcnow()

        try:
            await channel.send("@everyone", embed=embed)
            print(f"[REMINDER] Sent reminder: {reminder_about}")
        except Exception as e:
            print(f"[REMINDER ERROR] {e}")

    # Launch the task in background
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
