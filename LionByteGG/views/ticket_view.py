import discord
from discord.ext import tasks
import re
import asyncio
from datetime import datetime, timedelta, timezone, time as dt_time
import os
import sys
import random
import json

from utils.constants import STUDENT_ROLE_ID, ticket_blacklist, TICKET_CATEGORY_NAME, TICKET_CHANNEL_PREFIX, GUILD_ID, TECHNICIAN_ROLE_ID
from utils.log_channels import get_or_create_ticket_logs_channel
from utils.safe_json import safe_json_dump

# Path to ticket log file for dashboard
TICKET_LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ticket_log.json")
LIVE_NOTIFICATIONS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "live_notifications.json")

def add_ticket_notification(title, message, link=None, target_id=None, target_name=None):
    """Add a live notification for ticket events"""
    try:
        if os.path.exists(LIVE_NOTIFICATIONS_FILE):
            with open(LIVE_NOTIFICATIONS_FILE, 'r', encoding='utf-8') as f:
                notifications = json.load(f)
        else:
            notifications = {"notifications": [], "last_cleared": None}
        
        notification = {
            "id": f"notif_{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(4).hex()}",
            "type": "ticket",
            "title": title,
            "message": message,
            "link": link,
            "target_id": str(target_id) if target_id else None,
            "target_name": target_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "read": False
        }
        
        notifications["notifications"].insert(0, notification)
        notifications["notifications"] = notifications["notifications"][:100]
        
        safe_json_dump(notifications, LIVE_NOTIFICATIONS_FILE, indent=2, default=str)
        
        print(f"[LIVE NOTIFICATION] Added: {title}")
    except Exception as e:
        print(f"[ERROR] Failed to add ticket notification: {e}")

def log_ticket(ticket_id, channel_name, user, user_id, ticket_type, first_name, email, explanation, status="open", staff_assisting=None, closed_by=None, close_reason=None, messages=None):
    """Log ticket data to JSON file for dashboard access"""
    try:
        # Load existing data
        if os.path.exists(TICKET_LOG_FILE):
            with open(TICKET_LOG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {"open": [], "closed": [], "blacklist": []}
        
        ticket_entry = {
            "id": ticket_id,
            "channel_name": channel_name,
            "user": str(user),
            "user_id": str(user_id),
            "type": ticket_type,
            "first_name": first_name,
            "email": email,
            "explanation": explanation,
            "status": status,
            "staff_assisting": staff_assisting,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        if status == "closed":
            ticket_entry["closed_at"] = datetime.now(timezone.utc).isoformat()
            ticket_entry["closed_by"] = closed_by
            ticket_entry["close_reason"] = close_reason
            ticket_entry["messages"] = messages or []
            # Remove from open, add to closed
            data["open"] = [t for t in data.get("open", []) if str(t.get("id")) != str(ticket_id)]
            data["closed"].append(ticket_entry)
        else:
            # Check if exists in open, update or add
            exists = False
            for i, t in enumerate(data.get("open", [])):
                if str(t.get("id")) == str(ticket_id):
                    data["open"][i] = ticket_entry
                    exists = True
                    break
            if not exists:
                data["open"].append(ticket_entry)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(TICKET_LOG_FILE), exist_ok=True)
        safe_json_dump(data, TICKET_LOG_FILE, indent=2)
    except Exception as e:
        print(f"[ERROR] Failed to log ticket: {e}")


def update_ticket_staff(channel_name, staff_name, staff_id):
    """Update the staff_assisting field for a ticket by channel name"""
    try:
        if not os.path.exists(TICKET_LOG_FILE):
            return False
            
        with open(TICKET_LOG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Find the ticket in open tickets
        for i, ticket in enumerate(data.get("open", [])):
            if ticket.get("channel_name") == channel_name:
                data["open"][i]["staff_assisting"] = f"{staff_name} ({staff_id})"
                data["open"][i]["staff_id"] = str(staff_id)
                data["open"][i]["taken_at"] = datetime.now(timezone.utc).isoformat()
                
                safe_json_dump(data, TICKET_LOG_FILE, indent=2)
                return True
        
        return False
    except Exception as e:
        print(f"[ERROR] Failed to update ticket staff: {e}")
        return False


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # Persistent view

    @discord.ui.button(label="Contact Support", style=discord.ButtonStyle.danger, custom_id="contact_support")
    async def contact_support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Please select the type of support you need:",
            view=SupportTypeSelectView(),
            ephemeral=True
        )


class SupportTypeSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        # Store the select so it doesn't get garbage collected
        self.support_type_select = discord.ui.Select(
            placeholder="Choose your support type...",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Discord", value="Discord"),
                discord.SelectOption(label="Minecraft", value="Minecraft"),
                discord.SelectOption(label="Clubs", value="Clubs"),
                discord.SelectOption(label="Arena PCs (Technician Support)", value="Arena PCs (Technician Support)"),
                discord.SelectOption(label="Varsity", value="Varsity"),
                discord.SelectOption(label="Other", value="Other"),
            ],
            custom_id="support_type_select"
        )
        self.support_type_select.callback = self.select_callback
        self.add_item(self.support_type_select)

    async def select_callback(self, interaction: discord.Interaction):
        support_type = self.support_type_select.values[0]
        await interaction.response.send_modal(
            TicketSupportModal(support_type)
        )


class TicketSupportModal(discord.ui.Modal):
    def __init__(self, support_type):
        super().__init__(title="PNW eSports Support Ticket")
        self.support_type = support_type
        self.first_name = discord.ui.TextInput(
            label="First Name", placeholder="Alex Rogers", required=True
        )
        self.purdue_email = discord.ui.TextInput(
            label="Purdue Email", placeholder="user@purdue.edu", required=True
        )
        self.explanation = discord.ui.TextInput(
            label="Brief Explanation", placeholder="How can we help?",
            style=discord.TextStyle.paragraph,
            required=True
        )
        self.add_item(self.first_name)
        self.add_item(self.purdue_email)
        self.add_item(self.explanation)

    async def on_submit(self, interaction: discord.Interaction):
        # Check if user is blacklisted
        if interaction.user.id in ticket_blacklist:
            await interaction.response.send_message("🚫 You are blacklisted from creating tickets. Please contact a Server Admin.", ephemeral=True)
            return

        # Check if user has the Student role
        member = interaction.guild.get_member(interaction.user.id)
        if not member or STUDENT_ROLE_ID not in [role.id for role in member.roles]:
            await interaction.response.send_message("❌ Only Purdue Students are allowed to use the ticket system.", ephemeral=True)
            return

        # Check if the email is a valid Purdue email
        import re
        if not re.match(r"[^@]+@purdue\.edu$", self.purdue_email.value, re.IGNORECASE):
            await interaction.response.send_message("❌ Invalid email. Only Purdue emails are allowed for support tickets.", ephemeral=True)
            return

        guild = interaction.guild
        
        # ===== DUPLICATE TICKET PREVENTION =====
        # Check if user already has an open ticket channel (by checking channel permissions)
        for channel in guild.text_channels:
            if channel.name.startswith(TICKET_CHANNEL_PREFIX):
                # Check if the user has explicit read permissions on this channel
                overwrites = channel.overwrites_for(interaction.user)
                if overwrites.read_messages == True:
                    await interaction.response.send_message(
                        f"⚠️ You already have an open ticket: {channel.mention}\n"
                        f"Please use your existing ticket or wait for it to be closed before creating a new one.",
                        ephemeral=True
                    )
                    return
        
        # Also check the ticket log JSON for any open tickets from this user
        try:
            if os.path.exists(TICKET_LOG_FILE):
                with open(TICKET_LOG_FILE, 'r', encoding='utf-8') as f:
                    ticket_data = json.load(f)
                    open_tickets = ticket_data.get("open", [])
                    user_open_tickets = [t for t in open_tickets if str(t.get("user_id")) == str(interaction.user.id)]
                    if user_open_tickets:
                        # Double-check that the channel still exists
                        for user_ticket in user_open_tickets:
                            existing_channel = discord.utils.get(guild.text_channels, name=user_ticket.get("channel_name"))
                            if existing_channel:
                                await interaction.response.send_message(
                                    f"⚠️ You already have an open ticket: {existing_channel.mention}\n"
                                    f"Please use your existing ticket or wait for it to be closed before creating a new one.",
                                    ephemeral=True
                                )
                                return
        except Exception as e:
            print(f"[TICKET] Error checking for duplicate tickets: {e}")
        # ===== END DUPLICATE PREVENTION =====
        
        # Use the same category as the channel where the button was pressed, if possible
        parent_category = None
        if interaction.channel and isinstance(interaction.channel, discord.TextChannel):
            parent_category = interaction.channel.category

        # If the parent category exists, use it; otherwise, fallback to default ticket category
        if parent_category:
            category = parent_category
        else:
            category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)
            if not category:
                category = await guild.create_category(TICKET_CATEGORY_NAME, reason="Support Ticket System")

        # Find next ticket number
        existing = [c for c in category.channels if c.name.startswith(TICKET_CHANNEL_PREFIX)]
        numbers = []
        for c in existing:
            try:
                numbers.append(int(c.name.replace(TICKET_CHANNEL_PREFIX, "")))
            except:
                pass
        next_number = max(numbers, default=0) + 1
        ticket_channel_name = f"{TICKET_CHANNEL_PREFIX}{str(next_number).zfill(4)}"
        # Set permissions: only user and admins
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True, embed_links=True),
        }
        for role in guild.roles:
            if role.permissions.administrator:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        ticket_channel = await guild.create_text_channel(
            ticket_channel_name,
            category=category,
            overwrites=overwrites,
            reason="New support ticket"
        )
        # Ticket embed
        embed = discord.Embed(
            title="🎫 PNW eSports Support Ticket",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
            description="A new support ticket has been created. Please wait for an admin to respond."
        )
        embed.add_field(name="First Name", value=self.first_name.value, inline=True)
        embed.add_field(name="Purdue eMail", value=self.purdue_email.value, inline=True)
        embed.add_field(name="Type of Support", value=self.support_type, inline=True)
        embed.add_field(name="Explanation", value=self.explanation.value, inline=False)
        embed.add_field(name="User", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False)
        embed.set_footer(text="PNW eSports | Support System")
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        # Ping Student Staff role when sending the ticket
        staff_role_id = 1012078776273874994
        staff_ping = f"<@&{staff_role_id}>"
        technician_ping = ""
        is_technician_ticket = False
        if self.support_type == "Arena PCs (Technician Support)":
            technician_ping = f" <@&{TECHNICIAN_ROLE_ID}>"
            is_technician_ticket = True
        ticket_admin_view = TicketAdminView(interaction.user.id, is_technician_ticket=is_technician_ticket)
        # Send the ticket message and store reference in the view
        ticket_msg = await ticket_channel.send(
            content=f"{interaction.user.mention} {staff_ping}{technician_ping}",
            embed=embed,
            view=ticket_admin_view
        )
        ticket_admin_view.set_ticket_message(ticket_msg)
        
        # Log ticket to JSON for dashboard
        log_ticket(
            ticket_id=next_number,
            channel_name=ticket_channel_name,
            user=interaction.user,
            user_id=interaction.user.id,
            ticket_type=self.support_type,
            first_name=self.first_name.value,
            email=self.purdue_email.value,
            explanation=self.explanation.value,
            status="open"
        )
        
        # Send live notification to dashboard
        add_ticket_notification(
            title="New Ticket Opened",
            message=f"{self.support_type} ticket created by {self.first_name.value}",
            link="/tickets",
            target_id=interaction.user.id,
            target_name=f"{interaction.user.display_name} ({interaction.user.name})"
        )
        
        await interaction.response.send_message(f"✅ Your ticket has been created: {ticket_channel.mention}", ephemeral=True)


class TicketAdminView(discord.ui.View):
    def __init__(self, user_id=None, is_technician_ticket=False):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.taken = False
        self.ticket_message = None
        self.is_technician_ticket = is_technician_ticket
        self.tech_notes = []

    def set_ticket_message(self, message):
        self.ticket_message = message

    @discord.ui.button(label="Take Ticket", style=discord.ButtonStyle.primary, custom_id="take_ticket")
    async def take_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Only admins can take tickets.", ephemeral=True)
            return
        if self.taken:
            await interaction.response.send_message("This ticket has already been taken.", ephemeral=True)
            return
        self.taken = True
        button.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message(f"Ticket has been taken by {interaction.user.mention}.", ephemeral=False)
        user = interaction.guild.get_member(self.user_id)
        if user:
            await interaction.channel.send(f"{user.mention}, your ticket has been taken by {interaction.user.mention}.")

        # Update ticket log with staff info
        update_ticket_staff(
            channel_name=interaction.channel.name,
            staff_name=str(interaction.user),
            staff_id=interaction.user.id
        )

        # Edit the original ticket message embed to show Staff Assisting
        if self.ticket_message:
            embed = self.ticket_message.embeds[0]
            embed_dict = embed.to_dict()
            # Remove previous "Staff Assisting" field if exists
            embed_dict['fields'] = [f for f in embed_dict.get('fields', []) if f.get('name') != "Staff Assisting"]
            # Add new field
            embed_dict['fields'].append({
                "name": "Staff Assisting",
                "value": f"{interaction.user.mention} ({interaction.user.id})",
                "inline": False
            })
            new_embed = discord.Embed.from_dict(embed_dict)
            await self.ticket_message.edit(embed=new_embed, view=self)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.user_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Are you sure you want to close this Ticket?",
                    description="By closing this ticket you are stating that you no longer require PNW eSports Support Staff.",
                    color=discord.Color.orange()
                ),
                view=UserCloseConfirmView(self.user_id, admin_view=self),
                ephemeral=True
            )
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Only admins can close tickets.", ephemeral=True)
            return
        await interaction.response.send_modal(TicketCloseModal(self.user_id, admin_view=self))

    @discord.ui.button(label="Tech Notes", style=discord.ButtonStyle.secondary, custom_id="tech_notes", row=1)
    async def tech_notes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_technician_ticket:
            await interaction.response.send_message("This is not a Technician Support ticket.", ephemeral=True)
            return
        # Only allow users with the technician role to use this button
        if TECHNICIAN_ROLE_ID not in [role.id for role in interaction.user.roles]:
            await interaction.response.send_message("Only Technicians can add tech notes.", ephemeral=True)
            return
        await interaction.response.send_modal(TechNotesModal(self))


class TechNotesModal(discord.ui.Modal):
    def __init__(self, admin_view):
        super().__init__(title="Add Tech Note")
        self.admin_view = admin_view
        self.note = discord.ui.TextInput(
            label="Tech Note",
            style=discord.TextStyle.paragraph,
            required=True,
            placeholder="Describe what was done or checked..."
        )
        self.add_item(self.note)

    async def on_submit(self, interaction: discord.Interaction):
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.admin_view.tech_notes.append(
            (interaction.user, self.note.value, timestamp)
        )
        # --- Write tech note to a single file per ticket ---
        folder_path = os.path.join("data", "tech_notes")
        os.makedirs(folder_path, exist_ok=True)
        # Use channel name for the file (one file per ticket)
        file_path = os.path.join(folder_path, f"{interaction.channel.name}.txt")
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(
                f"Technician: {interaction.user} ({interaction.user.id})\n"
                f"Time: {timestamp}\n"
                f"Note: {self.note.value}\n"
                "--------------------------\n"
            )
        await interaction.response.send_message("✅ Tech note added.", ephemeral=True)


async def ensure_ticket_panel_message(bot, guild_id, channel_id):
    """
    Ensures only one ticket panel message exists in the specified channel.
    If not found, sends a new panel message.
    """
    guild = bot.get_guild(guild_id)
    if not guild:
        return
    channel = guild.get_channel(channel_id)
    if not channel:
        return

    panel_exists = False
    async for message in channel.history(limit=100):
        if message.author == bot.user and message.embeds:
            embed = message.embeds[0]
            if embed.title and embed.title.strip() == "🎫 Welcome to the PNW eSports Support System":
                panel_exists = True
                try:
                    await message.edit(view=TicketPanelView())
                except Exception as e:
                    print(f"[ERROR] Could not re-attach view to message {message.id}: {e}")
    if not panel_exists:
        embed = discord.Embed(
            title="🎫 Welcome to the PNW eSports Support System",
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
        embed.set_footer(text="PNW eSports | Support System")
        await channel.send(embed=embed, view=TicketPanelView())
    async for message in channel.history(limit=100):
        if message.author == bot.user and message.embeds:
            embed = message.embeds[0]
            if embed.title and embed.title.strip() == "🎫 Welcome to the PNW eSports Support System":
                panel_exists = True
                try:
                    await message.edit(view=TicketPanelView())
                except Exception as e:
                    print(f"[ERROR] Could not re-attach view to message {message.id}: {e}")
    if not panel_exists:
        embed = discord.Embed(
            title="🎫 Welcome to the PNW eSports Support System",
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
        embed.set_footer(text="PNW eSports | Support System")
        await channel.send(embed=embed, view=TicketPanelView())
        embed.set_footer(text="PNW eSports | Support System")
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        await channel.send(embed=embed, view=TicketPanelView())


# --- UserCloseConfirmView ---
class UserCloseConfirmView(discord.ui.View):
    def __init__(self, user_id, admin_view=None):
        super().__init__(timeout=30)
        self.user_id = user_id
        self.admin_view = admin_view

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success, custom_id="user_close_yes")
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the ticket creator can close this ticket.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await interaction.channel.send("User has Closed the ticket and Channel will be Deleted Shortly")
        guild = interaction.guild or interaction.client.get_guild(GUILD_ID)
        user = guild.get_member(self.user_id) if guild else None
        if user:
            embed = discord.Embed(
                title="🎫 Your Ticket Has Been Closed",
                color=discord.Color.red(),
                description="You have closed your ticket. If you need further help, you may open a new ticket.",
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Closed By", value=f"{interaction.user.mention} ({interaction.user.name})", inline=False)
            embed.set_footer(text="Thank you for using the PNW eSports Support System!")
            try:
                await user.send(embed=embed)
            except Exception:
                pass
        ticket_logs_channel = await get_or_create_ticket_logs_channel(guild)
        messages = []
        async for msg in interaction.channel.history(limit=100, oldest_first=True):
            timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            author = f"{msg.author} ({msg.author.id})"
            content = msg.content
            if msg.attachments:
                content += " " + " ".join(a.url for a in msg.attachments)
            messages.append(f"[{timestamp}] {author}: {content}")
        transcript = "\n".join(messages) or "No messages found."
        reason = "Closed by user"

        # --- Read tech notes from file ---
        folder_path = os.path.join("data", "tech_notes")
        file_path = os.path.join(folder_path, f"{interaction.channel.name}.txt")
        tech_notes_content = None
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                tech_notes_content = f.read()
            os.remove(file_path)  # Clean up after logging

        # --- Extract Explanation from original ticket message embed ---
        explanation_text = None
        async for msg in interaction.channel.history(limit=10, oldest_first=True):
            if msg.author == interaction.guild.me and msg.embeds:
                embed = msg.embeds[0]
                for field in embed.fields:
                    if field.name == "Explanation":
                        explanation_text = field.value
                        break
                if explanation_text:
                    break

        # If transcript is too long for an embed, send as a file
        if len(transcript) > 10:
            import io
            file = discord.File(io.BytesIO(transcript.encode()), filename=f"ticket-{interaction.channel.name}-transcript.txt")
            log_embed = discord.Embed(
                title=f"📝 Ticket Closed: {interaction.channel.name}",
                color=discord.Color.green(),
                description=(
                    f"**Closed by:** {interaction.user.mention}\n"
                    f"**Reason:** {reason}\n"
                    f"**Ticket Channel:** `{interaction.channel.name}`"
                ),
                timestamp=datetime.now(timezone.utc)
            )
            log_embed.set_footer(text="PNW eSports | Ticket Logs")
            # Add explanation field if available
            if explanation_text:
                log_embed.add_field(name="Ticket Explanation", value=explanation_text, inline=False)
            await ticket_logs_channel.send(embed=log_embed, file=file)
        else:
            log_embed = discord.Embed(
                title=f"📝 Ticket Closed: {interaction.channel.name}",
                color=discord.Color.green(),
                description=(
                    f"**Closed by:** {interaction.user.mention}\n"
                    f"**Reason:** {reason}\n"
                    f"**Ticket Channel:** `{interaction.channel.name}`"
                ),
                timestamp=datetime.now(timezone.utc)
            )
            log_embed.set_footer(text="PNW eSports | Ticket Logs")
            # Add explanation field if available
            if explanation_text:
                log_embed.add_field(name="Ticket Explanation", value=explanation_text, inline=False)
            await ticket_logs_channel.send(embed=log_embed)

        # --- Send Tech Notes as an embed ---
        if tech_notes_content and tech_notes_content.strip():
            # Parse notes and group by technician
            notes = tech_notes_content.strip().split("--------------------------\n")
            tech_dict = {}
            for note in notes:
                if note.strip():
                    lines = note.strip().split("\n")
                    tech_name = ""
                    date = ""
                    note_text = ""
                    for line in lines:
                        if line.startswith("Technician:"):
                            match = re.match(r"Technician:\s+(.+)\s+\(\d+\)", line)
                            if match:
                                tech_name = match.group(1)
                        elif line.startswith("Time:"):
                            full_datetime = line[len("Time:"):].strip()
                            date = full_datetime.split(" ")[0]
                        elif line.startswith("Note:"):
                            note_text = line[len("Note:"):].strip()
                    key = tech_name
                    entry = f"**Date:** `{date}`\n> {note_text}"
                    if key in tech_dict:
                        tech_dict[key].append(entry)
                    else:
                        tech_dict[key] = [entry]

            tech_embed = discord.Embed(
                title="🛠️ Technician Notes",
                color=discord.Color.red(),
                description="Below are all technician notes for this ticket."
            )
            for tech_name, entries in tech_dict.items():
                value = "\n\n".join(entries)
                tech_embed.add_field(
                    name=f"Technician: {tech_name}",
                    value=value,
                    inline=False
                )
            tech_embed.set_footer(text="PNW eSports | Ticket Logs")
            await ticket_logs_channel.send(embed=tech_embed)
        else:
            tech_embed = discord.Embed(
                title="🛠️ Technician Notes",
                color=discord.Color.red(),
                description="No technician notes were added for this ticket."
            )
            tech_embed.set_footer(text="PNW eSports | Ticket Logs")
            await ticket_logs_channel.send(embed=tech_embed)
        
        # Log ticket closure to JSON for dashboard (user close)
        try:
            ticket_id = interaction.channel.name.replace(TICKET_CHANNEL_PREFIX, "")
            first_name = None
            email = None
            ticket_type = None
            orig_user_id = self.user_id
            async for msg in interaction.channel.history(limit=10, oldest_first=True):
                if msg.author == interaction.guild.me and msg.embeds:
                    embed_data = msg.embeds[0]
                    for field in embed_data.fields:
                        if field.name == "First Name":
                            first_name = field.value
                        elif field.name == "Purdue eMail":
                            email = field.value
                        elif field.name == "Type of Support":
                            ticket_type = field.value
                    break
            
            msg_list = []
            async for msg in interaction.channel.history(limit=100, oldest_first=True):
                msg_list.append({
                    "author": f"{msg.author} ({msg.author.id})",
                    "content": msg.content + (" " + " ".join(a.url for a in msg.attachments) if msg.attachments else ""),
                    "timestamp": msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
                })
            
            log_ticket(
                ticket_id=int(ticket_id) if ticket_id.isdigit() else ticket_id,
                channel_name=interaction.channel.name,
                user=str(interaction.guild.get_member(orig_user_id) or "Unknown"),
                user_id=orig_user_id,
                ticket_type=ticket_type or "Unknown",
                first_name=first_name or "Unknown",
                email=email or "Unknown",
                explanation=explanation_text or "Unknown",
                status="closed",
                closed_by=str(interaction.user) + " (User)",
                close_reason=reason,
                messages=msg_list
            )
        except Exception as e:
            print(f"[ERROR] Failed to log ticket closure: {e}")
        
        await asyncio.sleep(2)
        await interaction.channel.delete(reason=reason)

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger, custom_id="user_close_no")
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the ticket creator can use this.", ephemeral=True)
            return
        await interaction.response.edit_message(content="Ticket closure cancelled.", embed=None, view=None)


# --- TicketCloseModal ---
class TicketCloseModal(discord.ui.Modal):
    def __init__(self, user_id, admin_view=None):
        super().__init__(title="Close Ticket")
        self.user_id = user_id
        self.admin_view = admin_view
        self.reason = discord.ui.TextInput(
            label="Reason for Closing Ticket",
            style=discord.TextStyle.paragraph,
            required=True
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Only admins can close tickets.", ephemeral=True)
            return
        await interaction.response.defer()
        guild = interaction.guild
        user = guild.get_member(self.user_id) if guild else None
        if user:
            embed = discord.Embed(
                title="🎫 Your Ticket Has Been Closed",
                color=discord.Color.red(),
                description="You have closed your ticket. If you need further help, you may open a new ticket.",
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Closed By", value=f"{interaction.user.mention} ({interaction.user.name})", inline=False)
            embed.add_field(name="Reason", value=self.reason.value, inline=False)
            embed.set_footer(text="Thank you for using the PNW eSports Support System!")
            try:
                await user.send(embed=embed)
            except Exception:
                pass
        ticket_logs_channel = await get_or_create_ticket_logs_channel(guild)
        messages = []
        async for msg in interaction.channel.history(limit=100, oldest_first=True):
            timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            author = f"{msg.author} ({msg.author.id})"
            content = msg.content
            if msg.attachments:
                content += " " + " ".join(a.url for a in msg.attachments)
            messages.append(f"[{timestamp}] {author}: {content}")
        transcript = "\n".join(messages) or "No messages found."
        reason = self.reason.value or "No reason provided"

        # --- Read tech notes from file ---
        folder_path = os.path.join("data", "tech_notes")
        file_path = os.path.join(folder_path, f"{interaction.channel.name}.txt")
        tech_notes_content = None
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                tech_notes_content = f.read()
            os.remove(file_path)  # Clean up after logging

        # --- Extract Explanation from original ticket message embed ---
        explanation_text = None
        async for msg in interaction.channel.history(limit=10, oldest_first=True):
            if msg.author == interaction.guild.me and msg.embeds:
                embed = msg.embeds[0]
                for field in embed.fields:
                    if field.name == "Explanation":
                        explanation_text = field.value
                        break
                if explanation_text:
                    break

        # If transcript is too long for an embed, send as a file
        if len(transcript) > 10:
            import io
            file = discord.File(io.BytesIO(transcript.encode()), filename=f"ticket-{interaction.channel.name}-transcript.txt")
            log_embed = discord.Embed(
                title=f"📝 Ticket Closed: {interaction.channel.name}",
                color=discord.Color.green(),
                description=(
                    f"**Closed by:** {interaction.user.mention}\n"
                    f"**Reason:** {reason}\n"
                    f"**Ticket Channel:** `{interaction.channel.name}`"
                ),
                timestamp=datetime.now(timezone.utc)
            )
            log_embed.set_footer(text="PNW eSports | Ticket Logs")
            # Add explanation field if available
            if explanation_text:
                log_embed.add_field(name="Ticket Explanation", value=explanation_text, inline=False)
            await ticket_logs_channel.send(embed=log_embed, file=file)
        else:
            log_embed = discord.Embed(
                title=f"📝 Ticket Closed: {interaction.channel.name}",
                color=discord.Color.green(),
                description=(
                    f"**Closed by:** {interaction.user.mention}\n"
                    f"**Reason:** {reason}\n"
                    f"**Ticket Channel:** `{interaction.channel.name}`"
                ),
                timestamp=datetime.now(timezone.utc)
            )
            log_embed.set_footer(text="PNW eSports | Ticket Logs")
            # Add explanation field if available
            if explanation_text:
                log_embed.add_field(name="Ticket Explanation", value=explanation_text, inline=False)
            await ticket_logs_channel.send(embed=log_embed)

        # --- Send Tech Notes as an embed ---
        if tech_notes_content and tech_notes_content.strip():
            # Parse notes and group by technician
            notes = tech_notes_content.strip().split("--------------------------\n")
            tech_dict = {}
            for note in notes:
                if note.strip():
                    lines = note.strip().split("\n")
                    tech_name = ""
                    date = ""
                    note_text = ""
                    for line in lines:
                        if line.startswith("Technician:"):
                            match = re.match(r"Technician:\s+(.+)\s+\(\d+\)", line)
                            if match:
                                tech_name = match.group(1)
                        elif line.startswith("Time:"):
                            full_datetime = line[len("Time:"):].strip()
                            date = full_datetime.split(" ")[0]
                        elif line.startswith("Note:"):
                            note_text = line[len("Note:"):].strip()
                    key = tech_name
                    entry = f"**Date:** `{date}`\n> {note_text}"
                    if key in tech_dict:
                        tech_dict[key].append(entry)
                    else:
                        tech_dict[key] = [entry]

            tech_embed = discord.Embed(
                title="🛠️ Technician Notes",
                color=discord.Color.red(),
                description="Below are all technician notes for this ticket."
            )
            for tech_name, entries in tech_dict.items():
                value = "\n\n".join(entries)
                tech_embed.add_field(
                    name=f"Technician: {tech_name}",
                    value=value,
                    inline=False
                )
            tech_embed.set_footer(text="PNW eSports | Ticket Logs")
            await ticket_logs_channel.send(embed=tech_embed)
        else:
            tech_embed = discord.Embed(
                title="🛠️ Technician Notes",
                color=discord.Color.red(),
                description="No technician notes were added for this ticket."
            )
            tech_embed.set_footer(text="PNW eSports | Ticket Logs")
            await ticket_logs_channel.send(embed=tech_embed)
        
        # Log ticket closure to JSON for dashboard (admin close)
        try:
            ticket_id = interaction.channel.name.replace(TICKET_CHANNEL_PREFIX, "")
            first_name = None
            email = None
            ticket_type = None
            orig_user_id = self.user_id
            async for msg in interaction.channel.history(limit=10, oldest_first=True):
                if msg.author == interaction.guild.me and msg.embeds:
                    embed_data = msg.embeds[0]
                    for field in embed_data.fields:
                        if field.name == "First Name":
                            first_name = field.value
                        elif field.name == "Purdue eMail":
                            email = field.value
                        elif field.name == "Type of Support":
                            ticket_type = field.value
                    break
            
            msg_list = []
            async for msg in interaction.channel.history(limit=100, oldest_first=True):
                msg_list.append({
                    "author": f"{msg.author} ({msg.author.id})",
                    "content": msg.content + (" " + " ".join(a.url for a in msg.attachments) if msg.attachments else ""),
                    "timestamp": msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
                })
            
            log_ticket(
                ticket_id=int(ticket_id) if ticket_id.isdigit() else ticket_id,
                channel_name=interaction.channel.name,
                user=str(guild.get_member(orig_user_id) or "Unknown"),
                user_id=orig_user_id,
                ticket_type=ticket_type or "Unknown",
                first_name=first_name or "Unknown",
                email=email or "Unknown",
                explanation=explanation_text or "Unknown",
                status="closed",
                closed_by=str(interaction.user) + " (Admin)",
                close_reason=reason,
                messages=msg_list
            )
        except Exception as e:
            print(f"[ERROR] Failed to log ticket closure (admin): {e}")
        
        await asyncio.sleep(2)
        await interaction.channel.delete(reason=reason)

