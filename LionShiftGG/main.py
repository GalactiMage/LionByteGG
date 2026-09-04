import sys
from typing import Optional
from discord import app_commands, Embed, Interaction
import discord
import importlib.util, os, inspect
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
import os
import json
import inspect  # NEW: used to detect sync/async setup functions
from datetime import datetime, timezone, timedelta
from constants import TOKEN, DIRECTOR_ID, STUDENT_WORKER_ROLE_ID
from safe_json import safe_json_dump
from schedule_image import generate_schedule_image

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Shared variables for offer-trade cog ---
shift_board = {}
shift_counter = 1
OFFER_BOARD_FILE = "offer_board.json"
SHIFT_BOARD_FILE = "shift_board.json"  # Add this for persistent shift_board
SCHEDULES_FILE = "schedules.json"  # Add this line near other constants
PANELS_FILE = "panels.json"  # NEW: persist panel message IDs
AVAILABILITY_FILE = "worker_availability.json"
SHIFT_LOGS_FILE = "shift_logs.json"

# Notification queue file (from LionByteGG web dashboard)
# Use abspath to handle cases where __file__ is a relative path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIONBYTE_DATA_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "LionByteGG", "data")
NOTIFICATION_QUEUE_FILE = os.path.join(LIONBYTE_DATA_DIR, "lionshift_notification_queue.json")

def load_panels():
    try:
        with open(PANELS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {
            "offer_shift_messages": [],
            "request_timeoff_messages": [],
            "clockpanel_messages": []
        }

def save_panels(panels):
    safe_json_dump(panels, PANELS_FILE, indent=2)

# Settings persistence helpers
SETTINGS_FILE = "settings.json"

def load_settings():
    try:
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_settings(settings):
    try:
        safe_json_dump(settings, SETTINGS_FILE, indent=2)
    except Exception:
        pass

# NEW: schedule persistence helpers (fixed missing functions)
def load_schedules():
    try:
        with open(SCHEDULES_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def save_schedules(schedules):
    try:
        safe_json_dump(schedules, SCHEDULES_FILE, indent=2)
    except Exception:
        pass

def load_shift_board():
    global shift_board, shift_counter
    try:
        with open(SHIFT_BOARD_FILE, "r") as f:
            data = json.load(f)
            shift_board = {int(k): v for k, v in data.get("shift_board", {}).items()}
            shift_counter = data.get("shift_counter", 1)
    except Exception:
        shift_board = {}
        shift_counter = 1

def save_shift_board():
    safe_json_dump({
        "shift_board": shift_board,
        "shift_counter": shift_counter
    }, SHIFT_BOARD_FILE, indent=2)

# Time off requests file for web dashboard
TIMEOFF_REQUESTS_FILE = "timeoff_requests.json"

def load_timeoff_requests():
    """Load time off requests from file"""
    try:
        with open(TIMEOFF_REQUESTS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def save_timeoff_requests(requests):
    """Save time off requests to file"""
    try:
        safe_json_dump(requests, TIMEOFF_REQUESTS_FILE, indent=2)
    except Exception as e:
        print(f"Error saving time off requests: {e}")

# ── Trades — single authoritative copy; both cogs import from here ────
TRADES_FILE = "trades.json"

def load_trades():
    """Load trades from file"""
    try:
        with open(TRADES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_trades(trades):
    """Save trades to file"""
    try:
        safe_json_dump(trades, TRADES_FILE, indent=2)
    except Exception:
        pass

def _next_trade_id(prefix="T"):
    """Timestamp + random suffix — never reuses an ID even after deletions."""
    import time as _t, random as _r
    return f"{prefix}{int(_t.time())}{_r.randint(10, 99)}"

# Worker cache file for web dashboard
WORKERS_CACHE_FILE = "workers_cache.json"

def save_workers_cache(workers):
    """Save the workers cache for the web dashboard"""
    try:
        safe_json_dump(workers, WORKERS_CACHE_FILE, indent=2)
    except Exception as e:
        print(f"Error saving workers cache: {e}")

async def update_workers_cache():
    """Update the workers cache with current student workers"""
    try:
        # Load existing cache to preserve clocked_in state
        existing = {}
        if os.path.exists(WORKERS_CACHE_FILE):
            with open(WORKERS_CACHE_FILE, "r") as f:
                for w in json.load(f):
                    existing[w.get("id") or w.get("discord_id")] = w

        workers = []
        for guild in bot.guilds:
            role = guild.get_role(STUDENT_WORKER_ROLE_ID)
            if role:
                for member in role.members:
                    mid = str(member.id)
                    prev = existing.get(mid, {})
                    workers.append({
                        "id": mid,
                        "discord_id": mid,
                        "name": member.display_name,
                        "username": str(member),
                        "avatar_url": member.display_avatar.url if member.display_avatar else None,
                        "clocked_in": prev.get("clocked_in", False),
                        "current_shift_type": prev.get("current_shift_type"),
                        "clock_in_time": prev.get("clock_in_time"),
                        "shifts_this_week": 0  # Will be calculated by web API
                    })
        save_workers_cache(workers)
        print(f"Updated workers cache with {len(workers)} workers")
    except Exception as e:
        print(f"Error updating workers cache: {e}")

# Availability helpers
def load_availability():
    try:
        with open(AVAILABILITY_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_availability(data):
    safe_json_dump(data, AVAILABILITY_FILE, indent=2)

# Shift log helpers (for reminder/late detection)
def load_shift_logs():
    try:
        with open(SHIFT_LOGS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

# Notification queue processor for schedule announcements from web dashboard
@tasks.loop(seconds=2)
async def process_notification_queue():
    """Process notification queue from LionByteGG web dashboard"""
    try:
        if not os.path.exists(NOTIFICATION_QUEUE_FILE):
            return
        
        with open(NOTIFICATION_QUEUE_FILE, 'r', encoding='utf-8') as f:
            notifications = json.load(f)
        
        if not notifications:
            return
        
        # Check for pending notifications
        pending_count = sum(1 for n in notifications if n.get('status') == 'pending')
        if pending_count > 0:
            print(f"[NOTIF] Found {pending_count} pending notification(s) to process")
        
        processed_any = False
        
        for notif in notifications:
            if notif.get('status') != 'pending':
                continue
            
            notif_type = notif.get('type')
            
            try:
                if notif_type == 'schedule_announcement':
                    # Send schedule announcement to channel
                    channel_id = notif.get('channel_id')
                    schedule = notif.get('schedule', {})
                    custom_message = notif.get('custom_message', '')
                    notify_workers = notif.get('notify_workers', False)
                    
                    channel_success = False
                    
                    if channel_id:
                        try:
                            # Try to fetch the channel (works even if not cached)
                            channel = bot.get_channel(int(channel_id))
                            if not channel:
                                channel = await bot.fetch_channel(int(channel_id))
                            
                            if channel:
                                # Generate beautiful schedule image
                                schedule_img = None
                                try:
                                    schedule_img = generate_schedule_image(schedule)
                                    print("[NOTIF] Generated schedule announcement image")
                                except Exception as img_err:
                                    print(f"[NOTIF] Image generation failed (will use text embed): {img_err}")

                                # Create embed with image
                                embed = Embed(
                                    title="📅 New Schedule Posted!",
                                    description=custom_message if custom_message else f"A new shift schedule has been posted for **{schedule.get('start_date', 'Unknown')}** to **{schedule.get('end_date', 'Unknown')}**.",
                                    color=0xF59E0B
                                )
                                
                                if schedule.get('name'):
                                    embed.add_field(name="📋 Schedule", value=schedule['name'], inline=False)
                                
                                embed.add_field(
                                    name="📆 Date Range",
                                    value=f"{schedule.get('start_date', 'Unknown')} to {schedule.get('end_date', 'Unknown')}",
                                    inline=True
                                )
                                
                                allow_offers = schedule.get('allow_offers', True)
                                embed.add_field(
                                    name="🔄 Shift Trading",
                                    value="✅ Allowed" if allow_offers else "❌ Not Allowed",
                                    inline=True
                                )

                                shift_count = schedule.get('shift_count', 0)
                                if shift_count:
                                    embed.add_field(
                                        name="👥 Total Shifts",
                                        value=str(shift_count),
                                        inline=True
                                    )

                                # Attach the generated image
                                if schedule_img:
                                    img_file = discord.File(schedule_img, filename="schedule.png")
                                    embed.set_image(url="attachment://schedule.png")
                                else:
                                    img_file = None
                                    # Fallback: show shift details as text
                                    shift_summary = schedule.get('shift_summary', {})
                                    if shift_summary:
                                        summary_lines = []
                                        for day in sorted(shift_summary.keys())[:7]:
                                            try:
                                                d = datetime.strptime(day, '%Y-%m-%d')
                                                day_label = d.strftime('%a %b %d')
                                            except Exception:
                                                day_label = day
                                            shifts_text = ', '.join(shift_summary[day][:3])
                                            if len(shift_summary[day]) > 3:
                                                shifts_text += f' +{len(shift_summary[day])-3} more'
                                            summary_lines.append(f"**{day_label}:** {shifts_text}")
                                        if summary_lines:
                                            embed.add_field(
                                                name="🗓️ Shift Details",
                                                value='\n'.join(summary_lines),
                                                inline=False
                                            )
                                
                                embed.set_footer(text=f"LionShiftGG • Posted by {schedule.get('created_by', 'Dashboard Admin')}")
                                embed.timestamp = datetime.now(timezone.utc)
                                
                                # Ping the student worker role with the announcement
                                role_mention = f"<@&{STUDENT_WORKER_ROLE_ID}>"
                                if img_file:
                                    await channel.send(content=role_mention, embed=embed, file=img_file)
                                else:
                                    await channel.send(content=role_mention, embed=embed)
                                print(f"[NOTIF] Sent schedule announcement to channel {channel_id}")
                                channel_success = True
                            else:
                                print(f"[NOTIF] Channel {channel_id} not found")
                        except Exception as e:
                            print(f"[NOTIF] Failed to send to channel {channel_id}: {e}")
                    
                    # DM student workers if enabled (independent of channel announcement)
                    if notify_workers:
                        dm_sent = 0
                        dm_failed = 0
                        for guild in bot.guilds:
                            role = guild.get_role(STUDENT_WORKER_ROLE_ID)
                            if role:
                                print(f"[NOTIF] Found {len(role.members)} workers with role in {guild.name}")
                                for member in role.members:
                                    try:
                                        dm_embed = Embed(
                                            title="📅 New Schedule Available!",
                                            description=f"A new shift schedule has been posted. Please check it and sign up for your shifts!",
                                            color=0xF59E0B
                                        )
                                        
                                        if schedule.get('name'):
                                            dm_embed.add_field(name="📋 Schedule", value=schedule['name'], inline=False)
                                        
                                        dm_embed.add_field(
                                            name="📆 Date Range",
                                            value=f"{schedule.get('start_date', 'Unknown')} to {schedule.get('end_date', 'Unknown')}",
                                            inline=True
                                        )

                                        shift_count = schedule.get('shift_count', 0)
                                        if shift_count:
                                            dm_embed.add_field(name="👥 Total Shifts", value=str(shift_count), inline=True)
                                        
                                        dm_embed.set_footer(text="LionShiftGG • Please sign up for your shifts promptly")
                                        dm_embed.timestamp = datetime.now(timezone.utc)
                                        
                                        await member.send(embed=dm_embed)
                                        dm_sent += 1
                                    except Exception as e:
                                        dm_failed += 1
                                        print(f"[NOTIF] Failed to DM {member.display_name}: {e}")
                        
                        print(f"[NOTIF] DM'd {dm_sent} workers about new schedule ({dm_failed} failed)")
                    
                    notif['status'] = 'completed'
                    notif['completed_at'] = datetime.now(timezone.utc).isoformat()
                    notif['channel_success'] = channel_success
                    processed_any = True

                elif notif_type == 'dm_workers':
                    # Send custom DM to specific workers or all workers
                    worker_ids = notif.get('worker_ids', [])
                    message_text = notif.get('message', '')
                    created_by = notif.get('created_by', 'Dashboard Admin')

                    if message_text:
                        dm_sent = 0
                        dm_failed = 0
                        dm_embed = Embed(
                            title="📬 Message from Management",
                            description=message_text,
                            color=0xF59E0B
                        )
                        dm_embed.set_footer(text=f"LionShiftGG • Sent by {created_by}")
                        dm_embed.timestamp = datetime.now(timezone.utc)

                        for guild in bot.guilds:
                            for wid in worker_ids:
                                try:
                                    member = guild.get_member(int(wid))
                                    if not member:
                                        member = await guild.fetch_member(int(wid))
                                    if member:
                                        await member.send(embed=dm_embed)
                                        dm_sent += 1
                                except Exception as e:
                                    dm_failed += 1
                                    print(f"[NOTIF] Failed to DM worker {wid}: {e}")

                        print(f"[NOTIF] Sent custom DM to {dm_sent} workers ({dm_failed} failed)")

                    notif['status'] = 'completed'
                    notif['completed_at'] = datetime.now(timezone.utc).isoformat()
                    processed_any = True
                
            except Exception as e:
                print(f"[NOTIF] Error processing notification: {e}")
                notif['status'] = 'error'
                notif['error'] = str(e)
                processed_any = True
        
        if processed_any:
            safe_json_dump(notifications, NOTIFICATION_QUEUE_FILE, indent=2)
    
    except Exception as e:
        print(f"[NOTIF] Error in notification queue processor: {e}")

# Helper: set embed thumbnail to a user's avatar (use from cogs when logging punches)
async def set_embed_thumbnail_from_user(embed: Embed, user_id: int):
    """
    Fetch the user by ID and set their avatar as the embed thumbnail.
    Safe to call even if the user or avatar can't be fetched.
    """
    try:
        user = await bot.fetch_user(user_id)
        # discord.py v2: use display_avatar.url
        embed.set_thumbnail(url=getattr(user, "display_avatar").url)
    except Exception:
        # silently ignore failures (e.g., missing user or API error)
        pass

# ── Shift Reminders & Late Detection ──────────────────────────────────────
# Tracks which (worker_id, shift_date, shift_start) combos we already reminded/flagged
_reminded_shifts = set()
_late_flagged_shifts = set()

def _get_chicago_tz():
    """Get Central timezone safely"""
    try:
        return ZoneInfo("America/Chicago")
    except Exception:
        return timezone(timedelta(hours=-6))

from zoneinfo import ZoneInfo

@tasks.loop(minutes=5)
async def shift_reminder_task():
    """Check upcoming shifts and send reminders before start (configurable). Flag late workers after configurable threshold."""
    try:
        settings = load_settings()
        schedules = load_schedules()
        logs = load_shift_logs()
        chicago = _get_chicago_tz()
        now = datetime.now(chicago)
        today_str = now.strftime("%Y-%m-%d")

        # Configurable timing — defaults match previous hardcoded values
        reminder_mins = max(5, int(settings.get("reminder_minutes_before", 60)))
        late_mins = max(1, int(settings.get("late_alert_minutes", 10)))
        # Detection windows are 10 minutes wide so a 5-min task loop never misses them
        reminder_secs = reminder_mins * 60
        late_secs = late_mins * 60

        for sched in schedules:
            if sched.get("status") == "draft":
                continue
            for shift in sched.get("shifts", []):
                shift_date = shift.get("date", "")
                shift_start = shift.get("start", "")
                worker_id = shift.get("worker_id") or shift.get("worker_discord_id")
                if not worker_id or not shift_date or not shift_start:
                    continue

                # Only process today's shifts
                if shift_date != today_str:
                    continue

                # Parse shift start time
                try:
                    shift_dt = datetime.strptime(f"{shift_date} {shift_start}", "%Y-%m-%d %H:%M")
                    shift_dt = shift_dt.replace(tzinfo=chicago)
                except Exception:
                    continue

                reminder_key = (str(worker_id), shift_date, shift_start)

                # Configurable lead-time reminder
                time_until = (shift_dt - now).total_seconds()
                if (reminder_secs - 600) < time_until <= reminder_secs and reminder_key not in _reminded_shifts:
                    _reminded_shifts.add(reminder_key)
                    if settings.get("dm_shift_reminders", True):
                        try:
                            member = None
                            for guild in bot.guilds:
                                member = guild.get_member(int(worker_id))
                                if member:
                                    break
                            if not member:
                                member = await bot.fetch_user(int(worker_id))
                            if member:
                                shift_type = (shift.get("type") or "shift").title()
                                if reminder_mins >= 60 and reminder_mins % 60 == 0:
                                    time_label = f"{reminder_mins // 60} hour{'s' if reminder_mins // 60 != 1 else ''}"
                                elif reminder_mins >= 60:
                                    hours = reminder_mins // 60
                                    mins = reminder_mins % 60
                                    time_label = f"{hours}h {mins}m"
                                else:
                                    time_label = f"{reminder_mins} minutes"
                                embed = Embed(
                                    title="⏰ Shift Reminder",
                                    description=(
                                        f"You have a **{shift_type}** shift starting in about **{time_label}**!\n\n"
                                        f"**📅 Date:** {shift_date}\n"
                                        f"**⏰ Time:** {shift_start} - {shift.get('end', '?')}\n"
                                        f"**📋 Schedule:** {sched.get('name', 'Unknown')}"
                                    ),
                                    color=0xF59E0B
                                )
                                embed.set_footer(text="LionShiftGG • Don't forget to clock in!")
                                await member.send(embed=embed)
                                print(f"[REMIND] Sent {time_label} reminder to {member.display_name}")
                        except Exception as e:
                            print(f"[REMIND] Failed to remind worker {worker_id}: {e}")

                # Configurable late detection — check after threshold, 10-min window
                if -(late_secs + 600) < time_until <= -late_secs and reminder_key not in _late_flagged_shifts:
                    # Check if worker clocked in today
                    clocked_in = False
                    for log in reversed(logs):
                        if (str(log.get("user_id")) == str(worker_id) and
                            log.get("action") == "start" and
                            log.get("timestamp", "").startswith(today_str)):
                            clocked_in = True
                            break
                    
                    if not clocked_in:
                        _late_flagged_shifts.add(reminder_key)
                        if settings.get("dm_late_alerts", True):
                            # DM the director about the late worker
                            try:
                                director = await bot.fetch_user(DIRECTOR_ID)
                                worker_name = shift.get("worker_name") or str(worker_id)
                                embed = Embed(
                                    title="🚨 Late Worker Alert",
                                    description=(
                                        f"**{worker_name}** (<@{worker_id}>) has not clocked in for their shift!\n\n"
                                        f"**📅 Date:** {shift_date}\n"
                                        f"**⏰ Shift Start:** {shift_start}\n"
                                        f"**🔖 Type:** {(shift.get('type') or 'shift').title()}\n"
                                        f"**📋 Schedule:** {sched.get('name', 'Unknown')}\n\n"
                                        f"They are now **{abs(int(time_until // 60))} minutes late**."
                                    ),
                                    color=0xE74C3C
                                )
                                embed.set_footer(text="LionShiftGG • Late Alert")
                                await director.send(embed=embed)
                                print(f"[LATE] Flagged {worker_name} as late for {shift_start} shift")
                            except Exception as e:
                                print(f"[LATE] Failed to send late alert: {e}")

                            # Also DM the worker
                            try:
                                member = None
                                for guild in bot.guilds:
                                    member = guild.get_member(int(worker_id))
                                    if member:
                                        break
                                if not member:
                                    member = await bot.fetch_user(int(worker_id))
                                if member:
                                    embed_worker = Embed(
                                        title="⚠️ You're Late!",
                                        description=(
                                            f"Your shift started at **{shift_start}** and you haven't clocked in yet!\n\n"
                                            f"**📅 Date:** {shift_date}\n"
                                            f"**📋 Schedule:** {sched.get('name', 'Unknown')}\n\n"
                                            f"Please clock in immediately or contact management."
                                        ),
                                        color=0xE74C3C
                                    )
                                    embed_worker.set_footer(text="LionShiftGG • Please clock in ASAP")
                                    await member.send(embed=embed_worker)
                            except Exception:
                                pass

    except Exception as e:
        print(f"[REMIND] Error in shift reminder task: {e}")


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    """Refresh workers cache immediately when the student worker role is added or removed."""
    if STUDENT_WORKER_ROLE_ID is None:
        return
    before_ids = {r.id for r in before.roles}
    after_ids = {r.id for r in after.roles}
    if STUDENT_WORKER_ROLE_ID in before_ids.symmetric_difference(after_ids):
        print(f"[WORKERS] Role change detected for {after.display_name} — refreshing workers cache")
        await update_workers_cache()


@bot.event
async def on_ready():
    print("[CONNECTION] Bot ready and connected.")
    panels = load_panels()

    # Register global views that rely only on custom_id handlers
    try:
        bot.add_view(OfferShiftView())
    except Exception:
        pass
    try:
        bot.add_view(RequestTimeOffView())
    except Exception:
        pass

    # Attempt to locate and register ClockPanelView from the cog file (safe import by path).
    ClockPanelViewClass = None
    try:
        import importlib.util, os
        cog_path = os.path.join(os.path.dirname(__file__), "cogs", "shift-management.py")
        spec = importlib.util.spec_from_file_location("shift_management_cog", cog_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ClockPanelViewClass = getattr(module, "ClockPanelView", None)
    except Exception:
        ClockPanelViewClass = None

    if ClockPanelViewClass:
        try:
            bot.add_view(ClockPanelViewClass())
        except Exception:
            pass

    # Re-register views bound to specific panel messages (if any)
    for entry in panels.get("offer_shift_messages", []):
        try:
            bot.add_view(OfferShiftView(), message_id=entry["message_id"])
        except Exception:
            pass

    for entry in panels.get("request_timeoff_messages", []):
        try:
            bot.add_view(RequestTimeOffView(), message_id=entry["message_id"])
        except Exception:
            pass

    if ClockPanelViewClass:
        for entry in panels.get("clockpanel_messages", []):
            try:
                bot.add_view(ClockPanelViewClass(), message_id=entry["message_id"])
            except Exception:
                pass

    # Ensure shift_board re-registration continues to work
    load_shift_board()
    for shift_id in list(shift_board.keys()):
        try:
            bot.add_view(TakeShiftView(shift_id))
        except Exception:
            pass

    # Re-register TakeOfferButton views for all currently open offers
    try:
        with open(SHIFT_BOARD_FILE, "r", encoding="utf-8") as _f:
            _board = json.load(_f)
        for _oid, _offer in _board.get("shift_board", {}).items():
            if _offer.get("status") == "open":
                try:
                    bot.add_view(TakeOfferView(_oid))
                except Exception:
                    pass
    except Exception:
        pass

    # --- Safe cog loader (handles hyphenated filenames and async/sync setup) ---
    async def load_cog_file(filename):
        try:
            import importlib.util
            cog_path = os.path.join(os.path.dirname(__file__), "cogs", filename)
            if not os.path.isfile(cog_path):
                print(f"Cog file not found: {cog_path}")
                return
            spec = importlib.util.spec_from_file_location(filename.replace("-", "_").replace(".py", ""), cog_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            setup = getattr(module, "setup", None)
            if setup:
                if inspect.iscoroutinefunction(setup):
                    await setup(bot)
                else:
                    setup(bot)
            print(f"Loaded cog file: {filename}")
        except Exception as e:
            print(f"Error loading cog file {filename}: {e}")

    # Load cogs by filename (works with hyphens)
    await load_cog_file("offer-trade.py")
    await load_cog_file("shift-management.py")

    activity = discord.Activity(type=discord.ActivityType.watching, name="the Clock")
    await bot.change_presence(activity=activity)
    print(f"LionShiftGG is online as {bot.user}")
    
    # Update workers cache for web dashboard
    await update_workers_cache()
    
    # Start notification queue processor for dashboard schedule announcements
    if not process_notification_queue.is_running():
        process_notification_queue.start()
        print(f"[STARTUP] Notification queue processor started")
        print(f"[STARTUP] Watching queue file: {NOTIFICATION_QUEUE_FILE}")
        print(f"[STARTUP] Queue file exists: {os.path.exists(NOTIFICATION_QUEUE_FILE)}")
        print(f"[STARTUP] Student Worker Role ID: {STUDENT_WORKER_ROLE_ID}")
    
    # Start shift reminder/late detection task
    if not shift_reminder_task.is_running():
        shift_reminder_task.start()
        print(f"[STARTUP] Shift reminder task started (runs every 5 min)")
    
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"Error syncing commands: {e}")

# --- UI Components ---
class OfferShiftView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(OfferShiftButton())
        self.add_item(TradeShiftButton())

class OfferShiftButton(Button):
    def __init__(self):
        super().__init__(label="🟥 Offer Shift", style=discord.ButtonStyle.danger, custom_id="offer_shift")

    async def callback(self, interaction: Interaction):
        if not load_settings().get("allow_shift_trading", True):
            await interaction.response.send_message(
                "❌ Shift trading is currently disabled by management.", ephemeral=True
            )
            return

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        worker_id = str(interaction.user.id)

        # Find the worker's actual upcoming scheduled shifts (same logic as /offer_shift slash command)
        schedules = load_schedules()
        upcoming = []
        for schedule in schedules:
            if schedule.get("status") != "published":
                continue
            for shift in schedule.get("shifts", []):
                if str(shift.get("worker_id", "")) == worker_id and shift.get("date", "") >= today_str:
                    upcoming.append(shift)

        if not upcoming:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⚠️ No Upcoming Shifts",
                    description="You have no published upcoming shifts to offer.",
                    color=0xf59e0b
                ),
                ephemeral=True
            )
            return

        # Deduplicate and cap at Discord's 25-option limit
        seen = set()
        unique = []
        for s in upcoming:
            key = (s.get("date"), s.get("type"))
            if key not in seen:
                seen.add(key)
                unique.append(s)
        unique = unique[:25]

        options = [
            discord.SelectOption(
                label=f"{s['date']} — {s.get('type','?').title()} ({s.get('start','')}–{s.get('end','')})",
                value=f"{s['date']}|{s.get('type','mid')}|{s.get('start','')}|{s.get('end','')}"
            )
            for s in unique
        ]

        select = discord.ui.Select(placeholder="Choose a shift to offer…", options=options, custom_id="offer_shift_select_panel")

        async def select_callback(sel_inter: Interaction):
            parts = select.values[0].split("|")
            date, stype, start, end = parts[0], parts[1], parts[2], parts[3]

            # Check for an existing open offer on this exact shift
            try:
                with open(SHIFT_BOARD_FILE, "r", encoding="utf-8") as _f:
                    _board = json.load(_f)
            except Exception:
                _board = {"shift_board": {}}
            for _existing in _board.get("shift_board", {}).values():
                if (
                    str(_existing.get("worker_id")) == worker_id
                    and _existing.get("date") == date
                    and _existing.get("shift_type") == stype
                    and _existing.get("status") == "open"
                ):
                    await sel_inter.response.send_message(
                        embed=discord.Embed(
                            title="⚠️ Already Offered",
                            description="You already have an open offer for that shift.",
                            color=0xF59E0B,
                        ),
                        ephemeral=True,
                    )
                    return

            # Show the reason modal — it handles posting to the channel
            await sel_inter.response.send_modal(
                OfferReasonModal(
                    shift_data={
                        "worker_id": worker_id,
                        "worker_name": sel_inter.user.display_name,
                        "date": date,
                        "stype": stype,
                        "start": start,
                        "end": end,
                    }
                )
            )

        select.callback = select_callback
        view = discord.ui.View(timeout=120)
        view.add_item(select)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="📋 Offer a Shift",
                description="Select the shift you want to put on the board:",
                color=0x3b82f6
            ),
            view=view,
            ephemeral=True
        )

class TradeShiftButton(Button):
    def __init__(self):
        super().__init__(label="🟦 Trade Shift", style=discord.ButtonStyle.primary, custom_id="trade_shift", disabled=False)

    async def callback(self, interaction: Interaction):
        if not load_settings().get("allow_shift_trading", True):
            await interaction.response.send_message(
                "❌ Shift trading is currently disabled by management.", ephemeral=True
            )
            return
        schedules = load_schedules()
        if not schedules:
            await interaction.response.send_message("No schedules available for trading.", ephemeral=True)
            return
        # Send the schedule select as an ephemeral message so only the user sees it
        await interaction.response.send_message(
            "Please select the schedule you want to trade a shift in:",
            view=TradeScheduleSelectView(schedules, interaction.user.id),
            ephemeral=True
        )

# ── Offer Reason Modal — shown after worker selects a shift ──────────────
class OfferReasonModal(Modal, title="Offer Your Shift"):
    reason = TextInput(
        label="Reason for Offering Shift",
        placeholder="Why can't you make this shift?",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500,
    )

    def __init__(self, shift_data: dict):
        super().__init__()
        self.shift_data = shift_data  # {worker_id, worker_name, date, stype, start, end}

    async def on_submit(self, interaction: Interaction):
        import time as _t, random as _rnd
        offer_id = f"O{int(_t.time())}{_rnd.randint(10, 99)}"

        try:
            with open(SHIFT_BOARD_FILE, "r", encoding="utf-8") as _f:
                board = json.load(_f)
        except Exception:
            board = {"shift_board": {}, "shift_counter": 0}

        board.setdefault("shift_board", {})[offer_id] = {
            "worker_id": self.shift_data["worker_id"],
            "worker_name": self.shift_data["worker_name"],
            "date": self.shift_data["date"],
            "shift_type": self.shift_data["stype"],
            "start": self.shift_data["start"],
            "end": self.shift_data["end"],
            "reason": self.reason.value,
            "taken_by": None,
            "taken_by_name": None,
            "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": "discord_bot",
        }
        safe_json_dump(board, SHIFT_BOARD_FILE, indent=2)

        def _fmt(t):
            try:
                return datetime.strptime(t, "%H:%M").strftime("%I:%M %p").lstrip("0")
            except Exception:
                return t

        date = self.shift_data["date"]
        stype = self.shift_data["stype"]
        start_nice = _fmt(self.shift_data["start"])
        end_nice = _fmt(self.shift_data["end"])
        try:
            date_nice = datetime.strptime(date, "%Y-%m-%d").strftime("%A, %B %d, %Y")
        except Exception:
            date_nice = date

        embed = Embed(
            title="🟢  Shift Available — Claim It!",
            color=0x2ECC71,
        )
        embed.set_author(
            name=f"{self.shift_data['worker_name']} is offering their shift",
            icon_url=interaction.user.display_avatar.url,
        )
        embed.add_field(name="📅  Date", value=date_nice, inline=True)
        embed.add_field(name="🔖  Type", value=stype.title(), inline=True)
        embed.add_field(name="⏰  Time", value=f"{start_nice} – {end_nice}", inline=True)
        embed.add_field(name="📝  Reason", value=self.reason.value, inline=False)
        embed.set_footer(text=f"LionShiftGG  •  Offer {offer_id}  •  Click the button below to claim this shift")
        embed.timestamp = datetime.now(timezone.utc)

        view = TakeOfferView(offer_id)
        content = (
            f"<@&{STUDENT_WORKER_ROLE_ID}> **A shift is up for grabs!**"
            if STUDENT_WORKER_ROLE_ID
            else "**A shift is up for grabs!**"
        )
        await interaction.channel.send(content=content, embed=embed, view=view)

        await interaction.response.send_message(
            embed=Embed(
                title="✅  Shift Offered",
                description=(
                    f"Your **{stype.title()}** shift on **{date_nice}** "
                    f"({start_nice} – {end_nice}) has been posted to the board."
                ),
                color=0x2ECC71,
            ),
            ephemeral=True,
        )


# ── Persistent view for taking a posted offer ─────────────────────────────
class TakeOfferView(View):
    def __init__(self, offer_id: str):
        super().__init__(timeout=None)
        self.add_item(TakeOfferButton(offer_id))


class TakeOfferButton(Button):
    def __init__(self, offer_id: str):
        super().__init__(
            label="✅  Take This Shift",
            style=discord.ButtonStyle.success,
            custom_id=f"take_offer_{offer_id}",
        )
        self.offer_id = offer_id

    async def callback(self, interaction: Interaction):
        try:
            with open(SHIFT_BOARD_FILE, "r", encoding="utf-8") as _f:
                board = json.load(_f)
        except Exception:
            board = {"shift_board": {}}

        offer = board.get("shift_board", {}).get(self.offer_id)
        if not offer or offer.get("status") != "open":
            await interaction.response.send_message(
                "❌ This shift has already been taken or is no longer available.",
                ephemeral=True,
            )
            return
        if str(offer["worker_id"]) == str(interaction.user.id):
            await interaction.response.send_message(
                "❌ You can't take your own shift.", ephemeral=True
            )
            return

        now = datetime.now(timezone.utc)
        now_str = now.strftime("%Y-%m-%d %I:%M %p").lstrip("0")

        # Mark as taken in the board file
        offer["status"] = "taken"
        offer["taken_by"] = str(interaction.user.id)
        offer["taken_by_name"] = interaction.user.display_name
        offer["taken_at"] = now.isoformat()
        board["shift_board"][self.offer_id] = offer
        safe_json_dump(board, SHIFT_BOARD_FILE, indent=2)

        # Transfer the shift in schedules.json so the taker can clock in
        updated_schedule = False
        try:
            schedules = load_schedules()
            for sched in schedules:
                for shift in sched.get("shifts", []):
                    if (
                        str(shift.get("worker_id", "")) == str(offer["worker_id"])
                        and shift.get("date") == offer["date"]
                        and shift.get("type") == offer["shift_type"]
                    ):
                        shift["worker_id"] = str(interaction.user.id)
                        shift["worker_discord_id"] = str(interaction.user.id)
                        shift["worker_name"] = interaction.user.display_name
                        updated_schedule = True
                        break
                if updated_schedule:
                    break
            if updated_schedule:
                save_schedules(schedules)
        except Exception as e:
            print(f"[OFFER] Failed to update schedules on take: {e}")

        def _fmt(t):
            try:
                return datetime.strptime(t, "%H:%M").strftime("%I:%M %p").lstrip("0")
            except Exception:
                return t

        try:
            date_nice = datetime.strptime(offer["date"], "%Y-%m-%d").strftime("%A, %B %d, %Y")
        except Exception:
            date_nice = offer["date"]
        start_nice = _fmt(offer.get("start", "?"))
        end_nice = _fmt(offer.get("end", "?"))
        stype = offer.get("shift_type", "shift").title()

        # Update the public embed to show claimed state
        if interaction.message:
            try:
                taken_embed = Embed(title="⛔  Shift Claimed", color=0x95A5A6)
                taken_embed.set_author(
                    name=f"Originally offered by {offer.get('worker_name', 'Unknown')}"
                )
                taken_embed.add_field(name="📅  Date", value=date_nice, inline=True)
                taken_embed.add_field(name="🔖  Type", value=stype, inline=True)
                taken_embed.add_field(name="⏰  Time", value=f"{start_nice} – {end_nice}", inline=True)
                taken_embed.add_field(name="🙋  Claimed By", value=interaction.user.mention, inline=False)
                taken_embed.set_footer(text=f"LionShiftGG  •  Claimed at {now_str}")
                taken_embed.timestamp = now
                await interaction.message.edit(
                    content="~~**A shift is up for grabs!**~~",
                    embed=taken_embed,
                    view=View(),
                )
                import asyncio
                _msg = interaction.message

                async def _del():
                    await asyncio.sleep(30)
                    try:
                        await _msg.delete()
                    except Exception:
                        pass

                asyncio.create_task(_del())
            except Exception:
                pass

        # DM the original worker
        try:
            orig = await interaction.client.fetch_user(int(offer["worker_id"]))
            dm = Embed(
                title="✅  Your Shift Was Taken!",
                description=f"**{interaction.user.display_name}** has claimed your shift.",
                color=0x2ECC71,
            )
            dm.add_field(name="📅  Date", value=date_nice, inline=True)
            dm.add_field(name="⏰  Time", value=f"{start_nice} – {end_nice}", inline=True)
            dm.add_field(name="📝  Your Reason", value=offer.get("reason", "—"), inline=False)
            dm.set_footer(text="LionShiftGG  •  Shift successfully transferred")
            dm.timestamp = now
            await orig.send(embed=dm)
        except Exception:
            pass

        # DM the director
        try:
            director = await interaction.client.fetch_user(DIRECTOR_ID)
            dir_em = Embed(title="🔄  Shift Transfer", color=0xE67E22)
            dir_em.add_field(name="📅  Date", value=date_nice, inline=True)
            dir_em.add_field(name="🔖  Type", value=stype, inline=True)
            dir_em.add_field(name="⏰  Time", value=f"{start_nice} – {end_nice}", inline=True)
            dir_em.add_field(
                name="👤  Original Worker",
                value=f"<@{offer['worker_id']}> ({offer.get('worker_name', '?')})",
                inline=True,
            )
            dir_em.add_field(
                name="🙋  Taken By",
                value=f"{interaction.user.mention} ({interaction.user.display_name})",
                inline=True,
            )
            dir_em.add_field(name="📝  Reason", value=offer.get("reason", "—"), inline=False)
            dir_em.add_field(
                name="📊  Schedule Updated",
                value=(
                    "✅ Yes — shift now assigned to taker"
                    if updated_schedule
                    else "⚠️ Could not locate shift in schedule"
                ),
                inline=False,
            )
            dir_em.set_footer(text=f"LionShiftGG  •  Offer {self.offer_id}")
            dir_em.timestamp = now
            await director.send(embed=dir_em)
        except Exception:
            pass

        await interaction.response.send_message(
            embed=Embed(
                title="✅  Shift Claimed!",
                description=(
                    f"You've taken the **{stype}** shift on **{date_nice}** "
                    f"({start_nice} – {end_nice}).\n\n"
                    "You are now scheduled for this shift and can clock in on that day."
                ),
                color=0x2ECC71,
            ),
            ephemeral=True,
        )


class TakeShiftView(View):
    def __init__(self, shift_id):
        super().__init__(timeout=None)
        self.add_item(TakeShiftButton(shift_id))

class TakeShiftButton(Button):
    def __init__(self, shift_id):
        super().__init__(label="✅ Take Shift", style=discord.ButtonStyle.success, custom_id=f"take_shift_{shift_id}")
        self.shift_id = shift_id

    async def callback(self, interaction: Interaction):
        shift = shift_board.get(self.shift_id)
        if not shift:
            await interaction.response.send_message("This shift is no longer available.", ephemeral=True)
            return
        if shift["user_id"] == interaction.user.id:
            await interaction.response.send_message("You cannot take your own shift.", ephemeral=True)
            return
        # Notify original offerer with an embed
        user = await bot.fetch_user(shift["user_id"])
        from datetime import datetime
        now_str = datetime.now().strftime("%Y-%m-%d %I:%M %p")
        embed_dm = Embed(
            title="✅ Your Shift Was Taken!",
            description=f"Your shift (ID: {self.shift_id}) was taken by {interaction.user.mention}.",
            color=0x2ecc71
        )
        embed_dm.add_field(name="📅 Date", value=shift["date"], inline=True)
        embed_dm.add_field(name="⏰ Time", value=shift["time"], inline=True)
        embed_dm.add_field(name="📝 Reason", value=shift["reason"], inline=False)
        embed_dm.set_footer(text=f"Taken: {now_str}")
        try:
            await user.send(embed=embed_dm)
        except Exception:
            pass
        # DM the director about the shift being taken
        director = await bot.fetch_user(DIRECTOR_ID)
        embed_director = Embed(
            title="🔄 Schedule Change",
            description=(
                f"**🆔 Shift ID:** {self.shift_id}\n"
                f"**👤 Offered By:** <@{shift['user_id']}>\n"
                f"**🙋 Taken By:** {interaction.user.mention}\n"
                f"**👤 Name:** {shift['name']}\n"
                f"**📅 Date:** {shift['date']}\n"
                f"**⏰ Time:** {shift['time']}\n"
                f"**📝 Reason:** {shift['reason']}"
            ),
            color=0xe67e22
        )
        embed_director.set_footer(text=f"Changed: {now_str}")
        try:
            await director.send(embed=embed_director)
        except Exception:
            pass
        # Update the original message to show taken and delete after delay
        if interaction.message:
            taken_embed = interaction.message.embeds[0].copy()
            taken_embed.color = 0x95a5a6
            taken_embed.title = "❌ Shift Taken!"
            taken_embed.description += f"\n\n**🙋 Taken by:** {interaction.user.mention}"
            taken_embed.set_footer(text=f"Taken: {now_str}")
            view = View()
            await interaction.message.edit(embed=taken_embed, view=view)
            # Delete the message after 15 seconds
            await interaction.message.delete(delay=15)
        del shift_board[self.shift_id]
        save_shift_board()  # Save after removing a shift
        await interaction.response.send_message(f"You have taken shift ID {self.shift_id}.", ephemeral=True)
# --- Slash Command to Setup Offer Shift Board ---
@bot.tree.command(name="setup_offershift", description="Setup the Offer Shift board for students.")
@app_commands.checks.has_permissions(administrator=True)
async def setup_offershift(interaction: Interaction):
    embed = Embed(
        title="🦁 LionShiftGG Shift Board",
        description=(
            "Welcome to the **Student Worker Shift Board**!\n\n"
            "🟥 If you need to offer your shift, use the red **Offer Shift** button below.\n"
            "🟦 If you want to trade a shift, use the blue **Trade Shift** button.\n\n"
            "All offered shifts will be posted for student workers to claim."
        ),
        color=0xe74c3c
    )
    embed.set_thumbnail(url="https://media.discordapp.net/attachments/1316453330695884912/1362053646170325032/8875956.png?ex=688a1ace&is=6888c94e&hm=4f0fe97ec1eae9001e4ab62a3effa2ccac9569eafb4838b54ff2ecd24257d5e4&=&format=webp&quality=lossless")
    embed.set_footer(text="🦁 LionShiftGG • Student Worker Shift Board")
    view = OfferShiftView()
    await interaction.response.defer(ephemeral=True)
    message = await interaction.channel.send(embed=embed, view=view)
    try:
        panels = load_panels()
        panels.setdefault("offer_shift_messages", []).append({"channel_id": message.channel.id, "message_id": message.id})
        save_panels(panels)
        bot.add_view(view, message_id=message.id)
    except Exception:
        pass
    await interaction.followup.send("Offer Shift board created and persisted.", ephemeral=True)


# --- Slash Command to View/Toggle DM Notification Settings ---
@bot.tree.command(name="dm_settings", description="View or toggle DM notifications for shift reminders and late alerts (admin only).")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    setting="Which DM setting to toggle (leave blank to view all current settings)",
    enabled="Turn this DM on or off"
)
@app_commands.choices(setting=[
    app_commands.Choice(name="Shift Reminders (1 hour before shift)", value="dm_shift_reminders"),
    app_commands.Choice(name="Late Alerts (worker hasn't clocked in)", value="dm_late_alerts"),
])
async def dm_settings(
    interaction: Interaction,
    setting: Optional[app_commands.Choice[str]] = None,
    enabled: Optional[bool] = None
):
    settings = load_settings()

    # If a setting and value are both provided, update it
    if setting is not None and enabled is not None:
        settings[setting.value] = enabled
        save_settings(settings)

    # Build current status for both settings
    reminders_on = settings.get("dm_shift_reminders", True)
    late_on = settings.get("dm_late_alerts", True)

    reminders_str = "✅ **ON**" if reminders_on else "❌ **OFF**"
    late_str = "✅ **ON**" if late_on else "❌ **OFF**"

    if setting is not None and enabled is not None:
        action_line = f"**{setting.name}** has been turned **{'ON ✅' if enabled else 'OFF ❌'}**.\n\n"
        embed_color = 0x2ECC71 if enabled else 0xE74C3C
    else:
        action_line = ""
        embed_color = 0xF59E0B

    embed = Embed(
        title="⚙️ LionShiftGG DM Settings",
        description=(
            f"{action_line}"
            f"**⏰ Shift Reminders (1 hr before):** {reminders_str}\n"
            f"**🚨 Late Alerts (not clocked in):** {late_str}"
        ),
        color=embed_color
    )
    embed.set_footer(text="LionShiftGG • Use /dm_settings to toggle • Affects worker & director DMs")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# --- Slash Command to Restart the Bot Service ---
# --- Slash Command to Restart the Bot Service ---
@bot.tree.command(name="restart_service", description="Restart the LionShiftGG bot service.")
@app_commands.checks.has_permissions(administrator=True)
async def restart_service(interaction: Interaction):
    embed = Embed(
        title="Restarting Service...",
        description="LionShiftGG is restarting. Please wait a few seconds.",
        color=0xf39c12
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)
    await interaction.client.close()
    os.execv(sys.executable, [sys.executable] + sys.argv)

# Place these above the if __name__ == "__main__": block

PURDUE_CLOCKIN_URL = "https://one.purdue.edu/launch-task/all/webclock"  # Replace with actual clock-in URL
OPENING_FORM_URL = "https://forms.cloud.microsoft/r/p8Ln3yhHjk"  # Replace with actual opening form URL
CLOSING_FORM_URL = "https://forms.cloud.microsoft/r/FVBFhEvfyk"  # Replace with actual closing form URL

# --- Slash Command to Learn About the Bot ---
@bot.tree.command(name="about", description="Learn about LionShiftGG and its features.")
async def about(interaction: Interaction):
    embed = Embed(
        title="🦁 About LionShiftGG",
        description=(
            "LionShiftGG is part of the **LionByteGG Suite**.\n\n"
            "This bot is designed to support **Purdue University Northwest** student workers by making it easy to:\n"
            "• 🕒 Clock in and out of shifts\n"
            "• 🟥 Offer your shifts to others\n"
            "• 🔄 Trade and claim available shifts\n"
            "• 📋 Access important forms and resources\n\n"
            "LionShiftGG helps streamline student worker scheduling and communication, making your work experience smoother and more efficient!"
        ),
        color=0xf1c40f
    )
    embed.set_footer(text="LionShiftGG • Proudly supporting PNW students")
    await interaction.response.send_message(embed=embed, ephemeral=True)

class NewScheduleModal(Modal, title="Post New Schedule"):
    def __init__(self):
        super().__init__()
        # Load saved channel ID from settings
        settings = load_settings()
        saved_channel_id = settings.get("schedule_announcement_channel_id", "")
        
        # Add fields with saved channel ID as default
        self.channel_id_input = TextInput(
            label="Announcement Channel ID",
            placeholder="Right-click channel → Copy Channel ID",
            required=True,
            default=str(saved_channel_id) if saved_channel_id else "",
            max_length=20
        )
        self.add_item(self.channel_id_input)
        
        self.schedule_link = TextInput(
            label="Schedule Spreadsheet Link",
            placeholder="Paste the link to the schedule",
            required=True
        )
        self.add_item(self.schedule_link)
        
        self.start_date = TextInput(
            label="Start Date",
            placeholder="e.g. 2024-07-01",
            required=True
        )
        self.add_item(self.start_date)
        
        self.end_date = TextInput(
            label="End Date",
            placeholder="e.g. 2024-07-14",
            required=True
        )
        self.add_item(self.end_date)
        
        self.allow_offers = TextInput(
            label="Allow students to offer/trade shifts?",
            placeholder="Yes or No",
            required=True,
            max_length=10
        )
        self.add_item(self.allow_offers)

    async def on_submit(self, interaction: Interaction):
        # Parse and validate channel ID
        try:
            channel_id = int(self.channel_id_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Invalid Channel ID. Please enter a valid numeric channel ID.", ephemeral=True)
            return
        
        # Save the channel ID for future use
        settings = load_settings()
        settings["schedule_announcement_channel_id"] = channel_id
        save_settings(settings)
        
        # Get the target channel
        target_channel = interaction.guild.get_channel(channel_id)
        if not target_channel:
            try:
                target_channel = await interaction.guild.fetch_channel(channel_id)
            except:
                await interaction.response.send_message(f"❌ Could not find channel with ID `{channel_id}`. Make sure the bot has access to that channel.", ephemeral=True)
                return
        
        role_mention = f"<@&{STUDENT_WORKER_ROLE_ID}>" if STUDENT_WORKER_ROLE_ID else "@everyone"
        allow_text = self.allow_offers.value.strip().lower()
        if allow_text in ("yes", "y", "true", "allowed"):
            offer_msg = "✅ **Students are allowed to offer and trade shifts for this schedule.**"
            allow_flag = True
        else:
            offer_msg = "⛔ **Students are NOT allowed to offer or trade shifts for this schedule.**"
            allow_flag = False
        embed = Embed(
            title="📅 New Schedule Posted!",
            description=(
                f"**Schedule Dates:** {self.start_date.value} to {self.end_date.value}\n"
                f"[View the Schedule]({self.schedule_link.value})\n\n"
                f"{offer_msg}"
            ),
            color=0x2980b9
        )
        embed.set_footer(text="LionShiftGG • Schedule Announcement")
        
        await target_channel.send(f"{role_mention} **NEW SCHEDULE POSTED**", embed=embed)
        await interaction.response.send_message(f"✅ Schedule posted to {target_channel.mention}!\n\n💾 Channel ID saved for future announcements.", ephemeral=True)
        
        # Save to schedules.json
        schedules = load_schedules()
        schedules.append({
            "schedule_link": self.schedule_link.value,
            "start_date": self.start_date.value,
            "end_date": self.end_date.value,
            "allow_offers": allow_flag
        })
        # Keep only the 3 most recent schedules
        if len(schedules) > 3:
            schedules = schedules[-3:]
        save_schedules(schedules)

@bot.tree.command(name="new-schedule", description="Post a new schedule and notify student workers (admin only).")
@app_commands.checks.has_permissions(administrator=True)
async def new_schedule(interaction: Interaction):
    await interaction.response.send_modal(NewScheduleModal())

class TradeScheduleSelect(discord.ui.Select):
    def __init__(self, schedules, requester_id):
        # Only include schedules where allow_offers is True
        allowed_schedules = [s for s in schedules if s.get("allow_offers", False)]
        options = [
            discord.SelectOption(
                label=f"{s['start_date']} to {s['end_date']}",
                value=str(idx),
                description=s['schedule_link'][:80]
            )
            for idx, s in enumerate(allowed_schedules)
        ]
        # Ensure there is at least one option
        if not options:
            options = [discord.SelectOption(label="No schedules available", value="none", description="")]
        super().__init__(
            placeholder="Select a schedule...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="trade_schedule_select"
        )
        self.schedules = allowed_schedules
        self.requester_id = requester_id

    async def callback(self, interaction: Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the requester can use this menu.", ephemeral=True)
            return
        if self.values[0] == "none":
            await interaction.response.send_message("No schedules available for trading.", ephemeral=True)
            return
        idx = int(self.values[0])
        selected_schedule = self.schedules[idx]
        # Prepare student select options
        role = interaction.guild.get_role(STUDENT_WORKER_ROLE_ID)
        options = []
        if role:
            for member in role.members:
                options.append(discord.SelectOption(
                    label=member.display_name,
                    value=str(member.id),
                    description=str(member)
                ))
        if not options:
            await interaction.response.send_message("No student workers found for trading.", ephemeral=True)
            return
        # Send student select as ephemeral message
        await interaction.response.send_message(
            "Please select the student you want to trade with:",
            view=TradeStudentSelectView(selected_schedule, options, interaction.user.id),
            ephemeral=True
        )
        self.disabled = True
        try:
            if interaction.message:  # Only try to edit if message exists
                await interaction.message.edit(view=self.view)
        except discord.errors.NotFound:
            pass  # Message was deleted or not found, ignore
        except Exception:
            pass  # Ignore other edit errors

class TradeScheduleSelectView(View):
    def __init__(self, schedules, requester_id):
        super().__init__(timeout=180)
        self.add_item(TradeScheduleSelect(schedules, requester_id))

class TradeStudentSelect(discord.ui.Select):
    def __init__(self, schedule, options, requester_id):
        super().__init__(
            placeholder="Select a student...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="trade_student_select"
        )
        self.schedule = schedule
        self.requester_id = requester_id

    async def callback(self, interaction: Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the requester can use this menu.", ephemeral=True)
            return
        target_user_id = int(self.values[0])
        await interaction.response.send_modal(TradeShiftDetailsModal(self.schedule, target_user_id))

class TradeStudentSelectView(View):
    def __init__(self, schedule, options, requester_id):
        super().__init__(timeout=180)
        self.add_item(TradeStudentSelect(schedule, options, requester_id))

class TradeShiftDetailsModal(Modal, title="Trade Shift - Step 2"):
    your_shift = TextInput(label="Your Shift (date/time)", placeholder="e.g. July 10, 2-6pm", required=True)
    wanted_shift = TextInput(label="Shift You Want (date/time)", placeholder="e.g. July 12, 10am-2pm", required=True)
    reason = TextInput(label="Reason for Trading Shift", placeholder="Why do you want to trade?", style=discord.TextStyle.paragraph, required=True)
    def __init__(self, schedule, target_user_id):
        super().__init__()
        self.schedule = schedule
        self.target_user_id = target_user_id

    async def on_submit(self, interaction: Interaction):
        try:
            user = await bot.fetch_user(self.target_user_id)
        except Exception:
            user = None
        if not user:
            await interaction.response.send_message("Could not find the user to trade with. Please check the selection.", ephemeral=True)
            return
        embed = Embed(
            title="🔄 Shift Trade Offer",
            description=(
                f"{interaction.user.mention} wants to trade shifts with you!\n\n"
                f"**Schedule:** {self.schedule['start_date']} to {self.schedule['end_date']}\n"
                f"**Their Shift:** {self.your_shift.value}\n"
                f"**Wants Your Shift:** {self.wanted_shift.value}\n"
                f"**Reason:** {self.reason.value}\n"
                f"[View Schedule]({self.schedule['schedule_link']})"
            ),
            color=0x3498db
        )
        embed.set_footer(text="LionShiftGG • Shift Trade Request")
        view = TradeAcceptDeclineView(
            requester_id=interaction.user.id,
            target_id=user.id,
            schedule=self.schedule,
            your_shift=self.your_shift.value,
            wanted_shift=self.wanted_shift.value
        )
        # DM the director with all info
        director = await bot.fetch_user(DIRECTOR_ID)
        embed_director = Embed(
            title="🔄 Shift Trade Requested",
            description=(
                f"**Requester:** {interaction.user.mention} (`{interaction.user.id}`)\n"
                f"**Target:** <@{user.id}> (`{user.id}`)\n"
                f"**Schedule:** {self.schedule['start_date']} to {self.schedule['end_date']}\n"
                f"**Requester Shift:** {self.your_shift.value}\n"
                f"**Requested Shift:** {self.wanted_shift.value}\n"
                f"**Reason:** {self.reason.value}\n"
                f"[View Schedule]({self.schedule['schedule_link']})"
            ),
            color=0xe67e22
        )
        embed_director.set_footer(text="LionShiftGG • Trade Notification")
        try:
            await director.send(embed=embed_director)
        except Exception:
            pass
        try:
            await user.send(embed=embed, view=view)
            await interaction.response.send_message("Trade offer sent! The student will receive a DM to accept or decline.", ephemeral=True)
        except Exception:
            await interaction.response.send_message("Could not DM the user. They may have DMs disabled.", ephemeral=True)

class TradeAcceptDeclineView(View):
    def __init__(self, requester_id, target_id, schedule, your_shift, wanted_shift):
        super().__init__(timeout=3600)
        self.requester_id = requester_id
        self.target_id = target_id
        self.schedule = schedule
        self.your_shift = your_shift
        self.wanted_shift = wanted_shift
        self.add_item(TradeAcceptButton())
        self.add_item(TradeDeclineButton())

class TradeAcceptButton(Button):
    def __init__(self):
        super().__init__(label="✅ Accept", style=discord.ButtonStyle.success, custom_id="trade_accept")

    async def callback(self, interaction: Interaction):
        view: TradeAcceptDeclineView = self.view
        if interaction.user.id != view.target_id:
            await interaction.response.send_message("You are not the recipient of this trade offer.", ephemeral=True)
            return
        # Disable buttons after pressing
        for item in self.view.children:
            item.disabled = True
        try:
            if interaction.message:
                await interaction.message.edit(view=self.view)
        except Exception:
            pass
        requester = await bot.fetch_user(view.requester_id)
        director = await bot.fetch_user(DIRECTOR_ID)
        embed_director = Embed(
            title="🔄 Director Approval Needed: Shift Trade",
            description=(
                f"**Requester:** <@{view.requester_id}> (`{view.requester_id}`)\n"
                f"**Target:** {interaction.user.mention} (`{interaction.user.id}`)\n"
                f"**Schedule:** {view.schedule['start_date']} to {view.schedule['end_date']}\n"
                f"**Requester Shift:** {view.your_shift}\n"
                f"**Requested Shift:** {view.wanted_shift}\n"
                f"[View Schedule]({view.schedule['schedule_link']})"
            ),
            color=0xf39c12
        )
        embed_director.set_footer(text="LionShiftGG • Director Approval Required")
        approval_view = DirectorApprovalView(
            requester_id=view.requester_id,
            target_id=view.target_id,
            schedule=view.schedule,
            your_shift=view.your_shift,
            wanted_shift=view.wanted_shift
        )
        try:
            await director.send(embed=embed_director, view=approval_view)
        except Exception:
            pass
        await interaction.response.send_message("You have accepted the trade offer. Awaiting director approval.", ephemeral=True)
        try:
            await requester.send("Your trade offer was accepted by the student. Awaiting director approval.")
        except Exception:
            pass
        self.view.stop()

class TradeDeclineButton(Button):
    def __init__(self):
        super().__init__(label="❌ Decline", style=discord.ButtonStyle.danger, custom_id="trade_decline")

    async def callback(self, interaction: Interaction):
        view: TradeAcceptDeclineView = self.view
        if interaction.user.id != view.target_id:
            await interaction.response.send_message("You are not the recipient of this trade offer.", ephemeral=True)
            return
        # Disable buttons after pressing
        for item in self.view.children:
            item.disabled = True
        try:
            if interaction.message:
                await interaction.message.edit(view=self.view)
        except Exception:
            pass
        # Prompt for reason via modal
        await interaction.response.send_modal(StudentDeclineReasonModal(view))

class StudentDeclineReasonModal(Modal, title="Reason for Declining Trade"):
    reason = TextInput(label="Reason for declining", style=discord.TextStyle.paragraph, required=True)
    def __init__(self, trade_view):
        super().__init__()
        self.trade_view = trade_view

    async def on_submit(self, interaction: Interaction):
        requester = await bot.fetch_user(self.trade_view.requester_id)
        embed = Embed(
            title="❌ Trade Declined",
            description=(
                f"{interaction.user.mention} has **declined** your shift trade.\n\n"
                f"**Schedule:** {self.trade_view.schedule['start_date']} to {self.trade_view.schedule['end_date']}\n"
                f"**Your Shift:** {self.trade_view.your_shift}\n"
                f"**Their Shift:** {self.trade_view.wanted_shift}\n"
                f"**Reason for Decline:** {self.reason.value}\n"
                f"[View Schedule]({self.trade_view.schedule['schedule_link']})"
            ),
            color=0xe74c3c
        )
        try:
            await requester.send(embed=embed)
        except Exception:
            pass
        await interaction.response.send_message("You have declined the trade offer. The requester has been notified.", ephemeral=True)
        self.trade_view.stop()

class DirectorApprovalView(View):
    def __init__(self, requester_id, target_id, schedule, your_shift, wanted_shift):
        super().__init__(timeout=3600)
        self.requester_id = requester_id
        self.target_id = target_id
        self.schedule = schedule
        self.your_shift = your_shift
        self.wanted_shift = wanted_shift
        self.add_item(DirectorApproveButton())
        self.add_item(DirectorDeclineButton())

class DirectorApproveButton(Button):
    def __init__(self):
        super().__init__(label="✅ Approve Trade", style=discord.ButtonStyle.success, custom_id="director_approve")

    async def callback(self, interaction: Interaction):
        if interaction.user.id != DIRECTOR_ID:
            await interaction.response.send_message("Only the director can approve this trade.", ephemeral=True)
            return
        # Disable buttons after pressing
        for item in self.view.children:
            item.disabled = True
        try:
            if interaction.message:
                await interaction.message.edit(view=self.view)
        except Exception:
            pass
        view: DirectorApprovalView = self.view
        requester = await bot.fetch_user(view.requester_id)
        target = await bot.fetch_user(view.target_id)
        embed = Embed(
            title="✅ Trade Approved by Director",
            description=(
                f"Your shift trade has been **approved** by the director!\n\n"
                f"**Schedule:** {view.schedule['start_date']} to {view.schedule['end_date']}\n"
                f"**Requester Shift:** {view.your_shift}\n"
                f"**Requested Shift:** {view.wanted_shift}\n"
                f"[View Schedule]({view.schedule['schedule_link']})"
            ),
            color=0x2ecc71
        )
        try:
            await requester.send(embed=embed)
        except Exception:
            pass
        try:
            await target.send(embed=embed)
        except Exception:
            pass
        await interaction.response.send_message("Trade approved. Both students have been notified.", ephemeral=True)
        self.view.stop()

class DirectorDeclineButton(Button):
    def __init__(self):
        super().__init__(label="❌ Decline Trade", style=discord.ButtonStyle.danger, custom_id="director_decline")

    async def callback(self, interaction: Interaction):
        if interaction.user.id != DIRECTOR_ID:
            await interaction.response.send_message("Only the director can decline this trade.", ephemeral=True)
            return
        # Disable buttons after pressing
        for item in self.view.children:
            item.disabled = True
        try:
            if interaction.message:
                await interaction.message.edit(view=self.view)
        except Exception:
            pass
        # Prompt for reason via modal
        await interaction.response.send_modal(DirectorDeclineReasonModal(self.view))

class DirectorDeclineReasonModal(Modal, title="Reason for Declining Trade"):
    reason = TextInput(label="Reason for declining", style=discord.TextStyle.paragraph, required=True)
    def __init__(self, director_view):
        super().__init__()
        self.director_view = director_view

    async def on_submit(self, interaction: Interaction):
        requester = await bot.fetch_user(self.director_view.requester_id)
        target = await bot.fetch_user(self.director_view.target_id)
        embed = Embed(
            title="❌ Trade Declined by Director",
            description=(
                f"Your shift trade has been **declined** by the director.\n\n"
                f"**Schedule:** {self.director_view.schedule['start_date']} to {self.director_view.schedule['end_date']}\n"
                f"**Requester Shift:** {self.director_view.your_shift}\n"
                f"**Requested Shift:** {self.director_view.wanted_shift}\n"
                f"**Reason for Decline:** {self.reason.value}\n"
                f"[View Schedule]({self.director_view.schedule['schedule_link']})"
            ),
            color=0xe74c3c
        )
        try:
            await requester.send(embed=embed)
        except Exception:
            pass
        try:
            await target.send(embed=embed)
        except Exception:
            pass
        await interaction.response.send_message("Trade declined. Both students have been notified.", ephemeral=True)
        self.director_view.stop()

# --- Slash Command to Delete a Schedule ---
@bot.tree.command(name="delete_schedule", description="Delete a schedule from the list (admin only).")
@app_commands.checks.has_permissions(administrator=True)
async def delete_schedule(interaction: Interaction):
    schedules = load_schedules()
    if not schedules:
        await interaction.response.send_message("No schedules to delete.", ephemeral=True)
        return
    await interaction.response.send_message(
        "Select a schedule to delete:",
        view=DeleteScheduleView(schedules),
        ephemeral=True
    )

class DeleteScheduleSelect(discord.ui.Select):
    def __init__(self, schedules):
        options = [
            discord.SelectOption(
                label=f"{s['start_date']} to {s['end_date']}",
                value=str(idx),
                description=s['schedule_link'][:80]
            )
            for idx, s in enumerate(schedules)
        ]
        super().__init__(
            placeholder="Select a schedule to delete...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="delete_schedule_select"
        )
        self.schedules = schedules

    async def callback(self, interaction: Interaction):
        idx = int(self.values[0])
        deleted = self.schedules.pop(idx)
        save_schedules(self.schedules)
        await interaction.response.send_message(
            f"Schedule from {deleted['start_date']} to {deleted['end_date']} has been deleted.",
            ephemeral=True
        )
        self.disabled = True
        try:
            if interaction.message:
                await interaction.message.edit(view=self.view)
        except Exception:
            pass

class DeleteScheduleView(View):
    def __init__(self, schedules):
        super().__init__(timeout=180)
        self.add_item(DeleteScheduleSelect(schedules))

# --- Slash Command to View Schedules ---
@bot.tree.command(name="view_schedules", description="View available schedules and their details.")
async def view_schedules(interaction: Interaction):
    schedules = load_schedules()
    if not schedules:
        await interaction.response.send_message("No schedules available.", ephemeral=True)
        return
    await interaction.response.send_message(
        "Select a schedule to view details:",
        view=ViewSchedulesSelectView(schedules, interaction.user.id),
        ephemeral=True
    )

class ViewSchedulesSelect(discord.ui.Select):
    def __init__(self, schedules, requester_id):
        options = [
            discord.SelectOption(
                label=f"{s['start_date']} to {s['end_date']}",
                value=str(idx),
                description=s['schedule_link'][:80]
            )
            for idx, s in enumerate(schedules)
        ]
        super().__init__(
            placeholder="Select a schedule...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="view_schedules_select"
        )
        self.schedules = schedules
        self.requester_id = requester_id

    async def callback(self, interaction: Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the requester can use this menu.", ephemeral=True)
            return
        idx = int(self.values[0])
        schedule = self.schedules[idx]
        allow_text = "✅ Students can offer/trade shifts." if schedule.get("allow_offers", False) else "⛔ Students cannot offer/trade shifts."
        embed = Embed(
            title="📅 Schedule Details",
            description=(
                f"**Dates:** {schedule['start_date']} to {schedule['end_date']}\n"
                f"[View Schedule Spreadsheet]({schedule['schedule_link']})\n\n"
                f"{allow_text}"
            ),
            color=0x2980b9
        )
        embed.set_footer(text="LionShiftGG • Schedule Info")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        self.disabled = True
        try:
            if interaction.message:
                await interaction.message.edit(view=self.view)
        except Exception:
            pass

class ViewSchedulesSelectView(View):
    def __init__(self, schedules, requester_id):
        super().__init__(timeout=180)
        self.add_item(ViewSchedulesSelect(schedules, requester_id))

# --- Slash Command to Setup Request Time Off ---
@bot.tree.command(name="setup_requesttimeoff", description="Setup the Request Time Off panel for student workers.")
@app_commands.checks.has_permissions(administrator=True)
async def setup_requesttimeoff(interaction: Interaction):
    embed = Embed(
        title="🔴 Request Time Off",
        description=(
            "Use this panel to request time off from work.\n\n"
            "Press the **Make Request** button below and fill out the form with the dates you need off and your reason."
        ),
        color=0xe74c3c
    )
    embed.set_footer(text="LionShiftGG • Time Off Requests")
    view = RequestTimeOffView()
    message = await interaction.channel.send(embed=embed, view=view)
    try:
        panels = load_panels()
        panels.setdefault("request_timeoff_messages", []).append({"channel_id": message.channel.id, "message_id": message.id})
        save_panels(panels)
        bot.add_view(view, message_id=message.id)
    except Exception:
        pass
    await interaction.response.send_message("Panel created and persisted.", ephemeral=True)

class RequestTimeOffView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(MakeRequestTimeOffButton())

class MakeRequestTimeOffButton(Button):
    def __init__(self):
        super().__init__(
            label="🔴 Make Request",
            style=discord.ButtonStyle.danger,
            custom_id="make_request_timeoff"
        )

    async def callback(self, interaction: Interaction):
        await interaction.response.send_modal(RequestTimeOffModal())

class RequestTimeOffModal(Modal, title="Request Time Off"):
    from_date = TextInput(label="From Date", placeholder="e.g. 2024-07-10", required=True)
    to_date = TextInput(label="To Date", placeholder="e.g. 2024-07-12", required=True)
    reason = TextInput(label="Reason for Requesting Off", style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, interaction: Interaction):
        from datetime import datetime
        
        # Save the time off request to JSON for web dashboard
        requests = load_timeoff_requests()
        request_id = str(len(requests) + 1)
        new_request = {
            "id": request_id,
            "user_id": str(interaction.user.id),
            "user_name": interaction.user.display_name,
            "from_date": self.from_date.value,
            "to_date": self.to_date.value,
            "reason": self.reason.value,
            "status": "pending",
            "submitted_at": datetime.now().isoformat()
        }
        requests.append(new_request)
        save_timeoff_requests(requests)
        
        embed = Embed(
            title="🔴 Time Off Request Submitted",
            description=(
                f"**From:** {self.from_date.value}\n"
                f"**To:** {self.to_date.value}\n"
                f"**Reason:** {self.reason.value}\n"
            ),
            color=0xe74c3c
        )
        embed.set_footer(text="LionShiftGG • Your request has been sent")
        await interaction.response.send_message("Your time off request has been submitted!", ephemeral=True)
        # DM the director with approval buttons
        director = await bot.fetch_user(DIRECTOR_ID)
        embed_director = Embed(
            title="🔴 New Time Off Request",
            description=(
                f"**Requested By:** {interaction.user.mention} (`{interaction.user.id}`)\n"
                f"**From:** {self.from_date.value}\n"
                f"**To:** {self.to_date.value}\n"
                f"**Reason:** {self.reason.value}"
            ),
            color=0xe74c3c
        )
        embed_director.set_footer(text="LionShiftGG • Time Off Notification")
        view = DirectorTimeOffApprovalView(
            student_id=interaction.user.id,
            from_date=self.from_date.value,
            to_date=self.to_date.value,
            reason=self.reason.value,
            request_id=request_id
        )
        try:
            await director.send(embed=embed_director, view=view)
        except Exception:
            pass

class DirectorTimeOffApprovalView(View):
    def __init__(self, student_id, from_date, to_date, reason, request_id=None):
        super().__init__(timeout=None)  # Make persistent
        self.student_id = student_id
        self.from_date = from_date
        self.to_date = to_date
        self.reason = reason
        self.request_id = request_id
        self.add_item(DirectorApproveTimeOffButton())
        self.add_item(DirectorDeclineTimeOffButton())

class DirectorApproveTimeOffButton(Button):
    def __init__(self):
        super().__init__(label="✅ Approve", style=discord.ButtonStyle.success, custom_id="director_approve_timeoff")

    async def callback(self, interaction: Interaction):
        if interaction.user.id != DIRECTOR_ID:
            await interaction.response.send_message("Only the director can approve this request.", ephemeral=True)
            return
        # Disable buttons
        for item in self.view.children:
            item.disabled = True
        try:
            if interaction.message:
                await interaction.message.edit(view=self.view)
        except Exception:
            pass
        
        # Update the request status in JSON
        if self.view.request_id:
            from datetime import datetime
            requests = load_timeoff_requests()
            for req in requests:
                if req.get("id") == self.view.request_id:
                    req["status"] = "approved"
                    req["approved_at"] = datetime.now().isoformat()
                    break
            save_timeoff_requests(requests)
        
        student = await bot.fetch_user(self.view.student_id)
        embed = Embed(
            title="✅ Time Off Request Approved",
            description=(
                f"Your time off request has been **approved** by the director!\n\n"
                f"**From:** {self.view.from_date}\n"
                f"**To:** {self.view.to_date}\n"
                f"**Reason:** {self.view.reason}"
            ),
            color=0x2ecc71
        )
        embed.set_footer(text="LionShiftGG • Time Off Approved")
        try:
            await student.send(embed=embed)
        except Exception:
            pass
        await interaction.response.send_message("Request approved. Student has been notified.", ephemeral=True)
        self.view.stop()

class DirectorDeclineTimeOffButton(Button):
    def __init__(self):
        super().__init__(label="❌ Decline", style=discord.ButtonStyle.danger, custom_id="director_decline_timeoff")

    async def callback(self, interaction: Interaction):
        if interaction.user.id != DIRECTOR_ID:
            await interaction.response.send_message("Only the director can decline this request.", ephemeral=True)
            return
        # Disable buttons
        for item in self.view.children:
            item.disabled = True
        try:
            if interaction.message:
                await interaction.message.edit(view=self.view)
        except Exception:
            pass
        await interaction.response.send_modal(DirectorTimeOffDeclineReasonModal(self.view))

class DirectorTimeOffDeclineReasonModal(Modal, title="Reason for Denying Time Off"):
    reason = TextInput(label="Reason for denial", style=discord.TextStyle.paragraph, required=True)
    def __init__(self, approval_view):
        super().__init__()
        self.approval_view = approval_view

    async def on_submit(self, interaction: Interaction):
        # Update the request status in JSON
        if self.approval_view.request_id:
            from datetime import datetime
            requests = load_timeoff_requests()
            for req in requests:
                if req.get("id") == self.approval_view.request_id:
                    req["status"] = "declined"
                    req["declined_at"] = datetime.now().isoformat()
                    req["decline_reason"] = self.reason.value
                    break
            save_timeoff_requests(requests)
        
        student = await bot.fetch_user(self.approval_view.student_id)
        embed = Embed(
            title="❌ Time Off Request Denied",
            description=(
                f"Your time off request has been **denied** by the director.\n\n"
                f"**From:** {self.approval_view.from_date}\n"
                f"**To:** {self.approval_view.to_date}\n"
                f"**Reason for Request:** {self.approval_view.reason}\n"
                f"**Reason for Denial:** {self.reason.value}"
            ),
            color=0xe74c3c
        )
        embed.set_footer(text="LionShiftGG • Time Off Denied")
        try:
            await student.send(embed=embed)
        except Exception:
            pass
        await interaction.response.send_message("Request denied. Student has been notified.", ephemeral=True)
        self.approval_view.stop()

@bot.tree.error
async def on_app_command_error(interaction: Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message(
            "❌ You do not have permission to use this command. Only administrators can use this command.",
            ephemeral=True
        )
    else:
        # Optionally handle other errors or re-raise
        raise error

# --- Admin slash command: set_log_channel (delegates to ShiftManagementCog) ---
@bot.tree.command(name="set_log_channel", description="Set channel for shift logs (admin only).")
@app_commands.checks.has_permissions(administrator=True)
async def set_log_channel(interaction: Interaction, channel: discord.TextChannel):
    """
    Delegates setting the log channel to the ShiftManagementCog.
    If the cog isn't loaded, attempt to load its file (handles hyphened filename).
    """
    cog = bot.get_cog("ShiftManagementCog")
    if cog is None:
        # Attempt best-effort to load the cog file by path (works when filenames have hyphens)
        try:
            cog_path = os.path.join(os.path.dirname(__file__), "cogs", "shift-management.py")
            if os.path.isfile(cog_path):
                spec = importlib.util.spec_from_file_location("shift_management_cog", cog_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                setup = getattr(module, "setup", None)
                if setup:
                    if inspect.iscoroutinefunction(setup):
                        await setup(bot)
                    else:
                        setup(bot)
                cog = bot.get_cog("ShiftManagementCog")
        except Exception:
            cog = None

    if cog is None:
        await interaction.response.send_message("ShiftManagement cog is not loaded; cannot set log channel.", ephemeral=True)
        return

    # Prefer cog method if available
    if hasattr(cog, "set_log_channel"):
        try:
            cog.set_log_channel(channel.id)
            await interaction.response.send_message(f"Shift log channel set to {channel.mention}.", ephemeral=True)
            return
        except Exception:
            pass

    # Fallback: try to call module-level save_settings/load_settings from the cog's module
    try:
        module = __import__(cog.__module__, fromlist=["*"])
        load_settings = getattr(module, "load_settings", None)
        save_settings = getattr(module, "save_settings", None)
        if callable(load_settings) and callable(save_settings):
            settings = load_settings() or {}
            settings["log_channel_id"] = channel.id
            save_settings(settings)
            await interaction.response.send_message(f"Shift log channel set to {channel.mention}.", ephemeral=True)
            return
    except Exception:
        pass

    await interaction.response.send_message("Failed to set log channel.", ephemeral=True)

if __name__ == "__main__":
    if not TOKEN:
        print("[FATAL] DISCORD_BOT_TOKEN not set in .env file!")
        sys.exit(1)
    _ = load_panels()
    load_shift_board()  # Ensure persistent shift board is loaded

    # --- Connection resilience events ---
    @bot.event
    async def on_connect():
        print("[CONNECTION] Bot connected to Discord gateway.")

    @bot.event
    async def on_disconnect():
        print("[CONNECTION] WARNING: Bot disconnected from Discord gateway. Will auto-reconnect.")

    @bot.event
    async def on_resumed():
        print("[CONNECTION] Bot resumed connection to Discord.")
        # Restart task loops that may have died during disconnect
        try:
            if not process_notification_queue.is_running():
                print("[RECOVERY] Restarting dead task loop: process_notification_queue")
                process_notification_queue.start()
        except Exception as e:
            print(f"[RECOVERY] Failed to restart process_notification_queue: {e}")

    @process_notification_queue.error
    async def process_notification_queue_error(error):
        print(f"[ERROR] process_notification_queue task died: {error}")
        import traceback
        traceback.print_exc()
        import asyncio
        await asyncio.sleep(30)
        if not process_notification_queue.is_running():
            process_notification_queue.start()

    bot.run(TOKEN)