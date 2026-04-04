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

def load_schedules():
    try:
        with open(SCHEDULES_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

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

def load_shift_logs():
    """Load shift logs from file"""
    try:
        with open(SHIFT_LOGS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def save_shift_logs(logs):
    """Save shift logs to file"""
    try:
        safe_json_dump(logs, SHIFT_LOGS_FILE, indent=2)
    except Exception:
        pass

def add_shift_log(action: str, user_id: int, user_name: str, shift_type: str, schedule: dict, timestamp: datetime):
    """Add a shift log entry to the JSON file for web dashboard"""
    logs = load_shift_logs()
    
    log_entry = {
        "action": action,
        "user_id": str(user_id),
        "user_name": user_name,
        "shift_type": shift_type,
        "schedule": {
            "start_date": schedule.get("start_date") if schedule else None,
            "end_date": schedule.get("end_date") if schedule else None,
            "schedule_link": schedule.get("schedule_link") if schedule else None
        } if schedule else None,
        "timestamp": timestamp.isoformat() if timestamp else datetime.utcnow().isoformat(),
        "source": "discord_bot"
    }
    
    logs.append(log_entry)
    
    # Keep only last 500 logs to prevent file from growing too large
    if len(logs) > 500:
        logs = logs[-500:]
    
    save_shift_logs(logs)

async def send_shift_log(bot, action: str, user: discord.User, schedule: dict, shift_type: str, timestamp: datetime):
    """
    action: "start" or "end"
    schedule: dict with start_date, end_date, schedule_link (may be None)
    shift_type: opener/mid/closer
    timestamp: datetime object (assumed UTC if naive)
    """
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
    
    # Also save to JSON file for web dashboard
    try:
        user_name = user.display_name if hasattr(user, 'display_name') else str(user)
        add_shift_log(action, user.id, user_name, shift_type, schedule, timestamp)
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
        await interaction.response.send_message(
            f"Which shift type are you {self.action.lower()}ing?",
            view=ShiftTypeSelectView(self.action, selected_schedule),
            ephemeral=True
        )

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
                # Show checklist first for closers (pass schedule through)
                await interaction.response.send_message(
                    embed=Embed(
                        title="🔒 Closing Checklist",
                        description=(
                            "Before ending your shift, please ensure:\n"
                            "• All **Non-Varsity Students** have left the Arena\n"
                            "• The **Arena Door is Closed**\n"
                            "• Everyone is **Logged out of GGLeap**\n\n"
                            "This ensures all student data/logins are removed and systems are fresh."
                        ),
                        color=0x3498db
                    ),
                    view=CloserChecklistDoneView(self.schedule),
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
            # Step 1: Checklist for closers (first thing they see)
            await interaction.response.send_message(
                embed=Embed(
                    title="🔒 Closing Checklist",
                    description=( 
                        "Before ending your shift, please ensure:\n"
                        "• All **Non-Varsity Students** have left the Arena\n"
                        "• The **Arena Door is Closed**\n"
                        "• Everyone is **Logged out of GGLeap**\n\n"
                        "This ensures all student data/logins are removed and systems are fresh."
                    ),
                    color=0x3498db
                ),
                view=CloserChecklistDoneView(self.schedule),
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
        super().__init__(label="✅ Done", style=discord.ButtonStyle.success, custom_id="closer_clockout_done")
        self.schedule = schedule

    async def callback(self, interaction: Interaction):
        # Step 4: Thank you message + logging
        await interaction.response.send_message(
            embed=Embed(
                title="✅ Shift Ended",
                description=f"Thank you for your work, {interaction.user.mention}!",
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

