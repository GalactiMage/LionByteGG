"""
BoilerCraftGG Ticket Commands Cog
Slash commands for managing the ticket system
"""

import discord
from discord.ext import commands
from discord import app_commands
import os
import json

import config
import settings
from views.ticket_view import (
    TicketPanelView, ensure_ticket_panel_message, TICKET_LOG_FILE,
    load_bot_config, save_bot_config
)
from safe_json import safe_json_dump


class TicketCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="setup-tickets",
        description="Deploy the ticket panel in a channel."
    )
    @app_commands.describe(channel="Channel to deploy the ticket panel in")
    async def setup_tickets(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            return

        # Save channel ID to bot_config.json
        cfg = load_bot_config()
        cfg["ticket_panel_channel_id"] = channel.id
        save_bot_config(cfg)

        # Also store in bot settings database for backward compat
        await self.bot.db.connection.execute(
            "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
            ("ticket_panel_channel_id", str(channel.id))
        )
        await self.bot.db.connection.commit()

        # Deploy the panel
        await ensure_ticket_panel_message(self.bot, interaction.guild.id, channel.id)

        await interaction.response.send_message(
            f"✅ Ticket panel deployed in {channel.mention}!",
            ephemeral=True
        )

    @app_commands.command(
        name="blacklist-tickets",
        description="Prevent a user from using the ticket system."
    )
    @app_commands.describe(user="User to blacklist from tickets", reason="Reason for blacklisting")
    async def blacklist_tickets(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            return

        try:
            if os.path.exists(TICKET_LOG_FILE):
                with open(TICKET_LOG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = {"open": [], "closed": [], "blacklist": []}

            # Check if already blacklisted
            existing_ids = [str(entry.get("user_id")) for entry in data.get("blacklist", [])]
            if str(user.id) in existing_ids:
                await interaction.response.send_message(f"⚠️ {user.mention} is already blacklisted.", ephemeral=True)
                return

            data.setdefault("blacklist", []).append({
                "user_id": str(user.id),
                "username": str(user),
                "reason": reason,
                "blacklisted_by": str(interaction.user),
                "blacklisted_at": discord.utils.utcnow().isoformat()
            })

            os.makedirs(os.path.dirname(TICKET_LOG_FILE), exist_ok=True)
            safe_json_dump(data, TICKET_LOG_FILE, indent=2)

            await interaction.response.send_message(
                f"🚫 {user.mention} has been blacklisted from the ticket system.\n**Reason:** {reason}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

    @app_commands.command(
        name="whitelist-tickets",
        description="Allow a user to use the ticket system again."
    )
    @app_commands.describe(user="User to remove from the ticket blacklist")
    async def whitelist_tickets(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            return

        try:
            if os.path.exists(TICKET_LOG_FILE):
                with open(TICKET_LOG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = {"open": [], "closed": [], "blacklist": []}

            original_len = len(data.get("blacklist", []))
            data["blacklist"] = [
                entry for entry in data.get("blacklist", [])
                if str(entry.get("user_id")) != str(user.id)
            ]

            if len(data["blacklist"]) == original_len:
                await interaction.response.send_message(f"⚠️ {user.mention} is not blacklisted.", ephemeral=True)
                return

            safe_json_dump(data, TICKET_LOG_FILE, indent=2)

            await interaction.response.send_message(
                f"✅ {user.mention} has been removed from the ticket blacklist.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(TicketCommands(bot))
