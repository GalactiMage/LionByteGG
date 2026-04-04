import discord
from discord.ext import tasks
from datetime import datetime, timezone
import re
import asyncio
import os
import json

import config
import settings
from safe_json import safe_json_dump

# Path to data files
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
TICKET_LOG_FILE = os.path.join(DATA_DIR, "ticket_log.json")
BOT_CONFIG_FILE = os.path.join(DATA_DIR, "bot_config.json")

# Logo file path
LOGO_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "purduenetworklogo.PNG")

# Default config used if bot_config.json doesn't exist yet
DEFAULT_CONFIG = {
    "staff_role_id": None,
    "ticket_panel_channel_id": None,
    "ticket_category_name": "MC Tickets",
    "ticket_channel_prefix": "mc-ticket-",
    "announce_channel_id": None,
    "minecraft_role_id": None,
    "faq_channel_id": None,
    "support_categories": [
        {"label": "Player Support", "value": "Player Support", "emoji": "🎮", "description": "General gameplay help and questions"},
        {"label": "Server Bugs", "value": "Server Bugs", "emoji": "🐛", "description": "Report server issues or bugs"},
        {"label": "Report a Player", "value": "Report a Player", "emoji": "🛡️", "description": "Report rule-breaking behavior"},
        {"label": "Appeal / Unban", "value": "Appeal / Unban", "emoji": "⚖️", "description": "Appeal a ban or punishment"},
        {"label": "General Question", "value": "General Question", "emoji": "❓", "description": "Anything else not listed above"},
    ]
}


def load_bot_config():
    """Load bot configuration from bot_config.json, falling back to defaults."""
    try:
        if os.path.exists(BOT_CONFIG_FILE):
            with open(BOT_CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Merge with defaults so new keys are always present
                merged = {**DEFAULT_CONFIG, **data}
                return merged
    except Exception as e:
        print(f"[CONFIG] Error loading bot_config.json: {e}")
    return dict(DEFAULT_CONFIG)


def save_bot_config(cfg):
    """Save bot configuration to bot_config.json."""
    try:
        os.makedirs(os.path.dirname(BOT_CONFIG_FILE), exist_ok=True)
        safe_json_dump(cfg, BOT_CONFIG_FILE, indent=2)
    except Exception as e:
        print(f"[CONFIG] Error saving bot_config.json: {e}")

# Blacklist stored in ticket log
def get_ticket_blacklist():
    """Get the list of blacklisted user IDs from the ticket log"""
    try:
        if os.path.exists(TICKET_LOG_FILE):
            with open(TICKET_LOG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return [int(entry.get("user_id", 0)) for entry in data.get("blacklist", [])]
    except Exception:
        pass
    return []


def log_ticket(ticket_id, channel_name, user, user_id, ticket_type, minecraft_username, email, explanation, status="open", staff_assisting=None, closed_by=None, close_reason=None, messages=None):
    """Log ticket data to JSON file for dashboard access"""
    try:
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
            "minecraft_username": minecraft_username,
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
            data["open"] = [t for t in data.get("open", []) if str(t.get("id")) != str(ticket_id)]
            data["closed"].append(ticket_entry)
        else:
            exists = False
            for i, t in enumerate(data.get("open", [])):
                if str(t.get("id")) == str(ticket_id):
                    data["open"][i] = ticket_entry
                    exists = True
                    break
            if not exists:
                data["open"].append(ticket_entry)

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


async def get_or_create_ticket_logs_channel(guild):
    """Find or create a ticket-logs channel for logging closed tickets"""
    channel_name = "mc-ticket-logs"
    existing = discord.utils.get(guild.text_channels, name=channel_name)
    if existing:
        return existing

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
    }
    for role in guild.roles:
        if role.permissions.administrator:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True)

    channel = await guild.create_text_channel(
        channel_name,
        overwrites=overwrites,
        reason="Purdue Network Ticket Logs"
    )
    return channel


# ==================== Panel View ====================

class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # Persistent view

    @discord.ui.button(label="Contact Support", style=discord.ButtonStyle.danger, custom_id="bc_contact_support", emoji="⛏️")
    async def contact_support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Please select the type of support you need:",
            view=IssueTypeSelectView(),
            ephemeral=True
        )


# ==================== Issue Type Select ====================

class IssueTypeSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        cfg = load_bot_config()
        categories = cfg.get("support_categories", DEFAULT_CONFIG["support_categories"])

        options = []
        for cat in categories:
            options.append(discord.SelectOption(
                label=cat.get("label", "Unknown"),
                value=cat.get("value", cat.get("label", "Unknown")),
                emoji=cat.get("emoji"),
                description=cat.get("description", "")[:100] if cat.get("description") else None
            ))

        # Fallback if no categories configured
        if not options:
            options = [discord.SelectOption(label="General Question", value="General Question", emoji="❓")]

        self.issue_type_select = discord.ui.Select(
            placeholder="Choose your support category...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="bc_issue_type_select"
        )
        self.issue_type_select.callback = self.select_callback
        self.add_item(self.issue_type_select)

    async def select_callback(self, interaction: discord.Interaction):
        issue_type = self.issue_type_select.values[0]
        await interaction.response.send_modal(
            TicketIssueModal(issue_type)
        )


# ==================== Ticket Modal ====================

class TicketIssueModal(discord.ui.Modal):
    def __init__(self, issue_type):
        super().__init__(title="Purdue Network Support Ticket")
        self.issue_type = issue_type
        self.mc_username = discord.ui.TextInput(
            label="Minecraft Username",
            placeholder="Steve",
            required=True
        )
        self.purdue_email = discord.ui.TextInput(
            label="Purdue Email",
            placeholder="user@purdue.edu",
            required=True
        )
        self.explanation = discord.ui.TextInput(
            label="Describe Your Issue",
            placeholder="What happened? Include as much detail as possible.",
            style=discord.TextStyle.paragraph,
            required=True
        )
        self.add_item(self.mc_username)
        self.add_item(self.purdue_email)
        self.add_item(self.explanation)

    async def on_submit(self, interaction: discord.Interaction):
        # Check if user is blacklisted
        if interaction.user.id in get_ticket_blacklist():
            await interaction.response.send_message(
                "🚫 You are blacklisted from creating tickets. Please contact a Server Admin.",
                ephemeral=True
            )
            return

        # Check if the user is verified (staff/admins bypass this check)
        member = interaction.guild.get_member(interaction.user.id)
        is_admin = member.guild_permissions.administrator if member else False

        cfg_check = load_bot_config()
        check_staff_role_id = cfg_check.get("staff_role_id")
        if check_staff_role_id:
            check_staff_role_id = int(check_staff_role_id)
        is_staff = check_staff_role_id and any(r.id == check_staff_role_id for r in (member.roles if member else []))

        if not is_admin and not is_staff:
            verified_role_id = settings.VERIFIED_ROLE_ID
            if not member or verified_role_id not in [role.id for role in member.roles]:
                await interaction.response.send_message(
                    "❌ Only verified Purdue students can use the ticket system. Please verify first with `/verify`.",
                    ephemeral=True
                )
                return

        # Validate Purdue email
        valid_domains = settings.VALID_EMAIL_DOMAINS
        email_valid = False
        for domain in valid_domains:
            if self.purdue_email.value.lower().endswith(domain):
                email_valid = True
                break
        if not email_valid:
            await interaction.response.send_message(
                "❌ Invalid email. Only Purdue emails are allowed for support tickets.",
                ephemeral=True
            )
            return

        guild = interaction.guild

        # Load config for dynamic settings
        cfg = load_bot_config()
        ticket_channel_prefix = cfg.get("ticket_channel_prefix", "mc-ticket-")
        ticket_category_name = cfg.get("ticket_category_name", "MC Tickets")
        staff_role_id = cfg.get("staff_role_id")
        if staff_role_id:
            staff_role_id = int(staff_role_id)

        # ===== DUPLICATE TICKET PREVENTION =====
        for channel in guild.text_channels:
            if channel.name.startswith(ticket_channel_prefix):
                overwrites = channel.overwrites_for(interaction.user)
                if overwrites.read_messages is True:
                    await interaction.response.send_message(
                        f"⚠️ You already have an open ticket: {channel.mention}\n"
                        f"Please use your existing ticket or wait for it to be closed.",
                        ephemeral=True
                    )
                    return

        try:
            if os.path.exists(TICKET_LOG_FILE):
                with open(TICKET_LOG_FILE, 'r', encoding='utf-8') as f:
                    ticket_data = json.load(f)
                    open_tickets = ticket_data.get("open", [])
                    user_open_tickets = [t for t in open_tickets if str(t.get("user_id")) == str(interaction.user.id)]
                    if user_open_tickets:
                        for user_ticket in user_open_tickets:
                            existing_channel = discord.utils.get(guild.text_channels, name=user_ticket.get("channel_name"))
                            if existing_channel:
                                await interaction.response.send_message(
                                    f"⚠️ You already have an open ticket: {existing_channel.mention}\n"
                                    f"Please use your existing ticket or wait for it to be closed.",
                                    ephemeral=True
                                )
                                return
        except Exception as e:
            print(f"[TICKET] Error checking for duplicate tickets: {e}")

        # Find or create the ticket category
        parent_category = None
        if interaction.channel and isinstance(interaction.channel, discord.TextChannel):
            parent_category = interaction.channel.category

        if parent_category:
            category = parent_category
        else:
            category = discord.utils.get(guild.categories, name=ticket_category_name)
            if not category:
                category = await guild.create_category(ticket_category_name, reason="Purdue Network Ticket System")

        # Find next ticket number
        existing = [c for c in category.channels if c.name.startswith(ticket_channel_prefix)]
        numbers = []
        for c in existing:
            try:
                numbers.append(int(c.name.replace(ticket_channel_prefix, "")))
            except:
                pass
        next_number = max(numbers, default=0) + 1
        ticket_channel_name = f"{ticket_channel_prefix}{str(next_number).zfill(4)}"

        # Set permissions
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(
                read_messages=True, send_messages=True,
                attach_files=True, embed_links=True
            ),
        }
        for role in guild.roles:
            if role.permissions.administrator:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        # Add staff role if configured
        if staff_role_id:
            staff_role = guild.get_role(staff_role_id)
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        ticket_channel = await guild.create_text_channel(
            ticket_channel_name,
            category=category,
            overwrites=overwrites,
            reason="New Purdue Network support ticket"
        )

        # Ticket embed
        embed = discord.Embed(
            title="🎮 Purdue Network Support Ticket",
            color=config.COLORS["purdue_gold"],
            timestamp=datetime.now(timezone.utc),
            description="A new support ticket has been created. Please wait for staff to respond."
        )
        embed.add_field(name="Minecraft Username", value=self.mc_username.value, inline=True)
        embed.add_field(name="Purdue Email", value=self.purdue_email.value, inline=True)
        embed.add_field(name="Issue Type", value=self.issue_type, inline=True)
        embed.add_field(name="Description", value=self.explanation.value, inline=False)
        embed.add_field(name="User", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False)
        embed.set_footer(text=f"{config.BOT_NAME} | Ticket System")
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        # Ping staff
        staff_ping = ""
        if staff_role_id:
            staff_ping = f" <@&{staff_role_id}>"

        ticket_admin_view = TicketAdminView(interaction.user.id)
        ticket_msg = await ticket_channel.send(
            content=f"{interaction.user.mention}{staff_ping}",
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
            ticket_type=self.issue_type,
            minecraft_username=self.mc_username.value,
            email=self.purdue_email.value,
            explanation=self.explanation.value,
            status="open"
        )

        await interaction.response.send_message(
            f"✅ Your ticket has been created: {ticket_channel.mention}",
            ephemeral=True
        )


# ==================== Admin View ====================

class TicketAdminView(discord.ui.View):
    def __init__(self, user_id=None):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.taken = False
        self.ticket_message = None

    def set_ticket_message(self, message):
        self.ticket_message = message

    @discord.ui.button(label="Take Ticket", style=discord.ButtonStyle.primary, custom_id="bc_take_ticket")
    async def take_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = load_bot_config()
        staff_role_id = cfg.get("staff_role_id")
        if staff_role_id:
            staff_role_id = int(staff_role_id)

        if not interaction.user.guild_permissions.administrator:
            staff_role = interaction.guild.get_role(staff_role_id) if staff_role_id else None
            if not staff_role or staff_role not in interaction.user.roles:
                await interaction.response.send_message("Only staff can take tickets.", ephemeral=True)
                return

        if self.taken:
            await interaction.response.send_message("This ticket has already been taken.", ephemeral=True)
            return

        self.taken = True
        button.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message(
            f"Ticket has been taken by {interaction.user.mention}.",
            ephemeral=False
        )

        user = interaction.guild.get_member(self.user_id)
        if user:
            await interaction.channel.send(f"{user.mention}, your ticket has been taken by {interaction.user.mention}.")

        update_ticket_staff(
            channel_name=interaction.channel.name,
            staff_name=str(interaction.user),
            staff_id=interaction.user.id
        )

        # Update embed with staff info
        if self.ticket_message:
            embed = self.ticket_message.embeds[0]
            embed_dict = embed.to_dict()
            embed_dict['fields'] = [f for f in embed_dict.get('fields', []) if f.get('name') != "Staff Assisting"]
            embed_dict['fields'].append({
                "name": "Staff Assisting",
                "value": f"{interaction.user.mention} ({interaction.user.id})",
                "inline": False
            })
            new_embed = discord.Embed.from_dict(embed_dict)
            await self.ticket_message.edit(embed=new_embed, view=self)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="bc_close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.user_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Are you sure you want to close this Ticket?",
                    description="By closing this ticket you are stating that your issue has been resolved.",
                    color=discord.Color.orange()
                ),
                view=UserCloseConfirmView(self.user_id, admin_view=self),
                ephemeral=True
            )
            return

        cfg = load_bot_config()
        staff_role_id = cfg.get("staff_role_id")
        if staff_role_id:
            staff_role_id = int(staff_role_id)

        if not interaction.user.guild_permissions.administrator:
            staff_role = interaction.guild.get_role(staff_role_id) if staff_role_id else None
            if not staff_role or staff_role not in interaction.user.roles:
                await interaction.response.send_message("Only staff can close tickets.", ephemeral=True)
                return

        await interaction.response.send_modal(TicketCloseModal(self.user_id, admin_view=self))


# ==================== User Close Confirm ====================

class UserCloseConfirmView(discord.ui.View):
    def __init__(self, user_id, admin_view=None):
        super().__init__(timeout=30)
        self.user_id = user_id
        self.admin_view = admin_view

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success, custom_id="bc_user_close_yes")
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the ticket creator can close this ticket.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await interaction.channel.send("User has closed the ticket. Channel will be deleted shortly.")

        guild = interaction.guild or interaction.client.get_guild(settings.GUILD_ID)
        user = guild.get_member(self.user_id) if guild else None

        if user:
            embed = discord.Embed(
                title="🎮 Your Ticket Has Been Closed",
                color=discord.Color.red(),
                description="Your Purdue Network support ticket has been closed. If you need further help, open a new ticket.",
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Closed By", value=f"{interaction.user.mention} ({interaction.user.name})", inline=False)
            embed.set_footer(text=f"{config.BOT_NAME} | Ticket System")
            try:
                await user.send(embed=embed)
            except Exception:
                pass

        # Collect transcript
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

        # Extract description from original embed
        explanation_text = None
        async for msg in interaction.channel.history(limit=10, oldest_first=True):
            if msg.author == interaction.guild.me and msg.embeds:
                embed = msg.embeds[0]
                for field in embed.fields:
                    if field.name == "Description":
                        explanation_text = field.value
                        break
                if explanation_text:
                    break

        # Send transcript to logs channel
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
        log_embed.set_footer(text=f"{config.BOT_NAME} | Ticket Logs")
        if explanation_text:
            log_embed.add_field(name="Ticket Description", value=explanation_text, inline=False)
        await ticket_logs_channel.send(embed=log_embed, file=file)

        # Log to JSON for dashboard
        try:
            close_cfg = load_bot_config()
            close_prefix = close_cfg.get("ticket_channel_prefix", "mc-ticket-")
            ticket_id = interaction.channel.name.replace(close_prefix, "")
            mc_username = None
            email = None
            ticket_type = None
            orig_user_id = self.user_id
            async for msg in interaction.channel.history(limit=10, oldest_first=True):
                if msg.author == interaction.guild.me and msg.embeds:
                    embed_data = msg.embeds[0]
                    for field in embed_data.fields:
                        if field.name == "Minecraft Username":
                            mc_username = field.value
                        elif field.name == "Purdue Email":
                            email = field.value
                        elif field.name == "Issue Type":
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
                minecraft_username=mc_username or "Unknown",
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

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger, custom_id="bc_user_close_no")
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the ticket creator can use this.", ephemeral=True)
            return
        await interaction.response.edit_message(content="Ticket closure cancelled.", embed=None, view=None)


# ==================== Admin Close Modal ====================

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
        cfg = load_bot_config()
        staff_role_id = cfg.get("staff_role_id")
        if staff_role_id:
            staff_role_id = int(staff_role_id)

        if not interaction.user.guild_permissions.administrator:
            staff_role = interaction.guild.get_role(staff_role_id) if staff_role_id else None
            if not staff_role or staff_role not in interaction.user.roles:
                await interaction.response.send_message("Only staff can close tickets.", ephemeral=True)
                return

        await interaction.response.defer()
        guild = interaction.guild
        user = guild.get_member(self.user_id) if guild else None

        if user:
            embed = discord.Embed(
                title="🎮 Your Ticket Has Been Closed",
                color=discord.Color.red(),
                description="Your Purdue Network support ticket has been closed by staff.",
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Closed By", value=f"{interaction.user.mention} ({interaction.user.name})", inline=False)
            embed.add_field(name="Reason", value=self.reason.value, inline=False)
            embed.set_footer(text=f"{config.BOT_NAME} | Ticket System")
            try:
                await user.send(embed=embed)
            except Exception:
                pass

        # Collect transcript
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

        # Extract description
        explanation_text = None
        async for msg in interaction.channel.history(limit=10, oldest_first=True):
            if msg.author == interaction.guild.me and msg.embeds:
                embed = msg.embeds[0]
                for field in embed.fields:
                    if field.name == "Description":
                        explanation_text = field.value
                        break
                if explanation_text:
                    break

        # Send transcript
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
        log_embed.set_footer(text=f"{config.BOT_NAME} | Ticket Logs")
        if explanation_text:
            log_embed.add_field(name="Ticket Description", value=explanation_text, inline=False)
        await ticket_logs_channel.send(embed=log_embed, file=file)

        # Log to JSON for dashboard
        try:
            close_cfg = load_bot_config()
            close_prefix = close_cfg.get("ticket_channel_prefix", "mc-ticket-")
            ticket_id = interaction.channel.name.replace(close_prefix, "")
            mc_username = None
            email = None
            ticket_type = None
            orig_user_id = self.user_id
            async for msg in interaction.channel.history(limit=10, oldest_first=True):
                if msg.author == interaction.guild.me and msg.embeds:
                    embed_data = msg.embeds[0]
                    for field in embed_data.fields:
                        if field.name == "Minecraft Username":
                            mc_username = field.value
                        elif field.name == "Purdue Email":
                            email = field.value
                        elif field.name == "Issue Type":
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
                minecraft_username=mc_username or "Unknown",
                email=email or "Unknown",
                explanation=explanation_text or "Unknown",
                status="closed",
                closed_by=str(interaction.user) + " (Staff)",
                close_reason=reason,
                messages=msg_list
            )
        except Exception as e:
            print(f"[ERROR] Failed to log ticket closure (staff): {e}")

        await asyncio.sleep(2)
        await interaction.channel.delete(reason=reason)


# ==================== Panel Setup ====================

async def ensure_ticket_panel_message(bot, guild_id, channel_id):
    """Ensures only one ticket panel message exists in the specified channel."""
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
            if embed.title and ("Support" in embed.title) and ("Purdue" in embed.title or "BoilerCraft" in embed.title):
                panel_exists = True
                try:
                    await message.edit(view=TicketPanelView())
                except Exception as e:
                    print(f"[ERROR] Could not re-attach view to message {message.id}: {e}")

    if not panel_exists:
        cfg = load_bot_config()
        categories = cfg.get("support_categories", DEFAULT_CONFIG["support_categories"])

        # Build dynamic category list for the panel
        category_lines = []
        for cat in categories:
            emoji = cat.get("emoji", "•")
            label = cat.get("label", "Unknown")
            desc = cat.get("description", "")
            if desc:
                category_lines.append(f"{emoji} **{label}** — {desc}")
            else:
                category_lines.append(f"{emoji} **{label}**")
        category_text = "\n".join(category_lines) if category_lines else "❓ General Support"

        embed = discord.Embed(
            title="🎮 Welcome to the Purdue Network Support System",
            description=(
                "Need help with the **Purdue Network** Minecraft server?\n"
                "Our team is here to assist you!\n\n"
                f"{category_text}\n\n"
                f"🖥️ **Server IP:** `{settings.MINECRAFT_SERVER_IP}`\n\n"
                "Click **Contact Support** below to open a ticket."
            ),
            color=config.COLORS["purdue_gold"]
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Purdue Network Support")

        # Attach logo as thumbnail
        logo_file = None
        if os.path.exists(LOGO_FILE):
            logo_file = discord.File(LOGO_FILE, filename="logo.png")
            embed.set_thumbnail(url="attachment://logo.png")

        if logo_file:
            await channel.send(embed=embed, view=TicketPanelView(), file=logo_file)
        else:
            await channel.send(embed=embed, view=TicketPanelView())
