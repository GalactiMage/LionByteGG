"""
BoilerCraftGG - Official Discord Bot for Purdue Network Minecraft Server
Main bot file - Entry point for the Discord bot
"""

import discord
from discord.ext import commands, tasks
import asyncio
import os
import sys
import json
import requests
from datetime import datetime, timezone, timedelta

import config
import aiohttp
import tempfile
import settings
from utils.database import Database
from views.ticket_view import TicketPanelView, TicketAdminView, ensure_ticket_panel_message, load_bot_config, save_bot_config, BOT_CONFIG_FILE
from safe_json import safe_json_dump

DASHBOARD_COMMANDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "dashboard_commands.json")
FAQ_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "faqs.json")
MEMBERS_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "members_cache.json")
USER_RECORDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "user_records")
SERVER_ANALYTICS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "server_analytics.json")

MC_SERVER_IP = "mc.esports.purdue.edu"

class BoilerCraftBot(commands.Bot):
    """Main bot class for BoilerCraftGG"""
    
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.voice_states = True
        intents.guilds = True
        
        super().__init__(
            command_prefix="!",  # Required but not used (slash commands only)
            intents=intents,
            description=config.BOT_DESCRIPTION
        )
        
        self.config = config
        self.settings = settings
        self.db = None
        
    async def setup_hook(self):
        """Called when the bot is starting up"""
        # Initialize database
        self.db = Database()
        await self.db.initialize()
        
        # Register persistent views for ticket system
        self.add_view(TicketPanelView())
        self.add_view(TicketAdminView())
        
        # Load all cogs
        await self.load_cogs()
        
        # Sync slash commands to guild
        try:
            if settings.GUILD_ID:
                guild = discord.Object(id=settings.GUILD_ID)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
            else:
                await self.tree.sync()
            print(f"[SETUP] Slash commands synced!")
        except Exception as e:
            print(f"[SETUP] Failed to sync commands on startup: {e}")
            print("[SETUP] Use /sync manually once the bot is ready.")
        
    async def load_cogs(self):
        """Load all cogs from the cogs directory"""
        cogs_dir = "cogs"
        
        for filename in os.listdir(cogs_dir):
            if filename.endswith(".py") and not filename.startswith("__"):
                cog_name = f"{cogs_dir}.{filename[:-3]}"
                try:
                    await self.load_extension(cog_name)
                    print(f"[COG] Loaded: {cog_name}")
                except Exception as e:
                    print(f"[COG] Failed to load {cog_name}: {e}")
                    
    async def on_ready(self):
        """Called when the bot is ready and connected"""
        print("=" * 50)
        print(f"  {config.BOT_NAME} v{config.BOT_VERSION}")
        print(f"  {config.BOT_DESCRIPTION}")
        print("=" * 50)
        print(f"  Logged in as: {self.user.name}#{self.user.discriminator}")
        print(f"  Bot ID: {self.user.id}")
        print(f"  Guilds: {len(self.guilds)}")
        print("=" * 50)
        
        # Set bot presence
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="Purdue Network | /help"
        )
        await self.change_presence(activity=activity, status=discord.Status.online)
        
        # Restore ticket panel if channel is configured
        try:
            cfg = load_bot_config()
            panel_channel_id = cfg.get("ticket_panel_channel_id")
            if panel_channel_id:
                await ensure_ticket_panel_message(self, settings.GUILD_ID, int(panel_channel_id))
                print(f"[TICKETS] Panel restored in channel {panel_channel_id}")
            else:
                # Fallback: check DB for legacy config
                if self.db:
                    async with self.db.connection.execute(
                        "SELECT value FROM bot_settings WHERE key = ?",
                        ("ticket_panel_channel_id",)
                    ) as cursor:
                        row = await cursor.fetchone()
                        if row:
                            channel_id = int(row[0])
                            cfg["ticket_panel_channel_id"] = channel_id
                            save_bot_config(cfg)
                            await ensure_ticket_panel_message(self, settings.GUILD_ID, channel_id)
                            print(f"[TICKETS] Panel restored from DB in channel {channel_id}")
        except Exception as e:
            print(f"[TICKETS] Could not restore panel: {e}")

        # Start dashboard command polling
        if not self.poll_dashboard_commands.is_running():
            self.poll_dashboard_commands.start()
        
        # Start members cache sync
        if not self.members_cache_loop.is_running():
            self.members_cache_loop.start()
        
        # Start server analytics tracking
        if not self.server_analytics_loop.is_running():
            self.server_analytics_loop.start()

    def save_members_cache(self):
        """Save guild members list to file for dashboard sync"""
        guild = self.get_guild(settings.GUILD_ID)
        if not guild:
            return
        
        members_data = []
        for member in guild.members:
            avatar_url = None
            if member.display_avatar:
                avatar_url = str(member.display_avatar.with_size(256).url)
            
            members_data.append({
                "id": str(member.id),
                "name": member.name,
                "username": member.name,
                "display_name": member.display_name,
                "discriminator": member.discriminator,
                "avatar": avatar_url,
                "avatar_url": avatar_url,
                "bot": member.bot,
                "joined_at": member.joined_at.isoformat() if member.joined_at else None,
                "created_at": member.created_at.isoformat() if member.created_at else None,
                "roles": [{"id": str(r.id), "name": r.name, "color": str(r.color)} for r in member.roles if r.name != "@everyone"],
                "top_role": member.top_role.name if member.top_role and member.top_role.name != "@everyone" else None,
                "status": str(member.status) if hasattr(member, 'status') else "offline",
                "nick": member.nick
            })
        
        try:
            safe_json_dump(members_data, MEMBERS_CACHE_FILE, indent=2)
        except Exception as e:
            print(f"[MEMBERS] Error saving cache: {e}")

    @tasks.loop(seconds=30)
    async def members_cache_loop(self):
        """Periodically save members cache"""
        self.save_members_cache()

    @members_cache_loop.before_loop
    async def before_members_cache(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=5)
    async def server_analytics_loop(self):
        """Poll MC server status and log player count for analytics"""
        try:
            async with aiohttp.ClientSession() as http_session:
                async with http_session.get(
                    f'https://api.mcsrvstat.us/3/{MC_SERVER_IP}',
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    data = await resp.json()
            
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "online": data.get("online", False),
                "players_online": data.get("players", {}).get("online", 0),
                "players_max": data.get("players", {}).get("max", 0),
            }
            
            # Load existing data
            analytics = []
            if os.path.exists(SERVER_ANALYTICS_FILE):
                try:
                    with open(SERVER_ANALYTICS_FILE, 'r', encoding='utf-8') as f:
                        analytics = json.load(f)
                except Exception:
                    analytics = []
            
            analytics.append(entry)
            
            # Keep only last 30 days of data (5 min intervals = ~8640 entries)
            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            analytics = [e for e in analytics if e.get("timestamp", "") >= cutoff]
            
            # Atomic write to prevent corruption
            dir_name = os.path.dirname(SERVER_ANALYTICS_FILE)
            fd, tmp_path = tempfile.mkstemp(suffix='.tmp', dir=dir_name)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(analytics, f)
                os.replace(tmp_path, SERVER_ANALYTICS_FILE)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
                
        except Exception as e:
            print(f"[ANALYTICS] Error polling server: {e}")

    @server_analytics_loop.before_loop
    async def before_server_analytics(self):
        await self.wait_until_ready()

    @tasks.loop(seconds=5)
    async def poll_dashboard_commands(self):
        """Check for commands from the website dashboard"""
        try:
            if not os.path.exists(DASHBOARD_COMMANDS_FILE):
                return

            with open(DASHBOARD_COMMANDS_FILE, 'r', encoding='utf-8') as f:
                commands_list = json.load(f)

            if not commands_list:
                return

            remaining = []
            for cmd in commands_list:
                if cmd.get("status") != "pending":
                    continue

                cmd_type = cmd.get("type")
                try:
                    if cmd_type == "deploy_panel":
                        channel_id = cmd.get("channel_id")
                        if channel_id:
                            # Delete old panel messages first
                            guild = self.get_guild(settings.GUILD_ID)
                            if guild:
                                channel = guild.get_channel(int(channel_id))
                                if channel:
                                    async for message in channel.history(limit=100):
                                        if message.author == self.user and message.embeds:
                                            embed = message.embeds[0]
                                            if embed.title and ("Purdue" in embed.title or "BoilerCraft" in embed.title) and "Support" in embed.title:
                                                await message.delete()
                            await ensure_ticket_panel_message(self, settings.GUILD_ID, int(channel_id))
                            print(f"[DASHBOARD] Deployed ticket panel to channel {channel_id}")
                        cmd["status"] = "completed"

                    elif cmd_type == "refresh_panel":
                        cfg = load_bot_config()
                        panel_channel_id = cfg.get("ticket_panel_channel_id")
                        if panel_channel_id:
                            guild = self.get_guild(settings.GUILD_ID)
                            if guild:
                                channel = guild.get_channel(int(panel_channel_id))
                                if channel:
                                    async for message in channel.history(limit=100):
                                        if message.author == self.user and message.embeds:
                                            embed = message.embeds[0]
                                            if embed.title and ("Purdue" in embed.title or "BoilerCraft" in embed.title) and "Support" in embed.title:
                                                await message.delete()
                            await ensure_ticket_panel_message(self, settings.GUILD_ID, int(panel_channel_id))
                            print(f"[DASHBOARD] Refreshed ticket panel in channel {panel_channel_id}")
                        cmd["status"] = "completed"

                    elif cmd_type == "faq_post":
                        channel_id = cmd.get("channel_id")
                        faq_index = cmd.get("faq_index")
                        if channel_id and faq_index is not None:
                            guild = self.get_guild(settings.GUILD_ID)
                            if guild:
                                channel = guild.get_channel(int(channel_id))
                                if channel:
                                    faqs = self._load_faqs()
                                    if 0 <= faq_index < len(faqs):
                                        faq = faqs[faq_index]
                                        embed = self._build_faq_embed(faq_index + 1, faq["question"], faq["answer"])
                                        msg = await channel.send(embed=embed)
                                        faqs[faq_index]["message_id"] = str(msg.id)
                                        self._save_faqs(faqs)
                                        print(f"[FAQ] Posted FAQ #{faq_index + 1}")
                        cmd["status"] = "completed"

                    elif cmd_type == "faq_edit":
                        channel_id = cmd.get("channel_id")
                        faq_index = cmd.get("faq_index")
                        message_id = cmd.get("message_id")
                        if channel_id and faq_index is not None:
                            guild = self.get_guild(settings.GUILD_ID)
                            if guild:
                                channel = guild.get_channel(int(channel_id))
                                if channel:
                                    faqs = self._load_faqs()
                                    if 0 <= faq_index < len(faqs):
                                        faq = faqs[faq_index]
                                        mid = message_id or faq.get("message_id")
                                        if mid:
                                            try:
                                                msg = await channel.fetch_message(int(mid))
                                                embed = self._build_faq_embed(faq_index + 1, faq["question"], faq["answer"])
                                                await msg.edit(embed=embed)
                                                print(f"[FAQ] Edited FAQ #{faq_index + 1}")
                                            except discord.NotFound:
                                                # Message was deleted, post a new one
                                                embed = self._build_faq_embed(faq_index + 1, faq["question"], faq["answer"])
                                                msg = await channel.send(embed=embed)
                                                faqs[faq_index]["message_id"] = str(msg.id)
                                                self._save_faqs(faqs)
                                                print(f"[FAQ] Re-posted FAQ #{faq_index + 1} (message was missing)")
                                        else:
                                            # No message_id, post fresh
                                            embed = self._build_faq_embed(faq_index + 1, faq["question"], faq["answer"])
                                            msg = await channel.send(embed=embed)
                                            faqs[faq_index]["message_id"] = str(msg.id)
                                            self._save_faqs(faqs)
                                            print(f"[FAQ] Posted FAQ #{faq_index + 1} (no prior message)")
                        cmd["status"] = "completed"

                    elif cmd_type == "faq_delete":
                        channel_id = cmd.get("channel_id")
                        message_id = cmd.get("message_id")
                        if channel_id and message_id:
                            guild = self.get_guild(settings.GUILD_ID)
                            if guild:
                                channel = guild.get_channel(int(channel_id))
                                if channel:
                                    try:
                                        msg = await channel.fetch_message(int(message_id))
                                        await msg.delete()
                                        print(f"[FAQ] Deleted FAQ message {message_id}")
                                    except discord.NotFound:
                                        print(f"[FAQ] Message {message_id} already deleted")
                        cmd["status"] = "completed"

                    elif cmd_type == "faq_renumber":
                        channel_id = cmd.get("channel_id")
                        if channel_id:
                            guild = self.get_guild(settings.GUILD_ID)
                            if guild:
                                channel = guild.get_channel(int(channel_id))
                                if channel:
                                    faqs = self._load_faqs()
                                    for i, faq in enumerate(faqs):
                                        mid = faq.get("message_id")
                                        if mid:
                                            try:
                                                msg = await channel.fetch_message(int(mid))
                                                embed = self._build_faq_embed(i + 1, faq["question"], faq["answer"])
                                                await msg.edit(embed=embed)
                                            except discord.NotFound:
                                                embed = self._build_faq_embed(i + 1, faq["question"], faq["answer"])
                                                new_msg = await channel.send(embed=embed)
                                                faqs[i]["message_id"] = str(new_msg.id)
                                    self._save_faqs(faqs)
                                    print(f"[FAQ] Re-numbered {len(faqs)} FAQs")
                        cmd["status"] = "completed"

                    elif cmd_type in ("member_kick", "member_ban", "member_timeout", "member_unban"):
                        guild = self.get_guild(settings.GUILD_ID)
                        if guild:
                            user_id = int(cmd.get("user_id"))
                            reason = cmd.get("reason", "No reason provided")
                            moderator = cmd.get("moderator", "Dashboard")
                            action = cmd_type.replace("member_", "")
                            
                            member = guild.get_member(user_id)
                            
                            if action == "kick" and member:
                                await member.kick(reason=f"{reason} (by {moderator})")
                                print(f"[MOD] Kicked {member.display_name}: {reason}")
                                self._save_user_record(user_id, "Kick", reason, moderator)
                            elif action == "ban":
                                if member:
                                    await member.ban(reason=f"{reason} (by {moderator})", delete_message_days=0)
                                else:
                                    user = discord.Object(id=user_id)
                                    await guild.ban(user, reason=f"{reason} (by {moderator})", delete_message_days=0)
                                print(f"[MOD] Banned user {user_id}: {reason}")
                                self._save_user_record(user_id, "Ban", reason, moderator)
                            elif action == "timeout" and member:
                                duration_min = cmd.get("duration") or 60
                                await member.timeout(timedelta(minutes=int(duration_min)), reason=f"{reason} (by {moderator})")
                                print(f"[MOD] Timed out {member.display_name} for {duration_min}min: {reason}")
                                self._save_user_record(user_id, "Timeout", f"{reason} (Duration: {duration_min} min)", moderator)
                            elif action == "unban":
                                user = discord.Object(id=user_id)
                                await guild.unban(user, reason=f"{reason} (by {moderator})")
                                print(f"[MOD] Unbanned user {user_id}: {reason}")
                                self._save_user_record(user_id, "Unban", reason, moderator)
                        cmd["status"] = "completed"

                    elif cmd_type == "send_dm":
                        user_id = int(cmd.get("user_id"))
                        message = cmd.get("message", "")
                        moderator = cmd.get("moderator", "Dashboard")
                        try:
                            user = await self.fetch_user(user_id)
                            if user:
                                await user.send(f"**Message from Purdue Network Staff ({moderator}):**\n{message}")
                                print(f"[DM] Sent DM to {user.display_name}")
                            cmd["status"] = "completed"
                        except discord.Forbidden:
                            print(f"[DM] Cannot DM user {user_id} - DMs disabled")
                            cmd["status"] = "dm_failed"
                        except Exception as e:
                            print(f"[DM] Error sending DM to {user_id}: {e}")
                            cmd["status"] = "error"

                    elif cmd_type == "ticket_close":
                        guild = self.get_guild(settings.GUILD_ID)
                        if guild:
                            channel_name = cmd.get("channel_name")
                            reason = cmd.get("reason", "Closed from dashboard")
                            channel = discord.utils.get(guild.text_channels, name=channel_name)
                            if channel:
                                embed = discord.Embed(
                                    title="🔒 Ticket Closed",
                                    description=f"This ticket has been closed from the dashboard.\n**Reason:** {reason}",
                                    color=discord.Color.red(),
                                    timestamp=discord.utils.utcnow()
                                )
                                embed.set_footer(text="BoilerCraftGG | Support System")
                                await channel.send(embed=embed)
                                # Archive: set permissions so user can't send, then delete after a delay
                                await channel.edit(name=f"closed-{channel_name}")
                                print(f"[TICKET] Closed ticket channel: {channel_name}")
                            else:
                                print(f"[TICKET] Channel not found: {channel_name}")
                        cmd["status"] = "completed"

                    elif cmd_type == "ticket_message":
                        guild = self.get_guild(settings.GUILD_ID)
                        if guild:
                            channel_name = cmd.get("channel_name")
                            message = cmd.get("message", "")
                            channel = discord.utils.get(guild.text_channels, name=channel_name)
                            if channel:
                                embed = discord.Embed(
                                    description=message,
                                    color=discord.Color.blurple(),
                                    timestamp=discord.utils.utcnow()
                                )
                                embed.set_author(name="Dashboard Staff Message")
                                embed.set_footer(text="BoilerCraftGG | Support System")
                                await channel.send(embed=embed)
                                print(f"[TICKET] Sent message to {channel_name}")
                            else:
                                print(f"[TICKET] Channel not found: {channel_name}")
                        cmd["status"] = "completed"

                    else:
                        cmd["status"] = "unknown_type"

                except Exception as e:
                    print(f"[DASHBOARD] Error processing command {cmd_type}: {e}")
                    cmd["status"] = "error"

            # Clear completed/processed commands, keep only truly new ones
            safe_json_dump([], DASHBOARD_COMMANDS_FILE)

        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(f"[DASHBOARD] Error polling commands: {e}")

    @poll_dashboard_commands.before_loop
    async def before_poll(self):
        await self.wait_until_ready()

    # =========================================================================
    # Moderation Helpers
    # =========================================================================
    def _save_user_record(self, user_id, action_type, reason, moderator):
        """Save a moderation record for a user"""
        from datetime import datetime, timezone
        os.makedirs(USER_RECORDS_DIR, exist_ok=True)
        record_file = os.path.join(USER_RECORDS_DIR, f"{user_id}_record.json")
        
        records = []
        if os.path.exists(record_file):
            try:
                with open(record_file, 'r', encoding='utf-8') as f:
                    records = json.load(f)
            except Exception:
                records = []
        
        records.append({
            "user_id": str(user_id),
            "type": action_type,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "moderator": moderator,
            "source": "website"
        })
        
        safe_json_dump(records, record_file, indent=2)

    # =========================================================================
    # FAQ Helpers
    # =========================================================================
    def _load_faqs(self):
        try:
            if os.path.exists(FAQ_FILE):
                with open(FAQ_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[FAQ] Error loading faqs.json: {e}")
        return []

    def _save_faqs(self, data):
        try:
            safe_json_dump(data, FAQ_FILE, indent=2)
        except Exception as e:
            print(f"[FAQ] Error saving faqs.json: {e}")

    def _build_faq_embed(self, number, question, answer):
        embed = discord.Embed(
            title=f"#{number}: {question}",
            description=answer,
            color=discord.Color.from_str("#CFB991")
        )
        embed.set_footer(text="Purdue Network | FAQ")
        return embed

    async def on_command_error(self, ctx, error):
        """Global error handler for commands"""
        if isinstance(error, commands.CommandNotFound):
            return
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You don't have permission to use this command!")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Missing required argument: {error.param.name}")
        else:
            print(f"[ERROR] {type(error).__name__}: {error}")
            
    async def close(self):
        """Cleanup when bot is shutting down"""
        if self.db:
            await self.db.close()
        await super().close()


async def main():
    """Main entry point"""
    # Validate token
    if not settings.DISCORD_TOKEN:
        print("[ERROR] No Discord token found! Please set DISCORD_TOKEN in your .env file.")
        sys.exit(1)
        
    # Create and run bot
    bot = BoilerCraftBot()
    
    try:
        await bot.start(settings.DISCORD_TOKEN)
    except discord.LoginFailure:
        print("[ERROR] Invalid Discord token!")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down...")
        await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
