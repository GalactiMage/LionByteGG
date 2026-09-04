"""
Combined Bot + Dashboard Runner
This runs both the Discord bot and the web dashboard together,
ensuring they share data properly.
"""

import asyncio
import threading
import sys
import os
import socket
from dotenv import load_dotenv

# Load .env from the LionByteGG directory
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

# Add the parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def get_local_ip():
    """Get the local IP address for LAN access."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def run_dashboard():
    """Run the Flask dashboard in a separate thread"""
    from web.app import app
    # Disable Flask's reloader since we're running in a thread
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

def main():
    local_ip = get_local_ip()
    print("=" * 60)
    print("LionByteGG Combined System")
    print("Starting Discord Bot + Web Dashboard")
    print("=" * 60)
    
    # Start dashboard in a background thread
    dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
    dashboard_thread.start()
    print(f"[DASHBOARD] Web dashboard starting...")
    print(f"[DASHBOARD] Local URL:  http://localhost:5000")
    print(f"[DASHBOARD] LAN URL:    http://{local_ip}:5000")
    print("=" * 60)
    
    # Import and run the bot (this will block)
    print("[BOT] Starting Discord bot...")
    
    # Import bot components
    import discord
    from discord.ext import commands, tasks
    from discord import app_commands
    import json
    from datetime import datetime, timedelta, timezone
    
    from views.setup_view import SetupView
    from views.ticket_view import TicketPanelView, TicketAdminView, ensure_ticket_panel_message
    from views.varsity_view import VarsityRegistrationView, VarsityApproveView
    from cogs.admin_commands import MigrateToStudentView, AdminCommands
    from cogs.ticket_commands import TicketCommands
    from cogs.moderation import Moderation
    from utils.constants import GUILD_ID, TICKET_PANEL_CHANNEL_ID, SETUP_CHANNEL_ID, pending_users
    from utils.arena_status import update_arena_status
    from utils.safe_json import safe_json_dump
    
    # File paths (use absolute paths based on script location)
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    COMBINED_DATA_DIR = os.path.join(SCRIPT_DIR, "data")
    BOT_STATUS_FILE = os.path.join(COMBINED_DATA_DIR, "bot_status.json")
    MEMBERS_CACHE_FILE = os.path.join(COMBINED_DATA_DIR, "members_cache.json")
    MODERATION_QUEUE_FILE = os.path.join(COMBINED_DATA_DIR, "moderation_queue.json")
    ACTIVITY_FILE = os.path.join(COMBINED_DATA_DIR, "bot_activity.json")
    JOIN_TRACK_FILE = os.path.join(COMBINED_DATA_DIR, "join_times.json")
    
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    intents.members = True
    intents.guild_messages = True
    intents.presences = True  # Need this for member status
    intents.auto_moderation_execution = True
    
    bot = commands.Bot(command_prefix="/", intents=intents)
    
    welcome_messages = {}
    
    def load_join_times():
        if os.path.exists(JOIN_TRACK_FILE):
            with open(JOIN_TRACK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    
    def save_join_times(data):
        os.makedirs(os.path.dirname(JOIN_TRACK_FILE), exist_ok=True)
        safe_json_dump(data, JOIN_TRACK_FILE)
    
    join_times = load_join_times()
    
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
            
            os.makedirs(COMBINED_DATA_DIR, exist_ok=True)
            safe_json_dump(status_data, BOT_STATUS_FILE, indent=2)
            print(f"[SYNC] Bot status updated: {total_members} members, {round(bot.latency * 1000)}ms latency")
        except Exception as e:
            print(f"[ERROR] Failed to save bot status: {e}")

    def save_members_cache():
        """Save members list to file for dashboard sync"""
        try:
            guild = bot.get_guild(GUILD_ID)
            if not guild:
                print(f"[ERROR] Could not find guild {GUILD_ID}")
                return
                
            members_data = []
            for member in guild.members:
                members_data.append({
                    "id": str(member.id),
                    "name": member.name,
                    "display_name": member.display_name,
                    "discriminator": member.discriminator,
                    "avatar": str(member.avatar.url) if member.avatar else None,
                    "bot": member.bot,
                    "joined_at": member.joined_at.isoformat() if member.joined_at else None,
                    "created_at": member.created_at.isoformat() if member.created_at else None,
                    "roles": [{"id": str(r.id), "name": r.name, "color": str(r.color)} for r in member.roles if r.name != "@everyone"],
                    "top_role": member.top_role.name if member.top_role else None,
                    "status": str(member.status) if hasattr(member, 'status') else "offline",
                    "nick": member.nick
                })
            
            os.makedirs(COMBINED_DATA_DIR, exist_ok=True)
            safe_json_dump(members_data, MEMBERS_CACHE_FILE, indent=2)
                
            print(f"[SYNC] Cached {len(members_data)} members for dashboard")
        except Exception as e:
            print(f"[ERROR] Failed to save members cache: {e}")
            import traceback
            traceback.print_exc()

    @tasks.loop(seconds=30)
    async def dashboard_sync_loop():
        """Sync bot status and members to files for dashboard"""
        try:
            save_bot_status()
        except Exception as e:
            print(f"[SYNC ERROR] Bot status sync failed: {e}")
        try:
            save_members_cache()
        except Exception as e:
            print(f"[SYNC ERROR] Members cache sync failed: {e}")
        
        # Check for activity change requests
        try:
            if os.path.exists(ACTIVITY_FILE):
                with open(ACTIVITY_FILE, 'r', encoding='utf-8') as f:
                    activity_data = json.load(f)
                
                if activity_data.get('pending'):
                    activity_text = activity_data.get('activity', '')
                    if activity_text:
                        await bot.change_presence(activity=discord.Game(name=activity_text))
                        print(f"[SYNC] Changed activity to: {activity_text}")
                    
                    # Mark as processed
                    activity_data['pending'] = False
                    activity_data['processed_at'] = datetime.now(timezone.utc).isoformat()
                    safe_json_dump(activity_data, ACTIVITY_FILE, indent=2)
        except Exception as e:
            print(f"[ERROR] Failed to process activity change: {e}")

    @tasks.loop(seconds=10)
    async def process_moderation_queue():
        """Process moderation actions queued from the dashboard"""
        try:
            if not os.path.exists(MODERATION_QUEUE_FILE):
                return
                
            with open(MODERATION_QUEUE_FILE, 'r', encoding='utf-8') as f:
                queue = json.load(f)
            
            if not queue:
                return
                
            guild = bot.get_guild(GUILD_ID)
            if not guild:
                return
                
            for item in queue:
                if item.get('status') != 'pending':
                    continue
                    
                user_id = item.get('user_id')
                action = item.get('action')
                reason = item.get('reason', 'Dashboard action')
                duration = item.get('duration')
                
                try:
                    if action == 'kick':
                        member = guild.get_member(int(user_id))
                        if member:
                            await member.kick(reason=reason)
                            item['status'] = 'completed'
                            print(f"[DASHBOARD] Kicked user {user_id}: {reason}")
                        else:
                            item['status'] = 'failed'
                            item['error'] = 'Member not found'
                            
                    elif action == 'ban':
                        member = guild.get_member(int(user_id))
                        if member:
                            await member.ban(reason=reason)
                            item['status'] = 'completed'
                            print(f"[DASHBOARD] Banned user {user_id}: {reason}")
                        else:
                            try:
                                await guild.ban(discord.Object(id=int(user_id)), reason=reason)
                                item['status'] = 'completed'
                            except:
                                item['status'] = 'failed'
                                item['error'] = 'User not found'
                                
                    elif action == 'unban':
                        try:
                            await guild.unban(discord.Object(id=int(user_id)), reason=reason)
                            item['status'] = 'completed'
                            print(f"[DASHBOARD] Unbanned user {user_id}: {reason}")
                        except:
                            item['status'] = 'failed'
                            item['error'] = 'User not banned or not found'
                            
                    elif action == 'timeout':
                        member = guild.get_member(int(user_id))
                        if member:
                            timeout_until = datetime.now(timezone.utc) + timedelta(minutes=int(duration or 10))
                            await member.timeout(timeout_until, reason=reason)
                            item['status'] = 'completed'
                            print(f"[DASHBOARD] Timed out user {user_id} for {duration} minutes: {reason}")
                        else:
                            item['status'] = 'failed'
                            item['error'] = 'Member not found'
                            
                except Exception as e:
                    item['status'] = 'failed'
                    item['error'] = str(e)
                    print(f"[DASHBOARD ERROR] Failed to {action} user {user_id}: {e}")
            
            safe_json_dump(queue, MODERATION_QUEUE_FILE, indent=2)
                
        except Exception as e:
            print(f"[ERROR] Failed to process moderation queue: {e}")

    @tasks.loop(minutes=1)
    async def arena_status_loop():
        try:
            await update_arena_status(bot)
        except Exception as e:
            print(f"[ERROR] Arena status update failed: {e}")

    @tasks.loop(minutes=1)
    async def check_for_timeouts():
        now = datetime.now(timezone.utc)
        timeout_duration = timedelta(minutes=1)
        for user_id, start_time in list(pending_users.items()):
            if now - start_time > timeout_duration:
                user = bot.get_user(user_id)
                if user:
                    try:
                        embed = discord.Embed(
                            title="⚠️ Setup Reminder",
                            description="You started setting up your account, but it looks like you didn't finish.\n\nPlease go back to the server and complete your setup.",
                            color=discord.Color.orange()
                        )
                        embed.set_footer(text="PNW Esports | Reminder")
                        await user.send(embed=embed)
                    except discord.Forbidden:
                        print(f"Could not DM user {user_id}")
                del pending_users[user_id]

    @bot.event
    async def on_member_join(member):
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
                welcome_messages[member.id] = msg
            except Exception as e:
                print(f"[ERROR] Could not send welcome message: {e}")
        join_times[str(member.id)] = datetime.utcnow().isoformat()
        save_join_times(join_times)
        
        # Update member cache when someone joins
        save_members_cache()

    @bot.event
    async def on_member_remove(member):
        if hasattr(SetupView, "selection_made"):
            SetupView.selection_made.discard(member.id)
        msg = welcome_messages.pop(member.id, None)
        if msg:
            try:
                await msg.delete()
            except:
                pass
        join_times.pop(str(member.id), None)
        save_join_times(join_times)
        
        # Update member cache when someone leaves
        save_members_cache()

    @bot.event
    async def on_ready():
        ping = round(bot.latency * 1000)
        server_count = len(bot.guilds)
        
        guild = bot.get_guild(GUILD_ID)
        member_count = guild.member_count if guild else 0
        
        print("=" * 60)
        print("Welcome to the LionByteGG Distinguished System")
        print(f"Bot User: {bot.user}")
        print(f"Ping: {ping} ms")
        print(f"Connected Servers: {server_count}")
        print(f"Total Members: {member_count}")
        print(f"Service Created By: Jay Moon")
        print("System is online and ready to serve your community.")
        print("=" * 60)

        try:
            await update_arena_status(bot)
            if not arena_status_loop.is_running():
                arena_status_loop.start()
            
            bot.add_view(MigrateToStudentView(bot))
            bot.add_view(TicketPanelView())
            bot.add_view(TicketAdminView())
            bot.add_view(VarsityApproveView())
            
            if not bot.get_cog("AdminCommands"):
                await bot.add_cog(AdminCommands(bot))
            if not bot.get_cog("TicketCommands"):
                await bot.add_cog(TicketCommands(bot))
            if not bot.get_cog("Moderation"):
                await bot.add_cog(Moderation(bot))

            try:
                bot.tree.copy_global_to(guild=discord.Object(id=GUILD_ID))
                synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
                print(f"🔁 Synced {len(synced)} slash commands.")
            except Exception as e:
                print(f"❌ Slash sync failed: {e}")

            if not check_for_timeouts.is_running():
                check_for_timeouts.start()
            
            # Pass bot instance to web app for live status
            try:
                from web.app import set_bot_instance
                set_bot_instance(bot)
                print("[SYNC] Bot instance passed to web dashboard")
            except Exception as e:
                print(f"[WARN] Could not set bot instance for web: {e}")
            
            # Start dashboard sync loop
            if not dashboard_sync_loop.is_running():
                dashboard_sync_loop.start()
            
            # Do initial sync immediately
            print("[SYNC] Performing initial sync...")
            save_bot_status()
            save_members_cache()
            print("[SYNC] Initial sync complete!")
            
            # Start moderation queue processor
            if not process_moderation_queue.is_running():
                process_moderation_queue.start()

            await ensure_ticket_panel_message(bot, GUILD_ID, TICKET_PANEL_CHANNEL_ID)
            
        except Exception as e:
            import traceback
            print("[ERROR] Exception in on_ready:", e)
            traceback.print_exc()

    async def run_bot():
        async with bot:
            await bot.load_extension("cogs.reaction_roles")
            await bot.load_extension("cogs.admin_commands")
            await bot.load_extension("cogs.vc-system")
            await bot.load_extension("utils.ggleap_status")
            await bot.load_extension("utils.ggleap_games")
            await bot.load_extension("cogs.userinfo")
            await bot.start(os.environ["DISCORD_BOT_TOKEN"])

    # Run the bot
    asyncio.run(run_bot())

if __name__ == "__main__":
    main()
