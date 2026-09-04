# Chapter 1: BoilerCraftGG — The Minecraft / Purdue Network Bot

**Location:** `BoilerCraftGG/` · **Language:** Python (discord.py 2.3+) · **Storage:** SQLite (`data/boilercraft.db`) + JSON files

## What This Bot Is For

BoilerCraftGG is the Discord bot for **Purdue Network**, the club's Minecraft server. Its job
is to bridge the gap between "someone in the Minecraft world" and "someone in the Discord
server" — it verifies that a Discord member actually owns the Minecraft account they claim,
relays flagged in-game chat to staff, runs a support-ticket system, and gives members
temporary voice channels for grouping up. Everything it does is driven entirely by slash
commands; the old `!prefix` command style is intentionally disabled.

---

## 1.1 Starting, Stopping, and Configuring the Bot

- **Start it:** double-click `BoilerCraftGG/start.bat`. It shows an ASCII banner, `cd`s into
  the bot folder, and runs `python bot.py`. If the process exits, the window stays open so
  you can read the error before it closes.
- **Stop it:** `BoilerCraftGG/stop_bot.bat` — it kills any window titled `BoilerCraftGG*` and
  any Python process whose command line contains `BoilerCraftGG...bot.py`, as a double
  safety net.
- **Configuration** lives in two places:
  - `config.py` — constants that never change per-deployment (bot name/version, Purdue-gold
    color palette, the four PNW campus definitions).
  - `settings.py` — everything that *does* vary per-deployment, loaded from a `.env` file:
    `DISCORD_TOKEN` (required), `GUILD_ID`, `START_HERE_CHANNEL_ID`, `VERIFIED_ROLE_ID`,
    `STAFF_ROLE_ID` (optional), a `CAMPUS_ROLES` dict, `ANNOUNCE_CHANNEL_ID`,
    `MINECRAFT_ROLE_ID`, `MINECRAFT_SERVER_IP` (`mc.esports.purdue.edu`), and
    `VALID_EMAIL_DOMAINS` (`@purdue.edu`, `@pnw.edu`, `@pfw.edu`).

---

## 1.2 How the Bot Boots Up

Discord bots built on discord.py go through a predictable lifecycle, and it's worth knowing
it because "the bot isn't responding to commands" almost always means it got stuck somewhere
in this sequence:

1. **`setup_hook()`** runs first, before the bot even finishes logging in. It:
   - Initializes the SQLite database (creates tables if they don't exist yet).
   - Registers two "persistent views" (`TicketPanelView`, `TicketAdminView`) so that the
     ticket buttons on old messages still work even after a restart — Discord buttons
     normally stop working the moment the bot process that created them restarts, unless
     you explicitly re-register a view with the same custom IDs.
   - Dynamically loads every cog in `cogs/` (see §1.4).
   - Syncs slash commands — to a single guild if `GUILD_ID` is set (near-instant), otherwise
     globally (can take up to an hour to propagate).
2. **`on_ready()`** fires once Discord has handed the bot its guild/member cache. It prints a
   banner with login info, sets the bot's presence to *"watching Purdue Network | /help"*,
   restores the ticket panel if one was previously deployed, and starts the three background
   loops described in §1.3.

If you ever see the bot connect to Discord but slash commands don't show up, it's almost
always because the sync happened globally and just hasn't propagated yet — wait up to an
hour, or temporarily set `GUILD_ID` for instant guild-scoped testing.

---

## 1.3 The Three Background Loops

BoilerCraftGG runs three `@tasks.loop` background jobs continuously once it's ready:

### `poll_dashboard_commands` (every 5 seconds)
This is the bot's half of the bridge to the Nova web dashboard. It reads
`data/dashboard_commands.json`, looks for entries with `status: "pending"`, and executes
whichever action they describe:

| Command type | What happens |
|---|---|
| `deploy_panel` / `refresh_panel` | (Re)posts the ticket support panel to a channel |
| `faq_post` / `faq_edit` / `faq_delete` / `faq_renumber` | Manages FAQ embeds in the FAQ channel |
| `member_kick` / `member_ban` / `member_timeout` / `member_unban` | Moderation actions |
| `send_dm` | Sends a direct message to a specific user |
| `ticket_close` / `ticket_message` | Ticket actions initiated from the dashboard |

Each command's status is updated to `completed`, `error`, or `dm_failed` once processed, so
the dashboard can show you whether your action actually went through.

### `members_cache_loop` (every 30 seconds)
Snapshots every guild member — ID, all the various name fields, avatar, join/creation dates,
full role list, status — into `data/members_cache.json`. This is purely so the dashboard has
fast, pre-computed member data to search and display without hitting the Discord API itself.

### `server_analytics_loop` (every 5 minutes)
Pings the Minecraft server's status through the free `mcsrvstat.us` API and appends an
`{timestamp, online, players_online, players_max}` entry to `data/server_analytics.json`.
This file is capped at roughly 30 days of history (about 8,640 entries at a 5-minute
cadence) and written atomically (temp file + `os.replace()`) so a crash mid-write can never
corrupt it.

---

## 1.4 The Cogs — What Each One Does

Discord.py organizes commands into "cogs" — think of them as feature modules that get loaded
independently. BoilerCraftGG has six:

### `cogs/admin.py` — Administrator Tools
Every command here requires the Discord "Administrator" permission. Highlights:
- **`/stop`** and **`/restart`** — immediate shutdown, or a full process re-exec (`os.execv`)
  for a clean restart without leaving the old process hanging around.
- **`/reload <cog>`** — hot-swaps a single cog's code without restarting the whole bot.
  Genuinely useful while iterating on one feature.
- **`/sync`** — manually re-syncs slash commands and tells you how many were registered.
- **`/status`** — a quick health check: version, latency, guild/user/bot counts, loaded cogs.
- **`/mc-maintenance-announcement <when> <servers>`** — posts a maintenance notice to the
  announcement channel and pings the `@minecraft` role.

### `cogs/verification.py` — Linking a Discord Account to a Minecraft Account
This is the heart of "why does this bot exist." The flow, step by step:
1. A new member joins → `on_member_join` sends a welcome embed to `#start-here` with a
   persistent **"Start Verification"** button.
2. Clicking it opens `VerificationModal`, asking for: first name, Minecraft username, Purdue
   email, and an optional phone number.
3. On submit, the bot validates three things before accepting anything: the Minecraft
   username is alphanumeric/underscore only *and* actually exists (checked against the real
   Mojang API), the email ends in an approved Purdue domain, and the user isn't already
   verified.
4. If everything checks out, a **campus selection dropdown** appears (West Lafayette,
   Northwest, Fort Wayne, Indianapolis). Picking one adds both the general `VERIFIED_ROLE_ID`
   and that campus's specific role, saves the record to the `verified_users` SQLite table,
   and deletes the original welcome message so the channel doesn't fill up with stale prompts.
- **`/setup_verification`** (admin) deploys the persistent panel. **`/unverify <user>`**
  (admin) reverses the whole process — removes both roles and the database row.

### `cogs/tempvc.py` — Join-to-Create Voice Channels
Up to **4** "generator" channels can be configured (`MAX_GENERATORS = 4`). Joining a
generator channel instantly creates a personal voice channel for you and moves you into it;
the channel auto-deletes the moment it's empty (checked immediately on leave, and again
every 3 minutes by a cleanup loop in case an event was missed). As the owner, you get a
**control panel** with Lock / Unlock / Hide / Reveal / Rename / Set Limit / Delete buttons,
plus a full `/vc` slash-command group (`rename`, `limit`, `lock`, `unlock`, `permit`,
`reject`, `claim`, `kick`, `transfer`, `info`) for people who prefer typing commands. Admins
manage the generators themselves with `/setup_tempvc`, `/tempvc_list`, and `/tempvc_remove`.

> **Tip:** `/vc claim` exists specifically for the "the owner left and the channel is now
> ownerless" situation — anyone still in the channel can claim it and take over permissions.

### `cogs/help.py` — Info Commands
`/help`, `/serverinfo`, `/userinfo [user]`, and `/ping` — all public, no special permissions
needed. `/userinfo` will show a member's linked Minecraft username if they're verified.

### `cogs/chat_monitor.py` — "BoilerWatch" (Minecraft Chat → Discord Alerts)
Minecraft chat itself is relayed into a Discord channel by DiscordSRV (a separate Minecraft
plugin, not part of this codebase); this cog watches that relay channel for flagged words and
turns hits into staff alerts. It understands both public chat (`<player> message`) and
whispers (`player issued server command: /w target message`), and has a 30-second
deduplication window so a whisper that DiscordSRV double-relays as public chat doesn't
trigger two alerts for the same message.

Configuration is a simple three-part system stored in `data/chat_monitor_config.json`:
whether monitoring is on at all, which channel gets the alerts, which role gets pinged, and
a dictionary of monitored servers (each with its own console channel, so a club running
multiple Minecraft servers can watch all of them from one bot). The actual flagged word list
lives in `data/flagged_words.json`, editable live via the `/chatmonitor` command group
(`add-word`, `remove-word`, `list-words`, `toggle`, `add-server`, `remove-server`, `status`)
— no restart required. Every hit is logged to `data/flagged_log.json` (capped at the last
500) with the player's name, Mojang avatar, the exact message, which words matched, and a
link to their Discord account if they're verified.

### `cogs/tickets.py` — Ticket Admin Commands
Just the administrative side: `/setup-tickets <channel>` deploys the panel,
`/blacklist-tickets <user> [reason]` / `/whitelist-tickets <user>` manage who's allowed to
open a ticket at all. The actual ticket-creation flow lives in `views/ticket_view.py`.

---

## 1.5 How a Support Ticket Actually Works

`views/ticket_view.py` is worth walking through end-to-end because the same pattern (panel →
category select → modal → private channel → transcript on close) repeats across every bot
in this suite.

1. A member clicks **"Contact Support"** on the panel message.
2. A dropdown appears with support categories pulled live from
   `data/bot_config.json`'s `support_categories` list (Player Support, Server Bugs, Report a
   Player, Appeal/Unban, General Question by default — fully editable without touching code).
3. Picking a category opens `TicketSupportModal`, asking for Minecraft username, Purdue
   email, and a description of the issue.
4. On submit, the bot checks (in order): is this user blacklisted? do they already have an
   open ticket? is the email a valid Purdue domain? If all clear, it creates a private
   channel named `mc-ticket-0001` (auto-incrementing) inside the "MC Tickets" category, with
   permissions limited to the ticket creator, admins, and the staff role.
5. Staff see a **"Take Ticket"** button (claims it, records who's helping) and a **"Close
   Ticket"** button. Closing — whether the user or staff does it — always: collects the last
   100 messages as a transcript, posts that transcript to an auto-created `#mc-ticket-logs`
   channel, updates the JSON log (moves the record from `open` to `closed`), DMs the user a
   summary, and deletes the channel two seconds later (giving Discord's UI a moment to
   settle before the channel vanishes).

Everything about a ticket — who opened it, what category, the full text, staff assigned,
close reason — lives in `data/ticket_log.json` as an `{open: [...], closed: [...], blacklist:
[...]}` object, which is also what the Nova dashboard's BoilerCraft Tickets page reads and
writes (see [Chapter 8](08_nova_web_lionshift_boilercraft_equipment.md)).

---

## 1.6 The Database

`utils/database.py` wraps a single SQLite file (`data/boilercraft.db`) in WAL mode (Write
Ahead Logging, which lets reads happen concurrently with writes — important since the bot is
constantly reading/writing while commands come in). Four tables:

| Table | Purpose |
|---|---|
| `verified_users` | discord_id ↔ minecraft_username/uuid ↔ campus/contact info |
| `temp_voice_channels` | channel_id ↔ owner_id, so ownership survives a bot restart |
| `bot_settings` | generic key/value store for anything that doesn't need its own table |
| `temp_vc_generators` | join_channel_id ↔ category_id ↔ display name |

---

## 1.7 Data Files at a Glance

| File | Contains |
|---|---|
| `data/boilercraft.db` | The four SQLite tables above |
| `data/bot_config.json` | Ticket settings, staff role, channel IDs, support category list |
| `data/chat_monitor_config.json` | BoilerWatch server list + alert config |
| `data/flagged_words.json` | Words BoilerWatch looks for |
| `data/flagged_log.json` | Last 500 flagged in-game messages |
| `data/ticket_log.json` | Open/closed/blacklisted tickets |
| `data/members_cache.json` | Full member snapshot, refreshed every 30s |
| `data/server_analytics.json` | 30-day Minecraft server player-count history |
| `data/faqs.json` | FAQ question/answer/message-id triples |
| `data/dashboard_commands.json` | Nova's queue of pending actions for this bot |
| `data/user_records/{user_id}_record.json` | Per-user moderation history |

---

## 1.8 Permission Requirements Cheat Sheet

Everything under `/chatmonitor`, plus `/stop`, `/restart`, `/reload`, `/sync`,
`/setup_verification`, `/unverify`, `/setup_tempvc`, `/tempvc_list`, `/tempvc_remove`,
`/setup-tickets`, `/blacklist-tickets`, `/whitelist-tickets`, and
`/mc-maintenance-announcement` all require the Discord **Administrator** permission — there's
no finer-grained role system inside this particular bot (that lives in Nova instead).
Everything else (`/status`, `/help`, `/serverinfo`, `/userinfo`, `/ping`, and the whole `/vc`
group for your own channel) is open to everyone.
