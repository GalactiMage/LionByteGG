"""
Chat Monitor Cog for BoilerCraftGG
Monitors Minecraft chat via DiscordSRV console channel for flagged words.
Supports multiple servers (one console channel per server).
"""

import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import re
from datetime import datetime, timezone, timedelta

from utils.embeds import EmbedBuilder
from safe_json import safe_json_dump
import config
import settings


# Central Time (UTC-6, or UTC-5 during DST)
CENTRAL_TZ = timezone(timedelta(hours=-5))  # CDT (summer) — change to -6 for CST (winter)

# Data file paths
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
FLAGGED_WORDS_FILE = os.path.join(DATA_DIR, "flagged_words.json")
CHAT_MONITOR_CONFIG_FILE = os.path.join(DATA_DIR, "chat_monitor_config.json")
FLAGGED_LOG_FILE = os.path.join(DATA_DIR, "flagged_log.json")

# Default config
DEFAULT_CONFIG = {
    "enabled": True,
    "alert_channel_id": 1489451801756434462,
    "mod_role_id": 1488552558468530366,
    "servers": {
        "PNW": {
            "name": "Purdue Northwest",
            "console_channel_id": 1489429912564662422,
            "enabled": True
        }
    }
}

# Strip code block markers from DiscordSRV console output
CODE_BLOCK_RE = re.compile(r'^```\w*\n?|```$', re.MULTILINE)

# Regex: whisper/command line
# Example: [Thu 22:25:01 INFO  Server/ServerGamePacketListenerImpl] MageOW issued server command: /w MageOW FUCK YOU BITCH
# Also matches without timestamp bracket prefix in case DiscordSRV strips it
WHISPER_PATTERN = re.compile(
    r'(\w+)\s+issued server command:\s*/(?:w|msg|tell|whisper|r|reply)\s+(\w+)\s+(.+)',
    re.IGNORECASE
)

# Regex: normal public chat line
# Example: [Thu 22:24:50 INFO  Server] <MageOW> how are you
CHAT_PATTERN = re.compile(
    r'<(\w+)>\s+(.+)',
    re.IGNORECASE
)


def load_flagged_words() -> list:
    if os.path.exists(FLAGGED_WORDS_FILE):
        with open(FLAGGED_WORDS_FILE, "r") as f:
            data = json.load(f)
            return [w.lower() for w in data.get("words", [])]
    return []


def save_flagged_words(words: list):
    safe_json_dump({"words": sorted(set(words))}, FLAGGED_WORDS_FILE, indent=2)


def load_monitor_config() -> dict:
    if os.path.exists(CHAT_MONITOR_CONFIG_FILE):
        with open(CHAT_MONITOR_CONFIG_FILE, "r") as f:
            return json.load(f)
    save_monitor_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG


def save_monitor_config(cfg: dict):
    safe_json_dump(cfg, CHAT_MONITOR_CONFIG_FILE, indent=2)


def check_message_for_flags(message_text: str, flagged_words: list) -> list:
    message_lower = message_text.lower()
    found = []
    for word in flagged_words:
        pattern = r'\b' + re.escape(word) + r'\b'
        if re.search(pattern, message_lower):
            found.append(word)
    return found


def strip_code_blocks(content: str) -> str:
    """Remove Discord code block markers (``` ) from content"""
    return CODE_BLOCK_RE.sub('', content).strip()


def save_flagged_log_entry(entry: dict):
    """Append a flagged message entry to the log file for the website dashboard."""
    logs = []
    if os.path.exists(FLAGGED_LOG_FILE):
        try:
            with open(FLAGGED_LOG_FILE, "r") as f:
                logs = json.load(f)
        except (json.JSONDecodeError, IOError):
            logs = []
    logs.insert(0, entry)
    # Keep last 500 entries
    logs = logs[:500]
    safe_json_dump(logs, FLAGGED_LOG_FILE, indent=2)


class ChatMonitor(commands.Cog):
    """Monitors Minecraft chat for flagged words via DiscordSRV console channel"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.flagged_words = load_flagged_words()
        self.monitor_config = load_monitor_config()
        # Track processed lines per message to avoid duplicate alerts
        self._processed_lines = {}
        # Track recent whispers to suppress their public chat duplicates
        # Key: "player:message_lower", Value: timestamp
        self._recent_whispers = {}
        # Don't process events until bot is fully ready
        self._ready = False
        self._rebuild_channel_set()

    @commands.Cog.listener()
    async def on_ready(self):
        # Pre-load existing messages in console channels so we don't re-alert on restart
        await self._preload_existing_lines()
        self._ready = True
        print("[CHAT MONITOR] Ready and monitoring.")

    async def _preload_existing_lines(self):
        """Read recent messages in all console channels and mark their lines as already processed.
        This prevents duplicate alerts when the bot restarts."""
        for channel_id in self.console_channel_ids:
            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue
            try:
                # Fetch last 50 messages in the console channel
                async for message in channel.history(limit=50):
                    content = message.content
                    if not content:
                        for embed in message.embeds:
                            if embed.description:
                                content = embed.description
                                break
                    if not content:
                        continue

                    clean = strip_code_blocks(content)
                    lines = clean.splitlines()
                    msg_id = message.id
                    if msg_id not in self._processed_lines:
                        self._processed_lines[msg_id] = set()
                    for line in lines:
                        line_stripped = line.strip()
                        if line_stripped:
                            self._processed_lines[msg_id].add(line_stripped)

                print(f"[CHAT MONITOR] Pre-loaded existing lines from channel {channel_id}")
            except Exception as e:
                print(f"[CHAT MONITOR] Could not pre-load channel {channel_id}: {e}")

    def _rebuild_channel_set(self):
        self.console_channel_ids = {}
        for server_key, server_cfg in self.monitor_config.get("servers", {}).items():
            if server_cfg.get("enabled", True):
                cid = server_cfg.get("console_channel_id")
                if cid:
                    self.console_channel_ids[cid] = server_key

    def _extract_new_lines(self, message: discord.Message, content: str) -> list:
        """Extract only lines we haven't processed yet for this message"""
        # Strip code block markers first
        clean = strip_code_blocks(content)
        lines = clean.splitlines()
        msg_id = message.id

        if msg_id not in self._processed_lines:
            self._processed_lines[msg_id] = set()

        new_lines = []
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue
            if line_stripped not in self._processed_lines[msg_id]:
                self._processed_lines[msg_id].add(line_stripped)
                new_lines.append(line_stripped)

        # Limit cache size
        if len(self._processed_lines) > 50:
            oldest_keys = sorted(self._processed_lines.keys())[:len(self._processed_lines) - 50]
            for k in oldest_keys:
                del self._processed_lines[k]

        return new_lines

    def _parse_line(self, line: str):
        """
        Parse a single console line. Returns (player, message, type, target) or None.
        Whisper check ALWAYS runs first. If a line matches whisper, it is NEVER public chat.
        """
        # Check whisper first — this is the more specific pattern
        whisper_match = WHISPER_PATTERN.search(line)
        if whisper_match:
            return (
                whisper_match.group(1),           # player
                whisper_match.group(3),           # message text
                "Whisper",                        # type
                whisper_match.group(2)            # target player
            )

        # Only if NOT a whisper, check public chat
        chat_match = CHAT_PATTERN.search(line)
        if chat_match:
            return (
                chat_match.group(1),              # player
                chat_match.group(2),              # message text
                "Public Chat",                    # type
                None                              # no target
            )

        return None

    async def _process_console_content(self, message: discord.Message):
        if not self._ready:
            return
        if not self.monitor_config.get("enabled", True):
            return
        if message.channel.id not in self.console_channel_ids:
            return
        if message.author.id == self.bot.user.id:
            return
        if not self.flagged_words:
            return

        server_key = self.console_channel_ids[message.channel.id]
        server_name = self.monitor_config["servers"][server_key].get("name", server_key)

        # Get content — check message text and embeds
        content = message.content
        if not content:
            for embed in message.embeds:
                if embed.description:
                    content = embed.description
                    break
        if not content:
            return

        new_lines = self._extract_new_lines(message, content)
        now = datetime.now(timezone.utc)

        # Clean old whisper history (older than 30 seconds)
        self._recent_whispers = {
            k: v for k, v in self._recent_whispers.items()
            if (now - v).total_seconds() < 30
        }

        for line in new_lines:
            parsed = self._parse_line(line)
            if not parsed:
                continue

            player_name, message_text, msg_type, target_player = parsed
            combo_key = f"{player_name.lower()}:{message_text.lower()}"

            if msg_type == "Whisper":
                # Record this whisper so any matching public chat line gets skipped
                self._recent_whispers[combo_key] = now
            elif msg_type == "Public Chat":
                # If we already saw this exact player+message as a whisper, skip it
                if combo_key in self._recent_whispers:
                    continue

            # Check for flagged words
            flagged = check_message_for_flags(message_text, self.flagged_words)
            if not flagged:
                continue

            await self._send_alert(
                server_name=server_name,
                player_name=player_name,
                message_text=message_text,
                msg_type=msg_type,
                target_player=target_player,
                flagged_words=flagged
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        await self._process_console_content(message)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        """Fires for ALL message edits, even if the message isn't cached.
        This is critical because after a bot restart, DiscordSRV keeps editing
        its existing console message which wouldn't be in the bot's cache."""
        if not self._ready:
            return
        if payload.channel_id not in self.console_channel_ids:
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return

        try:
            message = await channel.fetch_message(payload.message_id)
            await self._process_console_content(message)
        except Exception:
            pass

    async def _send_alert(self, server_name, player_name, message_text, msg_type, target_player, flagged_words):
        alert_channel_id = self.monitor_config.get("alert_channel_id")
        mod_role_id = self.monitor_config.get("mod_role_id")

        if not alert_channel_id:
            return

        channel = self.bot.get_channel(alert_channel_id)
        if not channel:
            return

        # Look up linked Discord account
        discord_user_str = "Unknown (not verified)"
        if self.bot.db:
            user_data = await self.bot.db.get_user_by_minecraft(player_name)
            if user_data:
                discord_id = user_data.get("discord_id")
                if discord_id:
                    discord_user_str = f"<@{discord_id}>"

        # Highlight flagged words
        highlighted = message_text
        for word in flagged_words:
            pattern = re.compile(r'(\b' + re.escape(word) + r'\b)', re.IGNORECASE)
            highlighted = pattern.sub(r'**__\1__**', highlighted)

        # Build embed with Central Time
        now_central = datetime.now(CENTRAL_TZ)

        # Save to log file for website dashboard
        log_entry = {
            "timestamp": now_central.isoformat(),
            "server": server_name,
            "player": player_name,
            "discord_user": discord_user_str,
            "message": message_text,
            "type": msg_type,
            "target_player": target_player,
            "flagged_words": flagged_words
        }
        try:
            save_flagged_log_entry(log_entry)
        except Exception as e:
            print(f"[CHAT MONITOR] Failed to save log entry: {e}")

        # Type icon and color
        if msg_type == "Whisper":
            type_icon = "🔒"
            type_label = "Private Message (Whisper)"
            embed_color = 0x9B59B6  # Purple for whispers
        else:
            type_icon = "💬"
            type_label = "Public Chat"
            embed_color = 0xE74C3C  # Red for public

        # Mojang avatar URL
        avatar_url = f"https://mc-heads.net/avatar/{player_name}/128"

        embed = discord.Embed(
            title="🚨  Flagged Message Detected",
            color=embed_color,
            timestamp=now_central
        )

        embed.set_thumbnail(url=avatar_url)

        # Player info section
        player_info = f"**Minecraft:** `{player_name}`\n**Discord:** {discord_user_str}"
        embed.add_field(name="👤  Player", value=player_info, inline=True)

        # Message type section
        type_info = f"{type_icon} **{type_label}**"
        if msg_type == "Whisper" and target_player:
            target_avatar = f"https://mc-heads.net/avatar/{target_player}/128"
            type_info += f"\n📨 **To:** `{target_player}`"
        embed.add_field(name="📋  Type", value=type_info, inline=True)

        # Server info
        embed.add_field(name="🖥️  Server", value=f"**{server_name}**", inline=True)

        # Separator — full message
        embed.add_field(
            name="━━━━━━━━━━  Message  ━━━━━━━━━━",
            value=f"```{message_text}```",
            inline=False
        )

        # Flagged words with red indicators
        words_display = "  ".join(f"🔴 `{w}`" for w in flagged_words)
        embed.add_field(
            name="⚠️  Flagged Words",
            value=words_display,
            inline=False
        )

        embed.set_footer(
            text=f"{config.BOT_NAME} • Chat Monitor • {now_central.strftime('%I:%M %p CT • %m/%d/%Y')}",
            icon_url=self.bot.user.display_avatar.url if self.bot.user.display_avatar else None
        )

        # Send with mod role ping
        ping = f"<@&{mod_role_id}>" if mod_role_id else ""
        await channel.send(content=ping, embed=embed)

    # =========================================================================
    # SLASH COMMANDS
    # =========================================================================

    chatmonitor_group = app_commands.Group(
        name="chatmonitor",
        description="Manage Minecraft chat monitoring",
        default_permissions=discord.Permissions(administrator=True)
    )

    @chatmonitor_group.command(name="add-word", description="Add a word to the flagged words list")
    @app_commands.describe(word="The word to flag")
    async def add_word(self, interaction: discord.Interaction, word: str):
        word_lower = word.lower().strip()
        if word_lower in self.flagged_words:
            embed = EmbedBuilder.warning(description=f"`{word_lower}` is already in the flagged words list.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        self.flagged_words.append(word_lower)
        save_flagged_words(self.flagged_words)
        embed = EmbedBuilder.success(description=f"Added `{word_lower}` to the flagged words list.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @chatmonitor_group.command(name="remove-word", description="Remove a word from the flagged words list")
    @app_commands.describe(word="The word to remove")
    async def remove_word(self, interaction: discord.Interaction, word: str):
        word_lower = word.lower().strip()
        if word_lower not in self.flagged_words:
            embed = EmbedBuilder.warning(description=f"`{word_lower}` is not in the flagged words list.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        self.flagged_words.remove(word_lower)
        save_flagged_words(self.flagged_words)
        embed = EmbedBuilder.success(description=f"Removed `{word_lower}` from the flagged words list.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @chatmonitor_group.command(name="list-words", description="Show all flagged words")
    async def list_words(self, interaction: discord.Interaction):
        if not self.flagged_words:
            embed = EmbedBuilder.info(description="No flagged words configured. Use `/chatmonitor add-word` to add some.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        words_display = ", ".join(f"`{w}`" for w in sorted(self.flagged_words))
        embed = EmbedBuilder.info(
            title="Flagged Words",
            description=f"**{len(self.flagged_words)} words configured:**\n{words_display}"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @chatmonitor_group.command(name="toggle", description="Enable or disable chat monitoring")
    async def toggle(self, interaction: discord.Interaction):
        self.monitor_config["enabled"] = not self.monitor_config.get("enabled", True)
        save_monitor_config(self.monitor_config)
        status = "enabled" if self.monitor_config["enabled"] else "disabled"
        embed = EmbedBuilder.success(description=f"Chat monitoring is now **{status}**.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @chatmonitor_group.command(name="add-server", description="Add a Minecraft server to monitor")
    @app_commands.describe(
        key="Short identifier for the server (e.g. PWL, PNW)",
        name="Display name for the server",
        console_channel="The DiscordSRV console channel for this server"
    )
    async def add_server(self, interaction: discord.Interaction, key: str, name: str, console_channel: discord.TextChannel):
        key = key.upper().strip()
        self.monitor_config.setdefault("servers", {})[key] = {
            "name": name,
            "console_channel_id": console_channel.id,
            "enabled": True
        }
        save_monitor_config(self.monitor_config)
        self._rebuild_channel_set()
        embed = EmbedBuilder.success(description=f"Added server **{name}** (`{key}`) monitoring console channel {console_channel.mention}.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @chatmonitor_group.command(name="remove-server", description="Remove a Minecraft server from monitoring")
    @app_commands.describe(key="The server identifier to remove (e.g. PWL, PNW)")
    async def remove_server(self, interaction: discord.Interaction, key: str):
        key = key.upper().strip()
        servers = self.monitor_config.get("servers", {})
        if key not in servers:
            embed = EmbedBuilder.warning(description=f"Server `{key}` not found.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        del servers[key]
        save_monitor_config(self.monitor_config)
        self._rebuild_channel_set()
        embed = EmbedBuilder.success(description=f"Removed server `{key}` from monitoring.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @chatmonitor_group.command(name="status", description="Show chat monitor status and configured servers")
    async def status(self, interaction: discord.Interaction):
        enabled = self.monitor_config.get("enabled", True)
        servers = self.monitor_config.get("servers", {})

        status_icon = "🟢" if enabled else "🔴"
        desc = f"**Status:** {status_icon} {'Enabled' if enabled else 'Disabled'}\n"
        desc += f"**Flagged Words:** {len(self.flagged_words)}\n"
        desc += f"**Alert Channel:** <#{self.monitor_config.get('alert_channel_id', 'Not set')}>\n\n"

        if servers:
            desc += "**Monitored Servers:**\n"
            for key, srv in servers.items():
                srv_icon = "🟢" if srv.get("enabled", True) else "🔴"
                desc += f"{srv_icon} **{srv['name']}** (`{key}`) — <#{srv['console_channel_id']}>\n"
        else:
            desc += "No servers configured."

        embed = EmbedBuilder.info(title="Chat Monitor Status", description=desc)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ChatMonitor(bot))
