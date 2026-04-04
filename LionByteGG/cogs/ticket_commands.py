import discord
from discord.ext import commands
from discord import app_commands
import re
import asyncio
from datetime import datetime, timedelta, timezone, time as dt_time
import os
import sys
import random
from utils.constants import (
    STUDENT_ROLE_ID,
    ticket_blacklist
)
from views.setup_view import SetupView

class TicketCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="blacklist-tickets", description="Prevent a user from using the ticket system.")
    @app_commands.describe(user="User to blacklist from tickets")
    async def blacklist_tickets(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            return
        ticket_blacklist.add(user.id)
        await interaction.response.send_message(f"🚫 {user.mention} has been blacklisted from the ticket system.", ephemeral=True)

    @app_commands.command(name="whitelist-tickets", description="Allow a user to use the ticket system again.")
    @app_commands.describe(user="User to whitelist for tickets")
    async def whitelist_tickets(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            return
        ticket_blacklist.discard(user.id)
        await interaction.response.send_message(f"✅ {user.mention} has been whitelisted for the ticket system.", ephemeral=True)

