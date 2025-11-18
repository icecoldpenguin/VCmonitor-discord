import discord
from discord.ext import commands
import asyncio
from datetime import datetime
import os

from aiohttp import web
import threading

async def alive(request):
    return web.Response(text="Bot running")

def run_web():
    app = web.Application()
    app.router.add_get("/", alive)
    web.run_app(app, port=10000)

threading.Thread(target=run_web).start()

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

# Track user monitoring tasks
initial_checks = {}        # member_id -> asyncio.Task
post_stream_checks = {}    # member_id -> {"reminder": Task, "kick": Task}

# ------------- DM HELPER -------------

async def safe_dm(member: discord.Member, embed: discord.Embed):
    """Try to DM the user, log why it fails if it does."""
    try:
        await member.send(embed=embed)
        print(f"[DM] Sent DM to {member} ({member.id})")
    except discord.Forbidden:
        print(f"[DM] Cannot DM {member} ({member.id}) - DMs disabled or blocked.")
    except Exception as e:
        print(f"[DM] Error DMing {member} ({member.id}): {e}")

# ------------- EMBEDS -------------

def make_initial_kick_embed(member: discord.Member, vc: discord.VoiceChannel):
    embed = discord.Embed(
        title="Voice Enforcement Notice",
        description=(
            f"Hey {member.mention},\n\n"
            "You were moved out of the voice channel because you didn’t have "
            "**camera or stream enabled** even after the required time."
        ),
        color=0xF97316  # orange
    )
    embed.add_field(
        name="What you need to do",
        value=(
            "• Join the voice channel again\n"
            "• Turn **on your camera** or **start streaming** within the allowed time"
        ),
        inline=False
    )
    embed.add_field(
        name="Channel",
        value=f"{vc.mention} (`{vc.id}`)",
        inline=True
    )
    embed.set_footer(text="This is an automated moderation action.")
    embed.timestamp = datetime.utcnow()
    return embed

def make_reminder_embed(member: discord.Member, vc: discord.VoiceChannel):
    embed = discord.Embed(
        title="Reminder: Turn On Stream / Camera",
        description=(
            f"{member.mention}, you turned off your **stream/camera** in "
            f"{vc.mention}.\n\n"
            "Please enable it again, or you may be removed from the VC."
        ),
        color=0x22C55E  # green
    )
    embed.add_field(
        name="Time remaining",
        value="You have about **3 minutes** before you’re kicked from the VC.",
        inline=False
    )
    embed.set_footer(text="VC activity monitoring")
    embed.timestamp = datetime.utcnow()
    return embed

def make_post_stream_kick_embed(member: discord.Member, vc: discord.VoiceChannel):
    embed = discord.Embed(
        title="You Were Removed From the Voice Channel",
        description=(
            f"{member.mention}, you were removed from {vc.mention} because you "
            "didn’t turn **stream/camera** back on in time."
        ),
        color=0xEF4444  # red
    )
    embed.add_field(
        name="Next steps",
        value="Rejoin the VC and keep your **camera/stream active** as required.",
        inline=False
    )
    embed.set_footer(text="VC activity enforcement")
    embed.timestamp = datetime.utcnow()
    return embed

# ------------- CHECK HELPERS -------------

def is_in_monitored_vc(member: discord.Member) -> bool:
    return member.voice and member.voice.channel and member.voice.channel.id in MONITORED_VC_IDS

def has_required_activity(member: discord.Member) -> bool:
    """True if user is streaming or camera on."""
    if not member.voice:
        return False
    vs = member.voice
    return vs.self_stream or vs.self_video

# ------------- TASKS -------------

async def initial_check_task(member: discord.Member, vc_id: int):
    """Run 2-min initial check after joining VC."""
    await asyncio.sleep(INITIAL_WAIT_SECONDS)

    # Re-fetch state
    guild = member.guild
    fresh_member = guild.get_member(member.id)
    if not fresh_member or not fresh_member.voice:
        return

    voice = fresh_member.voice
    if not voice.channel or voice.channel.id != vc_id:
        # User left or moved elsewhere
        return

    if has_required_activity(fresh_member):
        # Okay, they complied
        return

    # DM first, then disconnect from VC
    embed = make_initial_kick_embed(fresh_member, voice.channel)
    await safe_dm(fresh_member, embed)

    try:
        await fresh_member.move_to(None, reason="No cam/stream after initial 2 minutes")
        print(f"[KICK-VC] Initial check kicked {fresh_member} from VC.")
    except Exception as e:
        print(f"[KICK-VC] Error kicking {fresh_member}: {e}")

async def post_stream_reminder_task(member: discord.Member, vc_id: int):
    """Wait 2 mins after they turn off stream/cam, then remind."""
    await asyncio.sleep(REMINDER_WAIT_SECONDS)

    guild = member.guild
    fresh_member = guild.get_member(member.id)
    if not fresh_member or not fresh_member.voice:
        return

    voice = fresh_member.voice
    if not voice.channel or voice.channel.id != vc_id:
        return

    if has_required_activity(fresh_member):
        # They turned it back on before reminder
        return

    embed = make_reminder_embed(fresh_member, voice.channel)
    await safe_dm(fresh_member, embed)
    print(f"[REMINDER] Sent reminder to {fresh_member}.")

async def post_stream_kick_task(member: discord.Member, vc_id: int):
    """3 mins after reminder, kick if still no activity."""
    await asyncio.sleep(KICK_WAIT_AFTER_REMINDER)

    guild = member.guild
    fresh_member = guild.get_member(member.id)
    if not fresh_member or not fresh_member.voice:
        return

    voice = fresh_member.voice
    if not voice.channel or voice.channel.id != vc_id:
        return

    if has_required_activity(fresh_member):
        # They turned it back on
        return

    embed = make_post_stream_kick_embed(fresh_member, voice.channel)
    await safe_dm(fresh_member, embed)

    try:
        await fresh_member.move_to(None, reason="No cam/stream after reminder window")
        print(f"[KICK-VC] Post-stream check kicked {fresh_member} from VC.")
    except Exception as e:
        print(f"[KICK-VC] Error kicking {fresh_member}: {e}")

# ------------- EVENTS -------------

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

@bot.event
async def on_voice_state_update(member: discord.Member,
                                before: discord.VoiceState,
                                after: discord.VoiceState):

    # ---- Handle leaving / disconnect ----
    if before.channel and before.channel.id in MONITORED_VC_IDS and (not after.channel or after.channel.id != before.channel.id):
        # Cancel any tasks for this member when they leave monitored VC
        if member.id in initial_checks:
            initial_checks[member.id].cancel()
            initial_checks.pop(member.id, None)

        if member.id in post_stream_checks:
            tasks = post_stream_checks.pop(member.id)
            for t in tasks.values():
                t.cancel()

    # ---- Handle joining monitored VC ----
    if after.channel and after.channel.id in MONITORED_VC_IDS and not before.channel:
        # Joined one of the monitored VCs
        print(f"[JOIN] {member} joined monitored VC {after.channel.name} ({after.channel.id})")
        # start initial check if not already streaming/cam
        if not has_required_activity(member):
            task = asyncio.create_task(initial_check_task(member, after.channel.id))
            initial_checks[member.id] = task

    # ---- Handle starting stream/cam ----
    before_active = before.self_stream or before.self_video if before else False
    after_active = after.self_stream or after.self_video if after else False

    # User starts stream/cam: cancel initial + post-stream tasks
    if not before_active and after_active:
        print(f"[ACTIVE] {member} started stream/cam.")
        if member.id in initial_checks:
            initial_checks[member.id].cancel()
            initial_checks.pop(member.id, None)

        if member.id in post_stream_checks:
            tasks = post_stream_checks.pop(member.id)
            for t in tasks.values():
                t.cancel()

    # User stops stream/cam in monitored VC -> schedule reminder + kick
    if before_active and not after_active:
        if after.channel and after.channel.id in MONITORED_VC_IDS:
            print(f"[INACTIVE] {member} turned off stream/cam in monitored VC.")
            # cancel previous post-stream tasks if any
            if member.id in post_stream_checks:
                tasks = post_stream_checks.pop(member.id)
                for t in tasks.values():
                    t.cancel()

            reminder_task = asyncio.create_task(post_stream_reminder_task(member, after.channel.id))
            kick_task = asyncio.create_task(post_stream_kick_task(member, after.channel.id))
            post_stream_checks[member.id] = {
                "reminder": reminder_task,
                "kick": kick_task,
            }

bot.run(TOKEN)
