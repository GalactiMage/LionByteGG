"""
Configuration file for BoilerCraftGG Discord Bot
General bot configuration and styling settings
"""

# =============================================================================
# BOT INFO
# =============================================================================
BOT_NAME = "BoilerCraftGG"
BOT_VERSION = "1.0.0"
BOT_DESCRIPTION = "Official Discord Bot for Purdue Network Minecraft Server"

# =============================================================================
# BOT COLORS (Purdue Theme)
# =============================================================================
COLORS = {
    "primary": 0xCFB991,      # Purdue Gold
    "secondary": 0x000000,    # Black
    "success": 0x2ECC71,      # Green
    "error": 0xE74C3C,        # Red
    "warning": 0xF39C12,      # Orange
    "info": 0x3498DB,         # Blue
    "purdue_gold": 0xCFB991,  # Purdue Gold
    "purdue_black": 0x000000  # Purdue Black
}

# =============================================================================
# DATABASE
# =============================================================================
DATABASE_PATH = "data/boilercraft.db"

# =============================================================================
# CAMPUS INFORMATION
# =============================================================================
CAMPUSES = {
    "west_lafayette": {
        "name": "West Lafayette",
        "emoji": "🏛️",
        "color": 0xCFB991
    },
    "northwest": {
        "name": "Purdue Northwest",
        "emoji": "🌊",
        "color": 0xCFB991
    },
    "fort_wayne": {
        "name": "Purdue Fort Wayne",
        "emoji": "🏰",
        "color": 0xCFB991
    },
    "indianapolis": {
        "name": "Purdue Indianapolis",
        "emoji": "🏙️",
        "color": 0xCFB991
    }
}
