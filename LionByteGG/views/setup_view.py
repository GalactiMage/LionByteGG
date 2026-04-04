import discord
import re
import asyncio
import random
import json
import os
from datetime import datetime, timezone, timedelta
from discord.ext import tasks
from datetime import time as dt_time

from utils.constants import (
    GUILD_ID,
    STUDENT_ROLE_ID,
    GUEST_ROLE_ID,
    pending_users,
    STUDENT_LIFE_LINK
)
from utils.log_channels import get_or_create_log_channel
from utils.safe_json import safe_json_dump

GUEST_TIMES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../guest_times"))
USER_RECORDS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../user_records"))


def ensure_guest_times_dir():
    os.makedirs(GUEST_TIMES_DIR, exist_ok=True)


def ensure_user_records_dir():
    os.makedirs(USER_RECORDS_DIR, exist_ok=True)


def guest_time_path(user_id):
    ensure_guest_times_dir()
    return os.path.join(GUEST_TIMES_DIR, f"{user_id}_guest_time.json")


def user_record_path(user_id):
    ensure_user_records_dir()
    return os.path.join(USER_RECORDS_DIR, f"{user_id}_record.json")


def load_guest_times():
    ensure_guest_times_dir()
    guest_times = {}
    for fname in os.listdir(GUEST_TIMES_DIR):
        if fname.endswith("_guest_time.json"):
            try:
                with open(os.path.join(GUEST_TIMES_DIR, fname), "r") as f:
                    data = json.load(f)
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


async def remove_expired_guests(bot):
    guest_times = load_guest_times()
    now = datetime.now(timezone.utc)
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    guest_role = guild.get_role(GUEST_ROLE_ID)
    to_remove = []
    for user_id, info in guest_times.items():
        expires_str = info.get("expires_at")
        try:
            expires_at = datetime.fromisoformat(expires_str)
        except Exception:
            continue
        if now >= expires_at:
            member = guild.get_member(int(user_id))
            if member and guest_role in member.roles:
                # DM the user before kicking
                try:
                    embed = discord.Embed(
                        title="⏰ Guest Trial Expired",
                        description=(
                            "Your **Guest Access** to the PNW Esports Discord server has expired after 30 days.\n\n"
                            "If you become a Purdue Northwest student, you can rejoin as a Student for permanent access.\n"
                            "Thank you for visiting!"
                        ),
                        color=discord.Color.red()
                    )
                    embed.set_footer(text="PNW Esports | Guest Access")
                    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
                    await member.send(embed=embed)
                except Exception:
                    pass
                try:
                    await member.kick(reason="Guest trial expired (30 days).")
                except Exception:
                    pass
            to_remove.append(user_id)
    # Remove expired users' guest time files
    for user_id in to_remove:
        try:
            os.remove(guest_time_path(user_id))
        except Exception:
            pass


def add_user_record(user_id, record):
    from datetime import datetime, timezone
    USER_RECORDS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../user_records"))
    os.makedirs(USER_RECORDS_DIR, exist_ok=True)
    path = os.path.join(USER_RECORDS_DIR, f"{user_id}_record.json")
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = []
    except Exception:
        data = []
    record["timestamp"] = datetime.now(timezone.utc).isoformat()
    data.append(record)
    safe_json_dump(data, path, indent=2)


def format_phone(phone):
    phone = re.sub(r"\D", "", phone)
    if len(phone) == 10:
        return f"{phone[:3]}-{phone[3:6]}-{phone[6:]}"
    return phone


class SetupView(discord.ui.View):
    selection_made = set()

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def disable_buttons_for_user(self, interaction):
        for item in self.children:
            item.disabled = True
        # Edit the original message to blank out the buttons
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

    async def delete_welcome_message(self, interaction_message):
        # Delete the welcome message after verification
        try:
            await interaction_message.delete()
        except Exception:
            pass

    @discord.ui.button(label="Student", style=discord.ButtonStyle.primary, custom_id="student_access")
    async def student_access(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Only block if user has COMPLETED setup
        if interaction.user.id in type(self).selection_made:
            await interaction.response.send_message("You have already completed the setup.", ephemeral=True)
            return
        from datetime import timezone
        pending_users[interaction.user.id] = datetime.now(timezone.utc)
        await interaction.response.send_modal(AccountSetupModal(self.bot, parent_view=self, interaction_message=interaction.message))

    @discord.ui.button(label="Guest Access", style=discord.ButtonStyle.secondary, custom_id="guest_access")
    async def guest_access(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Only block if user has COMPLETED setup
        if interaction.user.id in type(self).selection_made:
            await interaction.response.send_message("You have already completed the setup.", ephemeral=True)
            return
        from datetime import timezone
        pending_users[interaction.user.id] = datetime.now(timezone.utc)
        await interaction.response.send_modal(GuestAccessModal(self.bot, parent_view=self, interaction_message=interaction.message))


class AccountSetupModal(discord.ui.Modal, title="PNW Esports Student Setup"):
    def __init__(self, bot, parent_view=None, interaction_message=None):
        super().__init__()
        self.bot = bot
        self.parent_view = parent_view
        self.interaction_message = interaction_message

    first_name = discord.ui.TextInput(label="First Name", placeholder="John", required=True)
    ign = discord.ui.TextInput(label="IGN (Gaming username)", placeholder="Gamer123", required=True)
    purdue_email = discord.ui.TextInput(label="Purdue Email", placeholder="example@purdue.edu (DO NOT USE @pnw.edu)", required=True)
    phone = discord.ui.TextInput(label="Phone Number (Optional)", placeholder="123-456-7890", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        # Accept either @purdue.edu or @pnw.edu; normalize pnw.edu -> purdue.edu
        email_raw = self.purdue_email.value.strip()
        m = re.match(r"([^@]+)@([^@]+\.[^@]+)$", email_raw, re.IGNORECASE)
        if not m:
            await interaction.response.send_message("❌ Invalid email format.", ephemeral=True)
            return
        local_part = m.group(1)
        domain = m.group(2).lower()
        if domain not in ("purdue.edu", "pnw.edu"):
            await interaction.response.send_message("❌ Invalid email. Only Purdue or PNW emails are allowed.", ephemeral=True)
            return
        # Normalize pnw.edu to purdue.edu
        if domain == "pnw.edu":
            email_val = f"{local_part}@purdue.edu"
        else:
            email_val = f"{local_part}@purdue.edu"

        # Validate phone number format if provided
        phone_val = self.phone.value.strip()
        formatted_phone = format_phone(phone_val) if phone_val else None
        if formatted_phone and not re.match(r"^\d{3}-\d{3}-\d{4}$", formatted_phone):
            await interaction.response.send_message("❌ Phone number must be in format 123-456-7890.", ephemeral=True)
            return
        nickname = f"{self.first_name.value} ({self.ign.value})"
        try:
            guild = self.bot.get_guild(GUILD_ID)
            member = guild.get_member(interaction.user.id) if guild else None
            if member is None:
                await interaction.response.send_message("⚠️ Could not find you in the server.", ephemeral=True)
                return
            await member.edit(nick=nickname)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don’t have permission to change your nickname.", ephemeral=True)
            return

        if guild:
            student_role = guild.get_role(STUDENT_ROLE_ID)
            guest_role = guild.get_role(GUEST_ROLE_ID)
            if guest_role and guest_role in member.roles:
                try:
                    await member.remove_roles(guest_role)
                except discord.Forbidden:
                    pass  # Ignore if can't remove
            if student_role and student_role not in member.roles:
                try:
                    await member.add_roles(student_role)
                except discord.Forbidden:
                    await interaction.response.send_message("⚠️ Could not assign the Student role. Please contact an admin.", ephemeral=True)
                    return

        embed = discord.Embed(
            title="✅ Setup Complete!",
            description=(
                "You're almost done!\n\n"
                "**Last Step:**\n"
                "Please join the **PNW Esports Club** on the Purdue Northwest Student Life page.\n"
                "[Click Here to Join](" + STUDENT_LIFE_LINK + ")"
            ),
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        embed.set_footer(text="PNW Esports | #RoarPRIDE")

        await interaction.response.send_message(embed=embed, ephemeral=True)

        dm_embed = discord.Embed(
            title="🦁 Welcome to the PNW Esports Discord Server",
            description=(
                "Hey there! You've successfully completed your **Student setup** for the PNW Esports Discord.\n\n"
                "Be sure to follow up by joining the official Student Life club.\n"
                "[Click Here to Join](" + STUDENT_LIFE_LINK + ")"
            ),
            color=discord.Color.yellow()
        )
        dm_embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        dm_embed.set_footer(text="PNW Esports | #RoarPRIDE")
        try:
            await interaction.user.send(embed=dm_embed)
        except discord.Forbidden:
            print(f"⚠️ Could not DM {interaction.user}.")

        pending_users.pop(interaction.user.id, None)

        # Mark user as completed only after successful setup
        if self.parent_view:
            type(self.parent_view).selection_made.add(interaction.user.id)
        if self.parent_view and self.interaction_message:
            await self.parent_view.disable_buttons_for_user(
                type("FakeInteraction", (), {"message": self.interaction_message})()
            )
            # Delete the welcome message after verification
            await self.parent_view.delete_welcome_message(self.interaction_message)

        # Log verification to lionbytegg-logs
        guild = interaction.guild or self.bot.get_guild(GUILD_ID)
        if guild is not None:
            log_channel = await get_or_create_log_channel(guild)
            log_embed = discord.Embed(
                title="✅ Student Verification Completed",
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc)
            )
            log_embed.add_field(name="Discord User", value=f"{interaction.user} ({interaction.user.id})", inline=False)
            log_embed.add_field(name="First Name", value=self.first_name.value, inline=True)
            log_embed.add_field(name="IGN", value=self.ign.value, inline=True)
            log_embed.add_field(name="Purdue Email", value=email_val, inline=False)
            # Add phone number to log as a spoiler if provided
            if formatted_phone:
                log_embed.add_field(name="Phone", value=f"||{formatted_phone}||", inline=True)
            log_embed.add_field(name="Nickname Set", value=nickname, inline=False)
            log_embed.add_field(name="Role Assigned", value="Student", inline=True)
            log_embed.set_footer(text="PNW Esports | Verification Log (LionByteGG)")
            log_embed.set_thumbnail(url=interaction.user.display_avatar.url)
            await log_channel.send(embed=log_embed)

        # Remove guest time record since user is now a student
        remove_guest_time(interaction.user.id)


def remove_guest_time(discord_id):
    try:
        os.remove(guest_time_path(discord_id))
    except Exception:
        pass


class GuestAccessModal(discord.ui.Modal, title="Guest Access Setup"):
    def __init__(self, bot, parent_view=None, interaction_message=None):
        super().__init__()
        self.bot = bot
        self.parent_view = parent_view
        self.interaction_message = interaction_message

    first_name = discord.ui.TextInput(label="First Name", placeholder="Alex", required=True)
    ign = discord.ui.TextInput(label="IGN (Gaming username)", placeholder="GamerGuest", required=True)
    personal_email = discord.ui.TextInput(label="Personal Email", placeholder="example@gmail.com", required=True)
    phone = discord.ui.TextInput(label="Phone Number", placeholder="123-456-7890", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        if not re.match(r"[^@]+@[^@]+\.[^@]+", self.personal_email.value):
            await interaction.response.send_message("❌ Invalid email format.", ephemeral=True)
            return

        phone_val = self.phone.value.strip()
        formatted_phone = format_phone(phone_val)
        if not re.match(r"^\d{3}-\d{3}-\d{4}$", formatted_phone):
            await interaction.response.send_message("❌ Phone number must be in format 123-456-7890.", ephemeral=True)
            return

        nickname = f"{self.first_name.value} ({self.ign.value})"
        try:
            guild = self.bot.get_guild(GUILD_ID)
            member = guild.get_member(interaction.user.id) if guild else None
            if member is None:
                await interaction.response.send_message("⚠️ Could not find you in the server.", ephemeral=True)
                return
            await member.edit(nick=nickname)
        except discord.Forbidden:
            await interaction.response.send_message("⚠️ Could not change nickname. Please contact an admin.", ephemeral=True)
            return

        if guild:
            guest_role = guild.get_role(GUEST_ROLE_ID)
            if guest_role:
                try:
                    await member.add_roles(guest_role)
                except discord.Forbidden:
                    await interaction.response.send_message("⚠️ Could not assign the Guest role. Please contact an admin.", ephemeral=True)
                    return
            # Create guest time record JSON with 30 days, username, and joined_at
            set_guest_timer(
                interaction.user.id,
                username=interaction.user.name,
                joined_at=member.joined_at if member and hasattr(member, "joined_at") else None
            )

        embed = discord.Embed(
            title="✅ Guest Access Granted!",
            description=(
                "You're all set! Welcome to the PNW Esports Discord server as a guest. "
                "You have been granted a 30-day trial period to explore the server and participate in our community.\n\n"
                "To check how much time you have remaining as a guest, use the `/time` command at any time.\n\n"
                "If you become a Purdue Northwest student, you can upgrade your account for permanent access."
            ),
            color=discord.Color.light_grey()
        )
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        embed.set_footer(text="PNW Esports | #RoarPRIDE")
        await interaction.response.send_message(embed=embed, ephemeral=True)

        dm_embed = discord.Embed(
            title="📬 Guest Access Confirmed",
            description="Welcome to the server as a **Guest**! You now have limited access to the PNW Esports Discord.\n\nFeel free to participate in public chats and events!",
            color=discord.Color.teal()
        )
        dm_embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        dm_embed.set_footer(text="PNW Esports | #RoarPRIDE")
        try:
            await interaction.user.send(embed=dm_embed)
        except discord.Forbidden:
            print(f"⚠️ Could not DM {interaction.user}.")

        pending_users.pop(interaction.user.id, None)

        # Mark user as completed only after successful setup
        if self.parent_view:
            type(self.parent_view).selection_made.add(interaction.user.id)
        if self.parent_view and self.interaction_message:
            await self.parent_view.disable_buttons_for_user(
                type("FakeInteraction", (), {"message": self.interaction_message})()
            )
            # Delete the welcome message after verification
            await self.parent_view.delete_welcome_message(self.interaction_message)

        # Log verification to lionbytegg-logs
        guild = interaction.guild or self.bot.get_guild(GUILD_ID)
        if guild is not None:
            log_channel = await get_or_create_log_channel(guild)
            log_embed = discord.Embed(
                title="✅ Guest Verification Completed",
                color=discord.Color.teal(),
                timestamp=datetime.now(timezone.utc)
            )
            log_embed.add_field(name="Discord User", value=f"{interaction.user} ({interaction.user.id})", inline=False)
            log_embed.add_field(name="First Name", value=self.first_name.value, inline=True)
            log_embed.add_field(name="IGN", value=self.ign.value, inline=True)
            log_embed.add_field(name="Personal Email", value=self.personal_email.value, inline=False)
            log_embed.add_field(name="Phone", value=self.phone.value, inline=True)
            log_embed.add_field(name="Nickname Set", value=nickname, inline=False)
            log_embed.add_field(name="Role Assigned", value="Guest", inline=True)
            log_embed.set_footer(text="PNW Esports | Verification Log (LionByteGG)")
            log_embed.set_thumbnail(url=interaction.user.display_avatar.url)
            await log_channel.send(embed=log_embed)



