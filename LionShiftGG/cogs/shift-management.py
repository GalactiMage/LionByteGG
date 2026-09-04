import discord
from discord import app_commands, Embed, Interaction
from discord.ext import commands
from discord.ui import View, Button, Select
from constants import DIRECTOR_ID, STUDENT_WORKER_ROLE_ID, PURDUE_CLOCKIN_URL, OPENING_FORM_URL, CLOSING_FORM_URL
import asyncio
import json
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo  # NEW: timezone support
from safe_json import safe_json_dump

SCHEDULES_FILE = "schedules.json"
SETTINGS_FILE = "settings.json"
SHIFT_LOGS_FILE = "shift_logs.json"
WORKERS_CACHE_FILE = "workers_cache.json"
SHIFT_DUTIES_FILE = "shift_duties.json"
SHIFT_BOARD_FILE = "shift_board.json"
ROOMS_FILE = "rooms.json"

# load_trades / save_trades / _next_trade_id live in main.py (single source of truth)
from main import load_trades, save_trades, _next_trade_id

def load_schedules():
    try:
        with open(SCHEDULES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def load_shift_duties():
    """Load shift duties. Supports both the new per-room format
    ({roomId: {opener,mid,closer}}) and the legacy flat format ({opener,mid,closer})."""
    try:
        with open(SHIFT_DUTIES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def get_tasks_for_action(duties, role, action_key):
    """
    Get tasks for a role filtered by action_key ('start' or 'end').
    Tasks can be plain strings (always shown) or dicts with show_on/required.
    Required tasks get a ⚠️ prefix.
    """
    role_duties = duties.get(role, {})
    raw_tasks = role_duties.get("tasks", [])
    result = []
    for t in raw_tasks:
        if isinstance(t, str):
            result.append(t)  # legacy format — always shown
        elif isinstance(t, dict):
            text = t.get("text", "").strip()
            if not text:
                continue
            show_on = t.get("show_on", "both")
            if show_on == "both" or show_on == action_key:
                prefix = "\u26a0\ufe0f " if t.get("required") else ""
                result.append(prefix + text)
    return result

def get_today_chicago():
    """Return today's date string (YYYY-MM-DD) in America/Chicago time."""
    try:
        chicago = ZoneInfo("America/Chicago")
    except Exception:
        chicago = timezone(timedelta(hours=-6))
    return datetime.now(chicago).date().isoformat()

_ROLE_KEYS = ("opener", "mid", "closer")

def load_rooms():
    """Configurable arena rooms (shared with the web dashboard via rooms.json)."""
    try:
        with open(ROOMS_FILE, "r", encoding="utf-8") as f:
            rooms = json.load(f)
        if isinstance(rooms, list) and rooms:
            rooms.sort(key=lambda r: r.get("order", 0))
            return rooms
    except Exception:
        pass
    return [{"id": "pc", "name": "PC Room", "emoji": "\U0001f5a5\ufe0f", "order": 0}]

def get_room_meta(room_id):
    for r in load_rooms():
        if r.get("id") == room_id:
            return r
    return None

def room_display(room_id):
    """Human label like '\U0001f3ae Console Room', or '' if unknown."""
    r = get_room_meta(room_id)
    if not r:
        return ""
    return (str(r.get("emoji", "")).strip() + " " + str(r.get("name", ""))).strip()

def get_room_duties(duties, room_id):
    """Return the {opener,mid,closer} block for a room from either format."""
    if not isinstance(duties, dict) or not duties:
        return {}
    if isinstance(duties.get("opener"), dict):   # legacy flat = single implicit room
        return duties
    if room_id and isinstance(duties.get(room_id), dict):
        return duties[room_id]
    for v in duties.values():                    # fallback: first room with role structure
        if isinstance(v, dict) and isinstance(v.get("opener"), dict):
            return v
    return {}

def _find_room_for(schedule, user_id, shift_type):
    """Re-derive the room a worker is scheduled into today (for logging)."""
    try:
        today = get_today_chicago()
        for sh in (schedule or {}).get("shifts", []) if isinstance(schedule, dict) else []:
            if (str(sh.get("worker_id", "")) == str(user_id)
                    and sh.get("date") == today
                    and sh.get("type") == shift_type):
                return sh.get("room")
    except Exception:
        pass
    return None

def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_settings(settings):
    try:
        safe_json_dump(settings, SETTINGS_FILE, indent=2)
    except Exception:
        pass

def load_shift_board():
    try:
        with open(SHIFT_BOARD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"shift_board": {}, "shift_counter": 0}

def save_shift_board(board):
    try:
        safe_json_dump(board, SHIFT_BOARD_FILE, indent=2)
    except Exception:
        pass

def load_shift_logs():
    """Load shift logs from file"""
    try:
        with open(SHIFT_LOGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_shift_logs(logs):
    """Save shift logs to file"""
    try:
        safe_json_dump(logs, SHIFT_LOGS_FILE, indent=2)
    except Exception:
        pass

def update_worker_clock_status(user_id: int, clocked_in: bool, shift_type: str = None):
    """Update the clocked_in status in workers_cache.json for the web dashboard"""
    try:
        workers = []
        if os.path.exists(WORKERS_CACHE_FILE):
            with open(WORKERS_CACHE_FILE, "r", encoding="utf-8") as f:
                workers = json.load(f)
        uid = str(user_id)
        found = False
        for w in workers:
            if w.get("id") == uid or w.get("discord_id") == uid:
                w["clocked_in"] = clocked_in
                if clocked_in:
                    w["current_shift_type"] = shift_type
                    w["clock_in_time"] = datetime.now(timezone.utc).isoformat()
                else:
                    w.pop("current_shift_type", None)
                    w.pop("clock_in_time", None)
                found = True
                break
        if not found:
            # Worker not in cache yet — add a minimal entry so future lookups work
            entry = {"id": uid, "discord_id": uid, "clocked_in": clocked_in,
                     "current_shift_type": None, "clock_in_time": None}
            if clocked_in:
                entry["current_shift_type"] = shift_type
                entry["clock_in_time"] = datetime.now(timezone.utc).isoformat()
            workers.append(entry)
        safe_json_dump(workers, WORKERS_CACHE_FILE, indent=2)
    except Exception:
        pass

def calculate_worker_hours(user_id: str, logs: list = None):
    """Calculate total hours for a worker from shift logs by pairing start/end entries"""
    if logs is None:
        logs = load_shift_logs()
    uid = str(user_id)
    # Filter logs for this user, sorted by timestamp
    user_logs = sorted(
        [l for l in logs if str(l.get("user_id")) == uid],
        key=lambda x: x.get("timestamp", "")
    )
    total_seconds = 0
    active_start = None
    for entry in user_logs:
        if entry.get("action") == "start":
            try:
                active_start = datetime.fromisoformat(entry["timestamp"])
            except Exception:
                active_start = None
        elif entry.get("action") == "end" and active_start:
            try:
                end_time = datetime.fromisoformat(entry["timestamp"])
                diff = (end_time - active_start).total_seconds()
                if 0 < diff < 86400:  # sanity: max 24 hours
                    total_seconds += diff
            except Exception:
                pass
            active_start = None
    return round(total_seconds / 3600, 2)

def add_shift_log(action: str, user_id: int, user_name: str, shift_type: str, schedule: dict, timestamp: datetime):
    """Add a shift log entry to the JSON file for web dashboard"""
    logs = load_shift_logs()

    room_id = _find_room_for(schedule, user_id, shift_type)
    # Resolve the tasks that were shown for this action + shift type + room
    try:
        duties = load_shift_duties()
        action_key = "start" if action == "start" else "end"
        completed_tasks = get_tasks_for_action(get_room_duties(duties, room_id), shift_type, action_key)
    except Exception:
        completed_tasks = []

    log_entry = {
        "action": action,
        "user_id": str(user_id),
        "user_name": user_name,
        "shift_type": shift_type,
        "room": room_id,
        "schedule": {
            "start_date": schedule.get("start_date") if schedule else None,
            "end_date": schedule.get("end_date") if schedule else None,
            "schedule_link": schedule.get("schedule_link") if schedule else None
        } if schedule else None,
        "timestamp": timestamp.isoformat() if timestamp else datetime.utcnow().isoformat(),
        "source": "discord_bot",
        "tasks": completed_tasks
    }
    
    logs.append(log_entry)
    
    # Keep only last 100 logs — oldest are dropped automatically
    if len(logs) > 100:
        logs = logs[-100:]
    
    save_shift_logs(logs)

async def send_shift_log(bot, action: str, user: discord.User, schedule: dict, shift_type: str, timestamp: datetime):
    """
    action: "start" or "end"
    schedule: dict with start_date, end_date, schedule_link (may be None)
    shift_type: opener/mid/closer
    timestamp: datetime object (assumed UTC if naive)
    """
    # Always update shift state first — these must run regardless of channel config
    try:
        user_name = user.display_name if hasattr(user, 'display_name') else str(user)
        add_shift_log(action, user.id, user_name, shift_type, schedule, timestamp)
    except Exception:
        pass
    try:
        update_worker_clock_status(user.id, clocked_in=(action == "start"), shift_type=shift_type)
    except Exception:
        pass

    settings = load_settings()
    channel_id = settings.get("log_channel_id")
    if not channel_id:
        return
    # Try to get the channel; fallback to fetch
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception:
            return

    # Normalize timestamp: assume UTC if naive, then convert to America/Chicago
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    try:
        chicago = ZoneInfo("America/Chicago")
    except Exception:
        # tzdata not available (common on some Windows installs) — fall back to fixed offset CST (UTC-6).
        # NOTE: this fallback does NOT handle DST. Install the 'tzdata' package to restore correct IANA zones:
        #    python -m pip install tzdata
        chicago = timezone(timedelta(hours=-6))

    local_ts = timestamp.astimezone(chicago)
    ts_str = local_ts.strftime("%Y-%m-%d %I:%M %p %Z")

    title = "🟢 Shift Started" if action == "start" else "🔴 Shift Ended"
    color = 0x2ecc71 if action == "start" else 0xe74c3c
    embed = Embed(title=title, color=color, timestamp=local_ts)
    embed.add_field(name="👤 Student", value=f"{user.mention} (`{user.id}`)", inline=False)
    embed.add_field(name="🔖 Shift Type", value=shift_type.title(), inline=True)
    if schedule:
        dates = f"{schedule.get('start_date','N/A')} to {schedule.get('end_date','N/A')}"
        embed.add_field(name="📅 Schedule Dates", value=dates, inline=True)
        if schedule.get("schedule_link"):
            embed.add_field(name="🔗 Schedule Link", value=schedule.get("schedule_link"), inline=False)
    embed.add_field(name="⏰ Time (Central)", value=ts_str, inline=False)
    embed.set_footer(text="LionShiftGG • Shift Logs")

    # Set the embed thumbnail to the student's Discord avatar (best-effort)
    try:
        # If we already have a Member/User object with a display_avatar attribute, use it
        if hasattr(user, "display_avatar"):
            avatar_url = getattr(user, "display_avatar").url
        else:
            # Fallback: fetch the user by ID from the API
            fetched = await bot.fetch_user(int(user.id))
            avatar_url = getattr(fetched, "display_avatar").url
        embed.set_thumbnail(url=avatar_url)
    except Exception:
        # ignore any failures to fetch avatar
        pass

    try:
        await channel.send(embed=embed)
    except Exception:
        pass

# --- UI Components ---
class ScheduleSelect(discord.ui.Select):
    def __init__(self, schedules, action):
        options = [
            discord.SelectOption(
                label=f"{s['start_date']} to {s['end_date']}",
                value=str(idx),
                description=s['schedule_link'][:80]
            )
            for idx, s in enumerate(schedules)
        ]
        super().__init__(
            placeholder="Select your schedule...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"{action.lower()}_schedule_select"
        )
        self.schedules = schedules
        self.action = action

    async def callback(self, interaction: Interaction):
        idx = int(self.values[0])
        selected_schedule = self.schedules[idx]

        # Auto-detect which shift this worker is assigned to today
        today = get_today_chicago()
        worker_id = str(interaction.user.id)

        assigned_shift = None
        for shift in selected_schedule.get("shifts", []):
            if str(shift.get("worker_id", "")) == worker_id and shift.get("date", "") == today:
                assigned_shift = shift
                break

        # Negative checks — block workers who gave away their shift
        blocked_reason = None
        stype_check = ""
        if assigned_shift:
            stype_check = assigned_shift.get("type", "")
            # Block if they offered this shift and someone claimed it
            try:
                board = load_shift_board()
                for offer in board.get("shift_board", {}).values():
                    if (str(offer.get("worker_id")) == worker_id
                            and offer.get("date") == today
                            and offer.get("shift_type") == stype_check
                            and offer.get("taken_by")):
                        blocked_reason = "offered_claimed"
                        assigned_shift = None
                        break
            except Exception:
                pass
            # Block if they have an approved trade where they are the requester (traded away)
            if assigned_shift:
                try:
                    for trade in load_trades():
                        if (trade.get("status") == "approved"
                                and str(trade.get("requester_id")) == worker_id
                                and trade.get("date") == today):
                            blocked_reason = "trade_approved"
                            assigned_shift = None
                            break
                except Exception:
                    pass

        if not assigned_shift:
            # Check if worker picked up an offered shift for today
            offer_shift = None
            try:
                board = load_shift_board()
                for _oid, offer in board.get("shift_board", {}).items():
                    if str(offer.get("taken_by")) == worker_id and offer.get("date") == today:
                        offer_shift = offer
                        break
            except Exception:
                pass

            # Check if worker has an approved trade for today (they are the TARGET/covering worker)
            trade_shift = None
            try:
                for trade in load_trades():
                    if (trade.get("status") == "approved"
                            and str(trade.get("target_id")) == worker_id
                            and trade.get("date") == today):
                        trade_shift = trade
                        break
            except Exception:
                pass

            assigned_shift = offer_shift or trade_shift

            if not assigned_shift:
                if blocked_reason == "offered_claimed":
                    description = (
                        f"Your **{stype_check.title()}** shift on **{today}** was offered and has been "
                        f"**picked up by another worker**. You are not eligible to clock in today.\n\n"
                        "Contact your director if this is a mistake."
                    )
                elif blocked_reason == "trade_approved":
                    description = (
                        f"Your shift trade for **{today}** was **approved** — another worker is covering "
                        f"your shift. You are not eligible to clock in today.\n\n"
                        "Contact your director if this is a mistake."
                    )
                else:
                    description = (
                        f"You are **not scheduled** to work today **({today})** and have no approved "
                        f"shift trades or picked-up offers.\n\n"
                        "To clock in you must:\n"
                        "\u2022 Be on the posted schedule, **or**\n"
                        "\u2022 Have picked up an **offered shift**, **or**\n"
                        "\u2022 Have an **approved shift trade**\n\n"
                        "Contact your director if you believe this is a mistake."
                    )
                embed = discord.Embed(
                    title="\U0001f6ab Not Eligible to Clock In",
                    description=description,
                    color=0xef4444
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        # Normalize field names — schedule uses "type", offers/trades use "shift_type"
        shift_type = assigned_shift.get("type") or assigned_shift.get("shift_type") or "mid"
        shift_start = assigned_shift.get("start", "")
        shift_end = assigned_shift.get("end", "")
        room_id = assigned_shift.get("room") or ""
        room_disp = room_display(room_id)

        # Load duties for this room + role, filtered by action
        duties = load_shift_duties()
        room_duties = get_room_duties(duties, room_id)
        role_duties = room_duties.get(shift_type, {})
        greeting = role_duties.get("greeting", f"You're the {shift_type.title()} today!")
        action_key = "start" if self.action == "Start" else "end"
        tasks = get_tasks_for_action(room_duties, shift_type, action_key)

        type_display = {"opener": "\U0001f305 Opener", "mid": "\u2600\ufe0f Mid-Shift", "closer": "\U0001f319 Closer"}.get(shift_type, shift_type.title())
        task_lines = "\n".join(f"\u2022 {t}" for t in tasks) if tasks else "\u2022 No specific tasks configured."
        footer_sfx = f" \u2022 {room_disp}" if room_disp else ""

        if self.action == "Start":
            # WebClock FIRST — worker must clock in before seeing their tasks
            embed = discord.Embed(
                title="\U0001f550 Step 1 of 2 \u2014 Clock In First",
                description=(
                    f"Hey {interaction.user.mention}! "
                    + (f"You're working the **{room_disp}** today.\n\n" if room_disp else "")
                    + f"Before anything else, you need to "
                    f"**clock in on Purdue WebClock**.\n\n"
                    f"[\U0001f517 Open Purdue WebClock]({PURDUE_CLOCKIN_URL})\n\n"
                    "Once you've clocked in, press **Done** and you'll see your shift tasks."
                ),
                color=0x3b82f6
            )
            embed.set_footer(text=f"Shift: {shift_start} \u2013 {shift_end} \u2022 {type_display}{footer_sfx}")
            await interaction.response.send_message(
                embed=embed,
                view=WebClockConfirmView(shift_type, selected_schedule, greeting, tasks, shift_start, shift_end, type_display, room_disp),
                ephemeral=True
            )
        else:
            end_greeting = greeting
            room_line = f"\U0001f4cd **Room:** {room_disp}\n\n" if room_disp else ""
            embed = discord.Embed(
                title=f"Ending {type_display}",
                description=f"{end_greeting}\n\n{room_line}**End-of-Shift Tasks:**\n{task_lines}\n\n\u23f0 **Shift Time:** {shift_start} \u2013 {shift_end}",
                color=0xe74c3c
            )
            embed.set_footer(text="Complete your tasks, then press the button below to clock out")
            await interaction.response.send_message(embed=embed, view=EndShiftAutoView(shift_type, selected_schedule), ephemeral=True)

class ScheduleSelectView(View):
    def __init__(self, schedules, action):
        super().__init__(timeout=180)
        self.add_item(ScheduleSelect(schedules, action))

class StartShiftButton(Button):
    def __init__(self):
        super().__init__(label="🟢 Start Shift", style=discord.ButtonStyle.success, custom_id="start_shift")

    async def callback(self, interaction: Interaction):
        schedules = load_schedules()
        if not schedules:
            await safe_send(interaction, "There are no available shifts/schedules.", ephemeral=True)
            return
        await safe_send(
            interaction,
            "Select your schedule to start your shift:",
            view=ScheduleSelectView(schedules, "Start"),
            ephemeral=True
        )

class EndShiftButton(Button):
    def __init__(self):
        super().__init__(label="🔴 End Shift", style=discord.ButtonStyle.danger, custom_id="end_shift")

    async def callback(self, interaction: Interaction):
        # Block end shift if the worker has not started a shift
        worker_id = str(interaction.user.id)
        is_clocked_in = False
        try:
            if os.path.exists(WORKERS_CACHE_FILE):
                with open(WORKERS_CACHE_FILE, "r", encoding="utf-8") as f:
                    workers_data = json.load(f)
                is_clocked_in = any(
                    (w.get("id") == worker_id or w.get("discord_id") == worker_id)
                    and w.get("clocked_in")
                    for w in workers_data
                )
        except Exception:
            pass

        # Fallback: check shift_logs.json directly — workers_cache may be stale
        if not is_clocked_in:
            try:
                today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                if os.path.exists(SHIFT_LOGS_FILE):
                    with open(SHIFT_LOGS_FILE, "r", encoding="utf-8") as f:
                        all_logs = json.load(f)
                    user_logs_today = [
                        l for l in all_logs
                        if str(l.get("user_id")) == worker_id
                        and l.get("timestamp", "").startswith(today_str)
                    ]
                    starts = sum(1 for l in user_logs_today if l.get("action") == "start")
                    ends = sum(1 for l in user_logs_today if l.get("action") == "end")
                    if starts > ends:
                        is_clocked_in = True
                        # Repair the cache so subsequent checks are correct
                        last_start = max(
                            (l for l in user_logs_today if l.get("action") == "start"),
                            key=lambda x: x.get("timestamp", "")
                        )
                        update_worker_clock_status(
                            int(worker_id), True, last_start.get("shift_type")
                        )
            except Exception:
                pass

        if not is_clocked_in:
            embed = discord.Embed(
                title="⚠️ You Haven't Started a Shift",
                description=(
                    f"You can't end a shift because you haven't started one yet, {interaction.user.mention}.\n\n"
                    "Press **🟢 Start Shift** first to clock in, then you can end your shift when you're done."
                ),
                color=0xf59e0b
            )
            embed.set_footer(text="LionShiftGG • Shift Management")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        schedules = load_schedules()
        if not schedules:
            await interaction.response.send_message("There are no available shifts/schedules.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Select your schedule to end your shift:",
            view=ScheduleSelectView(schedules, "End"),
            ephemeral=True
        )

class ShiftTypeSelect(discord.ui.Select):
    def __init__(self, action, schedule):
        options = [
            discord.SelectOption(label="Opener", value="opener"),
            discord.SelectOption(label="Mid-Shift", value="mid"),
            discord.SelectOption(label="Closer", value="closer"),
        ]
        super().__init__(
            placeholder=f"Which shift type are you {action.lower()}ing?",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"{action.lower()}_shift_type_select"
        )
        self.action = action
        self.schedule = schedule

    async def callback(self, interaction: Interaction):
        shift_type = self.values[0]
        if self.action == "Start":
            await interaction.response.send_message(
                embed=Embed(
                    title="🕒 Clock In",
                    description=f"Please clock in using the [Purdue WebClock]({PURDUE_CLOCKIN_URL}).\n\nPress **Done** once finished.",
                    color=0x27ae60
                ),
                view=StartShiftDoneView(shift_type, self.schedule),
                ephemeral=True
            )
        else:
            if shift_type == "closer":
                clock_out_embed = Embed(
                    title="🕒 Last Step — Clock Out",
                    description=(
                        f"Great work today, {interaction.user.mention}! 🌙\n\n"
                        "Before you head out, please **clock out on Purdue WebClock** to officially end your shift.\n\n"
                        f"[🔗 Open Purdue WebClock]({PURDUE_CLOCKIN_URL})\n\n"
                        "Once you've clocked out, press **Done** below."
                    ),
                    color=0xe74c3c
                )
                clock_out_embed.set_footer(text="LionShiftGG • 🌙 Closer Shift")
                await interaction.response.send_message(
                    embed=clock_out_embed,
                    view=CloserClockOutDoneView(self.schedule),
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    embed=Embed(
                        title="🕒 Clock Out",
                        description=f"Please clock out using the [Purdue WebClock]({PURDUE_CLOCKIN_URL}).\n\nPress **Done** once finished.",
                        color=0xe74c3c
                    ),
                    view=EndShiftDoneView(shift_type, self.schedule),
                    ephemeral=True
                )

# ── WebClock-first confirm ───────────────────────────────────────────

class WebClockConfirmView(View):
    """Step 1: Worker must clock into WebClock before seeing tasks."""
    def __init__(self, shift_type, schedule, greeting, tasks, shift_start, shift_end, type_display, room_disp=""):
        super().__init__(timeout=300)
        self.add_item(WebClockConfirmedButton(shift_type, schedule, greeting, tasks, shift_start, shift_end, type_display, room_disp))

class WebClockConfirmedButton(Button):
    def __init__(self, shift_type, schedule, greeting, tasks, shift_start, shift_end, type_display, room_disp=""):
        super().__init__(label="\u2705 Done \u2014 I've Clocked In", style=discord.ButtonStyle.success, custom_id=f"webclock_confirmed_{shift_type}")
        self.shift_type = shift_type
        self.schedule = schedule
        self.greeting = greeting
        self.tasks = tasks
        self.shift_start = shift_start
        self.shift_end = shift_end
        self.type_display = type_display
        self.room_disp = room_disp

    async def callback(self, interaction: Interaction):
        # Step 2: Now show the duties/tasks embed
        task_lines = "\n".join(f"\u2022 {t}" for t in self.tasks) if self.tasks else "\u2022 No specific tasks configured."
        room_line = f"\U0001f4cd **You're in the {self.room_disp}**\n\n" if self.room_disp else ""
        embed = discord.Embed(
            title=f"\U0001f4cb Step 2 of 2 \u2014 {self.type_display} Tasks",
            description=f"{self.greeting}\n\n{room_line}**Your Tasks:**\n{task_lines}\n\n\u23f0 **Shift Time:** {self.shift_start} \u2013 {self.shift_end}",
            color=0x2ecc71
        )
        embed.set_footer(text="Have a great shift! Press the button when you're done reading.")
        if self.shift_type == "opener":
            await interaction.response.send_message(embed=embed, view=OpenerFormDoneView(self.schedule), ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, view=StartShiftDoneView(self.shift_type, self.schedule), ephemeral=True)

class EndShiftAutoView(View):
    """Shown after auto-detecting the worker's shift type — lets them confirm clock out."""
    def __init__(self, shift_type, schedule):
        super().__init__(timeout=180)
        self.add_item(EndShiftAutoButton(shift_type, schedule))

class EndShiftAutoButton(Button):
    def __init__(self, shift_type, schedule):
        super().__init__(label="🔴 End My Shift", style=discord.ButtonStyle.danger, custom_id=f"end_auto_{shift_type}")
        self.shift_type = shift_type
        self.schedule = schedule

    async def callback(self, interaction: Interaction):
        if self.shift_type == "closer":
            clock_out_embed = Embed(
                title="🕒 Last Step — Clock Out",
                description=(
                    f"Great work today, {interaction.user.mention}! 🌙\n\n"
                    "Before you head out, please **clock out on Purdue WebClock** to officially end your shift.\n\n"
                    f"[🔗 Open Purdue WebClock]({PURDUE_CLOCKIN_URL})\n\n"
                    "Once you've clocked out, press **Done** below."
                ),
                color=0xe74c3c
            )
            clock_out_embed.set_footer(text="LionShiftGG • 🌙 Closer Shift")
            await interaction.response.send_message(
                embed=clock_out_embed,
                view=CloserClockOutDoneView(self.schedule),
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                embed=Embed(
                    title="🕒 Clock Out",
                    description=f"Please clock out using the [Purdue WebClock]({PURDUE_CLOCKIN_URL}).\n\nPress **Done** once finished.",
                    color=0xe74c3c
                ),
                view=EndShiftDoneView(self.shift_type, self.schedule),
                ephemeral=True
            )

# ── Keep ShiftTypeSelectView as internal fallback ────────────────────

class ShiftTypeSelectView(View):
    def __init__(self, action, schedule):
        super().__init__(timeout=180)
        self.add_item(ShiftTypeSelect(action, schedule))

class StartShiftDoneView(View):
    def __init__(self, shift_type, schedule):
        super().__init__(timeout=180)
        self.schedule = schedule
        self.add_item(StartShiftDoneButton(shift_type, schedule))

class StartShiftDoneButton(Button):
    def __init__(self, shift_type, schedule):
        super().__init__(label="✅ Done", style=discord.ButtonStyle.success, custom_id=f"start_shift_done_{shift_type}")
        self.shift_type = shift_type
        self.schedule = schedule

    async def callback(self, interaction: Interaction):
        # If opener, require opening form first
        if self.shift_type == "opener":
            await interaction.response.send_message(
                embed=Embed(
                    title="📋 Required Opening Form",
                    description=f"Please fill out the [Opening Form]({OPENING_FORM_URL}) before starting your shift.\n\nPress **Done** once completed.",
                    color=0x3498db
                ),
                view=OpenerFormDoneView(self.schedule),
                ephemeral=True
            )
            return

        # Non-opener immediate acknowledgement + logging
        await interaction.response.send_message(
            embed=Embed(
                title="✅ You're All Set!",
                description=f"Have a Great Shift {interaction.user.mention}!",
                color=0x2ecc71
            ),
            ephemeral=True
        )
        # Log the clock-in
        now = datetime.utcnow()
        await send_shift_log(interaction.client, "start", interaction.user, self.schedule, self.shift_type, now)

class OpenerFormDoneView(View):
    def __init__(self, schedule):
        super().__init__(timeout=180)
        self.schedule = schedule
        self.add_item(OpenerFormDoneButton(schedule))

class OpenerFormDoneButton(Button):
    def __init__(self, schedule):
        super().__init__(label="✅ Done", style=discord.ButtonStyle.success, custom_id="opener_form_done")
        self.schedule = schedule

    async def callback(self, interaction: Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="✅ You're All Set!",
                description=f"Have a Great Shift {interaction.user.mention}!",
                color=0x2ecc71
            ),
            ephemeral=True
        )
        now = datetime.utcnow()
        await send_shift_log(interaction.client, "start", interaction.user, self.schedule, "opener", now)

class EndShiftDoneView(View):
    def __init__(self, shift_type, schedule):
        super().__init__(timeout=180)
        self.schedule = schedule
        self.add_item(EndShiftDoneButton(shift_type, schedule))

class EndShiftDoneButton(Button):
    def __init__(self, shift_type, schedule):
        super().__init__(label="✅ Done", style=discord.ButtonStyle.success, custom_id=f"end_shift_done_{shift_type}")
        self.shift_type = shift_type
        self.schedule = schedule

    async def callback(self, interaction: Interaction):
        if self.shift_type == "closer":
            clock_out_embed = Embed(
                title="🕒 Last Step — Clock Out",
                description=(
                    f"Great work today, {interaction.user.mention}! 🌙\n\n"
                    "Before you head out, please **clock out on Purdue WebClock** to officially end your shift.\n\n"
                    f"[🔗 Open Purdue WebClock]({PURDUE_CLOCKIN_URL})\n\n"
                    "Once you've clocked out, press **Done** below."
                ),
                color=0xe74c3c
            )
            clock_out_embed.set_footer(text="LionShiftGG • 🌙 Closer Shift")
            await interaction.response.send_message(
                embed=clock_out_embed,
                view=CloserClockOutDoneView(self.schedule),
                ephemeral=True
            )
            return
        else:
            await interaction.response.send_message(
                embed=Embed(
                    title="✅ Shift Ended",
                    description=f"Thank you for your work, {interaction.user.mention}!",
                    color=0xe74c3c
                ),
                ephemeral=True
            )
            # Log the clock-out
            now = datetime.utcnow()
            await send_shift_log(interaction.client, "end", interaction.user, self.schedule, self.shift_type, now)

class CloserChecklistDoneView(View):
    def __init__(self, schedule):
        super().__init__(timeout=180)
        self.schedule = schedule
        self.add_item(CloserChecklistDoneButton(schedule))

class CloserChecklistDoneButton(Button):
    def __init__(self, schedule):
        super().__init__(label="✅ Done", style=discord.ButtonStyle.success, custom_id="closer_checklist_done")
        self.schedule = schedule

    async def callback(self, interaction: Interaction):
        # Step 2: Required closing form
        await interaction.response.send_message(
            embed=Embed(
                title="📋 Required Closing Form",
                description=f"Please fill out the [Closing Form]({CLOSING_FORM_URL}) before finishing your shift.\n\nPress **Done** once completed.",
                color=0x3498db
            ),
            view=CloserFormDoneView(self.schedule),
            ephemeral=True
        )

class CloserFormDoneView(View):
    def __init__(self, schedule):
        super().__init__(timeout=180)
        self.schedule = schedule
        self.add_item(CloserFormDoneButton(schedule))

class CloserFormDoneButton(Button):
    def __init__(self, schedule):
        super().__init__(label="✅ Done", style=discord.ButtonStyle.success, custom_id="closer_form_done")
        self.schedule = schedule

    async def callback(self, interaction: Interaction):
        # Step 3: Clock out
        await interaction.response.send_message(
            embed=Embed(
                title="🕒 Clock Out",
                description=(
                    "You have completed the closing form.\n\n"
                    f"Now, please clock out using the Purdue WebClock: {PURDUE_CLOCKIN_URL}\n\n"
                    "Press **Done** once finished."
                ),
                color=0x27ae60
            ),
            view=CloserClockOutDoneView(self.schedule),
            ephemeral=True
        )

class CloserClockOutDoneView(View):
    def __init__(self, schedule):
        super().__init__(timeout=180)
        self.schedule = schedule
        self.add_item(CloserClockOutDoneButton(schedule))

class CloserClockOutDoneButton(Button):
    def __init__(self, schedule):
        super().__init__(label="✅ Done — I've Clocked Out", style=discord.ButtonStyle.success, custom_id="closer_clockout_done")
        self.schedule = schedule

    async def callback(self, interaction: Interaction):
        await interaction.response.send_message(
            embed=Embed(
                title="✅ Shift Ended",
                description=f"Thank you for your work, {interaction.user.mention}! 🌙 Great job closing up today!",
                color=0x2ecc71
            ),
            ephemeral=True
        )
        now = datetime.utcnow()
        await send_shift_log(interaction.client, "end", interaction.user, self.schedule, "closer", now)

class ClockPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)  # Make persistent
        self.add_item(StartShiftButton())
        self.add_item(EndShiftButton())

class ShiftManagementCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def set_log_channel(self, channel_id: int):
        """Programmatic helper — set and persist the log channel."""
        settings = load_settings()
        settings["log_channel_id"] = channel_id
        save_settings(settings)

    @app_commands.command(name="offer_shift", description="Offer one of your scheduled shifts for someone else to pick up.")
    async def offer_shift(self, interaction: Interaction):
        today = get_today_chicago()
        worker_id = str(interaction.user.id)

        # Find all upcoming scheduled shifts for this worker
        schedules = load_schedules()
        upcoming = []
        for schedule in schedules:
            if schedule.get("status") != "published":
                continue
            for shift in schedule.get("shifts", []):
                if str(shift.get("worker_id", "")) == worker_id and shift.get("date", "") >= today:
                    upcoming.append(shift)

        if not upcoming:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="\u26a0\ufe0f No Upcoming Shifts",
                    description="You have no published upcoming shifts to offer.",
                    color=0xf59e0b
                ),
                ephemeral=True
            )
            return

        # Deduplicate by date+type
        seen = set()
        unique = []
        for s in upcoming:
            key = (s.get("date"), s.get("type"))
            if key not in seen:
                seen.add(key)
                unique.append(s)
        unique = unique[:25]  # Discord select limit

        options = [
            discord.SelectOption(
                label=f"{s['date']} — {s.get('type','?').title()} ({s.get('start','')}–{s.get('end','')})",
                value=f"{s['date']}|{s.get('type','mid')}|{s.get('start','')}|{s.get('end','')}"
            )
            for s in unique
        ]

        select = discord.ui.Select(placeholder="Choose a shift to offer…", options=options, custom_id="offer_shift_select")

        async def select_callback(sel_inter: Interaction):
            parts = select.values[0].split("|")
            date, stype, start, end = parts[0], parts[1], parts[2], parts[3]

            # Check for duplicate offer
            board = load_shift_board()
            for _oid, existing in board.get("shift_board", {}).items():
                if (existing.get("worker_id") == worker_id
                        and existing.get("date") == date
                        and existing.get("shift_type") == stype
                        and not existing.get("taken_by")):
                    await sel_inter.response.send_message(
                        embed=discord.Embed(
                            title="\u26a0\ufe0f Already Offered",
                            description="You already have an open offer for that shift.",
                            color=0xf59e0b
                        ),
                        ephemeral=True
                    )
                    return

            counter = board.get("shift_counter", 0) + 1
            offer_id = f"O{counter:03d}"
            board.setdefault("shift_board", {})[offer_id] = {
                "worker_id": worker_id,
                "worker_name": interaction.user.display_name,
                "date": date,
                "shift_type": stype,
                "start": start,
                "end": end,
                "taken_by": None,
                "taken_by_name": None,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            board["shift_counter"] = counter
            save_shift_board(board)

            await sel_inter.response.send_message(
                embed=discord.Embed(
                    title="\u2705 Shift Offered",
                    description=(
                        f"Your **{stype.title()}** shift on **{date}** ({start}–{end}) "
                        f"has been posted to the shift board as **#{offer_id}**.\n\n"
                        "Another worker can pick it up with `/pickup_shift`."
                    ),
                    color=0x2ecc71
                ),
                ephemeral=True
            )

        select.callback = select_callback
        view = discord.ui.View(timeout=120)
        view.add_item(select)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="\U0001f4cb Offer a Shift",
                description="Select the shift you want to put on the board:",
                color=0x3b82f6
            ),
            view=view,
            ephemeral=True
        )

    @app_commands.command(name="pickup_shift", description="Pick up an available offered shift from the board.")
    async def pickup_shift(self, interaction: Interaction):
        worker_id = str(interaction.user.id)
        board = load_shift_board()
        open_offers = [
            (oid, offer) for oid, offer in board.get("shift_board", {}).items()
            if not offer.get("taken_by") and str(offer.get("worker_id")) != worker_id
        ]

        if not open_offers:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="\U0001f4cb No Open Offers",
                    description="There are no available shifts on the board right now.",
                    color=0xf59e0b
                ),
                ephemeral=True
            )
            return

        open_offers = open_offers[:25]
        options = [
            discord.SelectOption(
                label=f"#{oid} — {o['date']} {o.get('shift_type','?').title()} ({o.get('start','')}–{o.get('end','')})",
                description=f"Posted by {o.get('worker_name','?')}",
                value=oid
            )
            for oid, o in open_offers
        ]

        select = discord.ui.Select(placeholder="Choose a shift to pick up…", options=options, custom_id="pickup_shift_select")

        async def select_callback(sel_inter: Interaction):
            oid = select.values[0]
            board2 = load_shift_board()
            offer = board2.get("shift_board", {}).get(oid)
            if not offer:
                await sel_inter.response.send_message("That offer no longer exists.", ephemeral=True)
                return
            if offer.get("taken_by"):
                await sel_inter.response.send_message("That shift has already been claimed.", ephemeral=True)
                return

            offer["taken_by"] = worker_id
            offer["taken_by_name"] = sel_inter.user.display_name
            offer["claimed_at"] = datetime.now(timezone.utc).isoformat()
            save_shift_board(board2)

            await sel_inter.response.send_message(
                embed=discord.Embed(
                    title="\u2705 Shift Claimed!",
                    description=(
                        f"You've picked up the **{offer.get('shift_type','?').title()}** shift on "
                        f"**{offer.get('date')}** ({offer.get('start','')}–{offer.get('end','')}). "
                        f"Make sure to clock in on that day!"
                    ),
                    color=0x2ecc71
                ),
                ephemeral=True
            )

        select.callback = select_callback
        view = discord.ui.View(timeout=120)
        view.add_item(select)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="\U0001f4cb Available Shifts",
                description="Select a shift to claim:",
                color=0x3b82f6
            ),
            view=view,
            ephemeral=True
        )

    @app_commands.command(name="trade_shift", description="Propose a shift trade with another worker.")
    @app_commands.describe(worker="The worker you want to trade your shift with")
    async def trade_shift(self, interaction: Interaction, worker: discord.Member):
        requester_id = str(interaction.user.id)
        today = get_today_chicago()

        if str(worker.id) == requester_id:
            await interaction.response.send_message("You can't trade with yourself.", ephemeral=True)
            return

        # Find upcoming shifts for requester
        schedules = load_schedules()
        my_shifts = []
        for schedule in schedules:
            if schedule.get("status") != "published":
                continue
            for shift in schedule.get("shifts", []):
                if str(shift.get("worker_id", "")) == requester_id and shift.get("date", "") >= today:
                    my_shifts.append(shift)
        my_shifts = my_shifts[:25]

        if not my_shifts:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="\u26a0\ufe0f No Upcoming Shifts",
                    description="You have no upcoming shifts to trade.",
                    color=0xf59e0b
                ),
                ephemeral=True
            )
            return

        options = [
            discord.SelectOption(
                label=f"{s['date']} — {s.get('type','?').title()} ({s.get('start','')}–{s.get('end','')})",
                value=f"{s['date']}|{s.get('type','mid')}|{s.get('start','')}|{s.get('end','')}"
            )
            for s in my_shifts
        ]

        select = discord.ui.Select(placeholder="Which of YOUR shifts to trade away?", options=options, custom_id="trade_shift_select")

        async def select_callback(sel_inter: Interaction):
            parts = select.values[0].split("|")
            date, stype, start, end = parts[0], parts[1], parts[2], parts[3]

            trades = load_trades()
            # Avoid duplicate pending trade
            for t in trades:
                if (t.get("status") == "pending"
                        and t.get("requester_id") == requester_id
                        and t.get("target_id") == str(worker.id)
                        and t.get("date") == date):
                    await sel_inter.response.send_message("You already have a pending trade for that shift.", ephemeral=True)
                    return

            import time as _time, random as _random
            trade_id = _next_trade_id("T")
            trades.append({
                "id": trade_id,
                "requester_id": requester_id,
                "requester_name": sel_inter.user.display_name,
                "target_id": str(worker.id),
                "target_name": worker.display_name,
                "date": date,
                "shift_type": stype,
                "start": start,
                "end": end,
                "status": "pending",
                "created_at": datetime.now(timezone.utc).isoformat()
            })
            save_trades(trades)

            await sel_inter.response.send_message(
                embed=discord.Embed(
                    title="\U0001f501 Trade Requested",
                    description=(
                        f"Your **{stype.title()}** shift on **{date}** ({start}–{end}) "
                        f"trade request with **{worker.display_name}** has been submitted as **#{trade_id}**.\n\n"
                        "A director must approve it from the dashboard before it takes effect."
                    ),
                    color=0x3b82f6
                ),
                ephemeral=True
            )

        select.callback = select_callback
        view = discord.ui.View(timeout=120)
        view.add_item(select)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="\U0001f501 Trade Shift",
                description=f"Select which of your shifts you want to give to **{worker.display_name}**:",
                color=0x3b82f6
            ),
            view=view,
            ephemeral=True
        )

    @app_commands.command(name="setup_clockpanel", description="Setup the LionShift ClockHub panel for students.")
    async def setup_clockpanel(self, interaction: Interaction):
        embed = Embed(
            title="🦁 LionShift ClockHub",
            description=(
                "Welcome to the **LionShift ClockHub**!\n\n"
                "To begin your shift, press the green **Start Shift** button below.\n"
                "To end your shift, press the red **End Shift** button below.\n\n"
                "Follow the prompts to clock in/out and complete required forms."
            ),
            color=0xf1c40f
        )
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png?ex=68bd9a34&is=68bc48b4&hm=67e295c37904921135992cf97ae9047b32afa852300d19b5213567907931d173&")
        embed.set_footer(text="LionShiftGG • ClockHub Panel")
        view = ClockPanelView()
        # send message and persist the message id so we can re-register the view after restarts
        msg = await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("ClockHub panel created!", ephemeral=True)

        # Persist panel message info to panels file (uses main.py helpers)
        try:
            from main import load_panels, save_panels
            panels = load_panels()
            panels.setdefault("clockpanel_messages", [])
            panels["clockpanel_messages"].append({
                "guild_id": interaction.guild.id if interaction.guild else None,
                "channel_id": interaction.channel.id,
                "message_id": msg.id
            })
            save_panels(panels)
        except Exception:
            # fail silently if persistence isn't available
            pass

    # Removed duplicate app command `/set_log_channel` here to avoid registration conflict.
    # If you want a cog-level slash command, keep only one definition (either here or in main.py).
# Replace duplicate setup functions with a single persistent registerer
async def setup(bot):
    # Add the cog instance so the app commands defined on the Cog are registered
    cog = ShiftManagementCog(bot)
    await bot.add_cog(cog)

    # Re-register persistent ClockPanelView for any saved panel messages so buttons work after restart
    try:
        from main import load_panels
        panels = load_panels()
        for entry in panels.get("clockpanel_messages", []):
            try:
                bot.add_view(ClockPanelView(), message_id=entry["message_id"])
            except Exception:
                pass
    except Exception:
        pass

    # Ensure the app commands provided by this cog are synced.
    # Global sync can take up to an hour to appear; for immediate testing you can
    # set TEST_GUILD_ID in constants.py and the cog will sync to that guild (instant).
    try:
        import constants as _const
        test_guild = getattr(_const, "TEST_GUILD_ID", None)
        if test_guild:
            await bot.tree.sync(guild=discord.Object(id=test_guild))
        else:
            await bot.tree.sync()
    except Exception:
        # Fail silently — commands may still register during the bot's on_ready sync
        pass

# --- Safe interaction sender to avoid "Unknown interaction" / already-responded errors ---
async def safe_send(interaction: Interaction, *args, use_followup_if_responded: bool = True, **kwargs):
    """
    Send a message for an interaction, using response.send_message if available,
    otherwise falling back to followup.send. Silently ignores NotFound errors.
    """
    try:
        is_done = False
        try:
            is_done = interaction.response.is_done()
        except Exception:
            # older versions or unexpected state — assume not done
            is_done = False

        if not is_done:
            await interaction.response.send_message(*args, **kwargs)
            return

        # already responded — use followup if allowed
        if use_followup_if_responded:
            await interaction.followup.send(*args, **kwargs)
    except discord.errors.InteractionResponded:
        # race condition — send as followup
        try:
            await interaction.followup.send(*args, **kwargs)
        except Exception:
            pass
    except discord.errors.NotFound:
        # Unknown interaction / expired — nothing to do
        pass
    except Exception:
        # swallow other send errors to avoid crashing the scheduled task loop
        pass

