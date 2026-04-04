# BoilerCraftGG 🎮

**Official Discord Bot for Purdue Network Minecraft Server**

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![discord.py](https://img.shields.io/badge/discord.py-2.3+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

## Features

- � **Student Verification** - Button-based verification with Purdue email validation
- 🏫 **Campus Selection** - Support for West Lafayette, Northwest, Fort Wayne, and Indianapolis
- 🔊 **Temporary Voice Channels** - Join to Create VC system with full channel management
- 🛡️ **Admin Commands** - Bot management with /stop, /restart, /reload
- 📊 **Embeds** - Beautiful Purdue Gold-themed embeds for all messages
- ⚡ **Slash Commands** - Modern Discord slash command interface

## Project Structure

```
BoilerCraftGG/
├── bot.py              # Main bot entry point
├── config.py           # General bot configuration
├── settings.py         # Sensitive settings (tokens, IDs)
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variables template
├── .gitignore          # Git ignore file
├── cogs/               # Command modules
│   ├── __init__.py
│   ├── admin.py        # Admin commands (/stop, /restart, etc.)
│   ├── verification.py # Student verification system
│   ├── tempvc.py       # Temporary voice channel system
│   └── help.py         # Help and info commands
├── utils/              # Utility modules
│   ├── __init__.py
│   ├── embeds.py       # Embed builder utility
│   └── database.py     # SQLite database handler
└── data/               # Database storage
```

## Verification Flow

1. **New member joins** → Bot sends welcome message in #start-here
2. **User clicks "Start Verification"** → Modal form opens
3. **User fills out form:**
   - First Name (required)
   - Minecraft Username (required, validated via Mojang API)
   - Purdue Email (required, must be @purdue.edu, @pnw.edu, or @pfw.edu)
   - Phone Number (optional)
4. **User selects campus** → Dropdown with 4 campus options
5. **Verification complete:**
   - User receives `Verified` role + Campus role
   - `Unverified` role is removed
   - Success message shown
   - Welcome DM sent with server IP

## Setup

### Prerequisites

- Python 3.10 or higher
- Discord Bot Token ([Create one here](https://discord.com/developers/applications))

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/BoilerCraftGG.git
   cd BoilerCraftGG
   ```

2. **Create virtual environment** (recommended)
   ```bash
   python -m venv venv
   
   # Windows
   venv\Scripts\activate
   
   # Linux/Mac
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   ```bash
   # Copy the example file
   cp .env.example .env
   
   # Edit .env with your values
   ```

5. **Run the bot**
   ```bash
   python bot.py
   ```

## Configuration

Edit the `.env` file with your Discord bot token and server IDs:

```env
# Required
DISCORD_TOKEN=your_bot_token_here
OWNER_ID=your_discord_user_id
GUILD_ID=your_guild_id

# Verification System
START_HERE_CHANNEL_ID=channel_id
VERIFIED_ROLE_ID=role_id
UNVERIFIED_ROLE_ID=role_id

# Campus Roles
WEST_LAFAYETTE_ROLE_ID=role_id
NORTHWEST_ROLE_ID=role_id
FORT_WAYNE_ROLE_ID=role_id
INDIANAPOLIS_ROLE_ID=role_id

# Temp VC System
JOIN_TO_CREATE_VC_ID=voice_channel_id
TEMP_VC_CATEGORY_ID=category_id

# Admin
ADMIN_ROLE_ID=admin_role_id
```

## Commands

### General Commands
| Command | Description |
|---------|-------------|
| `/help` | View all available commands |
| `/ping` | Check bot latency |
| `/status` | View bot status and statistics |
| `/serverinfo` | View server information |
| `/userinfo [user]` | View user information |

### Verification Commands
| Command | Description |
|---------|-------------|
| Click **Start Verification** button | Begin the verification process |
| `/whois [user]` | Look up a user's Minecraft account |
| `/unverify <user>` | Remove user verification (Admin) |
| `/setup_verification` | Send verification prompt (Admin) |

### Voice Channel Commands
| Command | Description |
|---------|-------------|
| `/vc rename <name>` | Rename your temp channel |
| `/vc limit <number>` | Set user limit (0 = unlimited) |
| `/vc lock` | Lock your channel |
| `/vc unlock` | Unlock your channel |
| `/vc permit <user>` | Allow a user to join |
| `/vc reject <user>` | Block a user from joining |
| `/vc claim` | Claim an orphaned channel |

### Admin Commands
| Command | Description |
|---------|-------------|
| `/stop` | Stop the bot |
| `/restart` | Restart the bot |
| `/reload <cog>` | Reload a specific cog |
| `/sync` | Sync slash commands |

## Setting Up Discord

### Required Bot Permissions

Enable these in the Discord Developer Portal:
- **Privileged Intents:**
  - Server Members Intent
  - Message Content Intent

### Invite URL Scopes
- `bot`
- `applications.commands`

### Required Bot Permissions
- Manage Channels
- Manage Roles
- Send Messages
- Embed Links
- Move Members
- Connect
- Speak

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License.

## Support

For support, join the Purdue Network Discord server or open an issue on GitHub.

---

**Boiler Up! 🚂**
