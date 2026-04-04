#------------------Server Variables------------------#

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root (one level up from utils/)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))

GUILD_ID = 728274695673348140
SETUP_CHANNEL_ID = 1384917614656094218
STUDENT_LIFE_LINK = "https://mypnwlife.pnw.edu/EsportClub/club_signup"

#-------------------Role IDs------------------#

STUDENT_ROLE_ID = 745068163313434716
GUEST_ROLE_ID = 1070186562236731474

#------------------Minecraft Club Variables------------------#

ANNOUNCE_CHANNEL_ID = 1041774671768604822  # <-- Replace with your announce channel ID
MINECRAFT_ROLE_ID = 1384918317189435585    # <-- Replace with your Minecraft role ID

#------------------Ticket System Channel------------------#

TICKET_PANEL_CHANNEL_ID = 1316235826950307860  # <-- Replace with your ticket panel channel ID

#------------------Ticket Logs Channel------------------#

TICKET_LOGS_CHANNEL_NAME = "lionbyte-ticket-logs"
STUDENTWORKER_LOGS_CHANNEL_NAME = "studentworker-logs"

#-----------------------------------------------------------#


pending_users = {}
LOG_CHANNEL_NAME = "lionbyte-logs" 
REGISTRATION_REVIEW_CHANNEL_NAME = "varsity-registrations"

# Project directories (resolve relative to repo root)
PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
USER_RECORDS_DIR = os.path.join(PROJECT_ROOT, "user_records")
GUEST_TIMES_DIR = os.path.join(PROJECT_ROOT, "guest_times")
VARSITY_REG_DIR = os.path.join(USER_RECORDS_DIR, "varsity_registrations")
SCHEDULE_IMAGES_DIR = os.path.join(USER_RECORDS_DIR, "schedule_images")

# --- Ticket System Implementation ---

TICKET_CATEGORY_NAME = "Tickets"
TICKET_CHANNEL_PREFIX = "ticket-"

ticket_blacklist = set()

SECURITY_CODE = os.environ.get("SECURITY_CODE", "146332")  # Bot security code for verification

TECHNICIAN_ROLE_ID = 1413287713393742024

# --- Team/Roster Role Sync Configuration ---
# Maps game names to their varsity/JV role IDs
# Format: "game_name": {"varsity": role_id, "jv": role_id}
# Add your game-specific roles here
TEAM_ROLE_MAPPING = {
    "Overwatch 2": {"varsity": None, "jv": None},
    "Valorant": {"varsity": None, "jv": None},
    "League of Legends": {"varsity": None, "jv": None},
    "Rocket League": {"varsity": None, "jv": None},
    "Super Smash Bros": {"varsity": None, "jv": None},
    "Counter-Strike 2": {"varsity": None, "jv": None},
    "Apex Legends": {"varsity": None, "jv": None},
    "Call of Duty": {"varsity": None, "jv": None},
    "Fortnite": {"varsity": None, "jv": None},
    "Rainbow Six Siege": {"varsity": None, "jv": None},
    "Marvel Rivals": {"varsity": None, "jv": None},
}

# General varsity/JV roles (applied to all varsity/JV players)
VARSITY_ROLE_ID = None  # Set this to your general Varsity role ID
JV_ROLE_ID = None       # Set this to your general JV role ID

# Esports Player Roles/Positions
ESPORTS_ROLES = {
    "igl": "IGL (In-Game Leader)",
    "captain": "Captain",
    "support": "Support",
    "dps": "DPS/Carry",
    "tank": "Tank/Front Line",
    "flex": "Flex",
    "entry": "Entry Fragger",
    "awper": "AWPer/Sniper",
    "lurker": "Lurker",
    "analyst": "Analyst",
    "coach": "Coach",
    "substitute": "Substitute"
}

# Player Status Options
PLAYER_STATUSES = {
    "active": "Active",
    "inactive": "Inactive",
    "benched": "Benched",
    "suspended": "Suspended",
    "tryout": "Tryout"
}


