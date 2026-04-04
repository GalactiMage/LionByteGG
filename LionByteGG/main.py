import discord
from discord.ext import commands, tasks
from discord import app_commands
import re
import asyncio
from datetime import datetime, timedelta, timezone
import os
import sys
import random
from datetime import time as dt_time
import json
from dotenv import load_dotenv

# Load .env from the same directory as main.py
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

# Get the directory where main.py is located for absolute paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
JOB_PROGRESS_FILE = os.path.join(DATA_DIR, "job_progress.json")

# Import views
from views.setup_view import SetupView
from views.ticket_view import TicketPanelView, TicketAdminView, ensure_ticket_panel_message  # <-- Ensure TicketAdminView is imported
from views.varsity_view import VarsityRegistrationView, VarsityApproveView, PersistentVarsityRegistrationView, add_pending_registration, remove_pending_registration
from cogs.admin_commands import MigrateToStudentView

# Import constants
from utils.constants import GUILD_ID, TICKET_PANEL_CHANNEL_ID, SETUP_CHANNEL_ID, pending_users

# Import cogs
from cogs.admin_commands import AdminCommands
from cogs.ticket_commands import TicketCommands
from cogs.moderation import Moderation  # <-- Add this import


from utils.arena_status import update_arena_status
# Add GGLeapStatus import for extension loading
from utils.safe_json import safe_json_dump

# Bot Created By Jay Moon

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.guild_messages = True
intents.presences = True  # Enable presence intent for online status
intents.auto_moderation_execution = True  # <-- Correct intent for AutoMod events
intents.voice_states = True  # Enable voice state tracking for watchlist alerts
bot = commands.Bot(command_prefix="/", intents=intents)

# Track welcome messages sent to users
welcome_messages = {}

JOIN_TRACK_FILE = os.path.join(DATA_DIR, "join_times.json")
WATCHLIST_FILE = os.path.join(DATA_DIR, "watchlist.json")

def load_join_times():
    if os.path.exists(JOIN_TRACK_FILE):
        with open(JOIN_TRACK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_join_times(data):
    os.makedirs(os.path.dirname(JOIN_TRACK_FILE), exist_ok=True)
    safe_json_dump(data, JOIN_TRACK_FILE)

# ========== Watchlist Functions ==========
def load_watchlist():
    """Load watchlist data"""
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {"watched_users": [], "settings": {}}
    return {"watched_users": [], "settings": {}}

def save_watchlist(data):
    """Save watchlist data"""
    os.makedirs(os.path.dirname(WATCHLIST_FILE), exist_ok=True)
    safe_json_dump(data, WATCHLIST_FILE, indent=2)

def is_user_watched(user_id):
    """Check if a user is on the watchlist"""
    watchlist = load_watchlist()
    return any(str(u.get('user_id')) == str(user_id) for u in watchlist.get('watched_users', []))

def get_watched_user(user_id):
    """Get watchlist entry for a user"""
    watchlist = load_watchlist()
    for user in watchlist.get('watched_users', []):
        if str(user.get('user_id')) == str(user_id):
            return user
    return None

def log_watchlist_activity(user_id, activity_type, details):
    """Log activity for a watched user"""
    watchlist = load_watchlist()
    for i, watched in enumerate(watchlist.get('watched_users', [])):
        if str(watched.get('user_id')) == str(user_id):
            watchlist['watched_users'][i]['activity_count'] = watched.get('activity_count', 0) + 1
            watchlist['watched_users'][i]['last_activity'] = datetime.now(timezone.utc).isoformat()
            watchlist['watched_users'][i].setdefault('activity_log', []).insert(0, {
                "type": activity_type,
                "details": details,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            # Keep only last 50 activity entries
            watchlist['watched_users'][i]['activity_log'] = watchlist['watched_users'][i]['activity_log'][:50]
            save_watchlist(watchlist)
            return True
    return False

async def send_watchlist_alert(user, activity_type, details, alert_level='normal'):
    """Send an alert about watched user activity"""
    watchlist = load_watchlist()
    settings = watchlist.get('settings', {})
    
    # Check if alerts are enabled for this activity type
    if activity_type == 'join' and not settings.get('alert_on_join', True):
        return
    if activity_type == 'message' and not settings.get('alert_on_message', True):
        return
    if activity_type == 'voice_join' and not settings.get('alert_on_voice_join', True):
        return
    
    # Determine alert channel
    alert_channel_id = settings.get('alert_channel_id')
    if not alert_channel_id:
        # Fallback to mod log channel if available
        from utils.log_channels import LOG_CHANNEL_IDS
        alert_channel_id = LOG_CHANNEL_IDS.get('mod_log')
    
    if not alert_channel_id:
        return
    
    try:
        channel = bot.get_channel(int(alert_channel_id))
        if not channel:
            channel = await bot.fetch_channel(int(alert_channel_id))
        
        if channel:
            # Build alert embed
            alert_colors = {
                'low': discord.Color.green(),
                'normal': discord.Color.gold(),
                'high': discord.Color.red()
            }
            
            activity_icons = {
                'join': '🚪',
                'message': '💬',
                'voice_join': '🔊',
                'voice_leave': '🔇'
            }
            
            watched_data = get_watched_user(user.id)
            
            embed = discord.Embed(
                title=f"{activity_icons.get(activity_type, '👁')} Watchlist Alert: {activity_type.replace('_', ' ').title()}",
                description=f"**{user.display_name}** ({user.mention}) is on the watchlist",
                color=alert_colors.get(alert_level, discord.Color.gold()),
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.add_field(name="Activity", value=details, inline=False)
            
            if watched_data:
                embed.add_field(name="Watch Reason", value=watched_data.get('reason', 'No reason'), inline=True)
                embed.add_field(name="Alert Level", value=alert_level.title(), inline=True)
                embed.add_field(name="Total Activity", value=str(watched_data.get('activity_count', 0) + 1), inline=True)
            
            if user.avatar:
                embed.set_thumbnail(url=user.avatar.url)
            
            embed.set_footer(text=f"User ID: {user.id}")
            
            await channel.send(embed=embed)
            
    except Exception as e:
        print(f"[WATCHLIST] Error sending alert: {e}")

def load_job_progress():
    """Load job progress data"""
    if os.path.exists(JOB_PROGRESS_FILE):
        try:
            with open(JOB_PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_job_progress(data):
    """Save job progress data (atomic write with Windows retry for file locking)"""
    os.makedirs(os.path.dirname(JOB_PROGRESS_FILE), exist_ok=True)
    import tempfile, time
    dir_name = os.path.dirname(JOB_PROGRESS_FILE)
    fd, tmp_path = tempfile.mkstemp(suffix='.tmp', dir=dir_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        # Retry os.replace up to 5 times - Windows fails if another process has the file open
        for attempt in range(5):
            try:
                os.replace(tmp_path, JOB_PROGRESS_FILE)
                return
            except PermissionError:
                if attempt < 4:
                    time.sleep(0.1 * (attempt + 1))
                else:
                    raise
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

def update_job_progress(job_id, updates):
    """Update progress for a specific job"""
    if not job_id:
        return
    progress_data = load_job_progress()
    if job_id in progress_data:
        progress_data[job_id].update(updates)
        progress_data[job_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_job_progress(progress_data)

join_times = load_join_times()

@bot.event
async def on_member_join(member):
    # Check if user is on watchlist
    watched = get_watched_user(member.id)
    if watched:
        alert_level = watched.get('alert_level', 'normal')
        log_watchlist_activity(member.id, 'join', f"Joined the server")
        await send_watchlist_alert(
            member, 
            'join', 
            f"User joined the server", 
            alert_level
        )
    
    setup_channel = bot.get_channel(SETUP_CHANNEL_ID)
    if setup_channel is None:
        try:
            setup_channel = await bot.fetch_channel(SETUP_CHANNEL_ID)
        except Exception as e:
            print(f"[ERROR] Could not fetch setup channel: {e}")
            return
    if setup_channel:
        embed = discord.Embed(
            title="👋 Welcome to PNW Esports!",
            description=f"{member.mention}, Welcome to the **PNW Esports Discord Server**!\n\nTo get started, please complete your onboarding by choosing one of the options below.\nFailure to do so will result in Removal from the Discord Server for having an incomplete account.",
            color=discord.Color.yellow()
        )
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        embed.set_footer(text="PNW Esports | #RoarPRIDE")
        try:
            msg = await setup_channel.send(content=f"{member.mention}", embed=embed, view=SetupView(bot))
            welcome_messages[member.id] = msg  # Store the message for later removal
        except Exception as e:
            print(f"[ERROR] Could not send welcome message: {e}")
    join_times[str(member.id)] = datetime.utcnow().isoformat()
    save_join_times(join_times)

# Call this function when a user completes registration (becomes guest or student)
async def remove_welcome_message(user_id):
    msg = welcome_messages.pop(user_id, None)
    if msg:
        try:
            await msg.delete()
        except Exception:
            pass

# Helper to be called from registration logic (DMs or welcome channel)
async def on_user_registration_complete(user_id):
    await remove_welcome_message(user_id)
    join_times.pop(str(user_id), None)
    save_join_times(join_times)

@bot.event
async def on_member_remove(member):
    # Remove user from completed setup tracking so they can redo setup if they rejoin
    if hasattr(SetupView, "selection_made"):
        SetupView.selection_made.discard(member.id)
    # Remove welcome message if user leaves before registering
    await remove_welcome_message(member.id)
    join_times.pop(str(member.id), None)
    save_join_times(join_times)

# Watchlist message tracking - track when watched users send messages
@bot.event
async def on_message(message):
    # Ignore bot messages
    if message.author.bot:
        return
    
    # Check if user is on watchlist
    watched = get_watched_user(message.author.id)
    if watched:
        alert_level = watched.get('alert_level', 'normal')
        # Only alert on messages for normal and high alert levels
        if alert_level in ['normal', 'high']:
            channel_name = message.channel.name if hasattr(message.channel, 'name') else 'DM'
            content_preview = message.content[:100] + '...' if len(message.content) > 100 else message.content
            log_watchlist_activity(
                message.author.id, 
                'message', 
                f"Sent message in #{channel_name}: {content_preview}"
            )
            # Only send immediate alerts for high priority
            if alert_level == 'high':
                await send_watchlist_alert(
                    message.author,
                    'message',
                    f"Sent message in {message.channel.mention}:\n> {content_preview}",
                    alert_level
                )

# Watchlist voice tracking - track when watched users join voice channels
@bot.event
async def on_voice_state_update(member, before, after):
    # Ignore bots
    if member.bot:
        return
    
    # Check if user is on watchlist
    watched = get_watched_user(member.id)
    if watched:
        alert_level = watched.get('alert_level', 'normal')
        
        # User joined a voice channel
        if before.channel is None and after.channel is not None:
            log_watchlist_activity(
                member.id,
                'voice_join',
                f"Joined voice channel: {after.channel.name}"
            )
            await send_watchlist_alert(
                member,
                'voice_join',
                f"Joined voice channel: **{after.channel.name}**",
                alert_level
            )
        
        # User left a voice channel
        elif before.channel is not None and after.channel is None:
            log_watchlist_activity(
                member.id,
                'voice_leave',
                f"Left voice channel: {before.channel.name}"
            )
        
        # User moved channels
        elif before.channel != after.channel and before.channel is not None and after.channel is not None:
            log_watchlist_activity(
                member.id,
                'voice_join',
                f"Moved from {before.channel.name} to {after.channel.name}"
            )
            # Alert for channel moves on high priority
            if alert_level == 'high':
                await send_watchlist_alert(
                    member,
                    'voice_join',
                    f"Moved voice channels: **{before.channel.name}** → **{after.channel.name}**",
                    alert_level
                )

@tasks.loop(minutes=1)
async def check_for_timeouts():
    from datetime import timezone
    now = datetime.now(timezone.utc)
    timeout_duration = timedelta(minutes=1)
    for user_id, start_time in list(pending_users.items()):
        if now - start_time > timeout_duration:
            user = bot.get_user(user_id)
            if user:
                try:
                    embed = discord.Embed(
                        title="⚠️ Setup Reminder",
                        description="You started setting up your account, but it looks like you didn’t finish.\n\nPlease go back to the server and complete your setup.",
                        color=discord.Color.orange()
                    )
                    embed.set_footer(text="PNW Esports | Reminder")
                    await user.send(embed=embed)
                except discord.Forbidden:
                    print(f"Could not DM user {user_id}")
            del pending_users[user_id]


@tasks.loop(minutes=1)
async def arena_status_loop():
    await update_arena_status(bot)

# Dashboard sync - write bot status and members cache (using absolute paths)
BOT_STATUS_FILE = os.path.join(DATA_DIR, "bot_status.json")
MEMBERS_CACHE_FILE = os.path.join(DATA_DIR, "members_cache.json")
ROLES_CACHE_FILE = os.path.join(DATA_DIR, "roles_cache.json")
MODERATION_QUEUE_FILE = os.path.join(DATA_DIR, "moderation_queue.json")
BOT_CONTROL_FILE = os.path.join(DATA_DIR, "bot_control.json")
BOT_PID_FILE = os.path.join(DATA_DIR, "bot.pid")
DISCORD_NOTIFICATION_QUEUE_FILE = os.path.join(DATA_DIR, "discord_notification_queue.json")
LIVE_NOTIFICATIONS_FILE = os.path.join(DATA_DIR, "live_notifications.json")

def add_bot_live_notification(notif_type, title, message, link=None, target_id=None, target_name=None):
    """Add a live notification that will appear in the dashboard bell (called from bot)"""
    try:
        # Load existing notifications
        if os.path.exists(LIVE_NOTIFICATIONS_FILE):
            with open(LIVE_NOTIFICATIONS_FILE, 'r', encoding='utf-8') as f:
                notifications = json.load(f)
        else:
            notifications = {"notifications": [], "last_cleared": None}
        
        notification = {
            "id": f"notif_{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(4).hex()}",
            "type": notif_type,  # warning, info, registration, error, success, ticket
            "title": title,
            "message": message,
            "link": link,
            "target_id": str(target_id) if target_id else None,
            "target_name": target_name,  # Username or identifier for who this is about
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "read": False
        }
        
        # Add to beginning of list
        notifications["notifications"].insert(0, notification)
        
        # Keep only last 100 notifications
        notifications["notifications"] = notifications["notifications"][:100]
        
        safe_json_dump(notifications, LIVE_NOTIFICATIONS_FILE, indent=2, default=str)
        
        print(f"[LIVE NOTIFICATION] Added: {title}")
        return notification
    except Exception as e:
        print(f"[ERROR] Failed to add live notification: {e}")
        return None

# Write PID file on startup
def write_pid_file():
    """Write current process ID to file for dashboard bot control"""
    try:
        os.makedirs(os.path.dirname(BOT_PID_FILE), exist_ok=True)
        with open(BOT_PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        print(f"[STARTUP] PID file written: {os.getpid()}")
    except Exception as e:
        print(f"[ERROR] Failed to write PID file: {e}")

def cleanup_pid_file():
    """Remove PID file on shutdown"""
    try:
        if os.path.exists(BOT_PID_FILE):
            os.remove(BOT_PID_FILE)
    except:
        pass

@tasks.loop(seconds=5)
async def check_bot_control():
    """Check for control commands from dashboard"""
    try:
        if not os.path.exists(BOT_CONTROL_FILE):
            return
            
        with open(BOT_CONTROL_FILE, 'r', encoding='utf-8') as f:
            control_data = json.load(f)
        
        command = control_data.get('command')
        requested_at = control_data.get('requested_at', '')
        
        # Only process recent commands (within last 30 seconds)
        if requested_at:
            try:
                req_time = datetime.fromisoformat(requested_at.replace('Z', '+00:00'))
                age = (datetime.now(timezone.utc) - req_time).total_seconds()
                if age > 30:
                    return  # Ignore old commands
            except:
                pass
        
        if command == 'restart':
            print("[CONTROL] Restart command received from dashboard")
            # Clear the command file
            os.remove(BOT_CONTROL_FILE)
            cleanup_pid_file()
            # Close the bot and restart using os.execv (same as /restart_service command)
            await bot.close()
            os.execv(sys.executable, ['python'] + sys.argv)
            
        elif command == 'stop':
            print("[CONTROL] Stop command received from dashboard")
            # Clear the command file
            os.remove(BOT_CONTROL_FILE)
            cleanup_pid_file()
            # Close the bot
            await bot.close()
            
    except Exception as e:
        print(f"[ERROR] Failed to check bot control: {e}")

@tasks.loop(seconds=10)
async def process_discord_notifications():
    """Process Discord notification queue from dashboard (varsity approvals/denials, etc.)"""
    try:
        if not os.path.exists(DISCORD_NOTIFICATION_QUEUE_FILE):
            return
        
        with open(DISCORD_NOTIFICATION_QUEUE_FILE, 'r', encoding='utf-8-sig') as f:
            notifications = json.load(f)
        
        if not notifications:
            return
        
        # Count pending notifications
        pending_count = sum(1 for n in notifications if n.get('status') == 'pending')
        if pending_count > 0:
            print(f"[NOTIFICATION QUEUE] Processing {pending_count} pending notification(s)...")
        
        processed_any = False
        
        for notif in notifications:
            if notif.get('status') != 'pending':
                continue
            
            notif_type = notif.get('type')
            print(f"[NOTIFICATION QUEUE] Processing: {notif_type}")
            
            try:
                # Handle notification types that don't require a single user_id first
                if notif_type == 'team_announcement':
                    # Send beautiful team announcement DMs
                    if notif.get('send_discord_dm'):
                        from views.varsity_view import load_teams
                        
                        title = notif.get('title', 'Team Announcement')
                        message = notif.get('message', '')
                        priority = notif.get('priority', 'normal')
                        team_id = notif.get('team_id', 'all')
                        player_ids = notif.get('player_ids', [])
                        
                        # Get team info for display
                        team_name = "All Teams"
                        team_game = None
                        if team_id and team_id != 'all':
                            teams_data = load_teams()
                            team = next((t for t in teams_data.get("teams", []) if t.get("id") == team_id), None)
                            if team:
                                team_name = team.get('name', 'Unknown Team')
                                team_game = team.get('game')
                        
                        # Priority styling
                        priority_config = {
                            'low': {'color': 0x808080, 'emoji': '📋', 'label': 'Low Priority'},
                            'normal': {'color': 0xFFD700, 'emoji': '📢', 'label': 'Announcement'},
                            'high': {'color': 0xFF8C00, 'emoji': '⚠️', 'label': 'Important'},
                            'urgent': {'color': 0xFF0000, 'emoji': '🚨', 'label': 'URGENT'}
                        }
                        config = priority_config.get(priority, priority_config['normal'])
                        
                        sent_count = 0
                        failed_count = 0
                        
                        for player_id in player_ids:
                            try:
                                ann_user = bot.get_user(int(player_id))
                                if not ann_user:
                                    ann_user = await bot.fetch_user(int(player_id))
                                
                                if ann_user:
                                    # Create beautiful announcement embed
                                    embed = discord.Embed(
                                        title=f"{config['emoji']} {title}",
                                        description=f"━━━━━━━━━━━━━━━━━━━━━━\n\n{message}\n\n━━━━━━━━━━━━━━━━━━━━━━",
                                        color=config['color'],
                                        timestamp=datetime.now(timezone.utc)
                                    )
                                    
                                    # Header with team info
                                    if team_game:
                                        embed.set_author(
                                            name=f"🎮 {team_name} • {team_game}",
                                            icon_url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png"
                                        )
                                    else:
                                        embed.set_author(
                                            name=f"📣 {team_name}",
                                            icon_url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png"
                                        )
                                    
                                    # Add priority badge for high/urgent
                                    if priority in ['high', 'urgent']:
                                        embed.add_field(
                                            name="📌 Priority Level",
                                            value=f"**{config['label'].upper()}**",
                                            inline=True
                                        )
                                    
                                    # Add team info field
                                    embed.add_field(
                                        name="🏆 Team",
                                        value=team_name,
                                        inline=True
                                    )
                                    
                                    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
                                    embed.set_footer(
                                        text="PNW Esports | Team Communication",
                                        icon_url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png"
                                    )
                                    
                                    await ann_user.send(embed=embed)
                                    sent_count += 1
                            except discord.Forbidden:
                                failed_count += 1
                            except Exception as e:
                                failed_count += 1
                                print(f"[ANNOUNCEMENT] Failed to DM {player_id}: {e}")
                        
                        print(f"[ANNOUNCEMENT] Sent '{title}' to {sent_count} players ({failed_count} failed)")
                        
                        # Send live notification if there were any failures
                        if failed_count > 0:
                            add_bot_live_notification(
                                notif_type="warning",
                                title="Team Announcement Partial Failure",
                                message=f"Sent '{title}' to {sent_count} players, but {failed_count} failed (DMs disabled).",
                                link="/rosters"
                            )
                    
                    notif['status'] = 'sent'
                    processed_any = True
                    continue
                
                elif notif_type == 'bulk_dm':
                    # Send bulk DM to players with beautiful styling
                    title = notif.get('title', 'Team Message')
                    message = notif.get('message', '')
                    player_ids = notif.get('player_ids', [])
                    
                    sent_count = 0
                    failed_count = 0
                    
                    for player_id in player_ids:
                        try:
                            dm_user = bot.get_user(int(player_id))
                            if not dm_user:
                                dm_user = await bot.fetch_user(int(player_id))
                            
                            if dm_user:
                                embed = discord.Embed(
                                    title=f"💬 {title}",
                                    description=f"━━━━━━━━━━━━━━━━━━━━━━\n\n{message}\n\n━━━━━━━━━━━━━━━━━━━━━━",
                                    color=discord.Color.gold(),
                                    timestamp=datetime.now(timezone.utc)
                                )
                                embed.set_author(
                                    name="PNW Esports Team Message",
                                    icon_url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png"
                                )
                                embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
                                embed.set_footer(
                                    text="PNW Esports | #RoarPRIDE",
                                    icon_url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png"
                                )
                                
                                await dm_user.send(embed=embed)
                                sent_count += 1
                        except discord.Forbidden:
                            failed_count += 1
                        except Exception:
                            failed_count += 1
                    
                    print(f"[BULK_DM] Sent '{title}' to {sent_count} players ({failed_count} failed)")
                    
                    # Send live notification if there were any failures
                    if failed_count > 0:
                        add_bot_live_notification(
                            notif_type="warning",
                            title="Bulk DM Partial Failure",
                            message=f"Sent '{title}' to {sent_count} players, but {failed_count} failed (DMs disabled).",
                            link="/rosters"
                        )
                    
                    notif['status'] = 'sent'
                    processed_any = True
                    continue
                
                # For other notification types that require a single user_id
                user_id = notif.get('user_id')
                user = bot.get_user(int(user_id)) if user_id else None
                if user_id and not user:
                    user = await bot.fetch_user(int(user_id))
                
                if notif_type == 'varsity_approved':
                    player_type = notif.get('player_type', 'varsity')
                    type_display = player_type.replace('_', ' ').title()
                    
                    embed = discord.Embed(
                        title=f"✅ {type_display} Registration Approved",
                        description=(
                            f"Congratulations! Your **{type_display}** registration information was **approved** by the Admin Team.\n\n"
                            "A recruiter will be in contact with you shortly to discuss next steps and welcome you to the program."
                        ),
                        color=discord.Color.green()
                    )
                    embed.set_footer(text="PNW Esports | Registration")
                    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
                    
                    try:
                        await user.send(embed=embed)
                        print(f"[NOTIFICATION] Sent {type_display} approval to {user_id}")
                    except discord.Forbidden:
                        print(f"[NOTIFICATION] FAILED to send approval to {user_id} - DMs are closed")
                        user_display = f"{user.display_name} ({user.name})" if user else f"User {user_id}"
                        add_bot_live_notification(
                            notif_type="warning",
                            title="Approval DM Failed",
                            message=f"Could not send {type_display} approval notification. User has DMs disabled.",
                            link=f"/members?search={user_id}",
                            target_id=user_id,
                            target_name=user_display
                        )
                    except discord.HTTPException as e:
                        print(f"[NOTIFICATION] FAILED to send approval to {user_id} - HTTP error: {e}")
                        user_display = f"{user.display_name} ({user.name})" if user else f"User {user_id}"
                        add_bot_live_notification(
                            notif_type="error",
                            title="Approval DM Failed",
                            message=f"Could not send {type_display} approval due to Discord error.",
                            link=f"/members?search={user_id}",
                            target_id=user_id,
                            target_name=user_display
                        )
                    
                    # Assign Esports Team role if requested
                    if notif.get('assign_role'):
                        try:
                            from views.varsity_view import load_json_file
                            role_settings_file = os.path.join(DATA_DIR, "team_role_settings.json")
                            role_settings = load_json_file(role_settings_file, {})
                            esports_role_id = role_settings.get("varsity_role_id")
                            
                            if esports_role_id:
                                guild = bot.get_guild(GUILD_ID)
                                if guild:
                                    member = guild.get_member(int(user_id))
                                    if member:
                                        esports_role = guild.get_role(int(esports_role_id))
                                        if esports_role and esports_role not in member.roles:
                                            await member.add_roles(esports_role, reason="Varsity registration approved via dashboard")
                                            print(f"[NOTIFICATION] Added Esports Team role to {member}")
                        except Exception as role_exc:
                            print(f"[NOTIFICATION] Error adding role: {role_exc}")
                    
                    notif['status'] = 'sent'
                    processed_any = True
                
                elif notif_type == 'varsity_denied':
                    reason = notif.get('reason', 'No reason provided')
                    embed = discord.Embed(
                        title="❌ Registration Denied",
                        description="Your registration was **Denied**.",
                        color=discord.Color.red()
                    )
                    embed.add_field(name="**Reason** (Message from Admin)", value=reason, inline=False)
                    embed.set_footer(text="PNW Esports | Registration")
                    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
                    
                    try:
                        await user.send(embed=embed)
                        print(f"[NOTIFICATION] Sent varsity denial to {user_id}")
                    except discord.Forbidden:
                        print(f"[NOTIFICATION] FAILED to send denial to {user_id} - DMs are closed")
                        user_display = f"{user.display_name} ({user.name})" if user else f"User {user_id}"
                        add_bot_live_notification(
                            notif_type="warning",
                            title="Denial DM Failed",
                            message="Could not send varsity denial notification. User has DMs disabled.",
                            link=f"/members?search={user_id}",
                            target_id=user_id,
                            target_name=user_display
                        )
                    except discord.HTTPException as e:
                        print(f"[NOTIFICATION] FAILED to send denial to {user_id} - HTTP error: {e}")
                        user_display = f"{user.display_name} ({user.name})" if user else f"User {user_id}"
                        add_bot_live_notification(
                            notif_type="error",
                            title="Denial DM Failed",
                            message="Could not send varsity denial due to Discord error.",
                            link=f"/members?search={user_id}",
                            target_id=user_id,
                            target_name=user_display
                        )
                    
                    notif['status'] = 'sent'
                    processed_any = True
                
                elif notif_type == 'send_varsity_registration':
                    # Import the varsity view to send registration
                    from views.varsity_view import VarsityRegistrationView, PLAYER_TYPE_DISPLAY, add_pending_registration
                    
                    player_type = notif.get('player_type', 'varsity')
                    job_id = notif.get('job_id')  # Optional job ID for tracking status
                    team_name = PLAYER_TYPE_DISPLAY.get(player_type, player_type.replace('_', ' ').title())
                    
                    # Get the bot user as the "admin" who requested this
                    admin_user = bot.user
                    
                    view = VarsityRegistrationView(requested_by=admin_user, player_type=player_type, user_id=user_id)
                    embed = discord.Embed(
                        title="Welcome to PNW Esports",
                        description=(
                            f"**You have been selected to join the {team_name} team for PNW Esports!**\n\n"
                            "PNW Esports is home to the elite and victorious. Please complete your registration below to finalize your onboarding.\n\n"
                            "We are excited to have you as part of our competitive family. Good luck and Roar Pride!"
                        ),
                        color=discord.Color.gold()
                    )
                    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
                    embed.set_footer(text="PNW Esports | Registration")
                    
                    try:
                        sent_msg = await user.send(embed=embed, view=view)
                        # Track the pending registration for persistence
                        add_pending_registration(user_id, player_type, str(sent_msg.id))
                        print(f"[NOTIFICATION] Sent {team_name} registration to {user_id}")
                        notif['status'] = 'sent'
                        notif['dm_status'] = 'success'
                        # Store username for success feedback
                        user_display = user.display_name if user else f"User {user_id}"
                        notif['dm_username'] = user_display
                        notif['dm_team'] = team_name
                        # Send live notification to dashboard for success
                        add_bot_live_notification(
                            notif_type="success",
                            title="Registration Sent Successfully",
                            message=f"{team_name} registration sent to {user_display}",
                            link=f"/members?search={user_id}",
                            target_id=user_id,
                            target_name=user_display
                        )
                    except discord.Forbidden:
                        # User has DMs disabled or blocked the bot
                        print(f"[NOTIFICATION] FAILED to send registration to {user_id} - DMs are closed")
                        notif['status'] = 'dm_failed'
                        notif['dm_status'] = 'failed'
                        notif['dm_error'] = 'User has DMs disabled or has blocked the bot'
                        # Send live notification to dashboard with username
                        user_display = f"{user.display_name} ({user.name})" if user else f"User {user_id}"
                        add_bot_live_notification(
                            notif_type="warning",
                            title="Registration DM Failed",
                            message=f"Could not send {team_name} registration. User has DMs disabled or blocked the bot.",
                            link=f"/members?search={user_id}",
                            target_id=user_id,
                            target_name=user_display
                        )
                    except discord.HTTPException as e:
                        print(f"[NOTIFICATION] FAILED to send registration to {user_id} - HTTP error: {e}")
                        notif['status'] = 'dm_failed'
                        notif['dm_status'] = 'failed'
                        notif['dm_error'] = f'Discord API error: {str(e)}'
                        # Send live notification to dashboard with username
                        user_display = f"{user.display_name} ({user.name})" if user else f"User {user_id}"
                        add_bot_live_notification(
                            notif_type="error",
                            title="Registration Failed",
                            message=f"Could not send {team_name} registration due to Discord API error.",
                            link=f"/members?search={user_id}",
                            target_id=user_id,
                            target_name=user_display
                        )
                    
                    processed_any = True
                
                elif notif_type == 'ticket_blacklist_add':
                    # Add user to ticket blacklist
                    from utils.constants import ticket_blacklist
                    ticket_blacklist.add(int(user_id))
                    print(f"[NOTIFICATION] Added user {user_id} to ticket blacklist")
                    notif['status'] = 'sent'
                    processed_any = True
                
                elif notif_type == 'ticket_blacklist_remove':
                    # Remove user from ticket blacklist
                    from utils.constants import ticket_blacklist
                    ticket_blacklist.discard(int(user_id))
                    print(f"[NOTIFICATION] Removed user {user_id} from ticket blacklist")
                    notif['status'] = 'sent'
                    processed_any = True
                
                elif notif_type == 'close_ticket':
                    # Close ticket channel from dashboard
                    channel_name = notif.get('channel_name')
                    close_reason = notif.get('reason', 'Closed from dashboard')
                    closed_by = notif.get('closed_by', 'Dashboard')
                    
                    guild = bot.get_guild(GUILD_ID)
                    if guild:
                        # Find the ticket channel
                        ticket_channel = discord.utils.get(guild.text_channels, name=channel_name)
                        if ticket_channel:
                            # Send closing message
                            embed = discord.Embed(
                                title="🎫 Ticket Closed",
                                description=f"This ticket has been closed remotely from the dashboard.",
                                color=discord.Color.red(),
                                timestamp=datetime.now(timezone.utc)
                            )
                            embed.add_field(name="Closed By", value=closed_by, inline=True)
                            embed.add_field(name="Reason", value=close_reason, inline=True)
                            embed.set_footer(text="PNW Esports | Support System")
                            
                            await ticket_channel.send(embed=embed)
                            await asyncio.sleep(3)
                            
                            # Delete the channel
                            await ticket_channel.delete(reason=f"Closed from dashboard: {close_reason}")
                            print(f"[NOTIFICATION] Closed ticket channel {channel_name}")
                        else:
                            print(f"[NOTIFICATION] Ticket channel {channel_name} not found")
                    
                    notif['status'] = 'sent'
                    processed_any = True
                
                elif notif_type == 'ticket_message':
                    # Send message to ticket channel from dashboard
                    channel_name = notif.get('channel_name')
                    message = notif.get('message', '')
                    mention_user = notif.get('mention_user', True)
                    ticket_user_id = notif.get('user_id')
                    sender = notif.get('sender', 'Dashboard Admin')
                    
                    guild = bot.get_guild(GUILD_ID)
                    if guild and channel_name and message:
                        ticket_channel = discord.utils.get(guild.text_channels, name=channel_name)
                        if ticket_channel:
                            # Create a nice embed for the message
                            embed = discord.Embed(
                                description=message,
                                color=discord.Color.blue(),
                                timestamp=datetime.now(timezone.utc)
                            )
                            embed.set_author(name=f"📩 Message from {sender}", icon_url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
                            embed.set_footer(text="PNW Esports | Dashboard Message")
                            
                            # Send with optional mention
                            content = f"<@{ticket_user_id}>" if mention_user and ticket_user_id else None
                            await ticket_channel.send(content=content, embed=embed)
                            print(f"[NOTIFICATION] Sent message to ticket channel {channel_name}")
                        else:
                            print(f"[NOTIFICATION] Ticket channel {channel_name} not found for message")
                    
                    notif['status'] = 'sent'
                    processed_any = True
                
                elif notif_type == 'ticket_assign':
                    # Send assignment notification to ticket channel
                    channel_name = notif.get('channel_name')
                    assigned_to = notif.get('assigned_to', 'Staff')
                    ticket_user_id = notif.get('user_id')
                    
                    guild = bot.get_guild(GUILD_ID)
                    if guild and channel_name:
                        ticket_channel = discord.utils.get(guild.text_channels, name=channel_name)
                        if ticket_channel:
                            embed = discord.Embed(
                                title="✋ Ticket Assigned",
                                description=f"**{assigned_to}** has taken this ticket and will assist you shortly.",
                                color=discord.Color.green(),
                                timestamp=datetime.now(timezone.utc)
                            )
                            embed.set_footer(text="PNW Esports | Support System")
                            
                            # Notify the user
                            content = f"<@{ticket_user_id}>" if ticket_user_id else None
                            await ticket_channel.send(content=content, embed=embed)
                            print(f"[NOTIFICATION] Sent assignment notification to {channel_name}")
                        else:
                            print(f"[NOTIFICATION] Ticket channel {channel_name} not found for assignment")
                    
                    notif['status'] = 'sent'
                    processed_any = True
                
                elif notif_type == 'vc_kick_user':
                    # Kick user from voice channel
                    channel_id = int(notif.get('channel_id'))
                    vc_user_id = int(notif.get('user_id'))
                    reason = notif.get('reason', 'Kicked from dashboard')
                    
                    guild = bot.get_guild(GUILD_ID)
                    if guild:
                        channel = guild.get_channel(channel_id)
                        member = guild.get_member(vc_user_id)
                        if channel and member and member.voice and member.voice.channel == channel:
                            await member.move_to(None, reason=reason)
                            print(f"[VC] Kicked {member} from {channel.name}")
                    notif['status'] = 'sent'
                    processed_any = True
                
                elif notif_type == 'vc_lock':
                    # Lock/unlock voice channel
                    channel_id = int(notif.get('channel_id'))
                    lock = notif.get('lock', True)
                    
                    guild = bot.get_guild(GUILD_ID)
                    if guild:
                        channel = guild.get_channel(channel_id)
                        if channel and isinstance(channel, discord.VoiceChannel):
                            overwrites = channel.overwrites
                            if guild.default_role not in overwrites:
                                overwrites[guild.default_role] = discord.PermissionOverwrite()
                            overwrites[guild.default_role].connect = not lock
                            await channel.edit(overwrites=overwrites)
                            print(f"[VC] {'Locked' if lock else 'Unlocked'} {channel.name}")
                    notif['status'] = 'sent'
                    processed_any = True
                
                elif notif_type == 'vc_set_limit':
                    # Set user limit on voice channel
                    channel_id = int(notif.get('channel_id'))
                    limit = int(notif.get('limit', 0))
                    
                    guild = bot.get_guild(GUILD_ID)
                    if guild:
                        channel = guild.get_channel(channel_id)
                        if channel and isinstance(channel, discord.VoiceChannel):
                            await channel.edit(user_limit=limit)
                            print(f"[VC] Set limit to {limit} on {channel.name}")
                    notif['status'] = 'sent'
                    processed_any = True
                
                elif notif_type == 'vc_delete':
                    # Delete voice channel
                    channel_id = int(notif.get('channel_id'))
                    
                    guild = bot.get_guild(GUILD_ID)
                    if guild:
                        channel = guild.get_channel(channel_id)
                        if channel and isinstance(channel, discord.VoiceChannel):
                            await channel.delete(reason="Deleted from dashboard")
                            print(f"[VC] Deleted channel {channel.name}")
                    notif['status'] = 'sent'
                    processed_any = True
                
                elif notif_type == 'vc_move_user':
                    # Move user to another voice channel
                    vc_user_id = int(notif.get('user_id'))
                    target_channel_id = int(notif.get('target_channel_id'))
                    
                    guild = bot.get_guild(GUILD_ID)
                    if guild:
                        member = guild.get_member(vc_user_id)
                        target_channel = guild.get_channel(target_channel_id)
                        if member and target_channel and isinstance(target_channel, discord.VoiceChannel):
                            await member.move_to(target_channel)
                            print(f"[VC] Moved {member} to {target_channel.name}")
                    notif['status'] = 'sent'
                    processed_any = True
                
                elif notif_type == 'vc_rename':
                    # Rename voice channel
                    channel_id = int(notif.get('channel_id'))
                    new_name = notif.get('name', 'Renamed VC')
                    
                    guild = bot.get_guild(GUILD_ID)
                    if guild:
                        channel = guild.get_channel(channel_id)
                        if channel and isinstance(channel, discord.VoiceChannel):
                            old_name = channel.name
                            await channel.edit(name=new_name)
                            print(f"[VC] Renamed channel '{old_name}' to '{new_name}'")
                    notif['status'] = 'sent'
                    processed_any = True
                
                elif notif_type == 'vc_hide':
                    # Hide/unhide voice channel from @everyone
                    channel_id = int(notif.get('channel_id'))
                    hide = notif.get('hide', True)
                    
                    guild = bot.get_guild(GUILD_ID)
                    if guild:
                        channel = guild.get_channel(channel_id)
                        if channel and isinstance(channel, discord.VoiceChannel):
                            overwrites = channel.overwrites
                            if guild.default_role not in overwrites:
                                overwrites[guild.default_role] = discord.PermissionOverwrite()
                            overwrites[guild.default_role].view_channel = not hide
                            await channel.edit(overwrites=overwrites)
                            print(f"[VC] {'Hid' if hide else 'Unhid'} channel {channel.name}")
                    notif['status'] = 'sent'
                    processed_any = True
                
                elif notif_type == 'sync_team_roles':
                    # Sync team roles for a player when assigned from dashboard
                    from views.varsity_view import sync_player_roles, load_teams
                    
                    discord_id = notif.get('discord_id')
                    team_id = notif.get('team_id')
                    player_type = notif.get('player_type', 'varsity')
                    
                    guild = bot.get_guild(GUILD_ID)
                    if guild and discord_id and team_id:
                        member = guild.get_member(int(discord_id))
                        teams_data = load_teams()
                        team = next((t for t in teams_data.get("teams", []) if t.get("id") == team_id), None)
                        
                        if member and team:
                            success, added_roles = await sync_player_roles(guild, member, team, player_type)
                            if success and added_roles:
                                role_names = ", ".join([r.name for r in added_roles])
                                print(f"[TEAM ROLES] Synced roles for {member}: {role_names}")
                                
                                # Notify the player
                                try:
                                    embed = discord.Embed(
                                        title="🎮 Team Assignment",
                                        description=f"You have been assigned to **{team.get('name')}**!",
                                        color=discord.Color.gold()
                                    )
                                    embed.add_field(name="Game", value=team.get("game", "N/A"), inline=True)
                                    embed.add_field(name="Team Type", value=team.get("type", "varsity").title(), inline=True)
                                    if added_roles:
                                        embed.add_field(name="Roles Added", value=role_names, inline=False)
                                    embed.set_footer(text="PNW Esports | Team Assignment")
                                    await member.send(embed=embed)
                                except discord.Forbidden:
                                    pass
                            else:
                                print(f"[TEAM ROLES] Could not sync roles for {member} (success={success})")
                        else:
                            print(f"[TEAM ROLES] Member or team not found: member={member}, team={team}")
                    notif['status'] = 'sent'
                    processed_any = True
                
                elif notif_type == 'bulk_sync_team_roles':
                    # Bulk sync team roles from dashboard
                    job_id = notif.get('job_id')  # For progress tracking
                    players = notif.get('players', [])
                    role_mapping = notif.get('role_mapping', {})
                    general_varsity_role = notif.get('general_varsity_role')  # This is now the general roster role for ALL players
                    captain_role_id = notif.get('captain_role_id')  # Role for team captains
                    
                    print(f"[BULK SYNC] Starting sync for {len(players)} players (Job: {job_id})")
                    print(f"[BULK SYNC] Role mapping: {role_mapping}")
                    print(f"[BULK SYNC] Esports Team Role: {general_varsity_role}")
                    print(f"[BULK SYNC] Captain Role: {captain_role_id}")
                    
                    # Update job progress: starting
                    update_job_progress(job_id, {
                        "status": "running",
                        "current_step": "Initializing sync operation...",
                        "phase": "init"
                    })
                    
                    guild = bot.get_guild(GUILD_ID)
                    if not guild:
                        print(f"[BULK SYNC] ERROR: Guild {GUILD_ID} not found!")
                        notif['status'] = 'failed'
                        notif['error'] = 'Guild not found'
                        update_job_progress(job_id, {
                            "status": "failed",
                            "current_step": "Error: Guild not found",
                            "error": "Guild not found"
                        })
                        processed_any = True
                        continue
                    
                    print(f"[BULK SYNC] Found guild: {guild.name} with {guild.member_count} members")
                    update_job_progress(job_id, {
                        "current_step": f"Connected to {guild.name}",
                    })
                    
                    # Collect all role IDs that are team roles (for removal check)
                    team_role_ids = set()
                    for game, roles in role_mapping.items():
                        if roles.get('varsity'):
                            team_role_ids.add(int(roles['varsity']))
                        if roles.get('jv'):
                            team_role_ids.add(int(roles['jv']))
                    # General roster role applies to ALL players
                    if general_varsity_role:
                        team_role_ids.add(int(general_varsity_role))
                    # Captain role for captains
                    if captain_role_id:
                        team_role_ids.add(int(captain_role_id))
                    
                    print(f"[BULK SYNC] Team role IDs to manage: {team_role_ids}")
                    
                    # Verify all roles exist in the guild
                    for rid in team_role_ids:
                        role = guild.get_role(rid)
                        if role:
                            print(f"[BULK SYNC] Role {rid} found: {role.name}")
                        else:
                            print(f"[BULK SYNC] WARNING: Role {rid} NOT FOUND in guild!")
                    
                    # Build expected roles per player
                    expected_roles_by_user = {}
                    player_names = {}  # For progress display
                    for player in players:
                        user_id = player.get('user_id')
                        expected_roles = player.get('expected_roles', [])
                        player_names[user_id] = player.get('username', 'Unknown')
                        print(f"[BULK SYNC] Player {user_id} ({player.get('username', 'Unknown')}) expects roles: {expected_roles}")
                        if user_id not in expected_roles_by_user:
                            expected_roles_by_user[user_id] = set()
                        for role_id in expected_roles:
                            expected_roles_by_user[user_id].add(int(role_id))
                    
                    # Count members who have team roles (for removal phase)
                    members_to_check = 0
                    for member in guild.members:
                        for role in member.roles:
                            if role.id in team_role_ids:
                                members_to_check += 1
                                break
                    
                    # Calculate total operations (rough estimate)
                    total_add_operations = len(expected_roles_by_user)
                    total_operations = total_add_operations + members_to_check
                    
                    update_job_progress(job_id, {
                        "current_step": "Analyzing role changes needed...",
                        "total_operations": total_operations,
                        "phase": "analyzing"
                    })
                    
                    added_count = 0
                    removed_count = 0
                    skipped_count = 0  # Users already up-to-date
                    errors = []
                    completed_operations = 0
                    
                    # Rate limit tracking - Discord allows ~10 role changes per 10 seconds per guild
                    role_changes_made = 0
                    RATE_LIMIT_THRESHOLD = 8  # Stay under 10 to be safe
                    RATE_LIMIT_COOLDOWN = 11  # Wait 11 seconds after hitting threshold
                    
                    async def rate_limit_check():
                        """Check and wait if we're approaching rate limit"""
                        nonlocal role_changes_made
                        role_changes_made += 1
                        if role_changes_made >= RATE_LIMIT_THRESHOLD:
                            print(f"[BULK SYNC] Rate limit threshold reached ({role_changes_made} changes), cooling down for {RATE_LIMIT_COOLDOWN}s...")
                            # Update progress with cooldown info
                            cooldown_until = (datetime.now(timezone.utc) + timedelta(seconds=RATE_LIMIT_COOLDOWN)).isoformat()
                            update_job_progress(job_id, {
                                "rate_limit_cooldown": True,
                                "rate_limit_wait_until": cooldown_until,
                                "current_step": f"Rate limit cooldown ({RATE_LIMIT_COOLDOWN}s)..."
                            })
                            await asyncio.sleep(RATE_LIMIT_COOLDOWN)
                            role_changes_made = 0
                            update_job_progress(job_id, {
                                "rate_limit_cooldown": False,
                                "rate_limit_wait_until": None
                            })
                        else:
                            # Small delay between individual operations
                            await asyncio.sleep(1.0)
                    
                    # Phase 1: Add missing roles to players
                    update_job_progress(job_id, {
                        "current_step": "Phase 1: Adding roles to players...",
                        "phase": "adding"
                    })
                    
                    player_index = 0
                    total_players = len(expected_roles_by_user)
                    
                    for user_id, expected in expected_roles_by_user.items():
                        player_index += 1
                        player_name = player_names.get(user_id, 'Unknown')
                        
                        update_job_progress(job_id, {
                            "current_step": f"Adding roles ({player_index}/{total_players})",
                            "current_player": player_name,
                            "completed_operations": completed_operations,
                            "added_count": added_count,
                            "removed_count": removed_count
                        })
                        
                        try:
                            member = guild.get_member(int(user_id))
                            if not member:
                                # Try to fetch the member if not cached
                                try:
                                    member = await guild.fetch_member(int(user_id))
                                except discord.NotFound:
                                    print(f"[BULK SYNC] Member {user_id} not found in guild")
                                    errors.append(f"Member {user_id} not found in guild")
                                    completed_operations += 1
                                    continue
                                except Exception as fetch_err:
                                    print(f"[BULK SYNC] Error fetching member {user_id}: {fetch_err}")
                                    errors.append(f"Error fetching {user_id}: {str(fetch_err)}")
                                    completed_operations += 1
                                    continue
                            
                            current_role_ids = {role.id for role in member.roles}
                            print(f"[BULK SYNC] {member.display_name} current roles: {[r.name for r in member.roles if r.id in team_role_ids]}")
                            
                            # Add missing roles
                            roles_to_add = [guild.get_role(rid) for rid in expected if rid not in current_role_ids]
                            roles_to_add = [r for r in roles_to_add if r is not None]
                            
                            if roles_to_add:
                                await member.add_roles(*roles_to_add, reason="Dashboard bulk role sync")
                                added_count += len(roles_to_add)
                                print(f"[BULK SYNC] Added {[r.name for r in roles_to_add]} to {member.display_name}")
                                # Rate limit protection
                                await rate_limit_check()
                            else:
                                # User already has all expected roles - skip efficiently
                                skipped_count += 1
                                print(f"[BULK SYNC] ✓ SKIPPED {member.display_name} (already has all expected roles)")
                                # Update progress to show skipped status (no API call needed)
                                update_job_progress(job_id, {
                                    "current_step": f"✓ {player_name} already up-to-date (skipped)",
                                    "skipped_count": skipped_count
                                })
                            
                            completed_operations += 1
                            
                        except discord.HTTPException as e:
                            if e.status == 429:  # Rate limited
                                retry_after = getattr(e, 'retry_after', 10)
                                print(f"[BULK SYNC] Rate limited! Waiting {retry_after}s...")
                                cooldown_until = (datetime.now(timezone.utc) + timedelta(seconds=retry_after + 1)).isoformat()
                                update_job_progress(job_id, {
                                    "rate_limit_cooldown": True,
                                    "rate_limit_wait_until": cooldown_until,
                                    "current_step": f"Rate limited by Discord, waiting {retry_after}s..."
                                })
                                await asyncio.sleep(retry_after + 1)
                                update_job_progress(job_id, {
                                    "rate_limit_cooldown": False,
                                    "rate_limit_wait_until": None
                                })
                                # Retry the operation
                                try:
                                    await member.add_roles(*roles_to_add, reason="Dashboard bulk role sync (retry)")
                                    added_count += len(roles_to_add)
                                    print(f"[BULK SYNC] Retry successful: Added {[r.name for r in roles_to_add]} to {member.display_name}")
                                except Exception as retry_err:
                                    errors.append(f"Error adding roles for {user_id} (retry): {str(retry_err)}")
                            else:
                                print(f"[BULK SYNC] HTTP Error processing {user_id}: {str(e)}")
                                errors.append(f"Error adding roles for {user_id}: {str(e)}")
                            completed_operations += 1
                        except Exception as e:
                            print(f"[BULK SYNC] Error processing {user_id}: {str(e)}")
                            errors.append(f"Error adding roles for {user_id}: {str(e)}")
                            completed_operations += 1
                    
                    # Phase 2: Remove roles from users who shouldn't have them
                    # Only proceed with removal if user explicitly confirmed via checkbox
                    allow_removal = notif.get('allow_removal', False)
                    game_filter = notif.get('game_filter', 'all')
                    type_filter = notif.get('type_filter', 'all')
                    
                    # Determine which role IDs are in scope for removal
                    # If filtering by game, only remove that game's roles
                    # If filtering by type, only remove that type's roles
                    roles_in_scope = set()
                    
                    if game_filter == 'all' and type_filter == 'all':
                        # Full sync - all team roles are in scope
                        roles_in_scope = team_role_ids.copy()
                    else:
                        # Partial sync - only include roles matching the filter
                        for game, roles in role_mapping.items():
                            game_matches = (game_filter == 'all' or game.lower() == game_filter.lower())
                            if game_matches:
                                if type_filter == 'all' or type_filter == 'varsity':
                                    if roles.get('varsity'):
                                        roles_in_scope.add(int(roles['varsity']))
                                if type_filter == 'all' or type_filter == 'jv':
                                    if roles.get('jv'):
                                        roles_in_scope.add(int(roles['jv']))
                        
                        # Include general roles only if type matches
                        if type_filter == 'all' or type_filter == 'varsity':
                            if general_varsity_role:
                                roles_in_scope.add(int(general_varsity_role))
                        # General roster role also applies to JV since all roster players get it
                        if type_filter == 'all' or type_filter == 'jv':
                            if general_varsity_role:
                                roles_in_scope.add(int(general_varsity_role))
                        # Captain role is always in scope (captains can be varsity or JV)
                        if captain_role_id:
                            roles_in_scope.add(int(captain_role_id))
                    
                    print(f"[BULK SYNC] Roles in scope for removal (game={game_filter}, type={type_filter}): {roles_in_scope}")
                    
                    # ===== REMOVAL CHECK: Only proceed if user confirmed via checkbox =====
                    if not allow_removal:
                        # User did not check the confirmation box - skip removal phase
                        print(f"[BULK SYNC] Removal phase skipped - user did not confirm role removal")
                        update_job_progress(job_id, {
                            "current_step": "Role addition complete. Removal skipped (not confirmed).",
                            "phase": "removing",
                            "warning": "Role removal was skipped because the confirmation checkbox was not checked."
                        })
                    else:
                        # User confirmed - proceed with removal phase
                        print(f"[BULK SYNC] Removal confirmed by user, proceeding with removal phase")
                        
                        update_job_progress(job_id, {
                            "current_step": "Phase 2: Checking for roles to remove...",
                            "phase": "removing",
                            "current_player": None
                        })
                        
                        print(f"[BULK SYNC] Checking for roles to remove from other members...")
                        members_checked = 0
                        
                        for member in guild.members:
                            user_str = str(member.id)
                            expected = expected_roles_by_user.get(user_str, set())
                            
                            # Only check members who have a role that's in scope for this sync
                            has_in_scope_role = any(role.id in roles_in_scope for role in member.roles)
                            if has_in_scope_role:
                                members_checked += 1
                                if members_checked % 10 == 0:  # Update every 10 members
                                    update_job_progress(job_id, {
                                        "current_step": f"Checking members ({members_checked}/{members_to_check})",
                                        "completed_operations": completed_operations,
                                        "added_count": added_count,
                                        "removed_count": removed_count
                                    })
                            
                            for role in member.roles:
                                # Only remove if:
                                # 1. Role is in scope for this sync (matches game/type filter)
                                # 2. User is not expected to have this role
                                if role.id in roles_in_scope and role.id not in expected:
                                    try:
                                        update_job_progress(job_id, {
                                            "current_step": f"Removing {role.name} from {member.display_name}",
                                            "current_player": member.display_name
                                        })
                                        
                                        await member.remove_roles(role, reason="Dashboard bulk role sync - no longer on team")
                                        removed_count += 1
                                        completed_operations += 1
                                        print(f"[BULK SYNC] Removed {role.name} from {member.display_name}")
                                        # Rate limit protection
                                        await rate_limit_check()
                                    except discord.HTTPException as e:
                                        if e.status == 429:  # Rate limited
                                            retry_after = getattr(e, 'retry_after', 10)
                                            print(f"[BULK SYNC] Rate limited! Waiting {retry_after}s...")
                                            cooldown_until = (datetime.now(timezone.utc) + timedelta(seconds=retry_after + 1)).isoformat()
                                            update_job_progress(job_id, {
                                                "rate_limit_cooldown": True,
                                                "rate_limit_wait_until": cooldown_until,
                                                "current_step": f"Rate limited by Discord, waiting {retry_after}s..."
                                            })
                                            await asyncio.sleep(retry_after + 1)
                                            update_job_progress(job_id, {
                                                "rate_limit_cooldown": False,
                                                "rate_limit_wait_until": None
                                            })
                                            # Retry the operation
                                            try:
                                                await member.remove_roles(role, reason="Dashboard bulk role sync - no longer on team (retry)")
                                                removed_count += 1
                                                completed_operations += 1
                                                print(f"[BULK SYNC] Retry successful: Removed {role.name} from {member.display_name}")
                                            except Exception as retry_err:
                                                errors.append(f"Error removing {role.name} from {member} (retry): {str(retry_err)}")
                                        else:
                                            errors.append(f"Error removing {role.name} from {member}: {str(e)}")
                                    except Exception as e:
                                        errors.append(f"Error removing {role.name} from {member}: {str(e)}")
                    
                    # Job complete
                    if errors:
                        print(f"[BULK SYNC] Completed with {len(errors)} errors: {errors[:5]}")
                    
                    print(f"[BULK SYNC] Complete: Added {added_count} roles, Removed {removed_count} roles, Skipped {skipped_count} (already up-to-date)")
                    
                    # Final progress update
                    update_job_progress(job_id, {
                        "status": "completed",
                        "phase": "done",
                        "current_step": "Sync completed successfully!",
                        "current_player": None,
                        "completed_operations": completed_operations,
                        "added_count": added_count,
                        "removed_count": removed_count,
                        "skipped_count": skipped_count,
                        "errors": errors[:10],  # Keep first 10 errors
                        "error_count": len(errors),
                        "completed_at": datetime.now(timezone.utc).isoformat()
                    })
                    
                    notif['status'] = 'sent'
                    notif['result'] = {'added': added_count, 'removed': removed_count, 'errors': len(errors)}
                    processed_any = True
                
                elif notif_type == 'team_announcement':
                    # Send beautiful team announcement DMs
                    if notif.get('send_discord_dm'):
                        from views.varsity_view import load_teams
                        
                        title = notif.get('title', 'Team Announcement')
                        message = notif.get('message', '')
                        priority = notif.get('priority', 'normal')
                        category = notif.get('category', 'general')
                        team_id = notif.get('team_id', 'all')
                        player_ids = notif.get('player_ids', [])
                        image_url = notif.get('image_url')
                        link_text = notif.get('link_text')
                        link_url = notif.get('link_url')
                        
                        # Get team info for display
                        team_name = "All Teams"
                        team_game = None
                        if team_id and team_id != 'all':
                            teams_data = load_teams()
                            team = next((t for t in teams_data.get("teams", []) if t.get("id") == team_id), None)
                            if team:
                                team_name = team.get('name', 'Unknown Team')
                                team_game = team.get('game')
                        
                        # Priority styling
                        priority_config = {
                            'low': {'color': 0x6B7280, 'emoji': '📋', 'label': 'Informational'},
                            'normal': {'color': 0xFFD700, 'emoji': '📢', 'label': 'Announcement'},
                            'high': {'color': 0xFF8C00, 'emoji': '⚠️', 'label': 'Important'},
                            'urgent': {'color': 0xFF0000, 'emoji': '🚨', 'label': 'URGENT'}
                        }
                        config = priority_config.get(priority, priority_config['normal'])
                        
                        # Category icons
                        category_icons = {
                            'general': '📋',
                            'practice': '🎮',
                            'match': '⚔️',
                            'meeting': '📅',
                            'deadline': '⏰',
                            'roster': '👥',
                            'celebration': '🎉'
                        }
                        cat_icon = category_icons.get(category, '📋')
                        
                        sent_count = 0
                        failed_count = 0
                        
                        for player_id in player_ids:
                            try:
                                dm_user = bot.get_user(int(player_id))
                                if not dm_user:
                                    dm_user = await bot.fetch_user(int(player_id))
                                
                                if dm_user:
                                    # Create beautiful announcement embed
                                    embed = discord.Embed(
                                        title=f"{config['emoji']} {title}",
                                        description=f"━━━━━━━━━━━━━━━━━━━━━━\n\n{message}\n\n━━━━━━━━━━━━━━━━━━━━━━",
                                        color=config['color'],
                                        timestamp=datetime.now(timezone.utc)
                                    )
                                    
                                    # Header with team info
                                    if team_game:
                                        embed.set_author(
                                            name=f"🎮 {team_name} • {team_game}",
                                            icon_url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png"
                                        )
                                    else:
                                        embed.set_author(
                                            name=f"📣 {team_name}",
                                            icon_url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png"
                                        )
                                    
                                    # Add priority badge for high/urgent
                                    if priority in ['high', 'urgent']:
                                        embed.add_field(
                                            name="📌 Priority",
                                            value=f"**{config['label'].upper()}**",
                                            inline=True
                                        )
                                    
                                    # Add category field
                                    embed.add_field(
                                        name=f"{cat_icon} Category",
                                        value=category.title(),
                                        inline=True
                                    )
                                    
                                    # Add link if provided
                                    if link_text and link_url:
                                        embed.add_field(
                                            name="🔗 Link",
                                            value=f"[{link_text}]({link_url})",
                                            inline=True
                                        )
                                    
                                    # Add image if provided
                                    if image_url:
                                        embed.set_image(url=image_url)
                                    
                                    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
                                    embed.set_footer(
                                        text="PNW Esports | Team Communication",
                                        icon_url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png"
                                    )
                                    
                                    await dm_user.send(embed=embed)
                                    sent_count += 1
                            except discord.Forbidden:
                                failed_count += 1
                            except Exception as e:
                                failed_count += 1
                                print(f"[ANNOUNCEMENT] Failed to DM {player_id}: {e}")
                        
                        print(f"[ANNOUNCEMENT] Sent '{title}' to {sent_count} players ({failed_count} failed)")
                    
                    notif['status'] = 'sent'
                    processed_any = True
                
                elif notif_type == 'bulk_dm':
                    # Send bulk DM to players with beautiful styling
                    title = notif.get('title', 'Team Message')
                    message = notif.get('message', '')
                    player_ids = notif.get('player_ids', [])
                    
                    sent_count = 0
                    failed_count = 0
                    
                    for player_id in player_ids:
                        try:
                            dm_user = bot.get_user(int(player_id))
                            if not dm_user:
                                dm_user = await bot.fetch_user(int(player_id))
                            
                            if dm_user:
                                embed = discord.Embed(
                                    title=f"💬 {title}",
                                    description=f"━━━━━━━━━━━━━━━━━━━━━━\n\n{message}\n\n━━━━━━━━━━━━━━━━━━━━━━",
                                    color=discord.Color.gold(),
                                    timestamp=datetime.now(timezone.utc)
                                )
                                embed.set_author(
                                    name="PNW Esports Team Message",
                                    icon_url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png"
                                )
                                embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
                                embed.set_footer(
                                    text="PNW Esports | #RoarPRIDE",
                                    icon_url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png"
                                )
                                
                                await dm_user.send(embed=embed)
                                sent_count += 1
                        except discord.Forbidden:
                            failed_count += 1
                        except Exception:
                            failed_count += 1
                    
                    print(f"[BULK_DM] Sent '{title}' to {sent_count} players ({failed_count} failed)")
                    notif['status'] = 'sent'
                    processed_any = True
                
                elif notif_type == 'bot_activity':
                    # Update bot activity/presence from dashboard
                    activity_text = notif.get('activity')
                    status_type = notif.get('status', 'online')
                    
                    try:
                        if activity_text:
                            # Set custom activity
                            activity = discord.Activity(
                                type=discord.ActivityType.playing,
                                name=activity_text
                            )
                            await bot.change_presence(activity=activity)
                            print(f"[BOT] Activity set to: {activity_text}")
                        else:
                            # Reset to default (arena status or default)
                            from utils.arena_status import get_arena_status_message
                            try:
                                arena_msg = await get_arena_status_message()
                                activity = discord.Activity(
                                    type=discord.ActivityType.watching,
                                    name=arena_msg
                                )
                            except:
                                activity = discord.Activity(
                                    type=discord.ActivityType.watching,
                                    name="PNW Esports"
                                )
                            await bot.change_presence(activity=activity)
                            print(f"[BOT] Activity reset to default")
                        
                        notif['status'] = 'sent'
                        processed_any = True
                    except Exception as e:
                        print(f"[BOT] Failed to update activity: {e}")
                        notif['status'] = 'failed'
                        notif['error'] = str(e)
                        processed_any = True
                
                elif notif_type == 'bot_restart':
                    # Restart the bot from dashboard
                    print(f"[BOT] Restart requested by {notif.get('requested_by', 'Dashboard')}")
                    notif['status'] = 'sent'
                    processed_any = True
                    
                    # Save the queue before restarting
                    safe_json_dump(notifications, DISCORD_NOTIFICATION_QUEUE_FILE, indent=2)
                    
                    # Close the bot and restart (os and sys are already imported at top)
                    await bot.close()
                    os.execv(sys.executable, [sys.executable] + sys.argv)
                
                elif notif_type == 'bot_stop':
                    # Stop the bot from dashboard
                    print(f"[BOT] Stop requested by {notif.get('requested_by', 'Dashboard')}")
                    notif['status'] = 'sent'
                    processed_any = True
                    
                    # Save the queue before stopping
                    safe_json_dump(notifications, DISCORD_NOTIFICATION_QUEUE_FILE, indent=2)
                    
                    # Close the bot
                    await bot.close()
                    import sys
                    sys.exit(0)
                
                elif notif_type == 'warn_user':
                    # Send warning DM to user from dashboard
                    user_id = notif.get('user_id')
                    reason = notif.get('reason', 'No reason provided')
                    moderator = notif.get('moderator', 'Dashboard')
                    
                    try:
                        user = await bot.fetch_user(int(user_id))
                        if user:
                            embed = discord.Embed(
                                title="⚠️ Official Warning",
                                description=(
                                    f"Dear {user.mention},\n\n"
                                    f"You have received an official warning from the **PNW eSports** moderation team.\n\n"
                                    f"**Reason:** {reason}\n\n"
                                    "Please review the server rules and ensure future compliance. "
                                    "Continued violations may result in further disciplinary action."
                                ),
                                color=discord.Color.orange(),
                                timestamp=discord.utils.utcnow()
                            )
                            embed.set_footer(text="PNW eSports | Moderation Team")
                            embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1173057958052630639/1175193751114293248/PNW-eSports-Logo-1.png")
                            
                            await user.send(embed=embed)
                            print(f"[WARN] Sent warning to user {user_id}: {reason}")
                            notif['status'] = 'sent'
                        else:
                            notif['status'] = 'failed'
                            notif['error'] = 'User not found'
                        processed_any = True
                    except discord.Forbidden:
                        print(f"[WARN] Could not DM user {user_id} (DMs disabled)")
                        notif['status'] = 'failed'
                        notif['error'] = 'Could not DM user - DMs disabled'
                        add_bot_live_notification(
                            notif_type="warning",
                            title="Warning DM Failed",
                            message=f"Could not send warning to user. Their DMs are disabled.",
                            link="/moderation",
                            target_id=user_id
                        )
                        processed_any = True
                    except Exception as e:
                        print(f"[WARN] Failed to warn user {user_id}: {e}")
                        notif['status'] = 'failed'
                        notif['error'] = str(e)
                        add_bot_live_notification(
                            notif_type="error",
                            title="Warning DM Failed",
                            message=f"Failed to send warning: {str(e)[:50]}",
                            link="/moderation",
                            target_id=user_id
                        )
                        processed_any = True
                
                elif notif_type == 'send_dm':
                    # Send a direct message to user from dashboard
                    user_id = notif.get('user_id')
                    message = notif.get('message', '')
                    moderator = notif.get('moderator', 'Dashboard')
                    
                    try:
                        user = await bot.fetch_user(int(user_id))
                        if user:
                            embed = discord.Embed(
                                title="📬 Message from Staff",
                                description=message,
                                color=discord.Color.blurple(),
                                timestamp=discord.utils.utcnow()
                            )
                            embed.set_footer(text=f"PNW eSports | From: {moderator}")
                            embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1173057958052630639/1175193751114293248/PNW-eSports-Logo-1.png")
                            
                            await user.send(embed=embed)
                            print(f"[DM] Sent message to user {user_id} from {moderator}")
                            notif['status'] = 'sent'
                            add_bot_live_notification(
                                notif_type="success",
                                title="DM Delivered",
                                message=f"Message sent to {user.display_name}",
                                link="/members",
                                target_id=user_id
                            )
                        else:
                            notif['status'] = 'failed'
                            notif['error'] = 'User not found'
                        processed_any = True
                    except discord.Forbidden:
                        print(f"[DM] Could not DM user {user_id} (DMs disabled)")
                        notif['status'] = 'failed'
                        notif['error'] = 'Could not DM user - DMs disabled'
                        add_bot_live_notification(
                            notif_type="warning",
                            title="DM Failed",
                            message=f"Could not send message. User has DMs disabled.",
                            link="/members",
                            target_id=user_id
                        )
                        processed_any = True
                    except Exception as e:
                        print(f"[DM] Failed to DM user {user_id}: {e}")
                        notif['status'] = 'failed'
                        notif['error'] = str(e)
                        add_bot_live_notification(
                            notif_type="error",
                            title="DM Failed",
                            message=f"Failed to send message: {str(e)[:50]}",
                            link="/members",
                            target_id=user_id
                        )
                        processed_any = True
                    
            except discord.Forbidden:
                print(f"[NOTIFICATION ERROR] Could not DM user {user_id} (DMs disabled)")
                notif['status'] = 'failed'
                notif['error'] = 'Could not DM user'
                # If this was a sync job, update job progress to failed
                if notif.get('type') == 'bulk_sync_team_roles' and notif.get('job_id'):
                    update_job_progress(notif['job_id'], {
                        "status": "failed",
                        "phase": "done",
                        "current_step": "Error: Discord permission denied",
                        "error": "Could not modify roles - bot lacks permission",
                        "completed_at": datetime.now(timezone.utc).isoformat()
                    })
                # Send live notification for general DM failures
                add_bot_live_notification(
                    notif_type="warning",
                    title="DM Delivery Failed",
                    message=f"Could not send {notif.get('type', 'notification')} to user. DMs are disabled.",
                    link="/dashboard",
                    target_id=user_id
                )
                processed_any = True
            except Exception as e:
                print(f"[NOTIFICATION ERROR] Failed to send notification: {e}")
                import traceback; traceback.print_exc()
                notif['status'] = 'failed'
                notif['error'] = str(e)
                # If this was a sync job, update job progress to failed
                if notif.get('type') == 'bulk_sync_team_roles' and notif.get('job_id'):
                    update_job_progress(notif['job_id'], {
                        "status": "failed",
                        "phase": "done",
                        "current_step": f"Fatal error: {str(e)}",
                        "error": str(e),
                        "completed_at": datetime.now(timezone.utc).isoformat()
                    })
                # Send live notification for general failures
                add_bot_live_notification(
                    notif_type="error",
                    title="Notification Failed",
                    message=f"Failed to process {notif.get('type', 'notification')}: {str(e)[:40]}",
                    link="/dashboard"
                )
                processed_any = True
        
        # Save updated queue (keep failed/sent for logging, or remove them)
        if processed_any:
            # Atomic write with Windows retry for file locking
            import tempfile, time
            dir_name = os.path.dirname(DISCORD_NOTIFICATION_QUEUE_FILE)
            fd, tmp_path = tempfile.mkstemp(suffix='.tmp', dir=dir_name)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(notifications, f, indent=2)
                for attempt in range(5):
                    try:
                        os.replace(tmp_path, DISCORD_NOTIFICATION_QUEUE_FILE)
                        break
                    except PermissionError:
                        if attempt < 4:
                            time.sleep(0.1 * (attempt + 1))
                        else:
                            raise
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            print(f"[NOTIFICATION QUEUE] Finished processing, queue updated")
                
    except Exception as e:
        import traceback
        print(f"[ERROR] Failed to process notification queue: {e}")
        traceback.print_exc()

@process_discord_notifications.before_loop
async def before_notification_loop():
    await bot.wait_until_ready()
    print("[NOTIFICATION QUEUE] Task loop started and ready")

@tasks.loop(seconds=10)
async def process_moderation_queue():
    """Process moderation actions queued from the dashboard"""
    try:
        if not os.path.exists(MODERATION_QUEUE_FILE):
            return
            
        with open(MODERATION_QUEUE_FILE, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return
            queue = json.loads(content)
        
        if not queue:
            return
            
        guild = bot.get_guild(GUILD_ID)
        if not guild:
            return
        
        # Get the moderation cog for record keeping
        mod_cog = bot.get_cog('Moderation')
            
        processed = []
        for item in queue:
            if item.get('status') != 'pending':
                continue
                
            user_id = item.get('user_id')
            action = item.get('action')
            reason = item.get('reason', 'Dashboard action')
            duration = item.get('duration')
            moderator_name = item.get('moderator', 'Dashboard Admin')
            moderator_id = item.get('moderator_id')
            source = item.get('source', 'website')
            
            try:
                if action == 'kick':
                    member = guild.get_member(int(user_id))
                    if member:
                        # Send DM before kick
                        try:
                            embed = discord.Embed(
                                title="👢 Notice of Removal from PNW eSports Discord",
                                description=(
                                    f"Dear {member.mention},\n\n"
                                    f"You have been **removed (kicked)** from the server by the moderation team.\n\n"
                                    f"**Reason:** {reason}\n"
                                    f"**Moderator:** {moderator_name}\n\n"
                                    "If you believe this was a mistake, please contact a server administrator."
                                ),
                                color=discord.Color.red()
                            )
                            await member.send(embed=embed)
                        except:
                            pass
                        
                        await member.kick(reason=f"{reason} (by {moderator_name})")
                        item['status'] = 'completed'
                        print(f"[DASHBOARD] Kicked user {user_id} by {moderator_name}: {reason}")
                        
                        # Add to user record
                        if mod_cog:
                            mod_cog.add_record(user_id, "Kick", reason, moderator_name=moderator_name, moderator_id=moderator_id, source=source)
                    else:
                        item['status'] = 'failed'
                        item['error'] = 'Member not found'
                        
                elif action == 'ban':
                    member = guild.get_member(int(user_id))
                    if member:
                        # Send DM before ban
                        try:
                            embed = discord.Embed(
                                title="🔨 Notice of Ban from PNW eSports Discord",
                                description=(
                                    f"Dear {member.mention},\n\n"
                                    f"You have been **banned** from the server by the moderation team.\n\n"
                                    f"**Reason:** {reason}\n"
                                    f"**Moderator:** {moderator_name}\n\n"
                                    "If you believe this action was taken in error, please contact an administrator."
                                ),
                                color=discord.Color.dark_red()
                            )
                            await member.send(embed=embed)
                        except:
                            pass
                        
                        await member.ban(reason=f"{reason} (by {moderator_name})")
                        item['status'] = 'completed'
                        print(f"[DASHBOARD] Banned user {user_id} by {moderator_name}: {reason}")
                        
                        # Add to user record
                        if mod_cog:
                            mod_cog.add_record(user_id, "Ban", reason, moderator_name=moderator_name, moderator_id=moderator_id, source=source)
                    else:
                        # Try to ban by user ID even if not in server
                        try:
                            await guild.ban(discord.Object(id=int(user_id)), reason=f"{reason} (by {moderator_name})")
                            item['status'] = 'completed'
                            if mod_cog:
                                mod_cog.add_record(user_id, "Ban", reason, moderator_name=moderator_name, moderator_id=moderator_id, source=source)
                        except:
                            item['status'] = 'failed'
                            item['error'] = 'User not found'
                            
                elif action == 'unban':
                    try:
                        await guild.unban(discord.Object(id=int(user_id)), reason=f"{reason} (by {moderator_name})")
                        item['status'] = 'completed'
                        print(f"[DASHBOARD] Unbanned user {user_id} by {moderator_name}: {reason}")
                        
                        # Add to user record
                        if mod_cog:
                            mod_cog.add_record(user_id, "Unban", reason, moderator_name=moderator_name, moderator_id=moderator_id, source=source)
                    except:
                        item['status'] = 'failed'
                        item['error'] = 'User not banned or not found'
                        
                elif action == 'timeout':
                    member = guild.get_member(int(user_id))
                    if member:
                        timeout_until = datetime.now(timezone.utc) + timedelta(minutes=int(duration or 10))
                        await member.timeout(timeout_until, reason=f"{reason} (by {moderator_name})")
                        item['status'] = 'completed'
                        print(f"[DASHBOARD] Timed out user {user_id} for {duration} minutes by {moderator_name}: {reason}")
                        
                        # Add to user record
                        if mod_cog:
                            mod_cog.add_record(user_id, "Timeout", f"{reason} (Duration: {duration} min)", moderator_name=moderator_name, moderator_id=moderator_id, source=source)
                    else:
                        item['status'] = 'failed'
                        item['error'] = 'Member not found'
                        
            except Exception as e:
                item['status'] = 'failed'
                item['error'] = str(e)
                print(f"[DASHBOARD ERROR] Failed to {action} user {user_id}: {e}")
        
        # Save updated queue
        safe_json_dump(queue, MODERATION_QUEUE_FILE, indent=2)
            
    except Exception as e:
        print(f"[ERROR] Failed to process moderation queue: {e}")

def save_bot_status():
    """Save bot status to file for dashboard sync"""
    try:
        guild = bot.get_guild(GUILD_ID)
        total_members = guild.member_count if guild else 0
        
        status_data = {
            "status": "online",
            "guilds": len(bot.guilds),
            "members": total_members,
            "latency": round(bot.latency * 1000),
            "last_update": datetime.now(timezone.utc).isoformat()
        }
        
        os.makedirs(os.path.dirname(BOT_STATUS_FILE), exist_ok=True)
        safe_json_dump(status_data, BOT_STATUS_FILE, indent=2)
    except Exception as e:
        print(f"[ERROR] Failed to save bot status: {e}")

def save_members_cache():
    """Save members list to file for dashboard sync"""
    try:
        guild = bot.get_guild(GUILD_ID)
        if not guild:
            return
            
        members_data = []
        for member in guild.members:
            # Use display_avatar to get the best avatar (server-specific or global, including GIFs)
            avatar_url = str(member.display_avatar.url) if member.display_avatar else None
            # Ensure we get the animated version if available by using size parameter
            if avatar_url and member.display_avatar.is_animated():
                avatar_url = str(member.display_avatar.with_size(256).url)
            elif avatar_url:
                avatar_url = str(member.display_avatar.with_size(256).url)
            
            # Also get the banner if available (requires fetching user)
            banner_url = None
            
            members_data.append({
                "id": str(member.id),
                "name": member.name,
                "username": member.name,  # For frontend compatibility
                "display_name": member.display_name,
                "discriminator": member.discriminator,
                "avatar": avatar_url,
                "avatar_url": avatar_url,  # For frontend compatibility
                "banner_url": banner_url,
                "bot": member.bot,
                "joined_at": member.joined_at.isoformat() if member.joined_at else None,
                "created_at": member.created_at.isoformat() if member.created_at else None,
                "roles": [{"id": str(r.id), "name": r.name, "color": str(r.color)} for r in member.roles if r.name != "@everyone"],
                "top_role": member.top_role.name if member.top_role else None,
                "status": str(member.status) if hasattr(member, 'status') else "offline",
                "nick": member.nick
            })
        
        os.makedirs(os.path.dirname(MEMBERS_CACHE_FILE), exist_ok=True)
        safe_json_dump(members_data, MEMBERS_CACHE_FILE, indent=2)
            
        print(f"[SYNC] Cached {len(members_data)} members for dashboard")
    except Exception as e:
        print(f"[ERROR] Failed to save members cache: {e}")

def save_roles_cache():
    """Save roles list with member counts to file for dashboard analytics"""
    try:
        guild = bot.get_guild(GUILD_ID)
        if not guild:
            return
        
        roles_data = []
        for role in guild.roles:
            if role.name == "@everyone":
                continue
            roles_data.append({
                "id": str(role.id),
                "name": role.name,
                "color": str(role.color),
                "member_count": len(role.members),
                "position": role.position,
                "mentionable": role.mentionable,
                "hoist": role.hoist,
                "managed": role.managed,
                "permissions": role.permissions.value
            })
        
        os.makedirs(os.path.dirname(ROLES_CACHE_FILE), exist_ok=True)
        safe_json_dump(roles_data, ROLES_CACHE_FILE, indent=2)
        
        print(f"[SYNC] Cached {len(roles_data)} roles for dashboard")
    except Exception as e:
        print(f"[ERROR] Failed to save roles cache: {e}")

def save_channels_cache():
    """Save text channels list to file for dashboard (announcement channel selection)"""
    try:
        guild = bot.get_guild(GUILD_ID)
        if not guild:
            return
        
        channels_data = []
        for channel in guild.text_channels:
            channels_data.append({
                "id": str(channel.id),
                "name": channel.name,
                "category": channel.category.name if channel.category else "No Category",
                "type": "text",
                "position": channel.position
            })
        
        # Sort by category then position
        channels_data.sort(key=lambda x: (x['category'], x['position']))
        
        channels_cache_file = os.path.join(DATA_DIR, "channels_cache.json")
        os.makedirs(os.path.dirname(channels_cache_file), exist_ok=True)
        safe_json_dump(channels_data, channels_cache_file, indent=2)
        
        print(f"[SYNC] Cached {len(channels_data)} channels for dashboard")
    except Exception as e:
        print(f"[ERROR] Failed to save channels cache: {e}")

@tasks.loop(seconds=30)
async def dashboard_sync_loop():
    """Sync bot status and members to files for dashboard"""
    save_bot_status()
    save_members_cache()
    save_roles_cache()
    save_channels_cache()
    save_vc_live_cache()

def save_vc_live_cache():
    """Cache live VC data for dashboard"""
    try:
        guild = bot.get_guild(GUILD_ID)
        if not guild:
            print(f"[VC_CACHE] Guild {GUILD_ID} not found")
            return
        
        # Load generator config using absolute path
        vc_gen_file = os.path.join(DATA_DIR, "vc-generators.json")
        generators = {"normal": [], "tryout": []}
        if os.path.exists(vc_gen_file):
            with open(vc_gen_file, 'r', encoding='utf-8') as f:
                generators = json.load(f)
        else:
            print(f"[VC_CACHE] Generator file not found: {vc_gen_file}")
        
        # Ensure IDs are integers for channel lookup
        normal_ids = set(int(x) for x in generators.get("normal", []))
        tryout_ids = set(int(x) for x in generators.get("tryout", []))
        
        # Get VCSystem cog to access generated_vc_ids
        vc_system = bot.get_cog("VCSystem")
        generated_ids = getattr(vc_system, 'generated_vc_ids', set()) if vc_system else set()
        
        # Build generator data with names
        normal_generators = []
        for vc_id in normal_ids:
            channel = guild.get_channel(vc_id)
            if channel:
                normal_generators.append({
                    "id": str(vc_id),
                    "name": channel.name,
                    "category": channel.category.name if channel.category else "No Category",
                    "member_count": len([m for m in channel.members if not m.bot])
                })
        
        tryout_generators = []
        for vc_id in tryout_ids:
            channel = guild.get_channel(vc_id)
            if channel:
                tryout_generators.append({
                    "id": str(vc_id),
                    "name": channel.name,
                    "category": channel.category.name if channel.category else "No Category",
                    "member_count": len([m for m in channel.members if not m.bot])
                })
        
        # Build active VCs data (generated VCs with members)
        active_vcs = []
        total_users = 0
        
        for vc in guild.voice_channels:
            members = [m for m in vc.members if not m.bot]
            if not members:
                continue
            
            # Check if this is a generated VC
            is_generated = vc.id in generated_ids
            is_generator = vc.id in normal_ids or vc.id in tryout_ids
            
            # Get owner info (first member who has manage_channels permission on this VC)
            owner = None
            for member in members:
                perms = vc.permissions_for(member)
                if perms.manage_channels:
                    owner = {
                        "id": str(member.id),
                        "name": member.display_name,
                        "avatar": str(member.avatar.url) if member.avatar else None
                    }
                    break
            
            # Check if locked (connect explicitly denied for @everyone)
            default_perms = vc.overwrites_for(guild.default_role)
            is_locked = default_perms.connect == False
            
            # Only mark as hidden if BOTH view_channel AND connect are explicitly denied
            # This prevents false positives from normal permission setups
            is_hidden = (default_perms.view_channel == False and default_perms.connect == False)
            
            vc_data = {
                "id": str(vc.id),
                "name": vc.name,
                "category": vc.category.name if vc.category else "No Category",
                "member_count": len(members),
                "user_limit": vc.user_limit,
                "bitrate": vc.bitrate // 1000,
                "is_generated": is_generated,
                "is_generator": is_generator,
                "is_tryout": vc.id in tryout_ids,
                "is_locked": is_locked,
                "is_hidden": is_hidden,
                "owner": owner,
                "members": [
                    {
                        "id": str(m.id),
                        "name": m.display_name,
                        "username": m.name,
                        "avatar": str(m.avatar.url) if m.avatar else None,
                        "is_muted": m.voice.self_mute if m.voice else False,
                        "is_deafened": m.voice.self_deaf if m.voice else False,
                        "is_streaming": m.voice.self_stream if m.voice else False,
                        "is_video": m.voice.self_video if m.voice else False,
                        "joined_at": datetime.now(timezone.utc).isoformat()  # Approximate
                    }
                    for m in members
                ],
                "created_at": vc.created_at.isoformat() if vc.created_at else None
            }
            active_vcs.append(vc_data)
            total_users += len(members)
        
        # Sort by member count descending
        active_vcs.sort(key=lambda x: x['member_count'], reverse=True)
        
        cache_data = {
            "generators": {
                "normal": normal_generators,
                "tryout": tryout_generators
            },
            "active_vcs": active_vcs,
            "stats": {
                "total_users": total_users,
                "active_vcs": len(active_vcs),
                "normal_generators": len(normal_generators),
                "tryout_generators": len(tryout_generators)
            },
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
        
        cache_file = os.path.join(DATA_DIR, "vc_live_cache.json")
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        safe_json_dump(cache_data, cache_file, indent=2)
        
        print(f"[VC_CACHE] Saved: {len(normal_generators)} normal, {len(tryout_generators)} tryout generators, {len(active_vcs)} active VCs")
            
    except Exception as e:
        print(f"[ERROR] Failed to save VC live cache: {e}")
        import traceback
        traceback.print_exc()

@bot.event
async def on_ready():
    # Write PID file immediately
    write_pid_file()
    
    # Print startup message FIRST
    ping = round(bot.latency * 1000)
    server_count = len(bot.guilds)
    print("=" * 60)
    print("Welcome to the LionByteGG Distinguished System")
    print(f"Bot User: {bot.user}")
    print(f"Ping: {ping} ms")
    print(f"Connected Servers: {server_count}")
    print(f"Service Created By: Jay Moon")
    print("System is online and ready to serve your community.")
    print("=" * 60)
    print("[DEBUG] on_ready event fired")

    try:
        # Set dynamic arena status
        await update_arena_status(bot)
        if not arena_status_loop.is_running():
            arena_status_loop.start()
        print("[DEBUG] Adding views...")
        # Do NOT add SetupView globally, since it needs user_id per message
        # bot.add_view(SetupView(bot))  # REMOVE or COMMENT OUT this line
        bot.add_view(MigrateToStudentView(bot))
        bot.add_view(TicketPanelView())
        bot.add_view(TicketAdminView())  # <-- Add this line for persistent ticket admin buttons
        bot.add_view(VarsityApproveView())  # <-- Add varsity approve/denial persistent view
        bot.add_view(PersistentVarsityRegistrationView())  # <-- Persistent varsity registration buttons (survives restarts)
        print("[DEBUG] Adding cogs...")
        if not bot.get_cog("AdminCommands"):
            await bot.add_cog(AdminCommands(bot))
        if not bot.get_cog("TicketCommands"):
            await bot.add_cog(TicketCommands(bot))
        if not bot.get_cog("Moderation"):
            await bot.add_cog(Moderation(bot))
        print("[DEBUG] Cogs added.")

        try:
            bot.tree.copy_global_to(guild=discord.Object(id=GUILD_ID))
            synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
            print(f"🔁 Synced {len(synced)} slash commands.")
        except Exception as e:
            print(f"❌ Slash sync failed: {e}")

        if not check_for_timeouts.is_running():
            check_for_timeouts.start()
        
        # Start dashboard sync loop
        if not dashboard_sync_loop.is_running():
            dashboard_sync_loop.start()
            # Do initial sync immediately
            save_bot_status()
            save_members_cache()
            save_channels_cache()
            save_vc_live_cache()
            print("[STARTUP] Initial caches saved (members, channels, VCs)")
        
        # Start moderation queue processor
        if not process_moderation_queue.is_running():
            process_moderation_queue.start()
        
        # Start bot control listener (for dashboard stop/restart)
        if not check_bot_control.is_running():
            check_bot_control.start()
        
        # Start Discord notification queue processor (for varsity registrations, etc.)
        if not process_discord_notifications.is_running():
            process_discord_notifications.start()
            print("[STARTUP] Discord notification processor started")

        # --- Automatically ensure the ticket panel exists ---
        await ensure_ticket_panel_message(bot, GUILD_ID, TICKET_PANEL_CHANNEL_ID)
    except Exception as e:
        import traceback
        print("[ERROR] Exception in on_ready:", e)
        traceback.print_exc()

async def main():
    async with bot:
        await bot.load_extension("cogs.reaction_roles")
        await bot.load_extension("cogs.admin_commands")
        await bot.load_extension("cogs.vc-system")
        await bot.load_extension("utils.ggleap_status")
        await bot.load_extension("utils.ggleap_games")
        await bot.load_extension("cogs.userinfo")
        await bot.load_extension("views.varsity_view")  # Load varsity registration commands
        await bot.start(os.environ["DISCORD_BOT_TOKEN"])

@bot.command(name="force-setup-user")
async def force_setup_user(ctx, member: discord.Member):
    setup_channel = bot.get_channel(SETUP_CHANNEL_ID)
    if setup_channel is None:
        setup_channel = await bot.fetch_channel(SETUP_CHANNEL_ID)
    embed = discord.Embed(
        title="👋 Welcome to PNW Esports!",
        description=f"{member.mention}, Welcome to the **PNW Esports Discord Server**!\n\nTo get started, please complete your onboarding by choosing one of the options below.\nFailure to do so may result in Removal from the Discord Server for having an incomplete account.",
        color=discord.Color.yellow()
    )
    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
    embed.set_footer(text="PNW Esports | #RoarPRIDE")
    msg = await setup_channel.send(content=f"{member.mention}", embed=embed, view=SetupView(bot))
    welcome_messages[member.id] = msg

@tasks.loop(hours=1)
async def registration_timeout_check():
    now = datetime.utcnow()
    timeout = timedelta(days=4)
    for user_id, join_time_str in list(join_times.items()):
        join_time = datetime.fromisoformat(join_time_str)
        if now - join_time > timeout:
            guild = bot.get_guild(GUILD_ID)
            member = guild.get_member(int(user_id))
            if member and member.id not in SetupView.selection_made:
                try:
                    await guild.kick(member, reason="Having an Incomplete Account")
                    print(f"Kicked {member} for incomplete registration.")
                except Exception as e:
                    print(f"Failed to kick {member}: {e}")
            join_times.pop(user_id)
            save_join_times(join_times)

if __name__ == "__main__":
    # REMOVE this line:
    # bot.run(os.getenv("DISCORD_TOKEN"))  # Or your token loading method

    # KEEP ONLY THIS:
    asyncio.run(main())