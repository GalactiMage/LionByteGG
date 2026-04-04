# LionByteGG — PNW Esports System

> **System created and founded by Jay Moon for Purdue University**

A complete esports management system built for **Purdue University Northwest (PNW)** — consisting of four Discord bots and a web dashboard that handle everything from student onboarding and moderation to shift management, music, and Minecraft server integration.

---

## System Overview

| Component | Language | Purpose |
|---|---|---|
| **LionByteGG** | Python (discord.py) | Main esports bot + Flask web dashboard |
| **LionShiftGG** | Python (discord.py) | Student worker shift management |
| **BoilerCraftGG** | Python (discord.py) | Purdue Network Minecraft server bot |
| **LionBeatsGG** | Node.js (discord.js) | Music bot with Lavalink audio server |

---

## Requirements

- **Python 3.11** (for LionByteGG, LionShiftGG, BoilerCraftGG)
- **Node.js 18+** (for LionBeatsGG)
- **Java 17+** (for Lavalink audio server)

---

## Setup

### 1. Clone the Repository

```bash
git clone https://github.com/GalactiMage/LionByteGG.git
cd LionByteGG
```

### 2. Create `.env` Files

Each bot has a `.env.example` file showing what environment variables are needed. Copy and fill them in:

```bash
# LionByteGG
cp LionByteGG/.env.example LionByteGG/.env

# LionShiftGG
cp LionShiftGG/.env.example LionShiftGG/.env

# BoilerCraftGG
cp BoilerCraftGG/.env.example BoilerCraftGG/.env

# LionBeatsGG
cp LionBeatsGG/bot/.env.example LionBeatsGG/bot/.env
```

**Where to get tokens:**
- **Discord Bot Tokens** — [Discord Developer Portal](https://discord.com/developers/applications) → Select the application → Bot → Reset Token
- **GGLeap API Tokens** — Contact GGLeap support or generate from the GGLeap admin dashboard
- **Security Code** — Set any code you want for admin command verification

### 3. Install Dependencies

```bash
# LionByteGG
cd LionByteGG
pip install -r requirements.txt

# LionShiftGG
cd ../LionShiftGG
pip install -r requirements.txt

# BoilerCraftGG
cd ../BoilerCraftGG
pip install -r requirements.txt

# LionBeatsGG
cd ../LionBeatsGG/bot
npm install
```

### 4. Start the System

**Start everything at once:**
```bash
LionByteGG\Start LionServices.bat
```

**Or start individually:**
```bash
# Main bot + web dashboard
LionByteGG\start_bot.bat
LionByteGG\start_website.bat

# Shift management bot
LionShiftGG\start_bot.bat

# Minecraft bot
BoilerCraftGG\start.bat

# Music bot (start Lavalink first, then the bot)
LionBeatsGG\start-all.bat
```

---

## Updating the System

Use the update scripts to pull the latest code **without touching any student data or databases**:

```bash
# Pull latest code changes
update_code.bat

# Or update and restart all bots
update_and_restart.bat
```

These scripts only update source code files — they never modify `.env` files, databases, user records, or any data files.

---

## LionByteGG — Main Bot Commands

### General Commands (Everyone)

| Command | Description |
|---|---|
| `/ping` | Check the bot's current latency |
| `/about` | Learn more about LionByteGG |
| `/club` | Get the link to join the official PNW Esports Club |
| `/arena-hours` | View the PNW Esports Arena hours |
| `/help` | Show all available bot commands |
| `/join-mc-server` | Get info about the Purdue Northwest Minecraft server |
| `/time` | Show how much time you have left as a Guest |
| `/serverinfo` | Show server information |

### Admin Commands (Administrator Only)

| Command | Description |
|---|---|
| `/force-setup-user <user>` | Manually trigger onboarding for a user |
| `/set-activity <activity>` | Set a custom bot activity status |
| `/reset-activity` | Reset bot activity to arena open/closed status |
| `/restart_service` | Restart the bot |
| `/stop-service` | Stop the bot |
| `/clear <amount>` | Delete recent messages (max 100) |
| `/warn <user> <reason>` | Warn a user and log it |
| `/kick <user> <reason>` | Kick a user |
| `/ban <user> <reason>` | Ban a user |
| `/unban <user_id>` | Unban a user by ID |
| `/mute <user> <duration> [reason]` | Timeout a user (duration in minutes) |
| `/announce <channel> <message>` | Send an announcement |
| `/lock <channel>` | Lock a channel |
| `/unlock <channel>` | Unlock a channel |
| `/setup-tickets` | Deploy the support ticket panel |
| `/setup_guest_transfer <channel>` | Post the Guest-to-Student migration panel |
| `/setup_reaction_role <channel> <message_id> <emoji> <role>` | Attach a reaction role |
| `/setup_vc_generator <voice_channel> <category>` | Setup auto-creating voice channels |
| `/setup_tryout_vc <voice_channel> <category>` | Setup tryout VC generator |
| `/list_vc_generators` | List all VC generators |
| `/force-register-all` | DM registration to unregistered members |
| `/download-transcript <user>` | Download a user's moderation record |
| `/admin-help` | Show all admin commands |
| `/say <message>` | Make the bot send a message |
| `/userinfo <user>` | Show detailed user info |
| `/blacklist-tickets <user>` | Block a user from tickets |
| `/whitelist-tickets <user>` | Allow a user to use tickets again |

### Automated Systems
- **Onboarding** — Welcome messages and setup flow for new members
- **Watchlist** — Track activity of flagged users (managed via dashboard)
- **Reaction Roles** — Auto-assign roles on emoji reactions
- **Temp Voice Channels** — Auto-create/delete voice channels
- **AutoMod Integration** — Logs Discord AutoMod events to user records

---

## LionShiftGG — Shift Management Commands

| Command | Description |
|---|---|
| `/setup_clockpanel` | Deploy the ClockHub panel (Admin) |
| `/setup_offershift` | Deploy the Shift Board panel (Admin) |

### Panel-Based Features (Student Workers)

| Feature | Description |
|---|---|
| **Start Shift** | Select schedule → shift type (Opener/Mid/Closer) → clock in |
| **End Shift** | Select schedule → shift type → closing checklist → clock out |
| **Offer Shift** | Post a shift for others to pick up |
| **Trade Shift** | Request a shift trade with another worker (requires director approval) |
| **Take Shift** | Claim an offered shift |

---

## BoilerCraftGG — Minecraft Bot Commands

### General Commands (Everyone)

| Command | Description |
|---|---|
| `/help` | View all commands |
| `/ping` | Check bot latency |
| `/status` | View bot status and stats |
| `/serverinfo` | View server information |
| `/userinfo [user]` | View user info + Minecraft account if verified |

### Voice Channel Commands — `/vc` (Channel Owner)

| Command | Description |
|---|---|
| `/vc rename <name>` | Rename your voice channel |
| `/vc limit <number>` | Set user limit (0 = unlimited) |
| `/vc lock` | Lock your channel |
| `/vc unlock` | Unlock your channel |
| `/vc permit <user>` | Allow a user into your locked channel |
| `/vc reject <user>` | Block and kick a user |
| `/vc kick <user>` | Kick a user from your channel |
| `/vc transfer <user>` | Transfer channel ownership |
| `/vc claim` | Claim an orphaned voice channel |
| `/vc info` | View voice channel info |

### Chat Monitor — `/chatmonitor` (Administrator Only)

| Command | Description |
|---|---|
| `/chatmonitor add-word <word>` | Add a flagged word |
| `/chatmonitor remove-word <word>` | Remove a flagged word |
| `/chatmonitor list-words` | List all flagged words |
| `/chatmonitor toggle` | Enable/disable monitoring |
| `/chatmonitor add-server <key> <name> <channel>` | Add a Minecraft server to monitor |
| `/chatmonitor remove-server <key>` | Remove a monitored server |
| `/chatmonitor status` | Show monitoring status |

### Admin Commands

| Command | Description |
|---|---|
| `/stop` | Stop the bot |
| `/restart` | Restart the bot |
| `/reload <cog>` | Reload a cog module |
| `/sync` | Sync slash commands |
| `/setup_verification` | Deploy the verification panel |
| `/unverify <user>` | Remove verified status |
| `/send-verify <user>` | Send verification DM |
| `/setup-tickets` | Deploy ticket panel |
| `/blacklist-tickets <user> [reason]` | Block a user from tickets |
| `/whitelist-tickets <user>` | Unblock a user from tickets |
| `/setup_tempvc` | Add a voice channel generator |
| `/tempvc_list` | List generators |
| `/tempvc_remove` | Remove a generator |
| `/mc-maintenance-announcement <when> <servers>` | Announce server maintenance |

---

## LionBeatsGG — Music Bot Commands

### General Commands (Everyone)

| Command | Description |
|---|---|
| `/play <query>` | Play a song (YouTube/SoundCloud/Spotify) |
| `/stop` | Stop playback and clear queue |
| `/skip` | Skip the current song |
| `/queue` | Show the queue |
| `/nowplaying` | Show what's playing |
| `/loop <mode>` | Set loop mode (Off/Track/Queue) |
| `/clearqueue` | Clear the queue |
| `/volume <level>` | Set volume (0-200) |
| `/bassboost` | Toggle bass boost |
| `/previous` | Play the previous track |
| `/quiz <genre> [rounds]` | Start a music quiz game |

### Admin Commands

| Command | Description |
|---|---|
| `/lock-channel <channel>` | Set a dedicated music channel |
| `/unlock-channel` | Remove the locked channel |
| `/restart` | Restart the bot |
| `/set-activity <activity> <type>` | Set custom activity |
| `/set-default` | Reset to default activity |

---

## Web Dashboard

The web dashboard provides a browser-based control panel for managing the entire system. Access requires Discord OAuth2 login with appropriate permissions.

### Pages

| Page | Description |
|---|---|
| **Dashboard** | System overview, bot status, quick stats |
| **Members** | View/search all Discord members |
| **Moderation** | Moderation templates, flagged word management |
| **Tickets** | View open/closed tickets, manage blacklist |
| **Varsity** | Review and approve/deny varsity registrations |
| **Rosters** | Team rosters, send announcements and DMs to teams |
| **Analytics** | Server statistics and charts |
| **Settings** | Bot configuration |
| **Logs** | Activity and moderation logs |
| **Reaction Roles** | Manage reaction role assignments |
| **VC System** | View/manage voice channel generators |
| **GGLeap** | Arena PC status and game management |
| **On-Duty Dashboard** | Student worker on-duty panel |
| **On-Duty Equipment** | Equipment tracking for staff |
| **Music Dashboard** | LionBeatsGG controls, now playing, history |
| **Music Settings** | Music bot configuration |
| **Music Features** | Quiz songs, panels, stats management |
| **BoilerCraft Dashboard** | Minecraft server status, tickets |
| **BoilerCraft FAQ** | Manage server FAQs |
| **BoilerCraft Verified Players** | View/export verified Minecraft players |
| **BoilerCraft BoilerWatch** | Minecraft chat moderation logs |
| **BoilerCraft Members** | Member management (kick/ban/timeout/DM) |
| **BoilerCraft Analytics** | Player count analytics |
| **Admin** | Dashboard user/group/permission management |

---

## Project Structure

```
LionByteGG/              ← Main bot + web dashboard
├── main.py              ← Bot entry point
├── run_combined.py      ← Bot + website combined launcher
├── cogs/                ← Bot command modules
├── utils/               ← Shared utilities
├── views/               ← Discord UI views (buttons, modals)
└── web/                 ← Flask web dashboard
    ├── app.py           ← Main web application
    ├── templates/       ← HTML templates
    └── static/          ← CSS, JS, images

LionShiftGG/             ← Shift management bot
├── main.py              ← Bot entry point
├── constants.py         ← Configuration
└── cogs/                ← Command modules

BoilerCraftGG/           ← Minecraft bot
├── bot.py               ← Bot entry point
├── settings.py          ← Configuration
├── cogs/                ← Command modules
├── utils/               ← Utilities
└── views/               ← Discord UI views

LionBeatsGG/             ← Music bot
├── bot/
│   ├── src/             ← Bot source code
│   └── package.json     ← Node.js dependencies
└── lavalink/
    └── application.yml  ← Lavalink audio server config
```

---

## Important Notes

- **Student data is NOT stored in this repository.** All user records, databases, caches, and logs are generated at runtime and excluded via `.gitignore`.
- **Never commit `.env` files.** They contain Discord tokens and API keys. Use `.env.example` as a template.
- **Python version:** All Python bots are built for and tested on Python 3.11. Do not upgrade without testing.
- **Lavalink:** The music bot requires a running Lavalink server. Download `Lavalink.jar` from [the Lavalink releases page](https://github.com/lavalink-devs/Lavalink/releases) and place it in `LionBeatsGG/lavalink/`.

---

## Contact

For questions about this system, reach out to the PNW Esports Club staff or the system creator.

**System created and founded by Jay Moon for Purdue University.**
