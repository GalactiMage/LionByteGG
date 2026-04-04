"""
Settings Configuration for BoilerCraftGG Discord Bot
Put your values directly here
"""

import os
from dotenv import load_dotenv

# Load .env from the same directory as settings.py
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

# =============================================================================
# BOT CREDENTIALS (KEEP SECRET!)
# =============================================================================
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")

# =============================================================================
# SERVER IDS
# =============================================================================
GUILD_ID = 1442632989518598176

# =============================================================================
# CHANNEL IDS
# =============================================================================
START_HERE_CHANNEL_ID = 1442720095670636544

# Note: Temp VC generators are now configured via /setup_tempvc command
# and stored in the database (supports up to 4 generators)

# =============================================================================
# ROLE IDS
# =============================================================================
# Verification Role (given after completing verification)
VERIFIED_ROLE_ID = 1465567975963758689

# Campus Roles
CAMPUS_ROLES = {
    "west_lafayette": 1465567079288799418,
    "northwest": 1465566884257595425,
    "fort_wayne": 1465567177754017880,
    "indianapolis": 1465567346889588850
}

# Staff Role (users who can manage tickets)
STAFF_ROLE_ID = None  # Set to your staff role ID, e.g. 1234567890

# =============================================================================
# ANNOUNCEMENT IDS
# =============================================================================
ANNOUNCE_CHANNEL_ID = 1041774671768604822
MINECRAFT_ROLE_ID = 1384918317189435585

# =============================================================================
# MINECRAFT SERVER
# =============================================================================
MINECRAFT_SERVER_IP = "mc.esports.purdue.edu"

# =============================================================================
# VALID PURDUE EMAIL DOMAINS
# =============================================================================
VALID_EMAIL_DOMAINS = [
    "@purdue.edu",
    "@pnw.edu",
    "@pfw.edu"
]
