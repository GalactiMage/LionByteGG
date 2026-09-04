import discord
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import os
import json
import asyncio

_ARENA_TZ = ZoneInfo("America/Chicago")

_HOURS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'arena_hours.json')
_DAY_NAMES = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
_DEFAULT_HOURS = {
    "monday":    {"open": "10:00", "close": "17:00", "closed": False},
    "tuesday":   {"open": "10:00", "close": "17:00", "closed": False},
    "wednesday": {"open": "10:00", "close": "17:00", "closed": False},
    "thursday":  {"open": "10:00", "close": "17:00", "closed": False},
    "friday":    {"open": "10:00", "close": "17:00", "closed": False},
    "saturday":  {"open": "10:00", "close": "17:00", "closed": True},
    "sunday":    {"open": "10:00", "close": "14:00", "closed": False},
}

def _load_hours():
    """Load arena hours from the JSON file, falling back to defaults on any error."""
    try:
        with open(_HOURS_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return _DEFAULT_HOURS

def _parse_time(t):
    """Parse 'HH:MM' string into (hour, minute) ints."""
    h, m = t.split(':')
    return int(h), int(m)

def _next_open(hours_data, start_weekday):
    """Return (days_offset, open_hour, open_min) for the next open day after start_weekday."""
    for i in range(1, 8):
        next_wd = (start_weekday + i) % 7
        day_name = _DAY_NAMES[next_wd]
        day = hours_data.get(day_name, _DEFAULT_HOURS[day_name])
        if not day.get('closed', False):
            oh, om = _parse_time(day['open'])
            return i, oh, om
    return None, None, None

def get_arena_hours_for_today():
    hours_data = _load_hours()
    now = datetime.now(_ARENA_TZ)
    day_name = _DAY_NAMES[now.weekday()]
    day = hours_data.get(day_name, _DEFAULT_HOURS[day_name])
    if day.get('closed', False):
        return None, now
    oh, om = _parse_time(day['open'])
    ch, cm = _parse_time(day['close'])
    return (oh, om, ch, cm), now

async def update_arena_status(bot):
    # Respect any manually set custom activity
    cog = bot.get_cog("AdminCommands")
    if cog and getattr(cog, "_custom_activity", None):
        await bot.change_presence(activity=discord.Game(name=cog._custom_activity))
        return

    hours_data = _load_hours()
    slot, now = get_arena_hours_for_today()

    if slot is None:
        # Closed all day — find next open day
        offset, oh, om = _next_open(hours_data, now.weekday())
        if offset is not None:
            next_open = (now + timedelta(days=offset)).replace(hour=oh, minute=om, second=0, microsecond=0)
            open_str = next_open.strftime("%A %I:%M %p")
            await bot.change_presence(activity=discord.Game(name=f"Arena Closed • Opens {open_str}"))
        else:
            await bot.change_presence(activity=discord.Game(name="Arena Closed"))
    else:
        oh, om, ch, cm = slot
        open_time  = now.replace(hour=oh, minute=om, second=0, microsecond=0)
        close_time = now.replace(hour=ch, minute=cm, second=0, microsecond=0)
        if open_time <= now < close_time:
            close_str = close_time.strftime("%I:%M %p")
            await bot.change_presence(activity=discord.Game(name=f"Arena Open • Closes at {close_str}"))
        elif now < open_time:
            open_str = open_time.strftime("%I:%M %p")
            await bot.change_presence(activity=discord.Game(name=f"Arena Closed • Opens at {open_str}"))
        else:
            # Past close — find next open day
            offset, oh, om = _next_open(hours_data, now.weekday())
            if offset is not None:
                next_open = (now + timedelta(days=offset)).replace(hour=oh, minute=om, second=0, microsecond=0)
                open_str = next_open.strftime("%A %I:%M %p")
                await bot.change_presence(activity=discord.Game(name=f"Arena Closed • Opens {open_str}"))
            else:
                await bot.change_presence(activity=discord.Game(name="Arena Closed"))

