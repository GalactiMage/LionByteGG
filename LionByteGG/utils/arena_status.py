import discord
from datetime import datetime, timedelta, timezone
import os
import asyncio


def get_arena_hours_for_today():
    # Arena hours as posted in the code/comments:
    # Monday:    10:00 AM – 5:00 PM
    # Tuesday:   10:00 AM – 5:00 PM
    # Wednesday: 10:00 AM – 5:00 PM
    # Thursday:  10:00 AM – 5:00 PM
    # Friday:    10:00 AM – 5:00 PM
    # Saturday:  Closed
    # Sunday:    10:00 AM – 2:00 PM
    hours = {
        0: (10, 0, 17, 0),   # Monday
        1: (10, 0, 17, 0),   # Tuesday
        2: (10, 0, 17, 0),   # Wednesday
        3: (10, 0, 17, 0),   # Thursday
        4: (10, 0, 17, 0),   # Friday (was 20, 0)
        5: None,             # Saturday Closed
        6: (10, 0, 14, 0),   # Sunday
    }
    now = datetime.now(timezone.utc).astimezone()
    weekday = now.weekday()
    return hours.get(weekday), now

async def update_arena_status(bot):
    # Check if a custom activity is set in AdminCommands cog
    cog = bot.get_cog("AdminCommands")
    if cog and getattr(cog, "_custom_activity", None):
        await bot.change_presence(activity=discord.Game(name=cog._custom_activity))
        return
    hours, now = get_arena_hours_for_today()
    if hours is None:
        # Closed all day
        # Find next open day
        for i in range(1, 8):
            next_day = (now.weekday() + i) % 7
            next_hours = {
                0: (10, 0), 1: (10, 0), 2: (10, 0), 3: (10, 0), 4: (10, 0), 5: None, 6: (10, 0)
            }.get(next_day)
            if next_hours:
                from datetime import timedelta
                next_open = (now + timedelta(days=i)).replace(hour=next_hours[0], minute=next_hours[1], second=0, microsecond=0)
                open_str = next_open.strftime("%A %I:%M %p")
                await bot.change_presence(activity=discord.Game(name=f"Arena Closed • Opens {open_str}"))
                return
        await bot.change_presence(activity=discord.Game(name="Arena Closed"))
    else:
        open_hour, open_min, close_hour, close_min = hours
        open_time = now.replace(hour=open_hour, minute=open_min, second=0, microsecond=0)
        close_time = now.replace(hour=close_hour, minute=close_min, second=0, microsecond=0)
        if open_time <= now < close_time:
            close_str = close_time.strftime("%I:%M %p")
            await bot.change_presence(activity=discord.Game(name=f"Arena Open • Closes at {close_str}"))
        else:
            # Find next open time (could be today or next day)
            if now < open_time:
                open_str = open_time.strftime("%I:%M %p")
                await bot.change_presence(activity=discord.Game(name=f"Arena Closed • Opens at {open_str}"))
            else:
                # After close, find next open day
                for i in range(1, 8):
                    next_day = (now.weekday() + i) % 7
                    next_hours = {
                        0: (10, 0), 1: (10, 0), 2: (10, 0),  3: (10, 0), 4: (10, 0), 5: None, 6: (10, 0)
                    }.get(next_day)
                    if next_hours:
                        from datetime import timedelta
                        next_open = (now + timedelta(days=i)).replace(hour=next_hours[0], minute=next_hours[1], second=0, microsecond=0)
                        open_str = next_open.strftime("%A %I:%M %p")
                        await bot.change_presence(activity=discord.Game(name=f"Arena Closed • Opens {open_str}"))
                        return
                await bot.change_presence(activity=discord.Game(name="Arena Closed"))

