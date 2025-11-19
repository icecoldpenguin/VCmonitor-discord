import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from datetime import datetime
import os
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


# =====================================================
#                 TEAM POINT COMMANDS
# =====================================================

@tree.command(name="addpoints", description="Add points to a member's team.")
async def addpoints(interaction: discord.Interaction, member: discord.Member, points: int):

    # Permission check
    if not any(role.id in ALLOWED_ROLES for role in interaction.user.roles):
        return await interaction.response.send_message(
            "You can't use this command.", ephemeral=True
        )

    # Determine team
    if any(role.id == TEAM_X_ROLE for role in member.roles):
        team = "X"
    elif any(role.id == TEAM_Y_ROLE for role in member.roles):
        team = "Y"
    else:
        return await interaction.response.send_message(
            "User is not in Team X or Team Y.", ephemeral=True
        )

    team_points[team] += points
    save_points()

    await interaction.response.send_message(
        f"Added **{points}** points to **Team {team}**!\n"
        f"Team {team} now has **{team_points[team]}** points."
    )


@tree.command(name="viewteampoints", description="See the current team points.")
async def viewteampoints(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🏆 Team Points",
        color=0x00B0F4
    )
    embed.add_field(name="Team X", value=f"**{team_points['X']}**", inline=True)
    embed.add_field(name="Team Y", value=f"**{team_points['Y']}**", inline=True)
    embed.timestamp = datetime.utcnow()

    await interaction.response.send_message(embed=embed)



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


# =====================================================
#                     MAIN ENTRY
# =====================================================

async def main():
    asyncio.create_task(start_webserver())
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
