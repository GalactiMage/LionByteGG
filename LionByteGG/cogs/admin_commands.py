import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone, timedelta
import asyncio
import re
import os
import sys
import random
from datetime import time as dt_time
import json

from utils.safe_json import safe_json_load
from views.setup_view import SetupView, AccountSetupModal  # Ensure this import is present
from views.varsity_view import VarsityRegistrationView  # Make sure this is the correct class name
from views.ticket_view import TicketPanelView
from utils.constants import STUDENT_LIFE_LINK, GUILD_ID, STUDENT_ROLE_ID, SECURITY_CODE, GUEST_TIMES_DIR
from utils.log_channels import get_or_create_log_channel, get_or_create_ticket_logs_channel
from utils.arena_status import update_arena_status
from views.setup_view import load_guest_times  # Ensure this import is present
from utils import db as user_db


def get_guest_time_info(user_id):
    path = os.path.join(GUEST_TIMES_DIR, f"{user_id}_guest_time.json")
    return safe_json_load(path, None)

class SecurityCodeModal(discord.ui.Modal, title="Security Check"):
    def __init__(self, action_callback):
        super().__init__()
        self.action_callback = action_callback
        self.security_code = discord.ui.TextInput(
            label="Enter Security Code",
            style=discord.TextStyle.short,
            required=True,
            min_length=1,
            max_length=32
        )
        self.add_item(self.security_code)

    async def on_submit(self, interaction: discord.Interaction):
        if self.security_code.value.strip() != SECURITY_CODE:
            await interaction.response.send_message("❌ Incorrect security code.", ephemeral=True)
            return
        await self.action_callback(interaction)

class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._custom_activity = None  # Track if custom activity is set

    @app_commands.command(name="force-setup-user", description="Manually trigger the onboarding view for a user (mention or user ID).")
    @app_commands.describe(user="User to force setup message to (mention or user ID)")
    async def force_setup(self, interaction: discord.Interaction, user: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You must be an administrator to use this command.", ephemeral=True)
            return

        member = None
        # Try to resolve user as mention or ID
        if user.isdigit():
            member = interaction.guild.get_member(int(user))
        else:
            # Try to resolve as mention
            try:
                member_id = int(re.sub(r'\D', '', user))
                member = interaction.guild.get_member(member_id)
            except Exception:
                member = None

        if not member:
            await interaction.response.send_message("❌ Could not find that user in this server.", ephemeral=True)
            return

        try:
            embed = discord.Embed(
                title="👋 Hello Friend",
                description="You’ve been asked to complete your setup for PNW Esports.\nPlease select one of the options below.",
                color=discord.Color.blue()
            )
            embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
            embed.set_footer(text="PNW Esports | #RoarPRIDE")
            await member.send(embed=embed, view=SetupView(self.bot))
            await interaction.response.send_message(f"✅ Setup sent to {member.mention}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(f"❌ Could not DM {member.mention}.", ephemeral=True)

    @app_commands.command(name="set-activity", description="Set a custom activity status for the bot.")
    @app_commands.describe(activity="The custom activity text to display")
    async def set_activity(self, interaction: discord.Interaction, activity: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only admins can set the bot activity.", ephemeral=True)
            return

        async def do_set_activity(inter):
            await self.bot.change_presence(activity=discord.Game(name=activity))
            self._custom_activity = activity
            await inter.response.send_message(f"✅ Bot activity set to: `{activity}`", ephemeral=True)

        await interaction.response.send_modal(SecurityCodeModal(do_set_activity))

    @app_commands.command(name="reset-activity", description="Reset the bot's activity to the arena open/closed status.")
    async def reset_activity(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only admins can reset the bot activity.", ephemeral=True)
            return
        self._custom_activity = None
        await update_arena_status(self.bot)
        await interaction.response.send_message("🔄 Bot activity reset to arena open/closed status.", ephemeral=True)

    @app_commands.command(name="restart_service", description="Restarts the bot service (Admin only).")
    async def restart_service(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You must be an administrator to use this command.", ephemeral=True)
            return

        async def do_restart(inter):
            await inter.response.send_message("🔄 Restarting the bot...", ephemeral=True)
            await self.bot.close()
            os.execv(sys.executable, ['python'] + sys.argv)

        await interaction.response.send_modal(SecurityCodeModal(do_restart))

    @app_commands.command(name="stop-service", description="Stops and powers off the bot (Admin only).")
    async def stop_service(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You must be an administrator to use this command.", ephemeral=True)
            return

        async def do_stop(inter):
            embed = discord.Embed(
                title="Are you sure you want to power off the bot?",
                description="This will disrupt the setup modules for new users to join and will cause some features to be unusable.",
                color=discord.Color.red()
            )
            await inter.response.send_message(embed=embed, view=StopServiceConfirmView(self.bot), ephemeral=True)

        await interaction.response.send_modal(SecurityCodeModal(do_stop))

    @app_commands.command(name="ping", description="Check the bot's current latency.")
    async def ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong! Latency is `{latency_ms}ms`.")

    @app_commands.command(name="about", description="Learn more about the LionByteGG.")
    async def about(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🤖 About LionByteGG",
            description=(
                "LionByteGG is a custom Discord bot designed for **PNW Esports**.\n\n"
                "It helps automate onboarding, registration, and management for the Purdue Northwest eSports community.\n\n"
                "**Created by:** Mage\n"
                "**Purpose:** Streamline club operations, player registration, and enhance the PNW Esports Discord experience."
            ),
            color=discord.Color.purple()
        )
        embed.set_footer(text="PNW Esports | LionByteGG")
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="club", description="Get the link to join the official PNW Esports Club.")
    async def club(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🦁 Join the Official PNW Esports Club NOW!",
            description=f"Become an official member of the PNW Esports Club and unlock all the benefits!\n\n[Click here to join the club]({STUDENT_LIFE_LINK})",
            color=discord.Color.gold()
        )
        embed.set_footer(text="PNW Esports | Club")
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="arena-hours", description="View the PNW Esports Arena hours.")
    async def arena_hours(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🕒 PNW Esports Arena Hours",
            description=(
                "**Monday:** 10:00 AM – 5:00 PM\n"
                "**Tuesday:** 10:00 AM – 5:00 PM\n"
                "**Wednesday:** 10:00 AM – 5:00 PM\n"
                "**Thursday:** 10:00 AM – 5:00 PM\n"
                "**Friday:** 10:00 AM – 5:00 PM\n"
                "**Saturday:** Closed\n"
                "**Sunday:** 10:00 AM – 2:00 PM\n\n"
                "Location: SULB 103 (Hammond Campus)\n"
                "Hours may vary during holidays or Breaks.\n"
                "Check the #announcements channel for updates."
            ),
            color=discord.Color.blue()
        )
        embed.set_footer(text="PNW Esports | Arena Hours")
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1316453330695884912/1362053646170325032/8875956.png?ex=68311d8e&is=682fcc0e&hm=22ee9eda167320e625fb420c9686b15baf0b13d5e3c39fbbae6e03ae5d8c3b78&")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="help", description="Show all available bot commands.")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🤖 LionByteGG Help",
            description="Here are the available commands:",
            color=discord.Color.green()
        )
        embed.add_field(name="/help", value="Show this help message.", inline=False)
        embed.add_field(name="/ping", value="Check the bot's current latency.", inline=False)
        embed.add_field(name="/about", value="Learn more about LionByteGG.", inline=False)
        embed.add_field(name="/club", value="Get the link to join the official PNW Esports Club.", inline=False)
        embed.add_field(name="/arena-hours", value="View the PNW Esports Arena hours.", inline=False)
        # Add more commands here as you implement them

        embed.set_footer(text="PNW Esports | LionByteGG")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="join-mc-server", description="Get info about the upcoming Purdue Northwest Minecraft server.")
    async def join_mc_server(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🟨 COMING SOON!",
            description="**PURDUE NORTHWEST MINECRAFT SERVER 2025**\nStay tuned for more details and launch announcements!",
            color=discord.Color.gold()
        )
        embed.set_footer(text="PNW Esports | Minecraft Division")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clear", description="Delete a number of recent messages in this channel.")
    @app_commands.describe(amount="Number of messages to delete (max 100)")
    async def clear(self, interaction: discord.Interaction, amount: int):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You must be an administrator to use this command.", ephemeral=True)
            return
        if amount < 1 or amount > 100:
            await interaction.response.send_message("Please specify a number between 1 and 100.", ephemeral=True)
            return
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.response.send_message(f"🧹 Deleted {len(deleted)} messages.", ephemeral=True)

    @app_commands.command(name="warn", description="Warn a user and log the reason.")
    @app_commands.describe(user="User to warn", reason="Reason for warning")
    async def warn(self, interaction: discord.Interaction, user: discord.Member, reason: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            return
        embed = discord.Embed(
            title="⚠️ Official Violation Notice",
            description=(
                f"Dear {user.mention},\n\n"
                "You have received an official violation notice from the **Purdue University Northwest eSports Discord Server** moderation team.\n\n"
                f"**Reason:** {reason}\n\n"
                "Please review the server rules and ensure future compliance. Continued violations may result in further disciplinary action."
            ),
            color=discord.Color.orange()
        )
        embed.set_footer(text="PNW Esports | Moderation Team")
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        try:
            await user.send(embed=embed)
        except Exception:
            pass
        await interaction.response.send_message(f"⚠️ {user.mention} has received a violation. Reason: {reason}", ephemeral=True)
        # Log to lionbytegg-logs
        log_channel = await get_or_create_log_channel(interaction.guild)
        log_embed = discord.Embed(
            title="⚠️ Violation Issued",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc)
        )
        log_embed.add_field(name="Violation Issued To", value=f"{user} (ID: {user.id})", inline=False)
        log_embed.add_field(name="Moderator", value=f"{interaction.user} (ID: {interaction.user.id})", inline=False)
        log_embed.add_field(name="Reason", value=reason, inline=False)
        log_embed.set_footer(text="PNW Esports | Moderation Log (LionByteGG)")
        log_embed.set_thumbnail(url=user.display_avatar.url)
        await log_channel.send(embed=log_embed)
        # Record to user_records
        moderation_cog = interaction.client.get_cog("Moderation")
        if moderation_cog:
            moderation_cog.add_record(
                str(user.id), "Violation", reason,
                moderator_name=str(interaction.user), moderator_id=interaction.user.id
            )

    @app_commands.command(name="kick", description="Kick a user from the server.")
    @app_commands.describe(user="User to kick", reason="Reason for kick")
    async def kick(self, interaction: discord.Interaction, user: discord.Member, reason: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            return
        embed = discord.Embed(
            title="👢 Notice of Removal from PNW Esports Discord",
            description=(
                f"Dear {user.mention},\n\n"
                "You have been **removed (kicked)** from the **Purdue University Northwest eSports Discord Server** by the moderation team.\n\n"
                f"**Reason:** {reason}\n\n"
                "If you believe this was a mistake or wish to appeal, please contact a server administrator."
            ),
            color=discord.Color.red()
        )
        embed.set_footer(text="PNW Esports | Moderation Team")
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        try:
            await user.send(embed=embed)
        except Exception:
            pass
        try:
            await user.kick(reason=reason)
            await interaction.response.send_message(f"👢 {user.mention} has been kicked. Reason: {reason}", ephemeral=True)
            # Log to lionbytegg-logs
            log_channel = await get_or_create_log_channel(interaction.guild)
            log_embed = discord.Embed(
                title="👢 User Kicked",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
            log_embed.add_field(name="Kicked User", value=f"{user} (ID: {user.id})", inline=False)
            log_embed.add_field(name="Moderator", value=f"{interaction.user} (ID: {interaction.user.id})", inline=False)
            log_embed.add_field(name="Reason", value=reason, inline=False)
            log_embed.set_footer(text="PNW Esports | Moderation Log (LionByteGG)")
            log_embed.set_thumbnail(url=user.display_avatar.url)
            await log_channel.send(embed=log_embed)
            # Record to user_records
            moderation_cog = interaction.client.get_cog("Moderation")
            if moderation_cog:
                moderation_cog.add_record(
                    str(user.id), "Kick", reason,
                    moderator_name=str(interaction.user), moderator_id=interaction.user.id
                )
        except Exception as e:
            await interaction.response.send_message(f"Failed to kick: {e}", ephemeral=True)

    @app_commands.command(name="ban", description="Ban a user from the server.")
    @app_commands.describe(user="User to ban", reason="Reason for ban")
    async def ban(self, interaction: discord.Interaction, user: discord.Member, reason: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🔨 Notice of Ban from PNW Esports Discord",
            description=(
                f"Dear {user.mention},\n\n"
                "You have been **banned** from the **Purdue Northwest eSports Discord Server** by the moderation team.\n\n"
                f"**Reason:** {reason}\n\n"
                "If you believe this action was taken in error or wish to appeal, please contact a server administrator outside of Discord."
            ),
            color=discord.Color.dark_red()
        )
        embed.set_footer(text="PNW Esports | Moderation Team")
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        try:
            await user.send(embed=embed)
        except Exception:
            pass
        try:
            await user.ban(reason=reason)
            await interaction.response.send_message(f"🔨 {user.mention} has been banned. Reason: {reason}", ephemeral=True)
            # Log to lionbytegg-logs
            log_channel = await get_or_create_log_channel(interaction.guild)
            log_embed = discord.Embed(
                title="🔨 User Banned",
                color=discord.Color.dark_red(),
                timestamp=datetime.now(timezone.utc)
            )
            log_embed.add_field(name="Banned User", value=f"{user} (ID: {user.id})", inline=False)
            log_embed.add_field(name="Moderator", value=f"{interaction.user} (ID: {interaction.user.id})", inline=False)
            log_embed.add_field(name="Reason", value=reason, inline=False)
            log_embed.set_footer(text="PNW Esports | Moderation Log (LionByteGG)")
            log_embed.set_thumbnail(url=user.display_avatar.url)
            await log_channel.send(embed=log_embed)
            # Record to user_records
            moderation_cog = interaction.client.get_cog("Moderation")
            if moderation_cog:
                moderation_cog.add_record(
                    str(user.id), "Ban", reason,
                    moderator_name=str(interaction.user), moderator_id=interaction.user.id
                )
        except Exception as e:
            await interaction.response.send_message(f"Failed to ban: {e}", ephemeral=True)

    @app_commands.command(name="unban", description="Unban a user by user ID.")
    @app_commands.describe(user_id="User ID to unban")
    async def unban(self, interaction: discord.Interaction, user_id: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            return
        try:
            user = await interaction.guild.fetch_ban(discord.Object(id=int(user_id)))
            await interaction.guild.unban(user.user)
            await interaction.response.send_message(f"✅ Unbanned user with ID {user_id}.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Failed to unban: {e}", ephemeral=True)

    @app_commands.command(name="mute", description="Mute a user for a duration (in minutes).")
    @app_commands.describe(user="User to mute", duration="Duration in minutes", reason="Reason for mute")
    async def mute(self, interaction: discord.Interaction, user: discord.Member, duration: int, reason: str = "No reason provided"):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            return
        try:
            if not interaction.guild.me.guild_permissions.moderate_members:
                await interaction.response.send_message("❌ I need the 'Moderate Members' permission.", ephemeral=True)
                return
            until = discord.utils.utcnow() + timedelta(minutes=duration)
            await user.timeout(until, reason=reason)
            await interaction.response.send_message(f"🔇 {user.mention} has been muted for {duration} minutes. Reason: {reason}", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Failed to mute: {e}", ephemeral=True)

    @app_commands.command(name="announce", description="Send an announcement to a channel.")
    @app_commands.describe(channel="Channel to announce in", message="Announcement message")
    async def announce(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            return
        # Student role ID for ping
        STUDENT_ROLE_ID = 745068163313434716
        student_role = interaction.guild.get_role(STUDENT_ROLE_ID)
        mention = student_role.mention if student_role else "@students"
        embed = discord.Embed(
            title="📢 Announcement",
            description=message,
            color=discord.Color.gold()
        )
        embed.set_footer(text="PNW Esports | Announcement")
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        try:
            await channel.send(content=mention, embed=embed)
            await interaction.response.send_message("Announcement sent.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Failed to announce: {e}", ephemeral=True)

    @app_commands.command(name="lock", description="Lock a channel so only admins can send messages.")
    @app_commands.describe(channel="Channel to lock")
    async def lock(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            return
        try:
            overwrite = channel.overwrites_for(interaction.guild.default_role)
            overwrite.send_messages = False
            await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            await interaction.response.send_message(f"🔒 {channel.mention} is now locked.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Failed to lock: {e}", ephemeral=True)

    @app_commands.command(name="unlock", description="Unlock a channel for everyone to send messages.")
    @app_commands.describe(channel="Channel to unlock")
    async def unlock(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            return
        try:
            overwrite = channel.overwrites_for(interaction.guild.default_role)
            overwrite.send_messages = None
            await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            await interaction.response.send_message(f"🔓 {channel.mention} is now unlocked.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Failed to unlock: {e}", ephemeral=True)

    @app_commands.command(name="serverinfo", description="Show info about the server.")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        embed = discord.Embed(
            title=f"Server Info: {guild.name}",
            color=discord.Color.green()
        )
        embed.add_field(name="Server ID", value=guild.id, inline=True)
        embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True)
        embed.add_field(name="Members", value=guild.member_count, inline=True)
        embed.add_field(name="Roles", value=len(guild.roles), inline=True)
        embed.add_field(name="Channels", value=len(guild.channels), inline=True)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="setup-tickets", description="Setup the PNW Esports Support Ticket system in this channel.")
    async def setup_tickets(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only admins can setup the ticket system.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🎫 Welcome to the PNW Esports Support System",
            description=(
                "Our support system helps you quickly get assistance from staff for a variety of needs.\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🔹 Discord issues or reports\n"
                "🔹 Minecraft server support\n"
                "🔹 Clubs questions/support\n"
                "🔹 Arena PC (Technician) help\n"
                "🔹 Varsity team support\n"
                "🔹 Anything else!\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Press **Contact Support** below to open a ticket and our team will assist you as soon as possible."
            ),
            color=discord.Color.gold()
        )
        embed.set_image(url="https://cdn.discordapp.com/attachments/1316453330695884912/1416456368038088714/discord_contact.png?ex=68c6e94a&is=68c597ca&hm=42ebe829706c54dbfdd10252a1ba69735302d3875257456b5c2725bca5f1b826&")
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        embed.set_footer(text="PNW Esports | Support System")
        await interaction.channel.send(embed=embed, view=TicketPanelView())
        await interaction.response.send_message("✅ Ticket system panel created in this channel.", ephemeral=True)

    @app_commands.command(name="setup_guest_transfer", description="Post a permanent message for Guests to migrate to Student.")
    @app_commands.describe(channel="Channel to post the migration message in")
    async def setup_guest_transfer(self, interaction: discord.Interaction, channel: discord.TextChannel):
        embed = discord.Embed(
            title="🎓 Migrate to Student",
            description=(
                "Are you now a Purdue Northwest student? Migrate your Guest account to a Student account!\n\n"
                "Click the **Migrate** button below to begin the Student registration process. You will need to provide your Purdue email and other details."
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text="PNW Esports | Guest to Student Migration")
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        await channel.send(embed=embed, view=MigrateToStudentView(self.bot))
        await interaction.response.send_message("✅ Migration panel posted.", ephemeral=True)

    @app_commands.command(name="time", description="Show how much time you have left as a Guest in the server.")
    async def time(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        info = get_guest_time_info(user_id)
        if not info:
            await interaction.response.send_message("You are not registered as a Guest.", ephemeral=True)
            return
        expires_str = info.get("expires_at")
        try:
            expires_at = datetime.fromisoformat(expires_str)
        except Exception:
            await interaction.response.send_message("Could not determine your expiration time.", ephemeral=True)
            return
        now = datetime.now(timezone.utc)
        remaining = expires_at - now
        if remaining.total_seconds() <= 0:
            await interaction.response.send_message("Your Guest access has expired.", ephemeral=True)
            return
        days = remaining.days
        hours, remainder = divmod(remaining.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        embed = discord.Embed(
            title="⏰ Guest Time Remaining",
            description=f"You have **{days} days, {hours} hours, {minutes} minutes** left as a Guest in the server.",
            color=discord.Color.orange()
        )
        embed.set_footer(text="PNW Esports | Guest Access")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="force-register-all", description="DM the registration setup to everyone without the Students role.")
    async def force_register_all(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You must be an administrator to use this command.", ephemeral=True)
            return

        view = ConfirmRegisterAllView(interaction.user)
        await interaction.response.send_message(
            "**Warning:** This will DM the registration setup to **everyone** in the server who does not have the Students role. Are you sure you want to continue?",
            view=view,
            ephemeral=True
        )
        await view.wait()

        if not view.value:
            return  # Cancelled or timed out

        guild = interaction.guild
        student_role = guild.get_role(STUDENT_ROLE_ID)
        if not student_role:
            await interaction.followup.send("❌ Student role not found.", ephemeral=True)
            return

        embed = discord.Embed(
            title="👋 Hello Friend",
            description="You’ve been asked to complete your setup for PNW Esports.\nPlease select one of the options below.",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        embed.set_footer(text="PNW Esports | #RoarPRIDE")

        # --- Threshold logic ---
        threshold = 50
        # Only non-bot members without the Students role will be DM'd
        members_to_dm = [member for member in guild.members if not member.bot and student_role not in member.roles]
        if len(members_to_dm) > threshold:
            confirm_view = ConfirmRegisterAllView(interaction.user)
            await interaction.followup.send(
                f"⚠️ There are {len(members_to_dm)} users to DM. This may cause rate limiting. Do you want to proceed?",
                view=confirm_view,
                ephemeral=True
            )
            await confirm_view.wait()
            if not confirm_view.value:
                await interaction.followup.send("❌ Aborted due to threshold.", ephemeral=True)
                return

        count = 0
        for member in members_to_dm:
            try:
                await member.send(embed=embed, view=SetupView(self.bot))
                count += 1
                await asyncio.sleep(2)  # Add delay to avoid rate limiting (2 seconds per DM)
            except discord.Forbidden:
                pass  # Ignore users who have DMs closed

        await interaction.followup.send(f"✅ Registration DM sent to {count} users without the Students role.", ephemeral=True)

    @app_commands.command(name="download-transcript", description="Download a user's moderation record as a transcript file.")
    @app_commands.describe(user="User to get transcript for")
    async def download_transcript(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            return
        moderation_cog = interaction.client.get_cog("Moderation")
        if not moderation_cog:
            await interaction.response.send_message("Moderation records not available.", ephemeral=True)
            return
        user_id = str(user.id)
        record = user_db.get_records(user_id)
        if not record:
            await interaction.response.send_message("No Record, Good Standing.", ephemeral=True)
            return
        lines = []
        for entry in record:
            lines.append(f"{entry['timestamp']} | {entry['type']}: {entry['reason']}")
        transcript_text = "\n".join(lines)
        filename = f"{user.id}_transcript.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(transcript_text)
        await interaction.response.send_message(file=discord.File(filename), ephemeral=True)
        os.remove(filename)

    @app_commands.command(
        name="setup_reaction_role",
        description="Attach a reaction role to an existing message"
    )
    @app_commands.describe(
        channel="Channel containing the message",
        message_id="The ID of the message to attach the reaction role to",
        emoji="The emoji to use for the reaction",
        role="The role to assign when the emoji is reacted"
    )
    async def setup_reaction_role(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message_id: str,
        emoji: str,
        role: discord.Role
    ):
        # Try to fetch the message from the specified channel
        try:
            message_id_int = int(message_id)
            message = await channel.fetch_message(message_id_int)
        except Exception:
            await interaction.response.send_message("Could not find the message with that ID in the selected channel.", ephemeral=True)
            return

        # Try to add the reaction
        try:
            await message.add_reaction(emoji)
        except Exception:
            await interaction.response.send_message("Could not add that emoji as a reaction.", ephemeral=True)
            return

        reaction_roles_cog = self.bot.get_cog("ReactionRoles")
        if reaction_roles_cog:
            reaction_roles_cog.update_reaction_role(message_id_int, emoji, role.id)
            await interaction.response.send_message(
                f"Reaction role set: {emoji} → {role.mention} on [message]({message.jump_url}) in {channel.mention}.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message("ReactionRoles cog not loaded.", ephemeral=True)

    @app_commands.command(name="admin-help", description="Show all admin commands and what they do.")
    async def admin_help(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return

        # Split commands into pages (20 per page for Discord embed field limit)
        commands_list = [
            ("/force-setup-user", "Manually trigger the onboarding view for a user."),
            ("/userinfo", "Show info about a user (Admin only)."),
            ("/set-activity", "Set a custom activity status for the bot."),
            ("/reset-activity", "Reset the bot's activity to the arena open/closed status."),
            ("/restart_service", "Restarts the bot service."),
            ("/stop-service", "Stops and powers off the bot."),
            ("/clear", "Delete a number of recent messages in this channel."),
            ("/warn", "Warn a user and log the reason."),
            ("/kick", "Kick a user from the server."),
            ("/ban", "Ban a user from the server."),
            ("/unban", "Unban a user by user ID."),
            ("/mute", "Mute a user for a duration (in minutes)."),
            ("/announce", "Send an announcement to a channel."),
            ("/lock", "Lock a channel so only admins can send messages."),
            ("/unlock", "Unlock a channel for everyone to send messages."),
            ("/force-register-all", "DM the registration setup to everyone without the Students role."),
            ("/download-transcript", "Download a user's moderation record as a transcript file."),
            ("/setup_reaction_role", "Attach a reaction role to an existing message."),
            ("/setup-tickets", "Setup the PNW Esports Support Ticket system in this channel."),
            ("/setup_guest_transfer", "Post a permanent message for Guests to migrate to Student."),
            ("/setup_ggleapgames", "Setup a GGLeap games/apps dashboard in this channel."),
            ("/sync-games", "Manually refresh the GGLeap games/apps dashboard for all guilds."),
            ("/setup_ggpanel", "Setup a GGLeap device status panel in this channel."),
            ("/pclookup", "Lookup the status of a specific PC."),
            ("/addword", "Add a word to the moderation database."),
            ("/removeword", "Remove a word from the moderation database."),
            ("/Records", "Download a user's moderation record as a transcript file."),
            ("/blacklist-tickets", "Prevent a user from using the ticket system."),
            ("/whitelist-tickets", "Allow a user to use the ticket system again."),
            ("/mc-maintenance-announcement", "Announce Minecraft server maintenance to all Minecraft role members."),
            ("/setup_vc_generator", "Setup a VC generator with a voice channel and category."),
            ("/setup_tryout_vc", "Setup a tryout VC generator with a voice channel and category."),
            ("/list_vc_generators", "List all current VC generators."),
            # ...add more as needed...
        ]
        page_size = 10
        total_pages = (len(commands_list) + page_size - 1) // page_size

        def make_embed(page):
            embed = discord.Embed(
                title="🛠️ Admin Commands Help",
                color=discord.Color.red(),
                description=f"List of admin-only commands for managing the server and LionByteGG.\n\n**Page {page+1}/{total_pages}**"
            )
            start = page * page_size
            end = start + page_size
            for cmd, desc in commands_list[start:end]:
                embed.add_field(name=cmd, value=desc, inline=False)
            embed.set_footer(text="PNW Esports | Admin Help")
            return embed

        class AdminHelpPages(discord.ui.View):
            def __init__(self, page=0):
                super().__init__(timeout=120)
                self.page = page

            @discord.ui.button(label="⬅️ Previous", style=discord.ButtonStyle.secondary)
            async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
                if self.page > 0:
                    self.page -= 1
                    await interaction.response.edit_message(embed=make_embed(self.page), view=self)
                else:
                    await interaction.response.defer()

            @discord.ui.button(label="Next ➡️", style=discord.ButtonStyle.secondary)
            async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
                if self.page < total_pages - 1:
                    self.page += 1
                    await interaction.response.edit_message(embed=make_embed(self.page), view=self)
                else:
                    await interaction.response.defer()

        await interaction.response.send_message(embed=make_embed(0), view=AdminHelpPages(), ephemeral=True)

    @app_commands.command(name="say", description="Make the bot say a message in this channel (Admin only).")
    @app_commands.describe(message="The message for the bot to say")
    async def say(self, interaction: discord.Interaction, message: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            return
        await interaction.channel.send(message)
        await interaction.response.send_message("✅ Message sent.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(AdminCommands(bot))

class ConfirmRegisterAllView(discord.ui.View):
    def __init__(self, author: discord.User):
        super().__init__(timeout=60)
        self.author = author
        self.value = None

    @discord.ui.button(label="Yes, send to everyone", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            await interaction.response.send_message("Only the command invoker can confirm this action.", ephemeral=True)
            return
        self.value = True
        self.stop()
        await interaction.response.edit_message(content="✅ Sending registration DM to all users without the Students role...", view=None)

    @discord.ui.button(label="No, cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            await interaction.response.send_message("Only the command invoker can cancel this action.", ephemeral=True)
            return
        self.value = False
        self.stop()
        await interaction.response.edit_message(content="❌ Cancelled. No messages were sent.", view=None)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

class ForceRegisterAllConfirmView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=60)
        self.bot = bot

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        success_count = 0
        failure_count = 0
        failed_users = []

        embed = discord.Embed(
            title="👋 Hello PNW Esports Member",
            description="We're excited to have you in the PNW Esports community! To get started, please complete your setup by selecting one of the options below.",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        embed.set_footer(text="PNW Esports | #RoarPRIDE")

        for member in interaction.guild.members:
            if member.bot:
                continue  # Skip bots
            try:
                await member.send(embed=embed, view=SetupView(self.bot))
                success_count += 1
            except Exception as e:
                failure_count += 1
                failed_users.append(f"{member} - {str(e)}")
            await asyncio.sleep(2)  # 2 seconds per DM to avoid rate limits

        summary_embed = discord.Embed(
            title="✅ Onboarding DM Summary",
            description=(
                f"Successfully sent onboarding messages to **{success_count}** members.\n"
                f"Failed to send messages to **{failure_count}** members. See details below."
            ),
            color=discord.Color.green() if failure_count == 0 else discord.Color.red()
        )
        summary_embed.set_footer(text="PNW Esports | Onboarding")
        await interaction.followup.send(embed=summary_embed, ephemeral=True)

        if failure_count > 0:
            failed_embed = discord.Embed(
                title="❌ Failed to Send Onboarding DM",
                description="Here are the members who could not be messaged:",
                color=discord.Color.red()
            )
            failed_embed.add_field(name="Failed Users", value="\n".join(failed_users), inline=False)
            failed_embed.set_footer(text="PNW Esports | Onboarding Errors")
            await interaction.channel.send(embed=failed_embed)

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❌ Action cancelled.", ephemeral=True)

    async def on_timeout(self):
        pass

class MigrateToStudentView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)  # Persistent view
        self.bot = bot

    @discord.ui.button(label="Migrate", style=discord.ButtonStyle.success, custom_id="migrate_to_student")
    async def migrate(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AccountSetupModal(self.bot, parent_view=None, interaction_message=None))

    async def on_timeout(self):
        pass

class ConfirmClearRecordView(discord.ui.View):
    def __init__(self, user_id, moderation_cog, embed, interaction, parent_view):
        super().__init__(timeout=30)
        self.user_id = user_id
        self.moderation_cog = moderation_cog
        self.embed = embed
        self.interaction = interaction
        self.parent_view = parent_view

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only admins can clear records.", ephemeral=True)
            return
        # Clear the record
        user_db.clear_records(self.user_id)
        cleared = True
        # Update embed
        self.embed.clear_fields()
        user = interaction.guild.get_member(int(self.user_id))
        self.embed.title = f"User Info: {user}" if user else "User Info"
        self.embed.add_field(name="ID", value=self.user_id, inline=True)
        if user:
            self.embed.add_field(name="Joined", value=user.joined_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
            self.embed.add_field(name="Created", value=user.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
            self.embed.add_field(name="Top Role", value=user.top_role.mention, inline=True)
            self.embed.add_field(name="Bot?", value=str(user.bot), inline=True)
            self.embed.add_field(name="Roles", value=user.roles, inline=False)
        self.embed.add_field(name="Violations", value="0", inline=True)
        self.embed.add_field(name="Record Summary", value="No Record, Good Standing", inline=False)
        await interaction.response.edit_message(embed=self.embed, view=self.parent_view)
        await interaction.followup.send("✅ Record cleared.", ephemeral=True)
        # Log to lionbyteGG-logs (fix: use correct channel name and fallback)
        if cleared:
            log_channel = discord.utils.get(interaction.guild.text_channels, name="lionbyte-logs")
            if not log_channel:
                log_channel = discord.utils.get(interaction.guild.text_channels, name="lionbyte-logs")
            if log_channel:
                log_embed = discord.Embed(
                    title="🗑️ User Record Cleared",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc)
                )
                log_embed.add_field(name="User", value=f"{user} (ID: {self.user_id})", inline=False)
                log_embed.add_field(name="Moderator", value=f"{interaction.user} (ID: {interaction.user.id})", inline=False)
                log_embed.set_footer(text="PNW Esports | Moderation Log (LionByteGG)")
                if user:
                    log_embed.set_thumbnail(url=user.display_avatar.url)
                await log_channel.send(embed=log_embed)

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=self.parent_view)
        await interaction.followup.send("❌ Record not cleared.", ephemeral=True)

    async def on_timeout(self):
        try:
            await self.interaction.edit_original_response(view=self.parent_view)
        except Exception:
            pass

class KickBanModal(discord.ui.Modal):
    def __init__(self, action, user, moderation_cog, parent_view):
        super().__init__(title=f"{action} User")
        self.action = action
        self.user = user
        self.moderation_cog = moderation_cog
        self.parent_view = parent_view
        self.reason = discord.ui.TextInput(label="Reason", style=discord.TextStyle.paragraph, required=True, max_length=300)
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(self.user.id)
        reason_text = self.reason.value
        log_channel = discord.utils.get(interaction.guild.text_channels, name="lionbyte-logs")
        if self.action == "Kick":
            try:
                embed = discord.Embed(
                    title="👢 Notice of Removal from PNW Esports Discord",
                    description=(
                        f"Dear {self.user.mention},\n\n"
                        "You have been **removed (kicked)** from the **Purdue University Northwest eSports Discord Server** by the moderation team.\n\n"
                        f"**Reason:** {reason_text}\n\n"
                        "If you believe this was a mistake or wish to appeal, please contact a server administrator."
                    ),
                    color=discord.Color.red()
                )
                embed.set_footer(text="PNW Esports | Moderation Team")
                embed.set_thumbnail(url=self.user.display_avatar.url)
                try:
                    await self.user.send(embed=embed)
                except Exception:
                    pass
                await self.user.kick(reason=reason_text)
                # Add to record
                self.moderation_cog.add_record(
                    user_id, "Kick", reason_text,
                    moderator_name=str(interaction.user), moderator_id=interaction.user.id
                )
                await interaction.response.send_message(f"👢 {self.user.mention} has been kicked. Reason: {reason_text}", ephemeral=True)
                # Log to lionbyte-logs
                if log_channel:
                    log_embed = discord.Embed(
                        title="👢 User Kicked",
                        color=discord.Color.red(),
                        timestamp=datetime.now(timezone.utc)
                    )
                    log_embed.add_field(name="Kicked User", value=f"{self.user} (ID: {self.user.id})", inline=False)
                    log_embed.add_field(name="Moderator", value=f"{interaction.user} (ID: {interaction.user.id})", inline=False)
                    log_embed.add_field(name="Reason", value=reason_text, inline=False)
                    log_embed.set_footer(text="PNW Esports | Moderation Log (LionByteGG)")
                    log_embed.set_thumbnail(url=self.user.display_avatar.url)
                    await log_channel.send(embed=log_embed)
            except Exception as e:
                await interaction.response.send_message(f"Failed to kick: {e}", ephemeral=True)
        elif self.action == "Ban":
            try:
                embed = discord.Embed(
                    title="🔨 Notice of Ban from PNW Esports Discord",
                    description=(
                        f"Dear {self.user.mention},\n\n"
                        "You have been **banned** from the **Purdue Northwest eSports Discord Server** by the moderation team.\n\n"
                        f"**Reason:** {reason_text}\n\n"
                        "If you believe this action was taken in error or wish to appeal, please contact a server administrator outside of Discord."
                    ),
                    color=discord.Color.dark_red()
                )
                embed.set_footer(text="PNW Esports | Moderation Team")
                embed.set_thumbnail(url=self.user.display_avatar.url)
                try:
                    await self.user.send(embed=embed)
                except Exception:
                    pass
                await self.user.ban(reason=reason_text)
                # Add to record
                self.moderation_cog.add_record(
                    user_id, "Ban", reason_text,
                    moderator_name=str(interaction.user), moderator_id=interaction.user.id
                )
                await interaction.response.send_message(f"🔨 {self.user.mention} has been banned. Reason: {reason_text}", ephemeral=True)
                # Log to lionbyte-logs
                if log_channel:
                    log_embed = discord.Embed(
                        title="🔨 User Banned",
                        color=discord.Color.dark_red(),
                        timestamp=datetime.now(timezone.utc)
                    )
                    log_embed.add_field(name="Banned User", value=f"{self.user} (ID: {self.user.id})", inline=False)
                    log_embed.add_field(name="Moderator", value=f"{interaction.user} (ID: {interaction.user.id})", inline=False)
                    log_embed.add_field(name="Reason", value=reason_text, inline=False)
                    log_embed.set_footer(text="PNW Esports | Moderation Log (LionByteGG)")
                    log_embed.set_thumbnail(url=self.user.display_avatar.url)
                    await log_channel.send(embed=log_embed)
            except Exception as e:
                await interaction.response.send_message(f"Failed to ban: {e}", ephemeral=True)
        # Optionally, you can refresh the embed in parent_view here

class ClearRecordView(discord.ui.View):
    def __init__(self, user_id, moderation_cog, embed, interaction, show_clear_record, show_cancel_timer):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.moderation_cog = moderation_cog
        self.embed = embed
        self.interaction = interaction

        if show_clear_record:
            self.add_item(self.ClearRecordButton())
        if show_cancel_timer:
            self.add_item(self.CancelTimerButton())

    class ClearRecordButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="Clear Record", style=discord.ButtonStyle.danger)

        async def callback(self, interaction: discord.Interaction):
            view = self.view
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Only admins can clear records.", ephemeral=True)
                return
            confirm_view = ConfirmClearRecordView(view.user_id, view.moderation_cog, view.embed, interaction, view)
            await interaction.response.edit_message(content="ARE YOU SURE you want to clear this user's record?", view=confirm_view)

    class CancelTimerButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="Cancel Timer", style=discord.ButtonStyle.danger, row=1)

        async def callback(self, interaction: discord.Interaction):
            view = self.view
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Only admins can cancel guest timers.", ephemeral=True)
                return
            guest_times = load_guest_times()
            if view.user_id in guest_times:
                del guest_times[view.user_id]
                # Remove the guest timer JSON file instead of save_guest_times
                import os
                path = os.path.join(GUEST_TIMES_DIR, f"{view.user_id}_guest_time.json")
                if os.path.exists(path):
                    os.remove(path)
                # Update embed
                for i, field in enumerate(view.embed.fields):
                    if field.name == "Guest Time Left":
                        view.embed.set_field_at(i, name="Guest Time Left", value="Timer Cancelled", inline=True)
                await interaction.response.edit_message(embed=view.embed, view=view)
                await interaction.followup.send("✅ Guest timer cancelled for this user.", ephemeral=True)
                # Log to lionbyte-logs channel
                guild = interaction.guild
                log_channel = discord.utils.get(guild.text_channels, name="lionbyte-logs")
                if log_channel:
                    user = guild.get_member(int(view.user_id))
                    log_embed = discord.Embed(
                        title="⏰ Guest Timer Cancelled",
                        color=discord.Color.red(),
                        timestamp=datetime.now(timezone.utc)
                    )
                    log_embed.add_field(name="User", value=f"{user} (ID: {view.user_id})" if user else f"ID: {view.user_id}", inline=False)
                    log_embed.add_field(name="Moderator", value=f"{interaction.user} (ID: {interaction.user.id})", inline=False)
                    log_embed.set_footer(text="PNW Esports | Moderation Log (LionByteGG)")
                    if user:
                        log_embed.set_thumbnail(url=user.display_avatar.url)
                    await log_channel.send(embed=log_embed)
            else:
                await interaction.response.send_message("This user does not have a guest timer.", ephemeral=True)

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.primary, emoji="👢")
    async def kick_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message("❌ You need the Kick Members permission.", ephemeral=True)
            return
        user = interaction.guild.get_member(int(self.user_id))
        if user:
            await interaction.response.send_modal(KickBanModal("Kick", user, self.moderation_cog, self))
        else:
            await interaction.response.send_message("User not found in guild.", ephemeral=True)

    @discord.ui.button(label="Ban", style=discord.ButtonStyle.danger, emoji="🔨")
    async def ban_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("❌ You need the Ban Members permission.", ephemeral=True)
            return
        user = interaction.guild.get_member(int(self.user_id))
        if user:
            await interaction.response.send_modal(KickBanModal("Ban", user, self.moderation_cog, self))
        else:
            await interaction.response.send_message("User not found in guild.", ephemeral=True)

    async def on_timeout(self):
        try:
            await self.interaction.edit_original_response(view=None)
        except Exception:
            pass

class StopServiceConfirmView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=60)
        self.bot = bot

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🛑 Shutting down the bot...", ephemeral=True)
        await self.bot.close()

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❌ Shutdown cancelled.", ephemeral=True)
        self.stop()
