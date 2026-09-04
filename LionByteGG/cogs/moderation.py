import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import re
import asyncio
from datetime import datetime, timezone, timedelta
from utils.constants import USER_RECORDS_DIR, GUEST_TIMES_DIR, LOG_CHANNEL_NAME, GUILD_ID
from utils.safe_json import safe_json_dump, safe_json_load
from utils import db as user_db
from utils.automod_sync import sync_automod

# Ensure data directory and flagged_words.json exist
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
FLAGGED_WORDS_PATH = os.path.join(DATA_DIR, "flagged_words.json")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
if not os.path.exists(FLAGGED_WORDS_PATH):
    safe_json_dump({"bannable": [], "kickable": [], "warning": []}, FLAGGED_WORDS_PATH, indent=2)

INAPPROPRIATE_PATTERNS = [
    r"discord\.gg",  # Example: block invite links
    r"nastyword",    # Example: block specific patterns
]

THUMBNAIL_URL = "https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png"
SERVER_NAME = "Purdue University Northwest eSports Discord Server"
WORDS_FILE = FLAGGED_WORDS_PATH
AUTOMOD_LOG_CHANNEL_ID = 1316780542078881854  # <-- Replace with your AutoMod log channel ID
BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN', '')

def load_words():
    return safe_json_load(WORDS_FILE, {"bannable": [], "kickable": [], "warning": []})

def save_words(words):
    safe_json_dump(words, WORDS_FILE, indent=2)

def ensure_user_records_dir():
    os.makedirs(USER_RECORDS_DIR, exist_ok=True)

def ensure_guest_times_dir():
    os.makedirs(GUEST_TIMES_DIR, exist_ok=True)

def user_record_path(user_id):
    ensure_user_records_dir()
    return os.path.join(USER_RECORDS_DIR, f"{user_id}_record.json")

def guest_time_path(user_id):
    ensure_guest_times_dir()
    return os.path.join(GUEST_TIMES_DIR, f"{user_id}_guest_time.json")

def load_guest_times():
    ensure_guest_times_dir()
    guest_times = {}
    for fname in os.listdir(GUEST_TIMES_DIR):
        if fname.endswith("_guest_time.json"):
            try:
                data = safe_json_load(os.path.join(GUEST_TIMES_DIR, fname), None)
                if data is not None:
                    user_id = fname.split("_")[0]
                    guest_times[user_id] = data
            except Exception:
                continue
    return guest_times

def save_guest_time(user_id, expires_at, username=None, joined_at=None):
    ensure_guest_times_dir()
    path = guest_time_path(user_id)
    data = {
        "discord_id": str(user_id),
        "expires_at": expires_at.isoformat()
    }
    if username:
        data["username"] = username
    if joined_at:
        data["joined_at"] = joined_at.isoformat() if hasattr(joined_at, "isoformat") else str(joined_at)
    safe_json_dump(data, path, indent=2)

def set_guest_timer(user_id, username=None, joined_at=None):
    ensure_guest_times_dir()
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    save_guest_time(user_id, expires_at, username=username, joined_at=joined_at)

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reload_words()
        self.processed_audit_ids = set()
        self.processed_automod_ids = set()  # Track processed AutoMod events to prevent duplicates
        user_db.init_db()
        # Optionally, you can start an auditlog watcher task if needed
        # self.auditlog_task = self.bot.loop.create_task(self.auditlog_watcher())

    async def _sync_automod(self):
        """Push the current flagged-word lists to Discord AutoMod (runs in a thread)."""
        try:
            words = load_words()
            result = await asyncio.to_thread(sync_automod, BOT_TOKEN, GUILD_ID, words)
            print(f"[AutoMod Sync] {result}")
        except Exception as exc:
            print(f"[AutoMod Sync] Error: {exc}")

    def add_record(self, user_id, type_, reason, moderator_name=None, moderator_id=None, source="discord"):
        user_id = str(user_id)
        user_db.add_record(user_id, type_, reason,
                           moderator=moderator_name,
                           moderator_id=moderator_id,
                           source=source)
        # Also log to activity log
        self.log_to_activity_log(
            action=type_.lower(),
            category="moderation",
            details=reason,
            target_id=user_id,
            moderator_name=moderator_name,
            moderator_id=moderator_id,
            source=source
        )
    
    def log_to_activity_log(self, action, category, details, target_id=None, target_name=None, moderator_name=None, moderator_id=None, source="discord"):
        """Log an activity to the unified activity log file"""
        try:
            activity_log_path = os.path.join(DATA_DIR, "activity_log.json")
            
            # Load existing log
            activity_log = safe_json_load(activity_log_path, [])
            
            # Create moderator info
            moderator_info = {
                "type": "bot" if source == "discord" else "website",
                "name": moderator_name or "LionByteGG Bot",
                "id": str(moderator_id) if moderator_id else None,
                "avatar": None
            }
            
            log_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "user": moderator_info,
                "ip_address": None,
                "action": action,
                "category": category,
                "success": True,
                "details": details,
                "target_id": str(target_id) if target_id else None,
                "target_name": target_name,
                "source": source,
                "path": None,
                "method": None
            }
            
            # Add to beginning (newest first)
            activity_log.insert(0, log_entry)
            
            # Keep only last 1000 entries
            activity_log = activity_log[:1000]
            
            safe_json_dump(activity_log, activity_log_path, indent=2)
                
        except Exception as e:
            print(f"[ACTIVITY LOG] Error logging activity: {e}")

    def get_user_records(self, user_id):
        return user_db.get_records(str(user_id))

    def reload_words(self):
        words = load_words()
        self.BANNABLE_WORDS = words.get("bannable", [])
        self.KICKABLE_WORDS = words.get("kickable", [])
        self.WARNING_WORDS = words.get("warning", [])
        self.tier_keywords = {}
        for word in self.BANNABLE_WORDS:
            self.tier_keywords[word] = 3
        for word in self.KICKABLE_WORDS:
            self.tier_keywords[word] = 2
        for word in self.WARNING_WORDS:
            self.tier_keywords[word] = 1

    def persist_words(self):
        words = {
            "bannable": self.BANNABLE_WORDS,
            "kickable": self.KICKABLE_WORDS,
            "warning": self.WARNING_WORDS,
        }
        save_words(words)

    @commands.Cog.listener()
    async def on_automod_action(self, execution):
        """
        Handles Discord AutoMod action events (discord.py 2.x).
        Always logs the flagged content to the user's record, then takes action if needed.
        """
        try:
            # Build a dedup key for all events.
            # For non-block actions a real message_id is available, so use it.
            # For block actions message_id is None; deduplicate by user + rule + matched keyword.
            if execution.message_id is not None:
                event_key = f"{execution.user_id}:{execution.rule_id}:{execution.message_id}"
            else:
                event_key = f"{execution.user_id}:{execution.rule_id}:{(execution.matched_keyword or execution.content or '')}"

            if event_key in self.processed_automod_ids:
                print(f"[AutoMod] Skipping duplicate event: {event_key[:50]}...")
                return
            self.processed_automod_ids.add(event_key)
            # Keep the set bounded
            if len(self.processed_automod_ids) > 200:
                self.processed_automod_ids = set(list(self.processed_automod_ids)[-100:])
            
            print(f"[DEBUG] AutoMod event fired!")
            print(f"[DEBUG] Execution: action={execution.action}, rule_id={execution.rule_id}")
            print(f"[DEBUG] Member: {execution.member}, Content: {execution.content}, Matched Keyword: {execution.matched_keyword}")
            
            guild = execution.guild
            if not guild:
                print(f"[AutoMod] Could not find guild")
                return
            
            member = execution.member
            user_id = str(execution.user_id)
            
            # Even if member not found, still log the record
            member_name = str(member) if member else f"User {user_id}"
            
            flagged_content = execution.content or ""
            matched_keyword = execution.matched_keyword or flagged_content
            channel = execution.channel
            channel_id = channel.id if channel else None
            message_id = execution.message_id
            rule_id = execution.rule_id
            
            print(f"[AutoMod] {member_name} triggered rule {rule_id} with '{flagged_content}'")
            
            # Get channel name if possible
            channel_name = f"#{channel.name}" if channel else "Unknown Channel"
            
            # Build the automod reason for logging
            automod_reason = f"AutoMod detected flagged content: \"{matched_keyword}\" in {channel_name}"
            if flagged_content and flagged_content != matched_keyword:
                automod_reason += f" (Full message contained: \"{flagged_content}\")"
            
            # Check if the word is in our custom lists FIRST to avoid duplicate logging
            # Only take action if we have a valid member object
            if not member:
                print(f"[AutoMod] Cannot take additional action - member not found for user {user_id}")
                # Still log the detection since we can't take action
                print(f"[AutoMod] Saving record for user {user_id}")
                self.add_record(
                    user_id,
                    "AutoMod Flag",
                    automod_reason,
                    moderator_name="Discord AutoMod",
                    moderator_id=None,
                    source="discord"
                )
                return
                
            flagged_words = load_words()
            bannable = flagged_words.get("bannable", [])
            kickable = flagged_words.get("kickable", [])
            warning = flagged_words.get("warning", [])
            
            # Check if word matches our custom lists - if so, the action method handles all logging
            for word in bannable:
                if word.lower() in flagged_content.lower():
                    await self.ban_user(member, f"Use of prohibited language: {word}", moderator_name="AutoMod")
                    return  # Action taken, method handles logging
            for word in kickable:
                if word.lower() in flagged_content.lower():
                    await self.kick_user(member, f"Use of prohibited language: {word}", moderator_name="AutoMod")
                    return  # Action taken, method handles logging
            for word in warning:
                if word.lower() in flagged_content.lower():
                    await self.warn_user(member, flagged_content, word)
                    return  # Action taken, method handles logging
            
            # No action was taken (word not in custom lists), so log the AutoMod detection
            print(f"[AutoMod] Saving record for user {user_id} (no custom action taken)")
            self.add_record(
                user_id,
                "AutoMod Flag",
                automod_reason,
                moderator_name="Discord AutoMod",
                moderator_id=None,
                source="discord"
            )
            
            # Log to the AutoMod log channel
            log_channel = guild.get_channel(AUTOMOD_LOG_CHANNEL_ID)
            if log_channel:
                embed = discord.Embed(
                    title="🚨 AutoMod Detection",
                    description=f"**User:** {member.mention} ({user_id})\n"
                               f"**Channel:** {channel_name}\n"
                               f"**Matched Keyword:** `{matched_keyword}`\n"
                               f"**Content:** {flagged_content[:500] if flagged_content else 'N/A'}",
                    color=discord.Color.orange(),
                    timestamp=discord.utils.utcnow()
                )
                embed.set_thumbnail(url=member.display_avatar.url if hasattr(member, 'display_avatar') else THUMBNAIL_URL)
                embed.set_footer(text="PNW eSports | AutoMod Log", icon_url=THUMBNAIL_URL)
                try:
                    await log_channel.send(embed=embed)
                except Exception as e:
                    print(f"[AutoMod] Error sending log message: {e}")
                    
        except Exception as e:
            print(f"[AutoMod] ERROR in on_automod_action: {e}")
            import traceback
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry):
        # Only process ban and kick actions
        if entry.action in [discord.AuditLogAction.ban, discord.AuditLogAction.kick]:
            guild = entry.guild
            user = entry.target
            moderator = entry.user
            action_type = "Ban" if entry.action == discord.AuditLogAction.ban else "Kick"
            reason = entry.reason or "No reason provided."

            log_channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
            if not log_channel:
                return

            embed = discord.Embed(
                title=f"Moderation Action Detected: {action_type}",
                color=discord.Color.dark_red() if action_type == "Ban" else discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="User", value=f"{user.mention} ({user.id})", inline=False)
            embed.add_field(name="Moderator", value=f"{moderator.mention} ({moderator.id})", inline=False)
            embed.add_field(name="Action", value=action_type, inline=True)
            embed.add_field(name="Reason", value=reason, inline=False)
            embed.set_footer(text="PNW eSports | Moderation Log", icon_url=THUMBNAIL_URL)
            embed.set_thumbnail(url=user.display_avatar.url if hasattr(user, "display_avatar") else THUMBNAIL_URL)
            await log_channel.send(embed=embed)

    async def log_action(self, guild, user, action_type, reason, moderator_name=None):
        log_channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
        if log_channel:
            embed = discord.Embed(
                title=f"{action_type} | {user}",
                description=(
                    f"**User:** {user.mention} (ID: {user.id})\n"
                    f"**Action:** {action_type}\n"
                    f"**Reason:** {reason}\n"
                    f"**Moderator:** {moderator_name if moderator_name else 'Moderation Team'}\n"
                    f"**Time:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                ),
                color=discord.Color.orange() if action_type in ("Warning", "Violation") else discord.Color.red() if action_type == "Kick" else discord.Color.dark_red()
            )
            embed.set_footer(text="PNW eSports | Moderation Log (LionByteGG)")
            embed.set_thumbnail(url=user.display_avatar.url)
            await log_channel.send(embed=embed)
        # The record is also saved in self.user_records, so /userinfo will show it

    async def warn_user(self, user, content, word):
        """
        Warning-tier words result in a logged Violation and a DM notice only.
        There is no escalation — users can accumulate as many violations as needed.
        Kickable-tier and bannable-tier words handle their own escalation separately.
        """
        embed = discord.Embed(
            title="⚠️ Language Violation",
            description=(
                f"Dear {user.mention},\n\n"
                f"You have received a **violation** from the **{SERVER_NAME}** moderation team.\n\n"
                f"**Reason:** Use of inappropriate language (`{word}`).\n\n"
                "Please review the server rules and ensure future compliance."
            ),
            color=discord.Color.orange()
        )
        embed.set_footer(text="PNW eSports | Moderation Team")
        embed.set_thumbnail(url=THUMBNAIL_URL)
        try:
            await user.send(embed=embed)
        except Exception:
            pass

        # Log the violation (always, even if DM failed)
        await self.log_action(user.guild, user, "Violation", f"Use of inappropriate language: {word}")
        self.add_record(user.id, "Violation", f"Use of inappropriate language: {word}", moderator_name="AutoMod", source="discord")

    async def kick_user(self, user, reason, moderator_name=None, moderator_id=None):
        # Use the same DM embed for all kicks
        embed = discord.Embed(
            title="👢 Notice of Removal from PNW eSports Discord",
            description=(
                f"Dear {user.mention},\n\n"
                f"You have been **removed (kicked)** from the **{SERVER_NAME}** by the moderation team.\n\n"
                f"**Reason:** {reason}\n"
                f"**Moderator:** {moderator_name if moderator_name else 'Moderation Team'}\n\n"
                "If you believe this was a mistake or wish to appeal, please contact a server administrator."
            ),
            color=discord.Color.red()
        )
        embed.set_footer(text="PNW eSports | Moderation Team")
        embed.set_thumbnail(url=THUMBNAIL_URL)
        try:
            await user.send(embed=embed)
        except Exception:
            pass
        try:
            await user.kick(reason=f"{reason} (by {moderator_name})" if moderator_name else reason)
        except Exception:
            pass
        await self.log_action(user.guild, user, "Kick", reason, moderator_name)
        self.add_record(user.id, "Kick", reason, moderator_name=moderator_name, moderator_id=moderator_id, source="discord")

    async def ban_user(self, user, reason, moderator_name=None, moderator_id=None):
        # Use the same DM embed for all bans
        embed = discord.Embed(
            title="🔨 Notice of Ban from PNW eSports Discord",
            description=(
                f"Dear {user.mention},\n\n"
                f"You have been **banned** from the **{SERVER_NAME}** by the moderation team.\n\n"
                f"**Reason:** {reason}\n"
                f"**Moderator:** {moderator_name if moderator_name else 'Moderation Team'}\n\n"
                "If you believe this action was taken in error or wish to appeal, please contact a server administrator outside of Discord."
            ),
            color=discord.Color.dark_red()
        )
        embed.set_footer(text="PNW eSports | Moderation Team")
        embed.set_thumbnail(url=THUMBNAIL_URL)
        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            pass
        try:
            await user.ban(reason=f"{reason} (by {moderator_name})" if moderator_name else reason)
        except Exception:
            pass
        await self.log_action(user.guild, user, "Ban", reason, moderator_name)
        self.add_record(user.id, "Ban", reason, moderator_name=moderator_name, moderator_id=moderator_id, source="discord")

    def log_user_action(self, user_id, action_type, reason, by):
        """Log a moderation action for a user."""
        record = self.user_records.get(str(user_id), [])
        record.append({
            "type": action_type,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "reason": reason,
            "by": by
        })
        self.user_records[str(user_id)] = record
        if hasattr(self, "save_user_records"):
            self.save_user_records()

    # --- Slash commands to manage word lists ---
    @app_commands.command(name="addword", description="Add a word to the moderation database.")
    @app_commands.describe(tier="ban, kick, or warn", word="The word to add")
    async def add_word(self, interaction: discord.Interaction, tier: str, word: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return
        word = word.lower().strip()
        self.reload_words()
        synced = False
        if tier.lower() == "ban":
            if word not in self.BANNABLE_WORDS:
                self.BANNABLE_WORDS.append(word)
                self.tier_keywords[word] = 3
                self.persist_words()
                synced = True
                await interaction.response.send_message(f"Added `{word}` to bannable words.", ephemeral=True)
            else:
                await interaction.response.send_message(f"`{word}` is already in bannable words.", ephemeral=True)
        elif tier.lower() == "kick":
            if word not in self.KICKABLE_WORDS:
                self.KICKABLE_WORDS.append(word)
                self.tier_keywords[word] = 2
                self.persist_words()
                synced = True
                await interaction.response.send_message(f"Added `{word}` to kickable words.", ephemeral=True)
            else:
                await interaction.response.send_message(f"`{word}` is already in kickable words.", ephemeral=True)
        elif tier.lower() == "warn":
            if word not in self.WARNING_WORDS:
                self.WARNING_WORDS.append(word)
                self.tier_keywords[word] = 1
                self.persist_words()
                synced = True
                await interaction.response.send_message(f"Added `{word}` to warning words.", ephemeral=True)
            else:
                await interaction.response.send_message(f"`{word}` is already in warning words.", ephemeral=True)
        else:
            await interaction.response.send_message("Invalid tier. Use `ban`, `kick`, or `warn`.", ephemeral=True)
        if synced:
            asyncio.create_task(self._sync_automod())

    @app_commands.command(name="removeword", description="Remove a word from the moderation database.")
    @app_commands.describe(tier="ban, kick, or warn", word="The word to remove")
    async def remove_word(self, interaction: discord.Interaction, tier: str, word: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return
        word = word.lower().strip()
        self.reload_words()
        synced = False
        if tier.lower() == "ban":
            if word in self.BANNABLE_WORDS:
                self.BANNABLE_WORDS.remove(word)
                self.tier_keywords.pop(word, None)
                self.persist_words()
                synced = True
                await interaction.response.send_message(f"Removed `{word}` from bannable words.", ephemeral=True)
            else:
                await interaction.response.send_message(f"`{word}` is not in bannable words.", ephemeral=True)
        elif tier.lower() == "kick":
            if word in self.KICKABLE_WORDS:
                self.KICKABLE_WORDS.remove(word)
                self.tier_keywords.pop(word, None)
                self.persist_words()
                synced = True
                await interaction.response.send_message(f"Removed `{word}` from kickable words.", ephemeral=True)
            else:
                await interaction.response.send_message(f"`{word}` is not in kickable words.", ephemeral=True)
        elif tier.lower() == "warn":
            if word in self.WARNING_WORDS:
                self.WARNING_WORDS.remove(word)
                self.tier_keywords.pop(word, None)
                self.persist_words()
                synced = True
                await interaction.response.send_message(f"Removed `{word}` from warning words.", ephemeral=True)
            else:
                await interaction.response.send_message(f"`{word}` is not in warning words.", ephemeral=True)
        else:
            await interaction.response.send_message("Invalid tier. Use `ban`, `kick`, or `warn`.", ephemeral=True)
        if synced:
            asyncio.create_task(self._sync_automod())

    # NOTE: Removed on_message listener that watched AutoMod log channel - 
    # it was redundant with on_automod_action and caused duplicate logging.
    # on_automod_action now handles all AutoMod detections directly.

    @commands.command(name="Records")
    async def transcript(self, ctx, member: discord.Member):
        record = self.get_user_records(member.id)
        if not record:
            await ctx.send("No Record, Good Standing.")
            return
        violations = sum(1 for r in record if r.get("type") in ("Warning", "Violation"))
        kicks = sum(1 for r in record if r.get("type") == "Kick")
        bans = sum(1 for r in record if r.get("type") == "Ban")
        automods = sum(1 for r in record if r.get("type") == "AutoMod")
        summary = f"Violations: {violations}, Kicks: {kicks}, Bans: {bans}, AutoMod Actions: {automods}"
        lines = [f"Summary: {summary}"]
        for entry in record:
            lines.append(f"{entry['timestamp']} | {entry['type']}: {entry['reason']}")
        transcript_text = "\n".join(lines)
        filename = f"{member.id}_transcript.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(transcript_text)
        await ctx.send(file=discord.File(filename))
        os.remove(filename)