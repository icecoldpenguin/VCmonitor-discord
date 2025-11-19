import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from datetime import datetime
import os

# ================== CONFIG ==================
TOKEN = os.getenv("TOKEN")

MONITORED_VC_IDS = {
    1422274947291676672
}

INITIAL_WAIT_SECONDS = 120       # 2 minutes
REMINDER_WAIT_SECONDS = 120      # 2 minutes after they turn off stream/cam
KICK_WAIT_AFTER_REMINDER = 180   # 3 minutes after reminder
# ============================================

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True
intents.messages = True
intents.dm_messages = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Track user monitoring tasks
initial_checks = {}        # member_id -> asyncio.Task
post_stream_checks = {}    # member_id -> {"reminder": Task, "kick": Task}

print("TOKEN LOADED?:", TOKEN is not None)

# ------------- DM HELPER -------------

async def safe_dm(member: discord.Member, embed: discord.Embed):
    try:
        await member.send(embed=embed)
        print(f"[DM] Sent DM to {member}")
    except discord.Forbidden:
        print(f"[DM] Cannot DM {member} - DMs disabled or blocked.")
    except Exception as e:
        print(f"[DM] Error DMing {member}: {e}")

# ------------- EMBEDS -------------

def make_initial_kick_embed(member: discord.Member, vc: discord.VoiceChannel):
    embed = discord.Embed(
        title="Voice Enforcement Notice",
        description=(
            f"Hey {member.mention},\n\n"
            "You were moved out of the voice channel because you didn’t have "
            "**camera or stream enabled** even after the required time."
        ),
        color=0xF97316
    )
    embed.add_field(
        name="What you need to do",
        value="• Rejoin the voice channel\n• Turn **on camera** or **start streaming**",
        inline=False
    )
    embed.timestamp = datetime.utcnow()
    return embed

def make_reminder_embed(member: discord.Member, vc: discord.VoiceChannel):
    embed = discord.Embed(
        title="Reminder: Turn On Stream / Camera",
        description=(
            f"{member.mention}, you turned off your **stream/camera**.\n\n"
            "Please enable it again within **3 minutes**, or you may be removed."
        ),
        color=0x22C55E
    )
    embed.timestamp = datetime.utcnow()
    return embed

def make_post_stream_kick_embed(member: discord.Member, vc: discord.VoiceChannel):
    embed = discord.Embed(
        title="You Were Removed From the Voice Channel",
        description=(
            f"{member.mention}, you were removed because your "
            "**stream/camera remained off** after the reminder."
        ),
        color=0xEF4444
    )
    embed.timestamp = datetime.utcnow()
    return embed


# ------------- HELPERS -------------

def is_in_monitored_vc(member: discord.Member) -> bool:
    return member.voice and member.voice.channel and member.voice.channel.id in MONITORED_VC_IDS

def has_required_activity(member: discord.Member) -> bool:
    if not member.voice:
        return False
    vs = member.voice
    return vs.self_stream or vs.self_video


# ------------- BACKGROUND TASKS -------------

async def initial_check_task(member: discord.Member, vc_id: int):
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
        print(f"[MOVE ERROR] {e}")

async def post_stream_reminder_task(member: discord.Member, vc_id: int):
    await asyncio.sleep(REMINDER_WAIT_SECONDS)

    mem = member.guild.get_member(member.id)
    if not mem or not mem.voice or mem.voice.channel.id != vc_id:
        return

    if has_required_activity(mem):
        return

    embed = make_reminder_embed(mem, mem.voice.channel)
    await safe_dm(mem, embed)

async def post_stream_kick_task(member: discord.Member, vc_id: int):
    await asyncio.sleep(KICK_WAIT_AFTER_REMINDER)

    mem = member.guild.get_member(member.id)
    if not mem or not mem.voice or mem.voice.channel.id != vc_id:
        return

    if has_required_activity(mem):
        return

    embed = make_post_stream_kick_embed(mem, mem.voice.channel)
    await safe_dm(mem, embed)

    try:
        await mem.move_to(None, reason="No cam/stream after reminder window")
    except Exception as e:
        print(f"[MOVE ERROR] {e}")


# ------------- EVENTS -------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print("Slash command sync failed:", e)


@bot.event
async def on_voice_state_update(member, before, after):

    # Leaving or switching out
    if before.channel and before.channel.id in MONITORED_VC_IDS and (not after.channel or after.channel.id not in MONITORED_VC_IDS):
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

    before_active = (before.self_stream or before.self_video) if before else False
    after_active = (after.self_stream or after.self_video) if after else False

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

# ---------- INVITE --------------
@tree.command(name="invite", description="Invite a user to your current voice channel")
async def invite_user(interaction: discord.Interaction, user: discord.Member):
    inviter = interaction.user

    # Check if inviter is in a VC
    if inviter.voice is None or inviter.voice.channel is None:
        return await interaction.response.send_message(
            "You need to be in a voice channel to use this command.",
            ephemeral=True
        )

    vc = inviter.voice.channel

    # Build DM embed
    embed = discord.Embed(
        title="Voice Channel Invitation",
        description=(
            f"**{inviter.mention}** invited you to join **{vc.name}**\n\n"
            f"Click here to join: <#{vc.id}>"
        ),
        color=0x5865F2
    )
    embed.set_footer(text=f"Server: {interaction.guild.name}")
    embed.timestamp = datetime.utcnow()

    # Try DMing the user
    try:
        await user.send(embed=embed)
        await interaction.response.send_message(
            f"Invitation sent to {user.mention}!",
            ephemeral=False
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "User cannot be DMed, try inviting manually.",
            ephemeral=False
        )


# ------------- RENDER WEB SERVER -------------    

from aiohttp import web

async def start_webserver():
    app = web.Application()
    app.add_routes([web.get("/", lambda r: web.Response(text="Bot Alive"))])

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", 10000)
    await site.start()
    print("Heartbeat server running")


# ------------- MAIN ENTRY POINT -------------    

async def main():
    print("Starting main()...")
    asyncio.create_task(start_webserver())   # start the uptime server

    print("Starting Discord bot...")
    await bot.start(TOKEN)                   # start the bot properly

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print("MAIN CRASHED:", e)
