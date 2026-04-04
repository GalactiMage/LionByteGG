import sys
from discord import app_commands, Embed, Interaction
import discord
import importlib.util, os, inspect
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
import os
import json
import inspect  # NEW: used to detect sync/async setup functions
from datetime import datetime, timezone
from constants import TOKEN, DIRECTOR_ID, STUDENT_WORKER_ROLE_ID
from safe_json import safe_json_dump

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
        workers = []
        for guild in bot.guilds:
            role = guild.get_role(STUDENT_WORKER_ROLE_ID)
            if role:
                for member in role.members:
                    workers.append({
                        "id": str(member.id),
                        "discord_id": str(member.id),
                        "name": member.display_name,
                        "username": str(member),
                        "avatar_url": member.display_avatar.url if member.display_avatar else None,
                        "clocked_in": False,  # This would need to be tracked separately
                        "shifts_this_week": 0  # This would need to be calculated
                    })
        save_workers_cache(workers)
        print(f"Updated workers cache with {len(workers)} workers")
    except Exception as e:
        print(f"Error updating workers cache: {e}")

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
                                # Create beautiful schedule announcement embed
                                embed = Embed(
                                    title="📅 New Schedule Posted!",
                                    description=custom_message if custom_message else f"A new shift schedule has been posted for **{schedule.get('start_date', 'Unknown')}** to **{schedule.get('end_date', 'Unknown')}**.",
                                    color=0x00D166
                                )
                                
                                if schedule.get('name'):
                                    embed.add_field(name="Schedule Name", value=schedule['name'], inline=False)
                                
                                embed.add_field(
                                    name="📆 Date Range",
                                    value=f"{schedule.get('start_date', 'Unknown')} to {schedule.get('end_date', 'Unknown')}",
                                    inline=True
                                )
                                
                                # Show if trading/offering shifts is allowed
                                allow_offers = schedule.get('allow_offers', True)
                                embed.add_field(
                                    name="🔄 Shift Trading",
                                    value="✅ Allowed" if allow_offers else "❌ Not Allowed",
                                    inline=True
                                )
                                
                                if schedule.get('schedule_link'):
                                    embed.add_field(
                                        name="🔗 View Schedule",
                                        value=f"[Click here to view]({schedule['schedule_link']})",
                                        inline=False
                                    )
                                
                                embed.set_footer(text=f"Posted by {schedule.get('created_by', 'Dashboard Admin')}")
                                embed.timestamp = datetime.now(timezone.utc)
                                
                                # Ping the student worker role with the announcement
                                role_mention = f"<@&{STUDENT_WORKER_ROLE_ID}>"
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
                                            color=0x00D166
                                        )
                                        
                                        if schedule.get('name'):
                                            dm_embed.add_field(name="Schedule Name", value=schedule['name'], inline=False)
                                        
                                        dm_embed.add_field(
                                            name="📆 Date Range",
                                            value=f"{schedule.get('start_date', 'Unknown')} to {schedule.get('end_date', 'Unknown')}",
                                            inline=True
                                        )
                                        
                                        if schedule.get('schedule_link'):
                                            dm_embed.add_field(
                                                name="🔗 View Schedule",
                                                value=f"[Click here to view]({schedule['schedule_link']})",
                                                inline=False
                                            )
                                        
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


@bot.event
async def on_ready():
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
    
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"Error syncing commands: {e}")

# --- UI Components ---
class OfferScheduleSelect(discord.ui.Select):
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
            custom_id="offer_schedule_select"
        )
        self.schedules = schedules
        self.requester_id = requester_id

    async def callback(self, interaction: Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the requester can use this menu.", ephemeral=True)
            return
        idx = int(self.values[0])
        selected_schedule = self.schedules[idx]
        await interaction.response.send_modal(OfferShiftModal(interaction.user.id, selected_schedule))

class OfferScheduleSelectView(View):
    def __init__(self, schedules, requester_id):
        super().__init__(timeout=180)
        self.add_item(OfferScheduleSelect(schedules, requester_id))

class OfferShiftModal(Modal, title="Offer Your Shift"):
    name = TextInput(label="Your Name", placeholder="Enter your name", required=True)
    date = TextInput(label="Date of Shift", placeholder="DD-MM-YYYY", required=True)
    time = TextInput(label="Time of Shift", placeholder="e.g. 2:00 PM - 6:00 PM", required=True)
    reason = TextInput(label="Reason for Offering", style=discord.TextStyle.paragraph, required=True)

    def __init__(self, author_id, schedule):
        super().__init__()
        self.author_id = author_id
        self.schedule = schedule

    async def on_submit(self, interaction: Interaction):
        global shift_counter
        shift_id = shift_counter
        shift_counter += 1
        shift_info = {
            "user_id": self.author_id,
            "name": self.name.value,
            "date": self.date.value,
            "time": self.time.value,
            "reason": self.reason.value,
            "schedule": self.schedule
        }
        shift_board[shift_id] = shift_info
        save_shift_board()  # Save after adding a shift
        # Notify all student workers
        from datetime import datetime
        now_str = datetime.now().strftime("%Y-%m-%d %I:%M %p")
        schedule_str = (
            f"**📅 Schedule:** {self.schedule['start_date']} to {self.schedule['end_date']}\n"
            f"[View Schedule]({self.schedule['schedule_link']})\n"
        )
        embed = Embed(
            title="🟢 Shift Available!",
            description=(
                f"{schedule_str}"
                f"**👤 Name:** {shift_info['name']}\n"
                f"**📅 Date:** {shift_info['date']}\n"
                f"**⏰ Time:** {shift_info['time']}\n"
                f"**📝 Reason:** {shift_info['reason']}\n"
                f"**🆔 Shift ID:** {shift_id}"
            ),
            color=0x27ae60
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"Posted: {now_str}")
        view = TakeShiftView(shift_id)
        # Send the message first, then register the view bound to that message so it's persistent
        if STUDENT_WORKER_ROLE_ID:
            role_mention = f"<@&{STUDENT_WORKER_ROLE_ID}>"
            message = await interaction.channel.send(f"{role_mention} **A NEW SHIFT IS AVAILABLE**", embed=embed, view=view)
        else:
            message = await interaction.channel.send("**A NEW SHIFT IS AVAILABLE**", embed=embed, view=view)
        # Register the view for that specific message (so it persists after restarts)
        try:
            bot.add_view(view, message_id=message.id)
        except Exception:
            try:
                bot.add_view(view)
            except Exception:
                pass
        await interaction.response.send_message("Your shift offer has been posted!", ephemeral=True)
        # No longer DM the director when a shift is offered

class OfferShiftView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(OfferShiftButton())
        self.add_item(TradeShiftButton())

class OfferShiftButton(Button):
    def __init__(self):
        super().__init__(label="🟥 Offer Shift", style=discord.ButtonStyle.danger, custom_id="offer_shift")

    async def callback(self, interaction: Interaction):
        schedules = load_schedules()
        allowed_schedules = [s for s in schedules if s.get("allow_offers", False)]
        if not allowed_schedules:
            await interaction.response.send_message("No schedules available for offering shifts.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Select the schedule for your shift offer:",
            view=OfferScheduleSelectView(allowed_schedules, interaction.user.id),
            ephemeral=True
        )

class TradeShiftButton(Button):
    def __init__(self):
        super().__init__(label="🟦 Trade Shift", style=discord.ButtonStyle.primary, custom_id="trade_shift", disabled=False)

    async def callback(self, interaction: Interaction):
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
    _ = load_panels()
    load_shift_board()  # Ensure persistent shift board is loaded
    bot.run(TOKEN)