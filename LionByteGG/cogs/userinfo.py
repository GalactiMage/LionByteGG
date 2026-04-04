import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from datetime import datetime, timezone, timedelta
import os
import json
from utils.constants import STUDENT_ROLE_ID, SECURITY_CODE, USER_RECORDS_DIR, GUEST_TIMES_DIR, VARSITY_REG_DIR, SCHEDULE_IMAGES_DIR, LOG_CHANNEL_NAME
from views.setup_view import load_guest_times  # Ensure this import is present
from utils.safe_json import safe_json_dump

# GUEST_TIMES_DIR is provided by utils.constants

def save_guest_time(user_id, expires_at, username=None, joined_at=None):
    os.makedirs(GUEST_TIMES_DIR, exist_ok=True)
    path = os.path.join(GUEST_TIMES_DIR, f"{user_id}_guest_time.json")
    data = {
        "expires_at": expires_at.isoformat()
    }
    if username:
        data["username"] = username
    if joined_at:
        data["joined_at"] = joined_at.isoformat() if hasattr(joined_at, "isoformat") else str(joined_at)
    safe_json_dump(data, path, indent=2)

def remove_guest_time(user_id):
    path = os.path.join(GUEST_TIMES_DIR, f"{user_id}_guest_time.json")
    if os.path.exists(path):
        os.remove(path)

class UserInfoSecurityModal(discord.ui.Modal, title="You are Accessing Critical Information"):
    def __init__(self, user: discord.Member, userinfo_cog):
        super().__init__()
        self.user = user
        self.userinfo_cog = userinfo_cog
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
        # Show loading embed first
        loading_embed = discord.Embed(
            title=f"Loading {self.user.display_name}'s Information...",
            description="Please wait while we gather the latest user data.",
            color=discord.Color.green()
        )
        loading_embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1316453330695884912/1401247265150078976/loading-gif.webp?ex=688f94b5&is=688e4335&hm=6ffa093134efa1f0ca582fa760b89a324d1f95c2dd4ce03b2e401edd42e87e05&")
        await interaction.response.defer(ephemeral=True)
        loading_msg = await interaction.followup.send(embed=loading_embed, ephemeral=True)
        await asyncio.sleep(5)
        try:
            await loading_msg.delete()
        except Exception:
            pass
        await self.userinfo_cog._show_userinfo(interaction, self.user)

class ActionReasonModal(discord.ui.Modal):
    def __init__(self, action_type, user_id, moderation_cog, interaction, userinfo_view):
        super().__init__(title=f"{action_type} Reason")
        self.action_type = action_type
        self.user_id = user_id
        self.moderation_cog = moderation_cog
        self.interaction = interaction
        self.userinfo_view = userinfo_view
        self.reason_input = discord.ui.TextInput(
            label=f"Enter reason for {action_type.lower()}",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=256
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        reason = self.reason_input.value.strip()
        user = interaction.guild.get_member(int(self.user_id))
        admin_name = interaction.user.display_name
        # Call moderation cog's action functions for consistency
        if self.moderation_cog:
            if self.action_type == "Kick" and hasattr(self.moderation_cog, "kick_user"):
                await self.moderation_cog.kick_user(user, reason, admin_name)
                await interaction.response.send_message(f"👢 {user.mention} has been kicked.\nReason: {reason}", ephemeral=True)
            elif self.action_type == "Ban" and hasattr(self.moderation_cog, "ban_user"):
                await self.moderation_cog.ban_user(user, reason, admin_name)
                await interaction.response.send_message(f"🔨 {user.mention} has been banned.\nReason: {reason}", ephemeral=True)
        # Optionally refresh the embed/view
        try:
            await self.userinfo_view.interaction.edit_original_response(view=None)
        except Exception:
            pass

class UserInfo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="userinfo", description="Show info about a user (Admin only).")
    @app_commands.describe(user="User to get info about")
    async def userinfo(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only admins can use this command.", ephemeral=True)
            return
        await interaction.response.send_modal(UserInfoSecurityModal(user, self))

    class ClearRecordView(discord.ui.View):
        def __init__(self, user_id, moderation_cog, embed, interaction, show_clear_record, show_cancel_timer, show_varsity_hub=False):
            super().__init__(timeout=60)
            self.user_id = user_id
            self.moderation_cog = moderation_cog
            self.embed = embed
            self.interaction = interaction

            if show_clear_record:
                self.add_item(self.ClearRecordButton())
            # Optionally add VarsityHUB button (red) when account is active
            if show_varsity_hub:
                self.add_item(self.VarsityHubButton())
            if show_cancel_timer or True:
                self.add_item(self.CancelTimerButton())
                self.add_item(self.ResetGuestTimerButton())

        class ClearRecordButton(discord.ui.Button):
            def __init__(self):
                super().__init__(label="Clear Record", style=discord.ButtonStyle.danger)

            async def callback(self, interaction: discord.Interaction):
                view = self.view
                if not interaction.user.guild_permissions.administrator:
                    await interaction.response.send_message("❌ Only admins can clear records.", ephemeral=True)
                    return
                # Show confirmation view
                await interaction.response.send_message(
                    f"Are you sure you want to clear this user's record?",
                    view=UserInfo.ConfirmClearRecordView(view.user_id, view.moderation_cog, view.embed, interaction, view),
                    ephemeral=True
                )

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
                    # Remove the guest timer JSON file
                    remove_guest_time(view.user_id)
                    # save_guest_times(guest_times)  # If you have a save function for in-memory guest_times
                    for i, field in enumerate(view.embed.fields):
                        if field.name == "Guest Time Left":
                            view.embed.set_field_at(i, name="Guest Time Left", value="Timer Cancelled", inline=True)
                    await interaction.response.edit_message(embed=view.embed, view=view)
                    await interaction.followup.send("✅ Guest timer cancelled for this user.", ephemeral=True)
                else:
                    # Also try to remove the JSON file even if not in guest_times
                    remove_guest_time(view.user_id)
                    await interaction.response.send_message("This user does not have a guest timer.", ephemeral=True)

        class ResetGuestTimerButton(discord.ui.Button):
            def __init__(self):
                super().__init__(label="Reset Guest Timer", style=discord.ButtonStyle.success, emoji="🔄", row=1)

            async def callback(self, interaction: discord.Interaction):
                view = self.view
                if not interaction.user.guild_permissions.administrator:
                    await interaction.response.send_message("❌ Only admins can reset guest timers.", ephemeral=True)
                    return
                expires_at = datetime.now(timezone.utc) + timedelta(days=30)
                user_obj = interaction.guild.get_member(int(view.user_id))
                username = user_obj.name if user_obj else str(view.user_id)
                joined_at = user_obj.joined_at if user_obj and hasattr(user_obj, "joined_at") else None
                save_guest_time(view.user_id, expires_at, username=username, joined_at=joined_at)
                # Update embed
                guest_time_str = "30 days, 0 hours, 0 minutes"
                found = False
                for i, field in enumerate(view.embed.fields):
                    if field.name == "Guest Time Left":
                        view.embed.set_field_at(i, name="Guest Time Left", value=guest_time_str, inline=True)
                        found = True
                        break
                if not found:
                    view.embed.add_field(name="Guest Time Left", value=guest_time_str, inline=True)
                await interaction.response.edit_message(embed=view.embed, view=view)
                await interaction.followup.send("✅ Guest timer reset to 30 days.", ephemeral=True)

        @discord.ui.button(label="Kick", style=discord.ButtonStyle.primary, emoji="👢")
        async def kick_user(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not interaction.user.guild_permissions.kick_members:
                await interaction.response.send_message("❌ You need the Kick Members permission.", ephemeral=True)
                return
            await interaction.response.send_modal(
                ActionReasonModal(
                    action_type="Kick",
                    user_id=self.user_id,
                    moderation_cog=self.moderation_cog,
                    interaction=interaction,
                    userinfo_view=self
                )
            )

        @discord.ui.button(label="Ban", style=discord.ButtonStyle.danger, emoji="🔨")
        async def ban_user(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not interaction.user.guild_permissions.ban_members:
                await interaction.response.send_message("❌ You need the Ban Members permission.", ephemeral=True)
                return
            await interaction.response.send_modal(
                ActionReasonModal(
                    action_type="Ban",
                    user_id=self.user_id,
                    moderation_cog=self.moderation_cog,
                    interaction=interaction,
                    userinfo_view=self
                )
            )

        @discord.ui.button(label="Register Varsity", style=discord.ButtonStyle.success, emoji="🎓")
        async def register_varsity(self, interaction: discord.Interaction, button: discord.ui.Button):
            # You may need to import VarsityRegistrationView if not already
            from views.varsity_view import VarsityRegistrationView
            user = interaction.guild.get_member(int(self.user_id))
            if user:
                try:
                    embed = discord.Embed(
                        title="🎓 Welcome to PNW eSports Varsity!",
                        description=(
                            "You've been selected to join the **Varsity eSports Team** — home to the elite and best of Purdue Northwest.\n\n"
                            "Please complete your registration below to finalize your onboarding."
                        ),
                        color=discord.Color.dark_red()
                    )
                    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
                    embed.set_footer(text="PNW eSports | Varsity Division")
                    await user.send(embed=embed, view=VarsityRegistrationView(requested_by=interaction.user))
                    await interaction.response.send_message(f"📩 Registration sent to {user.mention}.", ephemeral=True)
                except Exception as e:
                    await interaction.response.send_message(f"❌ Could not DM {user.mention}: {e}", ephemeral=True)
            else:
                await interaction.response.send_message("User not found in guild.", ephemeral=True)

        class VarsityHubButton(discord.ui.Button):
            def __init__(self):
                super().__init__(label="VarsityHUB", style=discord.ButtonStyle.danger, emoji="🎓", row=1)

            async def callback(self, interaction: discord.Interaction):
                # Show varsity registration info for this user if present in VARSITY_REG_DIR or fallback to USER_RECORDS_DIR
                user_id = self.view.user_id
                # First try dedicated varsity file
                vpath = os.path.join(VARSITY_REG_DIR, f"{user_id}_varsity.json")
                data = None
                if os.path.exists(vpath):
                    try:
                        with open(vpath, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        data = None
                # Fallback to legacy user records
                if data is None:
                    record_path = os.path.join(USER_RECORDS_DIR, f"{user_id}_record.json")
                    if os.path.exists(record_path):
                        try:
                            with open(record_path, "r", encoding="utf-8") as f:
                                data = json.load(f)
                        except Exception:
                            data = None

                if not data:
                    await interaction.response.send_message("❌ No registration on file.", ephemeral=True)
                    return

                # Find the latest VarsityRegistration entry
                varsity_entries = [e for e in data if str(e.get("type", "")).lower().startswith("varsityregistration")]
                if not varsity_entries:
                    await interaction.response.send_message("❌ No registration on file.", ephemeral=True)
                    return
                latest = varsity_entries[-1]
                status = latest.get("status", "Unknown")
                saved = latest.get("data", {})
                embed = discord.Embed(
                    title="Registration",
                    description=f"Status: **{status}**",
                    color=discord.Color.gold()
                )
                # Add common fields if present
                def add_field_safe(name, key):
                    if saved.get(key):
                        embed.add_field(name=name, value=saved.get(key), inline=False)

                add_field_safe("Full Name", "Full Name")
                add_field_safe("Purdue Email", "Purdue Email")
                add_field_safe("Personal Email", "Personal Email")
                add_field_safe("Phone Number", "Phone Number")
                add_field_safe("PUID", "PUID")
                add_field_safe("IGN / In Game Name", "IGN")
                add_field_safe("Primary Game Title", "Primary Game Title")
                add_field_safe("Current Rank", "Current Rank in Game")
                add_field_safe("Tracker Link", "Tracker Link")
                add_field_safe("Anything Else", "Anything Else")
                attachments = saved.get("attachments", [])
                if attachments:
                    embed.add_field(name="Attachments", value="\n".join(attachments), inline=False)
                await interaction.response.send_message(embed=embed, ephemeral=True)

        async def on_timeout(self):
            try:
                await self.interaction.edit_original_response(view=None)
            except Exception:
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
            # Clear the record from memory and save
            cleared = False
            if self.user_id in self.moderation_cog.user_records:
                del self.moderation_cog.user_records[self.user_id]
                self.moderation_cog.save_user_records()
                cleared = True
            # Delete the user's record JSON file
            record_path = os.path.join(USER_RECORDS_DIR, f"{self.user_id}_record.json")
            if os.path.exists(record_path):
                os.remove(record_path)
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
                self.embed.add_field(name="Roles", value=", ".join(role.mention for role in user.roles if role.name != "@everyone"), inline=False)
            self.embed.add_field(name="Record Summary", value="✅ **No Record, Good Standing**", inline=False)
            await interaction.response.edit_message(embed=self.embed, view=self.parent_view)
            await interaction.followup.send("✅ Record cleared.", ephemeral=True)
            # Log to lionbyte-logs
            log_channel = discord.utils.get(interaction.guild.text_channels, name="lionbyte-logs")
            if cleared and log_channel:
                log_embed = discord.Embed(
                    title="🗑️ User Record Cleared",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc)
                )
                log_embed.add_field(name="User", value=f"{user} (ID: {self.user_id})" if user else f"ID: {self.user_id}", inline=False)
                log_embed.add_field(name="Moderator", value=f"{interaction.user} (ID: {interaction.user.id})", inline=False)
                log_embed.set_footer(text="PNW eSports | Moderation Log (LionByteGG)")
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

    async def _show_userinfo(self, interaction: discord.Interaction, user: discord.Member, skip_loading: bool = False):
        moderation_cog = interaction.client.get_cog("Moderation")
        warning_count = 0
        kick_count = 0
        ban_count = 0
        automod_count = 0
        record_summary = ""
        record_details = ""
        transcript_file = None
        has_record = False
        student_email = None
        student_phone = None
        
        # Try to get student info from user_records (read from disk if available)
        record_data = []
        record_path = os.path.join(USER_RECORDS_DIR, f"{str(user.id)}_record.json")
        
        # First try to read from disk
        if os.path.exists(record_path):
            try:
                with open(record_path, "r", encoding="utf-8") as f:
                    record_data = json.load(f)
            except Exception:
                # Fall back to in-memory if disk read fails
                if moderation_cog and hasattr(moderation_cog, "user_records"):
                    record_data = moderation_cog.user_records.get(str(user.id), [])
        elif moderation_cog and hasattr(moderation_cog, "user_records"):
            # Try in-memory as fallback
            record_data = moderation_cog.user_records.get(str(user.id), [])
        
        if isinstance(record_data, list) and record_data:
            has_record = True
            warning_count = sum(1 for r in record_data if r.get("type") == "Warning")
            kick_count = sum(1 for r in record_data if r.get("type") == "Kick")
            ban_count = sum(1 for r in record_data if r.get("type") == "Ban")
            automod_count = sum(1 for r in record_data if r.get("type") == "AutoMod")
            record_summary = (
                f"Warnings: {warning_count}, Kicks: {kick_count}, Bans: {ban_count}, AutoMod Actions: {automod_count}"
            )
            lines = []
            for entry in record_data:
                if "timestamp" in entry and "type" in entry and "reason" in entry:
                    lines.append(f"{entry['timestamp']} | {entry['type']}: {entry['reason']}")
            if lines:
                record_details = "\n".join(lines)
                filename = f"{str(user.id)}_transcript.txt"
                try:
                    with open(filename, "w", encoding="utf-8") as f:
                        f.write(record_details)
                    transcript_file = filename
                except Exception:
                    pass
        else:
            record_summary = "No Record, Good Standing"

        roles = [role for role in user.roles if role.name != "@everyone"]
        roles_str = ", ".join(role.mention for role in roles) if roles else "None"
        header_embed = discord.Embed(
            title="LionByteGG User Record System",
            description="PNW eSports Moderation & User Info",
            color=discord.Color.gold()
        )
        header_embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        header_embed.set_footer(text="PNW eSports | LionByteGG")
        info_embed = discord.Embed(
            title="User Record",
            description=f"**User:** {user.mention}\n**ID:** `{user.id}`",
            color=discord.Color.red() if has_record else discord.Color.blue()
        )
        info_embed.add_field(name="Joined", value=user.joined_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
        info_embed.add_field(name="Created", value=user.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
        info_embed.add_field(name="Top Role", value=user.top_role.mention, inline=True)
        info_embed.add_field(name="Bot?", value=str(user.bot), inline=True)
        info_embed.add_field(name="Roles", value=roles_str, inline=False)
        # Add Student Purdue Email and Phone (spoilered) if available
        if student_email:
            info_embed.add_field(name="Purdue Email", value=f"||{student_email}||", inline=False)
        if student_phone:
            info_embed.add_field(name="Phone Number", value=f"||{student_phone}||", inline=False)
        # Record summary logic:
        if has_record:
            info_embed.add_field(
                name="Record Summary",
                value=(
                    f"📄 **User Has Record Actions on File**\n"
                    f"Warnings: `{warning_count}` | Kicks: `{kick_count}` | Bans: `{ban_count}`"
                ),
                inline=False
            )
        else:
            info_embed.add_field(
                name="Record Summary",
                value="✅ **No Record, Good Standing**",
                inline=False
            )
        info_embed.set_thumbnail(url=user.display_avatar.url)
        info_embed.set_footer(text="PNW eSports | Moderation Record")

        guest_times = load_guest_times()
        guest_info = guest_times.get(str(user.id))
        show_cancel_timer = bool(guest_info)
        show_clear_record = has_record

        # Show Guest Time Left and when it was set (joined_at)
        if guest_info:
            expires_str = guest_info.get("expires_at")
            joined_at_str = guest_info.get("joined_at")
            try:
                expires_at = datetime.fromisoformat(expires_str)
                now = datetime.now(timezone.utc)
                remaining = expires_at - now
                if remaining.total_seconds() > 0:
                    days = remaining.days
                    hours, remainder = divmod(remaining.seconds, 3600)
                    minutes, _ = divmod(remainder, 60)
                    time_left = f"{days} days, {hours} hours, {minutes} minutes"
                    info_embed.add_field(name="Guest Time Left", value=time_left, inline=True)
                else:
                    info_embed.add_field(name="Guest Time Left", value="Expired", inline=True)
            except Exception:
                info_embed.add_field(name="Guest Time Left", value="Unknown", inline=True)
            # Show when timer was set (joined_at)
            if joined_at_str:
                try:
                    dt = datetime.fromisoformat(joined_at_str)
                    formatted = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                except Exception:
                    formatted = joined_at_str
                info_embed.add_field(name="Guest Timer Set On", value=formatted, inline=True)
        else:
            student_role = interaction.guild.get_role(STUDENT_ROLE_ID)
            info_embed.add_field(
                name="Account Status",
                value="Active" if student_role and student_role in user.roles else "Unknown",
                inline=True
            )

        # Show VarsityHUB button when account is active (student role present) OR has varsity record
        student_role = interaction.guild.get_role(STUDENT_ROLE_ID)
        has_student_role = bool(student_role and student_role in user.roles)
        
        # Check if user has a varsity registration on file
        has_varsity_record = False
        try:
            vpath = os.path.join(VARSITY_REG_DIR, f"{str(user.id)}_varsity.json")
            if os.path.exists(vpath):
                has_varsity_record = True
            else:
                # Fallback check for legacy records
                record_path = os.path.join(USER_RECORDS_DIR, f"{str(user.id)}_record.json")
                if os.path.exists(record_path):
                    with open(record_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    # Check if any VarsityRegistration entries exist
                    varsity_entries = [e for e in data if str(e.get("type", "")).lower().startswith("varsityregistration")]
                    has_varsity_record = bool(varsity_entries)
        except Exception:
            pass
        
        show_varsity_hub = has_student_role or has_varsity_record
        view = UserInfo.ClearRecordView(str(user.id), moderation_cog, info_embed, interaction, show_clear_record, show_cancel_timer, show_varsity_hub=show_varsity_hub)

        embeds = [header_embed, info_embed]
        if transcript_file:
            await interaction.followup.send(
                embeds=embeds,
                ephemeral=True,
                file=discord.File(transcript_file),
                view=view
            )
            # Delete transcript file after sending
            try:
                os.remove(transcript_file)
            except Exception:
                pass
        else:
            await interaction.followup.send(
                embeds=embeds,
                ephemeral=True,
                view=view
            )
        # ...existing code for adding views/buttons if needed...

    @app_commands.command(name="pending-registrations", description="List pending registrations across user records.")
    async def pending_registrations(self, interaction: discord.Interaction):
        """Admin command: scan user_records for pending VarsityRegistration entries and display them."""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only admins can use this command.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        pending = []
        try:
            if not os.path.exists(VARSITY_REG_DIR):
                await interaction.followup.send("No registrations directory found.", ephemeral=True)
                return
            for fname in os.listdir(VARSITY_REG_DIR):
                if not fname.endswith("_varsity.json"):
                    continue
                user_id = fname.split("_varsity.json")[0]
                path = os.path.join(VARSITY_REG_DIR, fname)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        entries = json.load(f)
                except Exception:
                    continue
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    etype = str(entry.get("type", "")).lower()
                    status = str(entry.get("status", "")).lower()
                    if etype.startswith("varsityregistration") and status == "pending":
                        saved = entry.get("data", {}) or {}
                        pending.append({
                            "user_id": user_id,
                            "timestamp": entry.get("timestamp"),
                            "full_name": saved.get("Full Name"),
                            "player_type": saved.get("player_type"),
                            "puid": saved.get("PUID"),
                            "data": saved,
                        })
        except Exception as e:
            await interaction.followup.send(f"Error scanning records: {e}", ephemeral=True)
            return

        if not pending:
            await interaction.followup.send("✅ No pending registrations found.", ephemeral=True)
            return

        # Summarize first N entries in an embed, attach full JSON for full details
        MAX_SHOW = 15
        embed = discord.Embed(
            title="Pending Registrations",
            description=f"Found {len(pending)} pending registrations.",
            color=discord.Color.gold()
        )
        for item in pending[:MAX_SHOW]:
            uid = item.get("user_id")
            member = interaction.guild.get_member(int(uid)) if interaction.guild else None
            who = member.display_name if member else uid
            pt = item.get("player_type") or "N/A"
            name = item.get("full_name") or "N/A"
            ts = item.get("timestamp") or "N/A"
            value = f"**Name:** {name}\n**Player Type:** {pt}\n**PUID:** {item.get('puid') or 'N/A'}\n**Submitted:** {ts}\n**User ID:** {uid}"
            embed.add_field(name=f"{who}", value=value, inline=False)

        # Write the full pending list to a temp JSON file and send it as attachment
        try:
            import time
            tmp_name = f"pending_varsity_regs_{int(time.time())}.json"
            safe_json_dump(pending, tmp_name, indent=2)
            await interaction.followup.send(embed=embed, file=discord.File(tmp_name), ephemeral=True)
            try:
                os.remove(tmp_name)
            except Exception:
                pass
        except Exception:
            # fallback: just send embed
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="clean-varsity-registrations", description="Admin: clean old registration files from disk.")
    async def clean_varsity_registrations(self, interaction: discord.Interaction, days: int = 90):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only admins can run this command.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        if not os.path.exists(VARSITY_REG_DIR):
            await interaction.followup.send(f"❌ Registrations directory not found: {VARSITY_REG_DIR}", ephemeral=True)
            return
        # Find files older than `days` days based on mtime
        import time
        cutoff = time.time() - (days * 24 * 60 * 60)
        candidates = []
        try:
            for fname in os.listdir(VARSITY_REG_DIR):
                if not fname.endswith("_varsity.json"):
                    continue
                path = os.path.join(VARSITY_REG_DIR, fname)
                try:
                    mtime = os.path.getmtime(path)
                except Exception:
                    continue
                if mtime < cutoff:
                    candidates.append(path)
        except Exception as e:
            await interaction.followup.send(f"❌ Error scanning directory: {e}", ephemeral=True)
            return

        if not candidates:
            await interaction.followup.send(f"✅ No registration files older than {days} days found in {VARSITY_REG_DIR}.", ephemeral=True)
            return

        class CleanConfirmView(discord.ui.View):
            def __init__(self, files, admin_id):
                super().__init__(timeout=60)
                self.files = files
                self.admin_id = admin_id

            @discord.ui.button(label="Yes, delete files", style=discord.ButtonStyle.danger)
            async def yes(self, interaction2: discord.Interaction, button: discord.ui.Button):
                if interaction2.user.id != self.admin_id:
                    await interaction2.response.send_message("❌ Only the admin who initiated this can confirm.", ephemeral=True)
                    return
                try:
                    await interaction2.response.defer(ephemeral=True)
                except Exception:
                    pass
                deleted = 0
                images_deleted = 0
                failed = 0
                for p in self.files:
                    try:
                        # First, delete any associated schedule images
                        try:
                            with open(p, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                            if isinstance(data, list):
                                for entry in data:
                                    attachments = entry.get('data', {}).get('attachments', [])
                                    if attachments and isinstance(attachments, list):
                                        for filename in attachments:
                                            if isinstance(filename, str) and not filename.startswith('http'):
                                                img_path = os.path.join(SCHEDULE_IMAGES_DIR, filename)
                                                if os.path.exists(img_path):
                                                    os.remove(img_path)
                                                    images_deleted += 1
                        except Exception:
                            pass
                        # Now delete the registration file
                        os.remove(p)
                        deleted += 1
                    except Exception:
                        failed += 1
                msg = f"✅ Deleted {deleted} registration file(s) and {images_deleted} schedule image(s)."
                if failed > 0:
                    msg += f" ({failed} failed)"
                try:
                    await interaction2.followup.send(msg, ephemeral=True)
                except Exception:
                    pass
                for item in self.children:
                    item.disabled = True
                try:
                    await interaction2.message.edit(view=self)
                except Exception:
                    pass

            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
            async def no(self, interaction2: discord.Interaction, button: discord.ui.Button):
                if interaction2.user.id != self.admin_id:
                    await interaction2.response.send_message("❌ Only the admin who initiated this can cancel.", ephemeral=True)
                    return
                try:
                    await interaction2.response.defer(ephemeral=True)
                except Exception:
                    pass
                try:
                    await interaction2.followup.send("❌ Cleanup cancelled.", ephemeral=True)
                except Exception:
                    pass
                for item in self.children:
                    item.disabled = True
                try:
                    await interaction2.message.edit(view=self)
                except Exception:
                    pass

        summary = f"Found {len(candidates)} file(s) older than {days} days in:\n`{VARSITY_REG_DIR}`\n\nDelete them?"
        await interaction.followup.send(summary, view=CleanConfirmView(candidates, interaction.user.id), ephemeral=True)

async def setup(bot):
    await bot.add_cog(UserInfo(bot))