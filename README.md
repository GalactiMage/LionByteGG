<p align="center">
  <img src="LionbyteGGLogo.png" alt="LionByteGG" width="150"/>
</p>

<h1 align="center">LionByteGG — PNW Esports System</h1>

<p align="center">
  <strong>System created and founded by Jay Moon for Purdue University</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/JavaScript-ES2022-F7DF1E?logo=javascript&logoColor=black" alt="JavaScript"/>
  <img src="https://img.shields.io/badge/Java-17+-ED8B00?logo=openjdk&logoColor=white" alt="Java"/>
  <img src="https://img.shields.io/badge/HTML%2FCSS-Jinja2-E34F26?logo=html5&logoColor=white" alt="HTML"/>
  <img src="https://img.shields.io/badge/SQL-SQLite3-003B57?logo=sqlite&logoColor=white" alt="SQL"/>
  <img src="https://img.shields.io/badge/discord.py-2.3+-5865F2?logo=discord&logoColor=white" alt="discord.py"/>
  <img src="https://img.shields.io/badge/discord.js-14-5865F2?logo=discord&logoColor=white" alt="discord.js"/>
  <img src="https://img.shields.io/badge/Flask-2.3+-000000?logo=flask&logoColor=white" alt="Flask"/>
</p>

---

A complete esports management system built for **Purdue University Northwest (PNW)** — four Discord bots and a full web dashboard that handle student onboarding, moderation, shift management, music, Minecraft server integration, arena kiosk sign-ins, and more.

---

## 📖 Full Documentation

This README is the quick-start. For everything else, read the docs:

| Document | What's in it |
|---|---|
| **[docs/NOVA_COMPLETE_GUIDE.md](docs/NOVA_COMPLETE_GUIDE.md)** | The complete human-readable guide: every dashboard page explained, the full permissions model, hard rules (do this / never do that), a troubleshooting quick-reference, and what makes the UI polished |
| **[docs/manual/](docs/manual/00_index.md)** | A 12-chapter deep-dive reference — every bot, cog, command, Flask route, permission key, and settings file, explained in full detail |
| **[docs/manual/00_index.md § Find It Fast](docs/manual/00_index.md#-find-it-fast--search-the-manual-by-topic)** | 🔎 **A searchable, alphabetized index** — look up any keyword (a permission, a setting, a feature) and jump straight to the exact chapter and section that covers it |

> **Starting the system?** Always use `LionByteGG\Start LionServices.bat` — it launches
> every bot, Lavalink, and the Nova web dashboard together in the right order. The host
> machine also runs this same script automatically on startup. Full startup/recovery
> instructions (including what to do if a service or the machine itself stops responding)
> are in [docs/manual/11_troubleshooting_and_operations_guide.md](docs/manual/11_troubleshooting_and_operations_guide.md).

---

## 🏗 System Overview

<table>
  <tr>
    <td align="center" width="25%"><img src="LionbyteGGLogo.png" width="80"/><br/><strong>LionByteGG</strong><br/><sub>Main Bot + Web Dashboard</sub><br/><code>Python · Flask · HTML · CSS · JS · SQL</code></td>
    <td align="center" width="25%"><img src="LionShiftGGLogo.png" width="80"/><br/><strong>LionShiftGG</strong><br/><sub>Shift Management</sub><br/><code>Python · discord.py</code></td>
    <td align="center" width="25%"><img src="purduenetworklogo.PNG" width="80"/><br/><strong>BoilerCraftGG</strong><br/><sub>Minecraft Server Bot</sub><br/><code>Python · discord.py · SQL</code></td>
    <td align="center" width="25%"><img src="LionBeatsGGLogo.png" width="80"/><br/><strong>LionBeatsGG</strong><br/><sub>Music Bot</sub><br/><code>JavaScript · Node.js · Java</code></td>
  </tr>
</table>

### Tech Stack

| Layer | Technologies |
|---|---|
| **Backend** | Python 3.11, Flask, discord.py 2.3+, Node.js, discord.js 14 |
| **Frontend** | HTML5 (Jinja2 templates), CSS3, JavaScript, Chart.js, Font Awesome |
| **Databases** | SQLite3 (auth, equipment, Minecraft data), JSON (config, runtime state) |
| **Audio** | Lavalink (Java 17+) — audio streaming server for music bot |
| **APIs** | Discord API v10, GGLeap API, Mojang API, mcsrvstat.us |
| **Hosting** | Windows batch scripts (local), Railway-ready (Procfile + railway.toml) |

---

## 📋 Requirements

| Requirement | Version | Used By |
|---|---|---|
| **Python** | 3.11 | LionByteGG, LionShiftGG, BoilerCraftGG |
| **Node.js** | 18+ | LionBeatsGG |
| **Java** | 17+ | Lavalink (audio server for LionBeatsGG) |
| **Git** | Latest | Pulling updates |

---

## 🚀 Setup

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

**Start everything at once (recommended — always use this):**
```bash
LionByteGG\Start LionServices.bat
```
This is the one script that launches every bot, Lavalink, and the Nova web dashboard
together in the correct order, then opens the Master Terminal for monitoring. On the machine
that hosts this system day-to-day, this same script is also configured to **run
automatically on Windows startup**, so a normal reboot brings the entire suite back online
by itself with no manual steps.

> **If you ever need to restart the host machine** (for an unexpected issue that a simple
> service restart doesn't fix), make sure it reconnects over a **wired Ethernet cable, not
> Wi-Fi** — the machine's static IP address is bound specifically to its Ethernet adapter
> (see `set_static_ip.bat`), and staying wired gives the most reliable, consistent
> experience. Full recovery steps (including other ways to fix a stuck machine or service)
> are in [docs/manual/11_troubleshooting_and_operations_guide.md](docs/manual/11_troubleshooting_and_operations_guide.md).

**Or start individually** (only if you need to bring back one specific service):
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

## 🔄 Updating the System

### Pulling the Latest Code

```bash
cd C:\LionByteGG
git pull origin main
```

`.gitignore` keeps this safe — student data, databases, `.env` files, and caches are never tracked, so a pull never touches or overwrites them.

### Restarting After a Pull

Restart only the services that changed:

```bash
# Stop then start a bot
LionByteGG\stop_bot.bat        &&  LionByteGG\start_bot.bat
LionShiftGG\stop_bot.bat       &&  LionShiftGG\start_bot.bat
BoilerCraftGG\stop_bot.bat     &&  BoilerCraftGG\start.bat
LionBeatsGG\stop-all.bat       &&  LionBeatsGG\start-all.bat

# Stop then start the web dashboard
LionByteGG\stop_website.bat    &&  LionByteGG\start_website_production.bat
```

Or just re-run `LionByteGG\Start LionServices.bat` to restart everything at once — it's single-instance guarded, so it won't double-launch anything already running.

> **Nova (the web dashboard) runs in production mode with no hot-reload.** Any edit to `web/app.py` or a template in `web/templates/` requires a restart to take effect, and a browser hard-refresh (Ctrl+F5) to clear cached assets.

### Pushing Your Own Changes

After modifying code locally:

```bash
git add -A
git commit -m "Brief description of what you changed"
git push
```

> **The `.gitignore` automatically blocks all student data, databases, `.env` files, and caches from ever being committed.** You cannot accidentally push personal information.

---

## 🛠 How to Modify the System

This section explains where to make changes when you need to add features, fix bugs, or update behavior.

### Understanding the Languages Used

| Language | Where It's Used | What It Does |
|---|---|---|
| **Python** | Bot logic (`main.py`, `cogs/`, `utils/`, `views/`) | Discord bot commands, event handlers, API integrations |
| **HTML + Jinja2** | `web/templates/*.html` | Web dashboard pages — Jinja2 is Python's templating language embedded in HTML |
| **CSS** | `web/static/css/custom.css` + inline in templates | Dashboard styling and layout |
| **JavaScript** | `web/static/js/main.js` + inline in templates | Dashboard interactivity, charts, AJAX calls to Flask API |
| **SQL (SQLite)** | `web/auth_db.py`, `web/equipment_db.py` | User authentication, equipment tracking, BoilerCraft data |
| **Java** | Lavalink server (`LionBeatsGG/lavalink/`) | Audio streaming engine — you don't modify this, just update the `.jar` |
| **JavaScript (Node.js)** | `LionBeatsGG/bot/src/` | Music bot commands and Lavalink client |

### Adding a New Bot Command

Bot commands live in **cogs** (modular command files). Each bot has a `cogs/` folder.

**Example — adding a new command to LionByteGG:**

1. Open `LionByteGG/cogs/admin_commands.py` (or create a new cog file)
2. Add your command:
   ```python
   @app_commands.command(name="my-command", description="What this command does")
   async def my_command(self, interaction: discord.Interaction):
       await interaction.response.send_message("Hello!")
   ```
3. If you created a new cog file, register it in `main.py`:
   ```python
   await bot.load_extension("cogs.my_new_cog")
   ```
4. Restart the bot. Run `/sync` in Discord if commands don't appear.

### Modifying the Web Dashboard

The dashboard is a **Flask** app using **Jinja2 HTML templates** with inline **CSS** and **JavaScript**.

| What You Want to Change | Where to Look |
|---|---|
| Add a new page | Create a template in `web/templates/`, add a route in `web/app.py` |
| Change page layout/style | Edit the HTML template + CSS in `web/static/css/custom.css` |
| Add interactive features | Add JavaScript in the template's `{% block extra_scripts %}` block |
| Change navigation/sidebar | Edit `web/templates/base.html` — all pages inherit from this |
| Add a new API endpoint | Add a `@app.route()` function in `web/app.py` |
| Change login/permissions | Edit `web/auth_db.py` and `web/oauth_routes.py` |
| Modify database tables | Edit `web/auth_db.py` or `web/equipment_db.py` (SQLite) |

**Example — adding a new dashboard page:**

1. Create `web/templates/my_page.html`:
   ```html
   {% extends "base.html" %}
   {% block page_title %}My Page{% endblock %}
   {% block content %}
   <div class="content-container">
       <h2>My New Page</h2>
       <p>Content goes here</p>
   </div>
   {% endblock %}
   ```

2. Add a route in `web/app.py`:
   ```python
   @app.route('/my-page')
   def my_page():
       return render_template('my_page.html')
   ```

3. Add a link in `web/templates/base.html` sidebar.

### Modifying Bot Behavior (Events, Automation)

| What You Want to Change | Where to Look |
|---|---|
| Welcome messages / onboarding | `LionByteGG/views/setup_view.py` |
| Ticket system | `LionByteGG/views/ticket_view.py` and `cogs/ticket_commands.py` |
| Varsity registration flow | `LionByteGG/views/varsity_view.py` |
| Moderation (warn/kick/ban) | `LionByteGG/cogs/moderation.py` |
| Reaction roles | `LionByteGG/cogs/reaction_roles.py` |
| Voice channel auto-create | `LionByteGG/cogs/vc-system.py` |
| Shift clock in/out flow | `LionShiftGG/cogs/shift-management.py` |
| Shift offers and trades | `LionShiftGG/cogs/offer-trade.py` |
| Minecraft verification | `BoilerCraftGG/cogs/verification.py` |
| Minecraft chat monitoring | `BoilerCraftGG/cogs/chat_monitor.py` |
| Music playback commands | `LionBeatsGG/bot/src/commands/play.js` |
| Music panel buttons | `LionBeatsGG/bot/src/music/controls.js` |

### Updating External Dependencies

```bash
# Python bots — check for updates
pip install --upgrade discord.py flask requests

# LionBeatsGG — check for updates
cd LionBeatsGG/bot
npm update

# Lavalink — download newest .jar from:
# https://github.com/lavalink-devs/Lavalink/releases
# Replace LionBeatsGG/lavalink/Lavalink.jar
```

> **Warning:** Always test after updating dependencies. Major version bumps (e.g., discord.py 2.x → 3.x) may require code changes.

---

## 🤖 LionByteGG — Main Bot Commands

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

## ⏰ LionShiftGG — Shift Management Commands

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

## ⛏️ BoilerCraftGG — Minecraft Bot Commands

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

## 🎵 LionBeatsGG — Music Bot Commands

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

## 🌐 Web Dashboard ("Nova")

The web dashboard ("Nova") provides a browser-based control panel for managing the entire
system — every bot above is administered from this one login. Full walkthrough of every page:
**[docs/NOVA_COMPLETE_GUIDE.md](docs/NOVA_COMPLETE_GUIDE.md)**.

### Pages

| Page | Description |
|---|---|
| **Dashboard** | System overview, bot status, quick stats |
| **Members** | View/search all Discord members |
| **Moderation** | Moderation templates, flagged word management |
| **Tickets** | View open/closed tickets, manage blacklist |
| **Varsity** | Review and approve/deny varsity registrations |
| **Rosters** | Team rosters (multi-team support), Discord role sync, match stats, CSV import/export |
| **Analytics** | Server statistics and charts |
| **Settings** | Arena hours, esports games list, team→role mapping, flagged words |
| **Logs** | Activity and moderation logs |
| **Reaction Roles** | Manage reaction role assignments |
| **VC System** | View/manage voice channel generators |
| **Arena Staff — Live Feed** | Real-time kiosk sign-ins |
| **Arena Staff — PC Manager** | Live PC room map (matches the physical kiosk floor layout) with lock/unlock controls and right-click quick actions |
| **Arena Staff — Kiosk Manager** | Kiosk hours, announcement banner, sign-in guard, PC screen-lock automation |
| **Arena Staff — Activity** | Traffic analytics: heatmaps, busiest hours, top visitors |
| **Arena Staff — Students** | Per-guest visit history, staff notes, ban/watch status |
| **Arena Staff — Incident Reports** | File and track behavioral incidents |
| **Arena Staff — Inventory** | Equipment checkout/checkin with QR-code self-service |
| **LionShift Dashboard** | Shift calendar, schedule creator, worker roster, offers/trades/time-off approvals |
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

### Permissions System

Every dashboard user belongs to a **permission group** with a list of keys following a simple
convention:

| Key pattern | Meaning |
|---|---|
| `section.NAME` | Shows an entire bot's section in the sidebar (e.g. `section.arena`) |
| `page.NAME` | Makes one specific page's nav link + route reachable (e.g. `page.rosters`) |
| `NAME.action` | A specific in-page capability, separate from just viewing (e.g. `arena.manage`, `moderation.warn`) |
| `admin.panel` | Full bypass — reserved for true administrators |

Groups are managed entirely in `/admin` — no code changes needed to create a new role.
Full details, including common pitfalls, are in
**[docs/NOVA_COMPLETE_GUIDE.md § 4](docs/NOVA_COMPLETE_GUIDE.md#4-the-permissions-system-read-this-before-editing-anyones-access)**.

### ⚠️ Rules to Live By

A short list of hard rules that have caused real incidents in this system — the full list
(with the reasoning behind each) is in
**[docs/NOVA_COMPLETE_GUIDE.md § 5](docs/NOVA_COMPLETE_GUIDE.md#5-rules-to-live-by--do-this-never-do-that)**:

- **Only send one varsity registration DM to a person at a time.** Check their pending status
  in Rosters before sending another.
- **Never stop or restart a bot while a sync process is running** (Discord role sync, AutoMod
  word-list sync, bulk DM send, `/force-register-all`).
- **Never run two `run.py` (Nova) processes at once** — the #1 historical cause of login bugs.
- **Never hand-edit a JSON data file while its bot/server is running.**
- **Don't weaken `.gitignore`** to force a commit through — student data and secrets must
  never be tracked.

---

## 📁 Project Structure

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

## ⚠️ Important Notes

- **Student data is NOT stored in this repository.** All user records, databases, caches, and logs are generated at runtime and excluded via `.gitignore`. This is required by Purdue policy.
- **Never commit `.env` files.** They contain Discord tokens and API keys. Use `.env.example` as a template.
- **Python version:** All Python bots are built for and tested on Python 3.11. Do not upgrade without testing.
- **Lavalink:** The music bot requires a running Lavalink server. Download `Lavalink.jar` from [the Lavalink releases page](https://github.com/lavalink-devs/Lavalink/releases) and place it in `LionBeatsGG/lavalink/`.
- **Data safety:** All JSON writes use atomic file operations (write to temp file → swap). This prevents data loss from crashes or power failures.
- **Secrets:** Bot tokens and API keys are loaded from `.env` files at runtime via `python-dotenv`. Never hardcode secrets in source files.

---

## ❓ Frequently Asked Questions

**Where do I find every command, route, and setting documented in full detail?**
[docs/manual/](docs/manual/00_index.md) — 12 chapters, plus a searchable
[Find It Fast index](docs/manual/00_index.md#-find-it-fast--search-the-manual-by-topic) at
the top for jumping straight to a specific topic.

**How do the varsity/JV registration questions work, and can I change them?**
Yes, and it's fully documented — see
[docs/manual/04_lionbytegg_bot.md § 4.5](docs/manual/04_lionbytegg_bot.md#45-varsity--jv-team-registration)
for the complete list of default questions (there are 15, across 3 pop-up forms, plus a
required schedule-photo upload step) and the exact steps to add, remove, or reword any of
them.

**Something broke — where do I start?**
[docs/manual/11_troubleshooting_and_operations_guide.md](docs/manual/11_troubleshooting_and_operations_guide.md)
— it covers starting/stopping every service, what to do if the host machine itself needs a
restart, and a running list of every known issue this project has hit with its fix.

**Do I need to restart anything after pulling new code?**
Yes — see the [Updating the System](#-updating-the-system) section above. Nova specifically
has no hot-reload in production, so a code/template change needs a server restart plus a
browser hard-refresh to actually show up.

---

## 📬 Contact

For questions about this system, reach out to the PNW Esports Club staff or the system creator.

---

<p align="center">
  <strong>System created and founded by Jay Moon for Purdue University</strong>
  <br/>
  <sub>LionByteGG · LionShiftGG · BoilerCraftGG · LionBeatsGG</sub>
</p>
