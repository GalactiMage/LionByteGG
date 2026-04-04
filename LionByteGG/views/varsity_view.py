import discord
from discord.ext import tasks, commands
from discord import app_commands
from datetime import datetime, timezone
import asyncio
import os
import json
from pathlib import Path
from utils.constants import (
    GUILD_ID, REGISTRATION_REVIEW_CHANNEL_NAME, USER_RECORDS_DIR, 
    VARSITY_REG_DIR, SCHEDULE_IMAGES_DIR, LOG_CHANNEL_NAME
)
from utils.safe_json import safe_json_dump

# Data directory for teams/rosters
DATA_DIR = os.path.join(str(Path(__file__).resolve().parents[1]), "data")
TEAMS_FILE = os.path.join(DATA_DIR, "teams.json")
ROSTERS_FILE = os.path.join(DATA_DIR, "rosters.json")
TEAM_ROLE_SETTINGS_FILE = os.path.join(DATA_DIR, "team_role_settings.json")
PENDING_REGISTRATIONS_FILE = os.path.join(DATA_DIR, "pending_varsity_registrations.json")
LIVE_NOTIFICATIONS_FILE = os.path.join(DATA_DIR, "live_notifications.json")

def add_varsity_notification(title, message, link=None, target_id=None, target_name=None, notif_type="registration"):
    """Add a live notification for varsity events"""
    try:
        if os.path.exists(LIVE_NOTIFICATIONS_FILE):
            with open(LIVE_NOTIFICATIONS_FILE, 'r', encoding='utf-8') as f:
                notifications = json.load(f)
        else:
            notifications = {"notifications": [], "last_cleared": None}
        
        notification = {
            "id": f"notif_{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(4).hex()}",
            "type": notif_type,
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
        print(f"[ERROR] Failed to add varsity notification: {e}")

def load_json_file(filepath, default=None):
    if default is None:
        default = {}
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return default
    return default

def save_json_file(filepath, data):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    safe_json_dump(data, filepath, indent=2)

def load_teams():
    return load_json_file(TEAMS_FILE, {"teams": []})

def load_rosters():
    return load_json_file(ROSTERS_FILE, {"players": []})

def load_esports_games():
    """Load esports games from the website-synced JSON file"""
    games_file = os.path.join(DATA_DIR, "esports_games.json")
    data = load_json_file(games_file, {"games": []})
    return data.get("games", [])

def save_rosters(data):
    save_json_file(ROSTERS_FILE, data)

def load_team_role_settings():
    """Load role mapping settings from JSON file (managed by website)"""
    return load_json_file(TEAM_ROLE_SETTINGS_FILE, {
        "mapping": {},
        "varsity_role_id": None,
        "jv_role_id": None
    })

def load_pending_registrations():
    """Load pending varsity registration DMs (for persistence across restarts)"""
    return load_json_file(PENDING_REGISTRATIONS_FILE, {})

def save_pending_registrations(data):
    """Save pending varsity registration DMs"""
    save_json_file(PENDING_REGISTRATIONS_FILE, data)

def add_pending_registration(user_id: str, player_type: str, message_id: str = None):
    """Track a pending registration DM sent to a user"""
    pending = load_pending_registrations()
    pending[str(user_id)] = {
        "user_id": str(user_id),
        "player_type": player_type,
        "message_id": str(message_id) if message_id else None,
        "sent_at": datetime.now(timezone.utc).isoformat()
    }
    save_pending_registrations(pending)

def remove_pending_registration(user_id: str):
    """Remove a pending registration (after user completes or cancels)"""
    pending = load_pending_registrations()
    if str(user_id) in pending:
        del pending[str(user_id)]
        save_pending_registrations(pending)

def get_pending_registration(user_id: str):
    """Get pending registration info for a user"""
    pending = load_pending_registrations()
    return pending.get(str(user_id))

# Human-friendly display names for player type values
PLAYER_TYPE_DISPLAY = {
    "varsity": "Varsity",
    "jv": "JV",
    "sub_varsity": "Substitute Varsity",
    "sub_jv": "Substitute JV",
}

class PlayerTypeSelectView(discord.ui.View):
    def __init__(self, requested_by: discord.User, target_user: discord.User):
        super().__init__(timeout=60)
        self.requested_by = requested_by
        self.target_user = target_user

    @discord.ui.select(
        placeholder="Select player type...",
        options=[
            discord.SelectOption(label="Varsity", value="varsity"),
            discord.SelectOption(label="JV", value="jv"),
            discord.SelectOption(label="Substitute Varsity", value="sub_varsity"),
            discord.SelectOption(label="Substitute JV", value="sub_jv"),
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        player_type = select.values[0]
        # Use friendly display names for team labels
        team_name = PLAYER_TYPE_DISPLAY.get(player_type, player_type.replace('_', ' ').title())
        await interaction.response.send_message(
            f"Starting {team_name} registration for {self.target_user.mention}.",
            ephemeral=True
        )
        view = VarsityRegistrationView(requested_by=self.requested_by, player_type=player_type)
        embed = discord.Embed(
            title="Welcome to PNW Esports",
            description=(
                f"**You have been selected to join the {team_name} team for PNW Esports!**\n\n"
                "PNW Esports is home to the elite and victorious. Please complete your registration below to finalize your onboarding.\n\n"
                "We are excited to have you as part of our competitive family. Good luck and Roar Pride!"
            ),
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        embed.set_footer(text="PNW Esports | Registration")
        try:
            await self.target_user.send(embed=embed, view=view)
        except discord.Forbidden:
            await interaction.followup.send("Could not DM the user.", ephemeral=True)


# ============ PERSISTENT REGISTRATION VIEW ============
# This view survives bot restarts because it uses fixed custom_id patterns
# and is registered on bot startup via bot.add_view()

class PersistentVarsityRegistrationView(discord.ui.View):
    """
    Persistent view for varsity registration buttons.
    This view is registered on bot startup to handle buttons from DMs
    that were sent before a bot restart.
    """
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(
        label="Start Registration", 
        style=discord.ButtonStyle.danger, 
        custom_id="persistent_varsity_register"
    )
    async def start_registration(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle registration button click - works even after bot restart"""
        user_id = str(interaction.user.id)
        
        # Get pending registration info to find player_type
        pending = get_pending_registration(user_id)
        if pending:
            player_type = pending.get("player_type", "varsity")
        else:
            # Fallback if not found in pending (shouldn't happen but handle gracefully)
            player_type = "varsity"
        
        # Show game selection dropdown first
        games = load_esports_games()
        if not games:
            await interaction.response.send_message(
                "❌ No games available. Please contact an admin.",
                ephemeral=True
            )
            return
        
        await interaction.response.send_message(
            "🎮 **Select Your Primary Game Title**\n\nPlease choose the game you will be competing in from the dropdown below:",
            view=GameSelectView(
                admin_user=interaction.client.user,
                player_type=player_type,
                interaction_message=interaction.message,
                games=games
            ),
            ephemeral=True
        )


class VarsityRegistrationView(discord.ui.View):
    """
    Non-persistent view used when sending new registration DMs.
    For persistence, we use PersistentVarsityRegistrationView with a fixed custom_id.
    """
    def __init__(self, requested_by: discord.User = None, player_type: str = "varsity", user_id: str = None):
        super().__init__(timeout=None)
        self.requested_by = requested_by
        self.player_type = player_type
        self.user_id = user_id
        # Track users who have completed Varsity registration for this view instance only
        self.varsity_completed = set()
        
        # Remove the default button and add our persistent one
        self.clear_items()
        self.add_item(PersistentRegisterButton(player_type=player_type))


class PersistentRegisterButton(discord.ui.Button):
    """Button with fixed custom_id for persistence"""
    def __init__(self, player_type: str = "varsity"):
        super().__init__(
            label="Start Registration",
            style=discord.ButtonStyle.danger,
            custom_id="persistent_varsity_register"  # Fixed ID - survives restarts
        )
        self.player_type = player_type
    
    async def callback(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        
        # Get pending registration info to find player_type
        pending = get_pending_registration(user_id)
        if pending:
            player_type = pending.get("player_type", "varsity")
        else:
            player_type = self.player_type
        
        # Show game selection dropdown first
        games = load_esports_games()
        if not games:
            await interaction.response.send_message(
                "❌ No games available. Please contact an admin.",
                ephemeral=True
            )
            return
        
        await interaction.response.send_message(
            "🎮 **Select Your Primary Game Title**\n\nPlease choose the game you will be competing in from the dropdown below:",
            view=GameSelectView(
                admin_user=interaction.client.user,
                player_type=player_type,
                interaction_message=interaction.message,
                games=games
            ),
            ephemeral=True
        )


class GameSelectView(discord.ui.View):
    """View with dropdown to select primary game before starting registration"""
    def __init__(self, admin_user, player_type: str, interaction_message, games: list):
        super().__init__(timeout=300)
        self.admin_user = admin_user
        self.player_type = player_type
        self.interaction_message = interaction_message
        self.games = games
        
        # Build dropdown options from synced games (max 25 options for Discord)
        options = []
        for game in games[:25]:
            options.append(discord.SelectOption(
                label=game.get("name", "Unknown Game"),
                value=game.get("name", "Unknown Game")
            ))
        
        if options:
            self.game_select = discord.ui.Select(
                placeholder="Choose your primary game...",
                options=options,
                min_values=1,
                max_values=1
            )
            self.game_select.callback = self.game_select_callback
            self.add_item(self.game_select)
    
    async def game_select_callback(self, interaction: discord.Interaction):
        selected_game = self.game_select.values[0]
        
        # Store the selected game in bot's registration data for this user
        if not hasattr(interaction.client, "varsity_registrations"):
            interaction.client.varsity_registrations = {}
        
        interaction.client.varsity_registrations[interaction.user.id] = {
            "Primary Game Title": selected_game,
            "admin_user": self.admin_user,
            "player_type": self.player_type
        }
        
        # Now send Modal 1
        await interaction.response.send_modal(VarsityRegistrationModal1(
            admin_user=self.admin_user,
            parent_view=None,
            interaction_message=self.interaction_message,
            player_type=self.player_type
        ))


# First modal (questions 1-5)
class VarsityRegistrationModal1(discord.ui.Modal, title="Personal Information"):
    def __init__(self, admin_user, parent_view=None, interaction_message=None, player_type="varsity"):
        super().__init__()
        self.admin_user = admin_user
        self.parent_view = parent_view
        self.interaction_message = interaction_message
        self.player_type = player_type

    name = discord.ui.TextInput(label="Full Name", placeholder="e.g. John Smith", required=True)
    purdue_email = discord.ui.TextInput(label="Purdue Email Address", placeholder="e.g. smith123@purdue.edu", required=True)
    personal_email = discord.ui.TextInput(label="Personal Email Address", placeholder="e.g. johnsmith@gmail.com", required=True)
    phone = discord.ui.TextInput(label="Phone Number", placeholder="e.g. 123-456-7890", required=True)
    ign = discord.ui.TextInput(label="Purdue ID (PUID)", placeholder="e.g. 0012345678", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        # Store answers in interaction.client (the bot) for this user
        # Preserve existing data (like game selection from dropdown)
        if not hasattr(interaction.client, "varsity_registrations"):
            interaction.client.varsity_registrations = {}
        
        existing_data = interaction.client.varsity_registrations.get(interaction.user.id, {})
        existing_data.update({
            "Full Name": self.name.value,
            "Purdue Email": self.purdue_email.value,
            "Personal Email": self.personal_email.value,
            "Phone Number": self.phone.value,
            "PUID": self.ign.value,
            "admin_user": self.admin_user,
            "player_type": self.player_type
        })
        interaction.client.varsity_registrations[interaction.user.id] = existing_data
        # Send a button to continue registration
        await interaction.response.send_message(
            "😃 Awesome, please click the button below to continue your PNW Esports registration.",
            view=VarsityContinueView(self.admin_user, self.parent_view, self.interaction_message, self.player_type),
            ephemeral=True
        )


class VarsityContinueView(discord.ui.View):
    def __init__(self, admin_user, parent_view=None, interaction_message=None, player_type="varsity"):
        super().__init__(timeout=300)
        self.admin_user = admin_user
        self.parent_view = parent_view
        self.interaction_message = interaction_message
        self.player_type = player_type

    @discord.ui.button(label="Continue Registration", style=discord.ButtonStyle.primary)
    async def continue_registration(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VarsityRegistrationModal2(
            admin_user=self.admin_user,
            parent_view=self.parent_view,
            interaction_message=self.interaction_message,
            player_type=self.player_type
        ))


# Second modal (questions 6-10)
class VarsityRegistrationModal2(discord.ui.Modal, title="Academic & Player Details"):
    gpa = discord.ui.TextInput(label="Current GPA", placeholder="Minimum 2.5 GPA required (e.g. 3.2)", required=True)
    hometown = discord.ui.TextInput(label="Home Town/City (State)", placeholder="e.g. Hammond, IN", required=True)
    year = discord.ui.TextInput(label="Year in School", placeholder="e.g. Freshman, Sophomore, Junior, Senior", required=True)
    major = discord.ui.TextInput(label="Major/Field of Study", placeholder="e.g. Computer Science", required=True)
    jersey = discord.ui.TextInput(
        label="Jersey Details (Size & Name)",
        placeholder="e.g. Large - SMITH",
        style=discord.TextStyle.paragraph,
        required=True
    )

    def __init__(self, admin_user, parent_view=None, interaction_message=None, player_type="varsity"):
        super().__init__()
        self.admin_user = admin_user
        self.parent_view = parent_view
        self.interaction_message = interaction_message
        self.player_type = player_type

    async def on_submit(self, interaction: discord.Interaction):
        reg_data = getattr(interaction.client, "varsity_registrations", {}).get(interaction.user.id, {})
        reg_data.update({
            "GPA": self.gpa.value,
            "Home Town/City (State)": self.hometown.value,
            "Year in School": self.year.value,
            "Major": self.major.value,
            "Jersey Details": self.jersey.value,
        })
        interaction.client.varsity_registrations[interaction.user.id] = reg_data
        # Send a button to continue to the final form
        await interaction.response.send_message(
            "🚩 Final step! Please click the button below to finish your registration.",
            view=VarsityFinalContinueView(self.admin_user, self.parent_view, self.interaction_message, self.player_type),
            ephemeral=True
        )


class VarsityFinalContinueView(discord.ui.View):
    def __init__(self, admin_user, parent_view=None, interaction_message=None, player_type="varsity"):
        super().__init__(timeout=300)
        self.admin_user = admin_user
        self.parent_view = parent_view
        self.interaction_message = interaction_message
        self.player_type = player_type

    @discord.ui.button(label="Final Registration Step", style=discord.ButtonStyle.success)
    async def continue_final(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VarsityRegistrationModal3(
            admin_user=self.admin_user,
            parent_view=self.parent_view,
            interaction_message=self.interaction_message,
            player_type=self.player_type
        ))


# Third modal (final 5 questions)
class VarsityRegistrationModal3(discord.ui.Modal, title="Gaming Information"):
    ign = discord.ui.TextInput(label="In-Game Name (IGN)", placeholder="e.g. ProGamer123", required=True)
    rank = discord.ui.TextInput(label="Current Rank", placeholder="e.g. Diamond 2, Immortal, Masters, Grand Champion", required=True)
    primary_role = discord.ui.TextInput(label="Primary Role in Game", placeholder="e.g. DPS, Support, Tank, Jungle, ADC, Duelist", required=True)
    tracker = discord.ui.TextInput(label="Stats Tracker Link", placeholder="e.g. tracker.gg/valorant/profile/...", required=True)
    notes = discord.ui.TextInput(label="Additional Notes (Optional)", placeholder="Anything else we should know?", style=discord.TextStyle.paragraph, required=False)

    def __init__(self, admin_user, parent_view=None, interaction_message=None, player_type="varsity"):
        super().__init__()
        self.admin_user = admin_user
        self.parent_view = parent_view
        self.interaction_message = interaction_message
        self.player_type = player_type

    async def on_submit(self, interaction: discord.Interaction):
        reg_data = getattr(interaction.client, "varsity_registrations", {}).pop(interaction.user.id, {})
        admin_user = reg_data.get("admin_user", None)
        # Map stored player_type value to a human-friendly display name
        raw_player_type = reg_data.get("player_type", "varsity")
        player_type = PLAYER_TYPE_DISPLAY.get(raw_player_type, raw_player_type.replace('_', ' ').title())
        if not admin_user:
            await interaction.response.send_message("❌ Registration error. Please contact an admin.", ephemeral=True)
            return

        reg_data["IGN"] = self.ign.value
        reg_data["Current Rank in Game"] = self.rank.value
        reg_data["Primary Role"] = self.primary_role.value
        reg_data["Tracker Link"] = self.tracker.value
        reg_data["Anything Else"] = self.notes.value

        await interaction.response.send_message(
            "📸 Please DM me (the bot) a picture of your schedule. Your registration will be submitted once you send the image.",
            ephemeral=True
        )

        gif_embed = discord.Embed(
            description="Here's how to send an image to the bot:",
            color=discord.Color.light_grey()
        )
        gif_embed.set_image(url="https://cdn.discordapp.com/attachments/1316453330695884912/1413913274315051071/Screen_Recording_20250906_104331_Discord.gif?ex=68bda8d9&is=68bc5759&hm=8a2229cbfc7000b00da663395ddfc77456c4707a20998b82263ae048ce8209e&")
        await interaction.user.send(embed=gif_embed)

        def check(m):
            return (
                m.author.id == interaction.user.id and
                m.attachments and
                isinstance(m.channel, discord.DMChannel)
            )

        try:
            msg = await interaction.client.wait_for('message', check=check, timeout=180)
            embed = discord.Embed(
                title="📝 Registration Received",
                description=f"A new **{player_type}** recruit has submitted their information. Please review the details below.",
                color=discord.Color.gold()
            )
            embed.add_field(
                name="Discord User",
                value=f"{interaction.user.mention} ({interaction.user.name}#{interaction.user.discriminator})",
                inline=False
            )
            embed.add_field(
                name="👤 Personal Information",
                value=(
                    f"**Full Name:** {reg_data.get('Full Name', 'N/A')}\n"
                    f"**Purdue Email:** {reg_data.get('Purdue Email', 'N/A')}\n"
                    f"**Personal Email:** {reg_data.get('Personal Email', 'N/A')}\n"
                    f"**Phone Number:** {reg_data.get('Phone Number', 'N/A')}\n"
                    f"**PUID:** {reg_data.get('PUID', 'N/A')}"
                ),
                inline=False
            )
            embed.add_field(
                name="🎓 Academic & Player Info",
                value=(
                    f"**GPA:** {reg_data.get('GPA', 'N/A')}\n"
                    f"**Home Town/City (State):** {reg_data.get('Home Town/City (State)', 'N/A')}\n"
                    f"**Year in School:** {reg_data.get('Year in School', 'N/A')}\n"
                    f"**Major:** {reg_data.get('Major', 'N/A')}\n"
                    f"**Jersey Details:** {reg_data.get('Jersey Details', 'N/A')}"
                ),
                inline=False
            )
            embed.add_field(
                name="🎮 Game Information",
                value=(
                    f"**Primary Game:** {reg_data.get('Primary Game Title', 'N/A')}\n"
                    f"**IGN:** {reg_data.get('IGN', 'N/A')}\n"
                    f"**Current Rank:** {reg_data.get('Current Rank in Game', 'N/A')}\n"
                    f"**Primary Role:** {reg_data.get('Primary Role', 'N/A')}\n"
                    f"**Tracker Link:** {reg_data.get('Tracker Link', 'N/A')}\n"
                    f"**Additional Notes:** {reg_data.get('Anything Else', 'N/A')}"
                ),
                inline=False
            )
            embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
            embed.set_footer(text="PNW Esports | Registration")

            view = VarsityApproveView(player_id=interaction.user.id)
            
            # Check if admin_user is the bot itself (registration came from website)
            # If so, skip DM to admin - registration will be viewable in review channel and dashboard
            is_website_registration = (admin_user and admin_user.id == interaction.client.user.id)
            
            if not is_website_registration and admin_user:
                # Send all attachments first, then send the embed with the view once
                try:
                    for attachment in msg.attachments:
                        await admin_user.send(file=await attachment.to_file())
                    # Send embed with view only once (so buttons work)
                    await admin_user.send(embed=embed, view=view)
                except discord.Forbidden:
                    # Admin has DMs disabled, continue without sending to admin
                    pass
            # Persist registration to the dedicated varsity registrations directory
            try:
                os.makedirs(VARSITY_REG_DIR, exist_ok=True)
                os.makedirs(SCHEDULE_IMAGES_DIR, exist_ok=True)
                record_path = os.path.join(VARSITY_REG_DIR, f"{interaction.user.id}_varsity.json")
                # Prepare a JSON-serializable copy of registration data
                saved_reg = {k: v for k, v in reg_data.items()}
                admin_user_obj = saved_reg.get("admin_user")
                if hasattr(admin_user_obj, "id"):
                    saved_reg["admin_user"] = {"id": admin_user_obj.id, "name": str(admin_user_obj)}
                # Download and save attachments locally (permanent storage)
                saved_attachment_paths = []
                try:
                    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                    for idx, attachment in enumerate(msg.attachments):
                        # Get file extension from filename
                        ext = os.path.splitext(attachment.filename)[1] or '.png'
                        # Create unique filename: userid_timestamp_index.ext
                        filename = f"{interaction.user.id}_{timestamp}_{idx}{ext}"
                        filepath = os.path.join(SCHEDULE_IMAGES_DIR, filename)
                        # Download and save the file
                        await attachment.save(filepath)
                        saved_attachment_paths.append(filename)
                except Exception as e:
                    print(f"Error saving attachment: {e}")
                saved_reg["attachments"] = saved_attachment_paths
                saved_reg["attachments_cdn"] = [a.url for a in msg.attachments]  # Keep CDN URLs as backup
                entry = {
                    "type": "VarsityRegistration",
                    "status": "Pending",
                    "data": saved_reg,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                # Load existing records
                existing = []
                if os.path.exists(record_path):
                    try:
                        with open(record_path, "r", encoding="utf-8") as f:
                            existing = json.load(f)
                    except Exception:
                        existing = []
                existing.append(entry)
                safe_json_dump(existing, record_path, indent=2)
                # Also post to the review channel for admins with approve/deny buttons
                try:
                    guild = interaction.client.get_guild(GUILD_ID)
                    if guild:
                        review_channel = discord.utils.get(guild.text_channels, name=REGISTRATION_REVIEW_CHANNEL_NAME)
                        if review_channel:
                            review_embed = discord.Embed(
                                title="📝 New Registration (Pending)",
                                description=f"A new registration was submitted by {interaction.user.mention}.",
                                color=discord.Color.gold(),
                                timestamp=datetime.now(timezone.utc)
                            )
                            review_embed.add_field(name="Discord User", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False)
                            review_embed.add_field(name="Full Name", value=saved_reg.get("Full Name", "N/A"), inline=True)
                            review_embed.add_field(name="Player Type", value=PLAYER_TYPE_DISPLAY.get(saved_reg.get("player_type", "varsity"), saved_reg.get("player_type", "varsity")), inline=True)
                            review_embed.add_field(name="PUID", value=saved_reg.get("PUID", "N/A"), inline=True)
                            review_embed.set_footer(text="PNW Esports | Registration Review")
                            view = VarsityApproveView(player_id=interaction.user.id)
                            # Send attachments first (without buttons)
                            for attachment in msg.attachments:
                                await review_channel.send(file=await attachment.to_file())
                            # Send embed with view only once
                            await review_channel.send(embed=review_embed, view=view)
                            
                            # Send dashboard notification
                            player_type_display = PLAYER_TYPE_DISPLAY.get(saved_reg.get("player_type", "varsity"), saved_reg.get("player_type", "varsity"))
                            add_varsity_notification(
                                title="New Registration",
                                message=f"{saved_reg.get('Full Name', 'Unknown')} submitted a {player_type_display} registration",
                                link="/varsity",
                                target_id=interaction.user.id,
                                target_name=f"{interaction.user.display_name} ({interaction.user.name})",
                                notif_type="registration"
                            )
                except Exception:
                    pass
            except Exception:
                # Don't block flow if saving fails
                pass

            # Send appropriate success message based on registration source
            if is_website_registration:
                await interaction.user.send("✅ Your registration has been submitted! The coaching staff will review your application and contact you soon.")
            else:
                await interaction.user.send("✅ Your registration has been submitted! Please wait for approval from the recruiter.")
            if self.parent_view:
                self.parent_view.varsity_completed.add(interaction.user.id)
            if self.parent_view and self.interaction_message:
                for item in self.parent_view.children:
                    item.disabled = True
                try:
                    await self.interaction_message.edit(view=self.parent_view)
                except Exception:
                    pass
        except asyncio.TimeoutError:
            await interaction.user.send("❌ You did not upload an image in time. Please try again.", ephemeral=True)


# ============ Team Assignment & Role Sync ============

async def sync_player_roles(guild: discord.Guild, member: discord.Member, team_data: dict, player_type: str):
    """
    Sync Discord roles based on team assignment.
    - Adds game-specific varsity/JV role
    - Adds general varsity/JV role
    Includes rate limit handling for smooth operation.
    Uses role settings from JSON file (managed by website dashboard).
    """
    import asyncio
    
    roles_to_add = []
    
    game_name = team_data.get("game", "")
    team_type = team_data.get("type", "varsity")  # varsity or jv
    
    # Load role settings from JSON file (same source as website)
    role_settings = load_team_role_settings()
    role_mapping = role_settings.get("mapping", {})
    general_roster_role_id = role_settings.get("varsity_role_id")  # This is now the general roster role for ALL players
    
    # Get game-specific role (case-insensitive lookup)
    game_roles = None
    for mapping_game, roles in role_mapping.items():
        if mapping_game.lower() == game_name.lower():
            game_roles = roles
            break
    
    if game_roles:
        role_id_str = game_roles.get(team_type)
        if role_id_str:
            try:
                role = guild.get_role(int(role_id_str))
                if role:
                    roles_to_add.append(role)
                    print(f"[ROLE SYNC] Will add game role: {role.name} for {game_name} ({team_type})")
                else:
                    print(f"[ROLE SYNC] Warning: Game role ID {role_id_str} not found in guild for {game_name} ({team_type})")
            except (ValueError, TypeError):
                print(f"[ROLE SYNC] Warning: Invalid role ID {role_id_str} for {game_name}")
    else:
        print(f"[ROLE SYNC] Warning: No role mapping found for game '{game_name}'")
    
    # ALL roster players get the general roster role (regardless of team type)
    if general_roster_role_id:
        try:
            roster_role = guild.get_role(int(general_roster_role_id))
            if roster_role:
                roles_to_add.append(roster_role)
                print(f"[ROLE SYNC] Will add general roster role: {roster_role.name}")
        except (ValueError, TypeError):
            pass
    
    # Apply roles with rate limit handling
    if roles_to_add:
        try:
            await member.add_roles(*roles_to_add, reason=f"Added to team: {team_data.get('name', 'Unknown')}")
            # Small delay to avoid rate limits when called in sequence
            await asyncio.sleep(1.0)
            return True, roles_to_add
        except discord.HTTPException as e:
            if e.status == 429:  # Rate limited
                retry_after = getattr(e, 'retry_after', 5)
                print(f"[ROLE SYNC] Rate limited, waiting {retry_after}s...")
                await asyncio.sleep(retry_after + 1)
                try:
                    await member.add_roles(*roles_to_add, reason=f"Added to team: {team_data.get('name', 'Unknown')} (retry)")
                    return True, roles_to_add
                except Exception:
                    return False, []
            return False, []
        except discord.Forbidden:
            return False, []
        except Exception as e:
            print(f"[ROLE SYNC] Error adding roles: {e}")
            return False, []
    else:
        print(f"[ROLE SYNC] No roles to add for {member.display_name} on team {team_data.get('name')}")
    
    return True, []


async def remove_player_team_roles(guild: discord.Guild, member: discord.Member, team_data: dict):
    """Remove team-specific roles when player is removed from team. 
    Uses role settings from JSON file (managed by website dashboard).
    Includes rate limit handling."""
    import asyncio
    
    roles_to_remove = []
    
    game_name = team_data.get("game", "")
    team_type = team_data.get("type", "varsity")
    
    # Load role settings from JSON file (same source as website)
    role_settings = load_team_role_settings()
    role_mapping = role_settings.get("mapping", {})
    
    # Case-insensitive lookup for game roles
    game_roles = None
    for mapping_game, roles in role_mapping.items():
        if mapping_game.lower() == game_name.lower():
            game_roles = roles
            break
    
    if game_roles:
        role_id_str = game_roles.get(team_type)
        if role_id_str:
            try:
                role = guild.get_role(int(role_id_str))
                if role and role in member.roles:
                    roles_to_remove.append(role)
            except (ValueError, TypeError):
                pass
    
    if roles_to_remove:
        try:
            await member.remove_roles(*roles_to_remove, reason=f"Removed from team: {team_data.get('name', 'Unknown')}")
            # Small delay to avoid rate limits
            await asyncio.sleep(1.0)
        except discord.HTTPException as e:
            if e.status == 429:  # Rate limited
                retry_after = getattr(e, 'retry_after', 5)
                print(f"[ROLE SYNC] Rate limited, waiting {retry_after}s...")
                await asyncio.sleep(retry_after + 1)
                try:
                    await member.remove_roles(*roles_to_remove, reason=f"Removed from team: {team_data.get('name', 'Unknown')} (retry)")
                except Exception:
                    pass
        except Exception:
            pass


class TeamAssignmentView(discord.ui.View):
    """View for assigning a player to a team after approval"""
    def __init__(self, player_id: int, player_name: str, player_type: str = "varsity", game_title: str = ""):
        super().__init__(timeout=300)
        self.player_id = player_id
        self.player_name = player_name
        self.player_type = player_type
        self.game_title = game_title
        
        # Load teams and create select options
        teams_data = load_teams()
        teams = teams_data.get("teams", [])
        
        # Filter teams by game if specified, otherwise show all
        if game_title:
            matching_teams = [t for t in teams if t.get("game", "").lower() == game_title.lower()]
            if not matching_teams:
                matching_teams = teams  # Fall back to all teams
        else:
            matching_teams = teams
        
        if matching_teams:
            options = [
                discord.SelectOption(
                    label=t.get("name", "Unknown Team")[:100],
                    value=t.get("id"),
                    description=f"{t.get('game', 'N/A')} - {t.get('type', 'varsity').title()}"[:100],
                    emoji="🎮"
                )
                for t in matching_teams[:25]  # Discord limit
            ]
            
            # Add the select menu dynamically
            select = discord.ui.Select(
                placeholder="Select a team to assign...",
                options=options,
                custom_id="team_assignment_select"
            )
            select.callback = self.select_callback
            self.add_item(select)
    
    async def select_callback(self, interaction: discord.Interaction):
        team_id = interaction.data.get("values", [None])[0]
        if not team_id:
            await interaction.response.send_message("❌ No team selected.", ephemeral=True)
            return
        
        # Load team data
        teams_data = load_teams()
        teams = teams_data.get("teams", [])
        team = next((t for t in teams if t.get("id") == team_id), None)
        
        if not team:
            await interaction.response.send_message("❌ Team not found.", ephemeral=True)
            return
        
        # Add player to roster
        rosters = load_rosters()
        players = rosters.get("players", [])
        
        # Check if player already exists
        existing = next((p for p in players if str(p.get("discord_id")) == str(self.player_id)), None)
        
        if existing:
            existing["team_id"] = team_id
            existing["player_type"] = self.player_type
            existing["updated_at"] = datetime.now(timezone.utc).isoformat()
        else:
            players.append({
                "discord_id": str(self.player_id),
                "name": self.player_name,
                "team_id": team_id,
                "player_type": self.player_type,
                "game": self.game_title,
                "is_captain": False,
                "added_at": datetime.now(timezone.utc).isoformat()
            })
            rosters["players"] = players
        
        save_rosters(rosters)
        
        # Sync Discord roles
        guild = interaction.client.get_guild(GUILD_ID)
        role_sync_message = ""
        
        if guild:
            member = guild.get_member(self.player_id)
            if member:
                success, added_roles = await sync_player_roles(guild, member, team, self.player_type)
                if success and added_roles:
                    role_names = ", ".join([r.name for r in added_roles])
                    role_sync_message = f"\n✅ **Roles synced:** {role_names}"
                elif not success:
                    role_sync_message = "\n⚠️ Could not sync roles (missing permissions)"
        
        # Disable the select after use
        for item in self.children:
            item.disabled = True
        
        await interaction.response.edit_message(
            content=f"✅ **{self.player_name}** has been added to **{team.get('name')}**!{role_sync_message}",
            view=self
        )
        
        # Notify the player
        try:
            user = interaction.client.get_user(self.player_id)
            if user:
                embed = discord.Embed(
                    title="🎮 Team Assignment",
                    description=f"You have been assigned to **{team.get('name')}**!",
                    color=discord.Color.gold()
                )
                embed.add_field(name="Game", value=team.get("game", "N/A"), inline=True)
                embed.add_field(name="Team Type", value=team.get("type", "varsity").title(), inline=True)
                embed.set_footer(text="PNW Esports | Team Assignment")
                await user.send(embed=embed)
        except:
            pass
    
    @discord.ui.button(label="Skip Team Assignment", style=discord.ButtonStyle.secondary, row=1)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="Team assignment skipped. You can assign teams later from the dashboard.",
            view=self
        )


class TeamManagementView(discord.ui.View):
    """View for managing teams - creating and assigning roles"""
    def __init__(self):
        super().__init__(timeout=300)
    
    @discord.ui.button(label="Create New Team", style=discord.ButtonStyle.success, emoji="➕")
    async def create_team(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreateTeamModal())
    
    @discord.ui.button(label="View Teams", style=discord.ButtonStyle.primary, emoji="📋")
    async def view_teams(self, interaction: discord.Interaction, button: discord.ui.Button):
        teams_data = load_teams()
        teams = teams_data.get("teams", [])
        
        if not teams:
            await interaction.response.send_message("No teams created yet.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="📋 Team Roster",
            color=discord.Color.gold()
        )
        
        for team in teams[:25]:
            rosters = load_rosters()
            player_count = len([p for p in rosters.get("players", []) if p.get("team_id") == team.get("id")])
            embed.add_field(
                name=f"{team.get('name')} ({team.get('type', 'varsity').title()})",
                value=f"🎮 {team.get('game', 'N/A')}\n👥 {player_count} players",
                inline=True
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


class CreateTeamModal(discord.ui.Modal, title="Create New Team"):
    team_name = discord.ui.TextInput(
        label="Team Name",
        placeholder="e.g. Overwatch Varsity A",
        required=True
    )
    game = discord.ui.TextInput(
        label="Game",
        placeholder="e.g. Overwatch 2, Valorant, League of Legends",
        required=True
    )
    team_type = discord.ui.TextInput(
        label="Team Type",
        placeholder="varsity or jv",
        default="varsity",
        required=True
    )
    description = discord.ui.TextInput(
        label="Description (Optional)",
        placeholder="Brief description of the team",
        style=discord.TextStyle.paragraph,
        required=False
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        teams_data = load_teams()
        teams = teams_data.get("teams", [])
        
        team_id = f"team_{len(teams) + 1}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        teams.append({
            "id": team_id,
            "name": self.team_name.value,
            "game": self.game.value,
            "type": self.team_type.value.lower(),
            "description": self.description.value,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": {"id": interaction.user.id, "name": str(interaction.user)}
        })
        
        teams_data["teams"] = teams
        save_json_file(TEAMS_FILE, teams_data)
        
        await interaction.response.send_message(
            f"✅ Team **{self.team_name.value}** created!\n"
            f"🎮 Game: {self.game.value}\n"
            f"📊 Type: {self.team_type.value.title()}",
            ephemeral=True
        )


# Modern approve/deny buttons for admin
class VarsityApproveView(discord.ui.View):
    def __init__(self, player_id=None):
        # Set timeout to None for persistent view (never expires)
        super().__init__(timeout=None)
        self.player_id = player_id
        self.action_taken = False

    async def disable_all(self, interaction, status_text, color, footer_text):
        for item in self.children:
            item.disabled = True
        embed = interaction.message.embeds[0].copy()
        embed.color = color
        embed.set_footer(text=footer_text)
        await interaction.message.edit(embed=embed, view=self)

    @discord.ui.button(label="Approve Information", style=discord.ButtonStyle.success, custom_id="varsity_approve_persistent")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user is admin (works in DM context by checking guild membership)
        try:
            guild = interaction.client.get_guild(GUILD_ID)
            if guild:
                member = guild.get_member(interaction.user.id)
                if not member or not member.guild_permissions.administrator:
                    await interaction.response.send_message("❌ Only administrators can approve registrations.", ephemeral=True)
                    return
            else:
                await interaction.response.send_message("❌ Could not verify permissions.", ephemeral=True)
                return
        except Exception:
            await interaction.response.send_message("❌ Permission check failed.", ephemeral=True)
            return
            
        if self.action_taken:
            await interaction.response.send_message("You have already made a decision.", ephemeral=True)
            return

        # Get player_id from view or extract from embed if not set
        player_id = self.player_id
        if not player_id:
            # Try to extract from embed fields (Discord User field contains user ID)
            try:
                if interaction.message and interaction.message.embeds:
                    embed = interaction.message.embeds[0]
                    for field in embed.fields:
                        if field.name == "Discord User":
                            # Extract ID from "(<user_id>)" pattern
                            import re
                            match = re.search(r'\((\d+)\)', field.value)
                            if match:
                                player_id = int(match.group(1))
                                break
            except Exception:
                pass
        
        if not player_id:
            await interaction.response.send_message("❌ Could not determine player ID.", ephemeral=True)
            return

        # Check if already approved/denied from file (handles bot restarts)
        try:
            record_path = os.path.join(VARSITY_REG_DIR, f"{player_id}_varsity.json")
            if os.path.exists(record_path):
                with open(record_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                for entry in reversed(existing):
                    if str(entry.get("type", "")).lower().startswith("varsityregistration"):
                        status = entry.get("status", "").lower()
                        if status in ("approved", "denied"):
                            await interaction.response.send_message(f"❌ This registration has already been {status}.", ephemeral=True)
                            # Disable buttons since it's already processed
                            await self.disable_all(
                                interaction,
                                status_text=status.title(),
                                color=discord.Color.green() if status == "approved" else discord.Color.red(),
                                footer_text=f"PNW Esports | Registration | {status.title()}"
                            )
                            return
                        break
        except Exception:
            pass

        # Defer immediately to avoid timeout during long operations
        await interaction.response.defer(ephemeral=True)

        # Execute approval in a guarded block so errors don't cause the interaction to fail
        try:
            self.action_taken = True
            user = interaction.client.get_user(player_id)
            if not user:
                await interaction.followup.send("Player not found.", ephemeral=True)
                return

            # Notify the user
            try:
                embed = discord.Embed(
                    title="✅ Registration Approved",
                    description=(
                        "Congratulations! Your registration has been **approved** by the Recruiter.\n\n"
                        "Welcome to the PNW Esports Program! The Recruiter will be in contact with you shortly to discuss next steps."
                    ),
                    color=discord.Color.green()
                )
                embed.set_footer(text="PNW Esports | Registration")
                embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
                await user.send(embed=embed)
                await interaction.followup.send("Player has been notified of approval.", ephemeral=True)
            except discord.Forbidden:
                await interaction.followup.send("Could not DM the player.", ephemeral=True)

            # Update varsity registration file: mark latest VarsityRegistration as Approved
            player_data = None
            player_type = "varsity"
            try:
                record_path = os.path.join(VARSITY_REG_DIR, f"{player_id}_varsity.json")
                if os.path.exists(record_path):
                    with open(record_path, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                    # find last VarsityRegistration entry
                    for i in range(len(existing) - 1, -1, -1):
                        if str(existing[i].get("type", "")).lower().startswith("varsityregistration"):
                            existing[i]["status"] = "Approved"
                            existing[i]["moderated_by"] = {"id": interaction.user.id, "name": str(interaction.user)}
                            existing[i]["moderated_at"] = datetime.now(timezone.utc).isoformat()
                            player_data = existing[i].get("data", {})
                            player_type = player_data.get("player_type", "varsity")
                            break
                    safe_json_dump(existing, record_path, indent=2)
                    
                    # Add player to rosters.json so they appear in dashboard
                    if player_data:
                        rosters = load_rosters()
                        players = rosters.get("players", [])
                        
                        # Check if player already exists
                        existing_player = next((p for p in players if str(p.get("discord_id")) == str(player_id)), None)
                        if not existing_player:
                            # Get Discord user info
                            discord_username = None
                            discord_avatar = None
                            try:
                                user_obj = interaction.client.get_user(player_id)
                                if user_obj:
                                    discord_username = str(user_obj)
                                    discord_avatar = user_obj.display_avatar.url if user_obj.display_avatar else None
                            except:
                                pass
                            
                            players.append({
                                "discord_id": str(player_id),
                                "full_name": player_data.get("Full Name"),
                                "player_type": player_type,
                                "game": player_data.get("Primary Game Title"),
                                "ign": player_data.get("IGN"),
                                "rank": player_data.get("Current Rank in Game"),
                                "tracker": player_data.get("Tracker Link"),
                                "purdue_email": player_data.get("Purdue Email"),
                                "personal_email": player_data.get("Personal Email"),
                                "discord_username": discord_username,
                                "avatar": discord_avatar,
                                "is_captain": False,
                                "team_id": None,
                                "role": player_data.get("Primary Role"),
                                "secondary_role": None,
                                "status": "active",
                                "stats": {
                                    "matches_played": 0,
                                    "wins": 0,
                                    "losses": 0,
                                    "draws": 0,
                                    "mvp_count": 0
                                },
                                "created_at": datetime.now(timezone.utc).isoformat(),
                                "updated_at": datetime.now(timezone.utc).isoformat()
                            })
                            rosters["players"] = players
                            save_rosters(rosters)
                        else:
                            # Update existing player data
                            existing_player["full_name"] = player_data.get("Full Name", existing_player.get("full_name"))
                            existing_player["game"] = player_data.get("Primary Game Title", existing_player.get("game"))
                            existing_player["ign"] = player_data.get("IGN", existing_player.get("ign"))
                            existing_player["rank"] = player_data.get("Current Rank in Game", existing_player.get("rank"))
                            existing_player["role"] = player_data.get("Primary Role", existing_player.get("role"))
                            existing_player["player_type"] = player_type  # Ensure player_type is updated
                            existing_player["updated_at"] = datetime.now(timezone.utc).isoformat()
                            save_rosters(rosters)
                        
                        # Assign Esports Team role to the player
                        try:
                            role_settings = load_json_file(TEAM_ROLE_SETTINGS_FILE, {})
                            esports_role_id = role_settings.get("varsity_role_id")
                            
                            if esports_role_id:
                                guild = interaction.client.get_guild(GUILD_ID)
                                if guild:
                                    member = guild.get_member(player_id)
                                    if member:
                                        esports_role = guild.get_role(int(esports_role_id))
                                        if esports_role and esports_role not in member.roles:
                                            await member.add_roles(esports_role, reason="Varsity registration approved")
                                            print(f"[VARSITY] Added Esports Team role to {member}")
                        except Exception as role_exc:
                            print(f"[VARSITY] Error adding role: {role_exc}")
            except Exception as exc:
                # Try to log to the configured log channel but don't raise
                try:
                    guild = interaction.guild
                    log_channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME) if guild else None
                    if log_channel:
                        err_embed = discord.Embed(title="Error updating record on Approve", description=str(exc), color=discord.Color.red())
                        await log_channel.send(embed=err_embed)
                except Exception:
                    pass

            await self.disable_all(
                interaction,
                status_text="Approved",
                color=discord.Color.green(),
                footer_text="PNW Esports | Registration | Approved"
            )
            
            # After approval, prompt to add player to a team
            try:
                teams_data = load_teams()
                teams = teams_data.get("teams", [])
                
                if teams:
                    # Send team selection view
                    team_view = TeamAssignmentView(
                        player_id=player_id,
                        player_name=player_data.get("Full Name", "Unknown") if player_data else "Unknown",
                        player_type=player_type,
                        game_title=player_data.get("Primary Game Title", "") if player_data else ""
                    )
                    await interaction.followup.send(
                        f"✅ **Player approved!** Would you like to assign them to a team?\n"
                        f"Player: **{player_data.get('Full Name', 'Unknown') if player_data else 'Unknown'}**\n"
                        f"Game: **{player_data.get('Primary Game Title', 'N/A') if player_data else 'N/A'}**",
                        view=team_view,
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "✅ Player approved! No teams exist yet. Create teams in the dashboard to assign players.",
                        ephemeral=True
                    )
            except Exception:
                pass
        except Exception as exc:
            # If anything unexpected happens, respond and log
            try:
                await interaction.followup.send("❌ An error occurred processing the approval. Check logs.", ephemeral=True)
            except Exception:
                pass
            try:
                guild = interaction.guild
                log_channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME) if guild else None
                if log_channel:
                    err_embed = discord.Embed(title="Approve Handler Exception", description=str(exc), color=discord.Color.red())
                    await log_channel.send(embed=err_embed)
            except Exception:
                pass

    @discord.ui.button(label="Deny Information", style=discord.ButtonStyle.danger, custom_id="varsity_deny_persistent")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user is admin (works in DM context by checking guild membership)
        try:
            guild = interaction.client.get_guild(GUILD_ID)
            if guild:
                member = guild.get_member(interaction.user.id)
                if not member or not member.guild_permissions.administrator:
                    await interaction.response.send_message("❌ Only administrators can deny registrations.", ephemeral=True)
                    return
            else:
                await interaction.response.send_message("❌ Could not verify permissions.", ephemeral=True)
                return
        except Exception:
            await interaction.response.send_message("❌ Permission check failed.", ephemeral=True)
            return
            
        if self.action_taken:
            await interaction.response.send_message("You have already made a decision.", ephemeral=True)
            return
        
        # Get player_id from view or extract from embed if not set
        player_id = self.player_id
        if not player_id:
            # Try to extract from embed fields (Discord User field contains user ID)
            try:
                if interaction.message and interaction.message.embeds:
                    embed = interaction.message.embeds[0]
                    for field in embed.fields:
                        if field.name == "Discord User":
                            # Extract ID from "(<user_id>)" pattern
                            import re
                            match = re.search(r'\((\d+)\)', field.value)
                            if match:
                                player_id = int(match.group(1))
                                break
            except Exception:
                pass
        
        if not player_id:
            await interaction.response.send_message("❌ Could not determine player ID.", ephemeral=True)
            return

        # Check if already approved/denied from file (handles bot restarts)
        try:
            record_path = os.path.join(VARSITY_REG_DIR, f"{player_id}_varsity.json")
            if os.path.exists(record_path):
                with open(record_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                for entry in reversed(existing):
                    if str(entry.get("type", "")).lower().startswith("varsityregistration"):
                        status = entry.get("status", "").lower()
                        if status in ("approved", "denied"):
                            await interaction.response.send_message(f"❌ This registration has already been {status}.", ephemeral=True)
                            # Disable buttons since it's already processed
                            for item in self.children:
                                item.disabled = True
                            msg_embed = interaction.message.embeds[0].copy()
                            msg_embed.color = discord.Color.green() if status == "approved" else discord.Color.red()
                            msg_embed.set_footer(text=f"PNW Esports | Registration | {status.title()}")
                            await interaction.message.edit(embed=msg_embed, view=self)
                            return
                        break
        except Exception:
            pass
            
        try:
            self.action_taken = True
            await interaction.response.send_modal(VarsityDenyReasonModal(player_id=player_id, parent_view=self))
        except Exception as exc:
            try:
                await interaction.response.send_message("❌ An error occurred opening the deny modal. Check logs.", ephemeral=True)
            except Exception:
                pass
            try:
                guild = interaction.guild
                log_channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME) if guild else None
                if log_channel:
                    err_embed = discord.Embed(title="Deny Handler Exception", description=str(exc), color=discord.Color.red())
                    await log_channel.send(embed=err_embed)
            except Exception:
                pass

class VarsityDenyReasonModal(discord.ui.Modal, title="Deny Registration"):
    reason = discord.ui.TextInput(
        label="Reason for Denial",
        placeholder="Please provide a reason for denying this registration.",
        style=discord.TextStyle.paragraph,
        required=True
    )

    def __init__(self, player_id, parent_view=None):
        super().__init__()
        self.player_id = player_id
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        user = interaction.client.get_user(self.player_id)
        if user:
            embed = discord.Embed(
                title="❌ Registration Denied",
                description="Your registration was **Denied**.",
                color=discord.Color.red()
            )
            embed.add_field(name="**Reason** (Message from Recruiter)", value=self.reason.value, inline=False)
            embed.set_footer(text="PNW Esports | Registration")
            embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
            try:
                await user.send(embed=embed)
                await interaction.response.send_message("Player has been notified of denial and reason.", ephemeral=True)
                # Update user_records: mark latest VarsityRegistration as Denied and add reason
                try:
                    record_path = os.path.join(VARSITY_REG_DIR, f"{self.player_id}_varsity.json")
                    if os.path.exists(record_path):
                        with open(record_path, "r", encoding="utf-8") as f:
                            existing = json.load(f)
                        for i in range(len(existing) - 1, -1, -1):
                            if str(existing[i].get("type", "")).lower().startswith("varsityregistration"):
                                existing[i]["status"] = "Denied"
                                existing[i]["moderated_by"] = {"id": interaction.user.id, "name": str(interaction.user)}
                                existing[i]["moderation_note"] = self.reason.value
                                existing[i]["moderated_at"] = datetime.now(timezone.utc).isoformat()
                                break
                        safe_json_dump(existing, record_path, indent=2)
                except Exception:
                    pass
                # Edit the admin's message to show Denied and disable buttons
                if self.parent_view and hasattr(interaction, "message") and interaction.message:
                    await self.parent_view.disable_all(
                        interaction,
                        status_text="Denied",
                        color=discord.Color.red(),
                        footer_text="PNW Esports | Registration | Denied"
                    )
                elif self.parent_view:
                    # fallback: try to edit the original message if possible
                    msg = None
                    for channel in interaction.client.private_channels:
                        if hasattr(channel, "history"):
                            async for m in channel.history(limit=20):
                                if m.author == interaction.client.user and m.embeds and m.embeds[0].title == "📝 Registration Received":
                                    msg = m
                                    break
                        if msg:
                            break
                    if msg:
                        await self.parent_view.disable_all(
                            interaction,
                            status_text="Denied",
                            color=discord.Color.red(),
                            footer_text="PNW Esports | Registration | Denied"
                        )
            except discord.Forbidden:
                await interaction.response.send_message("Could not DM the player.", ephemeral=True)
        else:
            await interaction.response.send_message("Player not found.", ephemeral=True)

    @discord.ui.button(label="Upload Schedule", style=discord.ButtonStyle.secondary)
    async def upload_schedule(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Please upload an image of your schedule.", ephemeral=True)

        def check(m):
            return m.author.id == interaction.user.id and m.attachments and m.channel == interaction.channel

        try:
            msg = await interaction.client.wait_for('message', check=check, timeout=120)
            # Forward the image to the admin who initiated the registration
            admin_user = getattr(self, "admin_user", None)
            if not admin_user:
                # Try to get from registration data if available
                reg_data = getattr(interaction.client, "varsity_registrations", {}).get(interaction.user.id, {})
                admin_user = reg_data.get("admin_user", None)
            if admin_user:
                for attachment in msg.attachments:
                    await admin_user.send(
                        f"Schedule image from {interaction.user.mention} ({interaction.user.id}):",
                        file=await attachment.to_file()
                    )
            await interaction.followup.send("✅ Your schedule has been sent to the recruiter.", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("❌ You did not upload an image in time. Please try again.", ephemeral=True)

class VarsityCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="register-player", description="Register a new Esports player (Varsity, JV, Substitute Varsity, Substitute JV).")
    @app_commands.describe(
        user="The player to register",
        player_type="Type of registration: Varsity, JV, Substitute Varsity, or Substitute JV"
    )
    @app_commands.choices(
        player_type=[
            app_commands.Choice(name="Varsity", value="varsity"),
            app_commands.Choice(name="JV", value="jv"),
            app_commands.Choice(name="Substitute Varsity", value="sub_varsity"),
            app_commands.Choice(name="Substitute JV", value="sub_jv"),
        ]
    )
    async def register_player(self, interaction: discord.Interaction, user: discord.Member, player_type: app_commands.Choice[str]):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You must be an administrator to use this command.", ephemeral=True)
            return

        view = VarsityRegistrationView(requested_by=interaction.user, player_type=player_type.value)
        team_name = player_type.name
        embed = discord.Embed(
            title="Welcome to PNW Esports",
            description=(
                f"**You have been selected to join the {team_name} team for PNW Esports!**\n\n"
                "PNW Esports is home to the elite and victorious. Please complete your registration below to finalize your onboarding.\n\n"
                "We are excited to have you as part of our competitive family. Good luck and Roar Pride!"
            ),
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        embed.set_footer(text="PNW Esports | Registration")

        try:
            await user.send(embed=embed, view=view)
            await interaction.response.send_message(
                f"📩 Sent {team_name} registration to {user.mention}.",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(f"❌ Could not DM {user.mention}.", ephemeral=True)

    @app_commands.command(name="create-team", description="Create a new Esports team.")
    @app_commands.describe(
        name="Team name (e.g. Overwatch Varsity A)",
        game="Game title (e.g. Overwatch 2, Valorant)",
        team_type="Team type: varsity or jv"
    )
    @app_commands.choices(
        team_type=[
            app_commands.Choice(name="Varsity", value="varsity"),
            app_commands.Choice(name="JV", value="jv"),
        ]
    )
    async def create_team(self, interaction: discord.Interaction, name: str, game: str, team_type: app_commands.Choice[str]):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You must be an administrator to use this command.", ephemeral=True)
            return
        
        teams_data = load_teams()
        teams = teams_data.get("teams", [])
        
        # Check for duplicate name
        if any(t.get("name", "").lower() == name.lower() for t in teams):
            await interaction.response.send_message(f"❌ A team named **{name}** already exists.", ephemeral=True)
            return
        
        team_id = f"team_{len(teams) + 1}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        teams.append({
            "id": team_id,
            "name": name,
            "game": game,
            "type": team_type.value,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": {"id": interaction.user.id, "name": str(interaction.user)}
        })
        
        teams_data["teams"] = teams
        save_json_file(TEAMS_FILE, teams_data)
        
        embed = discord.Embed(
            title="✅ Team Created",
            color=discord.Color.green()
        )
        embed.add_field(name="Team Name", value=name, inline=True)
        embed.add_field(name="Game", value=game, inline=True)
        embed.add_field(name="Type", value=team_type.name, inline=True)
        embed.set_footer(text=f"Team ID: {team_id}")
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="add-to-team", description="Add a player to a team and sync their Discord roles.")
    @app_commands.describe(
        user="The player to add to a team",
        player_type="Player type: Varsity, JV, etc."
    )
    @app_commands.choices(
        player_type=[
            app_commands.Choice(name="Varsity", value="varsity"),
            app_commands.Choice(name="JV", value="jv"),
            app_commands.Choice(name="Substitute Varsity", value="sub_varsity"),
            app_commands.Choice(name="Substitute JV", value="sub_jv"),
        ]
    )
    async def add_to_team(self, interaction: discord.Interaction, user: discord.Member, player_type: app_commands.Choice[str]):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You must be an administrator to use this command.", ephemeral=True)
            return
        
        teams_data = load_teams()
        teams = teams_data.get("teams", [])
        
        if not teams:
            await interaction.response.send_message("❌ No teams exist. Create a team first with `/create-team`.", ephemeral=True)
            return
        
        # Send team selection view
        team_view = TeamAssignmentView(
            player_id=user.id,
            player_name=user.display_name,
            player_type=player_type.value
        )
        
        await interaction.response.send_message(
            f"Select a team to add **{user.display_name}** to:",
            view=team_view,
            ephemeral=True
        )

    @app_commands.command(name="teams", description="View all Esports teams and their rosters.")
    async def view_teams(self, interaction: discord.Interaction):
        teams_data = load_teams()
        teams = teams_data.get("teams", [])
        rosters = load_rosters()
        players = rosters.get("players", [])
        
        if not teams:
            await interaction.response.send_message("No teams created yet. Use `/create-team` to create one.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🎮 PNW Esports Teams",
            color=discord.Color.gold()
        )
        
        for team in teams[:25]:
            team_players = [p for p in players if p.get("team_id") == team.get("id")]
            player_list = []
            
            for p in team_players[:10]:
                captain_badge = "👑 " if p.get("is_captain") else ""
                player_type_badge = f"({PLAYER_TYPE_DISPLAY.get(p.get('player_type', 'varsity'), p.get('player_type', 'varsity'))})"
                player_list.append(f"{captain_badge}<@{p.get('discord_id')}> {player_type_badge}")
            
            if len(team_players) > 10:
                player_list.append(f"*...and {len(team_players) - 10} more*")
            
            embed.add_field(
                name=f"{team.get('name')} ({team.get('type', 'varsity').title()})",
                value=f"🎮 **{team.get('game', 'N/A')}**\n" + 
                      ("\n".join(player_list) if player_list else "*No players yet*"),
                inline=False
            )
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="remove-from-team", description="Remove a player from their team.")
    @app_commands.describe(user="The player to remove from their team")
    async def remove_from_team(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You must be an administrator to use this command.", ephemeral=True)
            return
        
        rosters = load_rosters()
        players = rosters.get("players", [])
        
        player = next((p for p in players if str(p.get("discord_id")) == str(user.id)), None)
        
        if not player or not player.get("team_id"):
            await interaction.response.send_message(f"❌ **{user.display_name}** is not on any team.", ephemeral=True)
            return
        
        # Get team info for role removal
        teams_data = load_teams()
        team = next((t for t in teams_data.get("teams", []) if t.get("id") == player.get("team_id")), None)
        
        old_team_name = team.get("name", "Unknown") if team else "Unknown"
        
        # Remove team assignment
        player["team_id"] = None
        player["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_rosters(rosters)
        
        # Remove team roles
        if team:
            await remove_player_team_roles(interaction.guild, user, team)
        
        await interaction.response.send_message(
            f"✅ **{user.display_name}** has been removed from **{old_team_name}**.",
            ephemeral=True
        )

    @app_commands.command(name="set-captain", description="Set or remove a player as team captain.")
    @app_commands.describe(
        user="The player to set as captain",
        is_captain="Whether to make them captain (True) or remove captain status (False)"
    )
    async def set_captain(self, interaction: discord.Interaction, user: discord.Member, is_captain: bool = True):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You must be an administrator to use this command.", ephemeral=True)
            return
        
        rosters = load_rosters()
        players = rosters.get("players", [])
        
        player = next((p for p in players if str(p.get("discord_id")) == str(user.id)), None)
        
        if not player:
            await interaction.response.send_message(f"❌ **{user.display_name}** is not on any roster.", ephemeral=True)
            return
        
        if not player.get("team_id"):
            await interaction.response.send_message(f"❌ **{user.display_name}** must be on a team first.", ephemeral=True)
            return
        
        player["is_captain"] = is_captain
        player["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_rosters(rosters)
        
        # Get team name
        teams_data = load_teams()
        team = next((t for t in teams_data.get("teams", []) if t.get("id") == player.get("team_id")), None)
        team_name = team.get("name", "their team") if team else "their team"
        
        if is_captain:
            await interaction.response.send_message(
                f"👑 **{user.display_name}** is now captain of **{team_name}**!"
            )
        else:
            await interaction.response.send_message(
                f"✅ **{user.display_name}** is no longer captain of **{team_name}**.",
                ephemeral=True
            )

    @app_commands.command(name="sync-team-roles", description="Sync Discord roles for all players on a team.")
    async def sync_team_roles(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You must be an administrator to use this command.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        teams_data = load_teams()
        teams = teams_data.get("teams", [])
        rosters = load_rosters()
        players = rosters.get("players", [])
        
        synced = 0
        failed = 0
        
        for player in players:
            if not player.get("team_id"):
                continue
            
            team = next((t for t in teams if t.get("id") == player.get("team_id")), None)
            if not team:
                continue
            
            member = interaction.guild.get_member(int(player.get("discord_id")))
            if not member:
                failed += 1
                continue
            
            success, _ = await sync_player_roles(
                interaction.guild, 
                member, 
                team, 
                player.get("player_type", "varsity")
            )
            
            if success:
                synced += 1
            else:
                failed += 1
        
        await interaction.followup.send(
            f"✅ Role sync complete!\n"
            f"**Synced:** {synced} players\n"
            f"**Failed:** {failed} players",
            ephemeral=True
        )

    @app_commands.command(name="set-player-role", description="Set a player's role/position on the team.")
    @app_commands.describe(
        user="The player to set role for",
        role="Primary role (e.g., IGL, Support, Captain, Flex)",
        secondary_role="Secondary role (optional)"
    )
    @app_commands.choices(
        role=[
            app_commands.Choice(name="IGL (In-Game Leader)", value="igl"),
            app_commands.Choice(name="Captain", value="captain"),
            app_commands.Choice(name="Support", value="support"),
            app_commands.Choice(name="DPS/Carry", value="dps"),
            app_commands.Choice(name="Tank/Front Line", value="tank"),
            app_commands.Choice(name="Flex", value="flex"),
            app_commands.Choice(name="Entry Fragger", value="entry"),
            app_commands.Choice(name="AWPer/Sniper", value="awper"),
            app_commands.Choice(name="Lurker", value="lurker"),
            app_commands.Choice(name="Analyst", value="analyst"),
            app_commands.Choice(name="Coach", value="coach"),
        ],
        secondary_role=[
            app_commands.Choice(name="IGL (In-Game Leader)", value="igl"),
            app_commands.Choice(name="Captain", value="captain"),
            app_commands.Choice(name="Support", value="support"),
            app_commands.Choice(name="DPS/Carry", value="dps"),
            app_commands.Choice(name="Tank/Front Line", value="tank"),
            app_commands.Choice(name="Flex", value="flex"),
            app_commands.Choice(name="Entry Fragger", value="entry"),
            app_commands.Choice(name="AWPer/Sniper", value="awper"),
            app_commands.Choice(name="Lurker", value="lurker"),
            app_commands.Choice(name="Analyst", value="analyst"),
        ]
    )
    async def set_player_role(
        self, 
        interaction: discord.Interaction, 
        user: discord.Member, 
        role: app_commands.Choice[str],
        secondary_role: app_commands.Choice[str] = None
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You must be an administrator to use this command.", ephemeral=True)
            return
        
        rosters = load_rosters()
        players = rosters.get("players", [])
        
        player = next((p for p in players if str(p.get("discord_id")) == str(user.id)), None)
        
        if not player:
            await interaction.response.send_message(f"❌ **{user.display_name}** is not on any roster.", ephemeral=True)
            return
        
        player["role"] = role.value
        player["secondary_role"] = secondary_role.value if secondary_role else None
        player["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_rosters(rosters)
        
        role_display = f"**{role.name}**"
        if secondary_role:
            role_display += f" / {secondary_role.name}"
        
        await interaction.response.send_message(
            f"✅ Set **{user.display_name}**'s role to {role_display}",
            ephemeral=True
        )

    @app_commands.command(name="team_announce", description="Send a team announcement to all players via DM.")
    @app_commands.describe(
        title="Announcement title",
        message="Announcement message",
        team="Specific team to announce to (leave empty for all teams)",
        priority="Announcement priority level"
    )
    @app_commands.choices(
        priority=[
            app_commands.Choice(name="Low", value="low"),
            app_commands.Choice(name="Normal", value="normal"),
            app_commands.Choice(name="High", value="high"),
            app_commands.Choice(name="Urgent", value="urgent"),
        ]
    )
    async def team_announce(
        self,
        interaction: discord.Interaction,
        title: str,
        message: str,
        team: str = None,
        priority: app_commands.Choice[str] = None
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You must be an administrator to use this command.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        rosters = load_rosters()
        players = rosters.get("players", [])
        teams_data = load_teams()
        
        # Filter players by team if specified
        target_team = None
        if team:
            target_team = next((t for t in teams_data.get("teams", []) if t.get("name", "").lower() == team.lower()), None)
            if target_team:
                players = [p for p in players if p.get("team_id") == target_team.get("id")]
            else:
                await interaction.followup.send(f"❌ Team **{team}** not found.", ephemeral=True)
                return
        
        if not players:
            await interaction.followup.send("❌ No players found to notify.", ephemeral=True)
            return
        
        # Determine embed color based on priority
        priority_value = priority.value if priority else "normal"
        priority_config = {
            "low": {"color": discord.Color.light_grey(), "emoji": "📋", "label": "Low Priority"},
            "normal": {"color": discord.Color.gold(), "emoji": "📢", "label": "Announcement"},
            "high": {"color": discord.Color.orange(), "emoji": "⚠️", "label": "Important"},
            "urgent": {"color": discord.Color.red(), "emoji": "🚨", "label": "URGENT"}
        }
        config = priority_config.get(priority_value, priority_config["normal"])
        
        # Create beautiful announcement embed
        embed = discord.Embed(
            title=f"{config['emoji']} {title}",
            description=f"━━━━━━━━━━━━━━━━━━━━━━\n\n{message}\n\n━━━━━━━━━━━━━━━━━━━━━━",
            color=config["color"],
            timestamp=datetime.now(timezone.utc)
        )
        
        # Set author with team info
        if target_team:
            team_game = target_team.get("game", "")
            if team_game:
                embed.set_author(
                    name=f"🎮 {target_team.get('name')} • {team_game}",
                    icon_url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png"
                )
            else:
                embed.set_author(
                    name=f"📣 Team: {target_team.get('name')}",
                    icon_url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png"
                )
        else:
            embed.set_author(
                name="📣 All Teams Announcement",
                icon_url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png"
            )
        
        # Add priority field for high/urgent
        if priority_value in ["high", "urgent"]:
            embed.add_field(
                name="📌 Priority Level",
                value=f"**{config['label'].upper()}**",
                inline=True
            )
        
        # Add team field
        embed.add_field(
            name="🏆 Team",
            value=target_team.get("name") if target_team else "All Teams",
            inline=True
        )
        
        # Add recipients count field
        embed.add_field(
            name="📨 Recipients",
            value=f"{len(players)} player(s)",
            inline=True
        )
        
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png")
        embed.set_footer(
            text=f"Announced by {interaction.user.display_name} | PNW Esports",
            icon_url="https://cdn.discordapp.com/attachments/1053299583830212639/1374397271583621240/pnw-athletics-head-fc.png"
        )
        
        # Send DMs to all players
        sent_count = 0
        failed_count = 0
        
        for player in players:
            try:
                user = self.bot.get_user(int(player.get("discord_id")))
                if user:
                    await user.send(embed=embed)
                    sent_count += 1
            except discord.Forbidden:
                failed_count += 1
            except Exception:
                failed_count += 1
        
        # Save announcement to file
        announcements_file = os.path.join(DATA_DIR, "team_announcements.json")
        announcements = load_json_file(announcements_file, {"announcements": []})
        announcements["announcements"].append({
            "id": f"ann_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "title": title,
            "message": message,
            "team_id": target_team.get("id") if target_team else "all",
            "priority": priority_value,
            "created_by": str(interaction.user),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "sent_count": sent_count,
            "failed_count": failed_count
        })
        save_json_file(announcements_file, announcements)
        
        await interaction.followup.send(
            f"✅ Announcement sent!\n"
            f"**Successfully sent:** {sent_count}\n"
            f"**Failed:** {failed_count}",
            ephemeral=True
        )

    @app_commands.command(name="player-stats", description="View a player's match statistics.")
    @app_commands.describe(user="The player to view stats for")
    async def player_stats(self, interaction: discord.Interaction, user: discord.Member):
        rosters = load_rosters()
        player = next((p for p in rosters.get("players", []) if str(p.get("discord_id")) == str(user.id)), None)
        
        if not player:
            await interaction.response.send_message(f"❌ **{user.display_name}** is not on any roster.", ephemeral=True)
            return
        
        stats = player.get("stats", {})
        matches = stats.get("matches_played", 0)
        wins = stats.get("wins", 0)
        losses = stats.get("losses", 0)
        draws = stats.get("draws", 0)
        mvps = stats.get("mvp_count", 0)
        
        win_rate = (wins / matches * 100) if matches > 0 else 0
        
        embed = discord.Embed(
            title=f"📊 Stats for {player.get('full_name') or user.display_name}",
            color=discord.Color.gold()
        )
        
        if player.get("avatar"):
            embed.set_thumbnail(url=player.get("avatar"))
        elif user.display_avatar:
            embed.set_thumbnail(url=user.display_avatar.url)
        
        embed.add_field(name="🎮 Game", value=player.get("game", "N/A"), inline=True)
        embed.add_field(name="🏷️ IGN", value=player.get("ign", "N/A"), inline=True)
        embed.add_field(name="📈 Rank", value=player.get("rank", "N/A"), inline=True)
        
        embed.add_field(name="📊 Matches Played", value=str(matches), inline=True)
        embed.add_field(name="✅ Wins", value=str(wins), inline=True)
        embed.add_field(name="❌ Losses", value=str(losses), inline=True)
        
        embed.add_field(name="📈 Win Rate", value=f"{win_rate:.1f}%", inline=True)
        embed.add_field(name="🏆 MVP Count", value=str(mvps), inline=True)
        
        if player.get("role"):
            role_display = player.get("role", "").upper()
            if player.get("secondary_role"):
                role_display += f" / {player.get('secondary_role', '').upper()}"
            embed.add_field(name="🎯 Role", value=role_display, inline=True)
        
        # Get team info
        if player.get("team_id"):
            teams_data = load_teams()
            team = next((t for t in teams_data.get("teams", []) if t.get("id") == player.get("team_id")), None)
            if team:
                embed.add_field(name="🏅 Team", value=team.get("name"), inline=True)
        
        if player.get("tracker"):
            embed.add_field(name="🔗 Tracker", value=f"[View Stats]({player.get('tracker')})", inline=True)
        
        embed.set_footer(text="PNW eSports | Player Statistics")
        
        await interaction.response.send_message(embed=embed)

    # NOTE: Notification queue processing is handled centrally in main.py
    # to prevent duplicate sends. Do not add duplicate processors here.

async def setup(bot):
    # Only add if not already registered
    if not bot.get_cog("VarsityCommands"):
        cog = VarsityCommands(bot)
        await bot.add_cog(cog)
        # NOTE: Notification processing is centralized in main.py to prevent duplicates