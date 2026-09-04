# Chapter 4: LionByteGG Bot — The Flagship PNW Esports Bot

**Location:** `LionByteGG/` (bot side — see [Chapter 5](05_nova_web_auth_admin.md) onward for the web dashboard, `web/`) · **Language:** Python (discord.py 2.3+) · **Storage:** SQLite (`user_records.db`) + JSON files, PII encrypted via Fernet

## What This Bot Is For

This is the main server's bot — the one that greets new members, decides whether they're a
Student or a Guest, enforces the rules, runs the varsity/JV esports team registration
pipeline, hands out temporary voice channels, and keeps a constant eye on the arena's PC
status through GGLeap. It's also the only bot that can optionally run **in the same process**
as the web dashboard (`run_combined.py`), which is worth understanding before you go looking
for "why are there two ways to start this."

---

## 4.1 Three Ways to Start This Bot

| Entry point | What it does |
|---|---|
| `main.py` | The bot, standalone. This is what `start_bot.bat` runs. |
| `run_combined.py` | Runs the bot **and** the Flask web dashboard together — the dashboard runs on a background thread while the bot owns the main async event loop. Useful for simpler single-process deployments. |
| `master_terminal.py` | A PyQt6 GUI that doesn't run the bot itself, but starts/stops/monitors it (and every other service) as a subprocess, with live CPU/RAM stats and an aggregated log viewer. |

There's also `intro_animation.py` — a purely cosmetic Matrix-style ASCII animation that plays
before the bot boots when launched through `Start LionServices.bat`. It has no functional
effect; it's there because it looks great on a big screen at the arena.

---

## 4.2 What Happens When a New Member Joins

This is the single most important workflow in the whole bot, so it's worth walking through
completely:

1. **`on_member_join`** fires immediately. If the new member happens to already be on the
   watchlist (see §4.6), an alert is logged/sent right away.
2. A welcome embed is posted to the onboarding channel with two buttons: **Student** and
   **Guest Access**. The message reference is kept in memory so it can be cleaned up later.
3. The join time is recorded to `data/join_times.json` — this matters because of what
   happens if they never finish setup (see §4.2.3).

### 4.2.1 Choosing "Student"
Opens `AccountSetupModal`: first name, in-game name (IGN), Purdue email (accepts either
`@purdue.edu` or `@pnw.edu`, normalized to one form), and an optional phone number
(auto-formatted to `XXX-XXX-XXXX`). On submit, the bot sets their nickname to
`"{first name} ({IGN})"`, swaps the Guest role for the Student role if they had one, and
sends a confirmation with a link to the official club signup page.

### 4.2.2 Choosing "Guest Access"
Opens `GuestAccessModal` (similar fields, plus a terms-acceptance checkbox). On submit, the
Guest role is granted and a **30-day countdown timer** starts, tracked in
`guest_times/{user_id}_guest_time.json`. A background job (`remove_expired_guests`) checks
every guest's timer and, once expired, DMs a warning and kicks them from the server. A guest
can check their own remaining time at any point with `/time`.

### 4.2.3 What If They Never Choose Either?
An hourly job (`registration_timeout_check`) looks at everyone still in `join_times.json` who
joined more than **4 days ago** without completing setup, and kicks them with the reason
"Having an Incomplete Account." This is intentionally generous — 4 days is enough time for
someone who's just busy, without leaving unverified accounts sitting around indefinitely.

---

## 4.3 Moderation & the AutoMod Bridge

`cogs/moderation.py` maintains a **three-tier flagged word system** in
`data/flagged_words.json`:

| Tier | What happens automatically |
|---|---|
| `bannable` | Instant ban |
| `kickable` | Instant kick |
| `warning` | DM notice only, no punitive action |

Beyond the bot's own detection, it also listens for **Discord's own native AutoMod**
firing (`on_automod_action`) — if Discord's built-in filter already blocked something and this
bot's own custom lists don't independently match it, the event still gets logged to the
database as an "AutoMod Flag" so staff have a complete picture either way. A background
sync (`utils/automod_sync.py`) pushes the three word tiers up to Discord's real AutoMod
configuration via its REST API, so the two systems stay in lockstep — editing the word list
with `/addword` or `/removeword` triggers this sync automatically.

Every moderation event of any kind — warning, kick, ban, AutoMod flag — is written to a
single SQLite table (`utils/db.py`'s `user_records` table: id, user_id, type, reason,
moderator, moderator_id, source, timestamp), which both this bot and the Nova dashboard read
from. `/warn`, `/kick`, `/ban`, `/mute`, and `/unban` are the manual commands; `/userinfo`
(security-code gated) shows a member's complete record, and `/download-transcript` exports
it as a plain text file.

---

## 4.4 Voice Channels — the Same Join-to-Create Pattern as BoilerCraftGG

`cogs/vc-system.py` implements the identical generator-channel concept described in
[Chapter 1 §1.4](01_boilercraftgg.md), but with an added **tryout** flavor
(`/setup_tryout_vc`) for esports tryout sessions specifically. `data/vc-generators.json`
tracks three sets: normal generators, tryout generators, and every currently-generated
channel (the source of truth for cleanup). `/list_vc_generators` shows the current
configuration to anyone.

---

## 4.5 Varsity & JV Team Registration

`views/varsity_view.py` runs a genuinely multi-step registration and approval pipeline:

1. An admin (or a staff member via the User Info panel's "Register Varsity" button) picks a
   player type — Varsity, JV, Substitute Varsity, or Substitute JV — for a target member.
2. That member gets a persistent DM prompt (`PersistentVarsityRegistrationView` — built with
   a fixed custom ID specifically so it keeps working even if the bot restarts between when
   the DM was sent and when they respond).
3. They fill out a multi-step form: game selection → game-specific details (rank, tracker
   link, etc.) → personal info (name, email, phone, PUID) → a final confirmation screen.
4. **All personal information is Fernet-encrypted** before it ever touches disk (see §4.7),
   stored per-user under `data/varsity_registrations/{discord_id}_varsity.json`.
5. An admin reviews it via `VarsityApproveView` — **Approve** adds them to the roster and
   queues the correct Discord roles; **Deny** removes the pending request and DMs a reason;
   **Request Changes** sends a follow-up form.

This same data (`data/teams.json`, `data/rosters.json`) is what powers Nova's Rosters page —
see [Chapter 6](06_nova_web_rosters_varsity.md) for the full multi-team assignment and
Discord-role-sync system built on top of it.

---

## 4.6 The Watchlist

A lightweight surveillance feature for keeping a closer eye on a specific member without
restricting them outright: adding someone to `data/watchlist.json` at a chosen alert level
(low = logged only, normal = logged + notified on notable events, high = immediate alert)
causes `on_message` and `on_voice_state_update` to log their activity and, depending on
level, ping staff in real time whenever they post a message or move between voice channels.

---

## 4.7 Encryption & Data Safety

Two library pieces are used everywhere sensitive data touches disk:

- **`utils/safe_json.py`** — every JSON read/write in this bot goes through a shared
  `threading.RLock()`-protected atomic-write helper. Critical files (`rosters.json`,
  `teams.json`, `watchlist.json`, `ticket_log.json`, `player_reports.json`) get an automatic
  `.bak` backup before every overwrite, and the loader will fall back to that backup if the
  primary file is ever found corrupted.
- **Fernet encryption** (`cryptography` library) protects all personally-identifiable
  varsity/roster data — email, phone, PUID, and similar fields are never stored in plain
  text. The key lives at `data/.roster_encrypt_key` and is auto-generated on first run;
  it's gitignored for exactly the reason you'd expect (see [Chapter 11](11_troubleshooting_and_operations_guide.md)).

---

## 4.8 GGLeap Integration (Arena PC Status & Game List)

Two small utility modules poll the arena's [GGLeap](https://ggleap.com) management platform
and post/maintain live Discord panels:

- **`utils/ggleap_status.py`** — polls `machines/get-all`, filters out Stage PCs
  (varsity-only) and virtual machines, and posts a live-updating "Available / In Use / Off"
  panel per PC (formatted as friendly names like `Island1S2`).
- **`utils/ggleap_games.py`** — polls the enabled apps/games list and posts an alphabetized,
  browsable panel with a **"➕ Request a Game"** button linking to a request form.

Both use their own separate GGLeap API tokens (`GGLEAP_AUTH_TOKEN_STATUS` /
`GGLEAP_AUTH_TOKEN_GAMES`). The web dashboard has its own, much more elaborate GGLeap
integration for the physical kiosks and PC-lock automation — see
[Chapter 9](09_arena_kiosk_system.md), which also explains the shared-cache system that
prevents these separate consumers from accidentally exceeding GGLeap's daily API quota.

---

## 4.9 Ticket System

`views/ticket_view.py` follows the exact same panel → category dropdown → modal → private
channel → transcript-on-close pattern described for BoilerCraftGG in
[Chapter 1 §1.5](01_boilercraftgg.md), with support categories tailored to this server
(Discord/Minecraft/Clubs/Arena PCs/Varsity/Other) — picking "Arena PCs" additionally pings
the Technician role.

---

## 4.10 Slash Commands Reference

### General (Everyone)

| Command | What it does |
|---|---|
| `/ping` | Reports the bot's current latency to Discord, in milliseconds |
| `/about` | Shows a short embed describing the bot's purpose and creator |
| `/club` | Posts a link to the official PNW Esports Club signup page |
| `/arena-hours` | Displays the arena's current weekly open/close schedule |
| `/help` | Lists every available command, grouped by category |
| `/join-mc-server` | Shows how to connect to the linked Minecraft server (see [Chapter 1](01_boilercraftgg.md)) |
| `/time` | Shows your own remaining Guest-access countdown, if you're a Guest |
| `/serverinfo` | Shows member/channel/role counts and other server statistics |

### Administrator Only

| Command | What it does |
|---|---|
| `/force-setup-user <user>` | Re-sends the Student/Guest onboarding prompt to a specific member (useful if they dismissed it or their DMs were closed the first time) |
| `/set-activity <text>` | Overrides the bot's Discord status text (passcode-gated, see below) |
| `/reset-activity` | Clears the override and restores the automatic arena open/closed status (passcode-gated) |
| `/restart_service` | Cleanly restarts the bot process (passcode-gated) |
| `/stop-service` | Shuts the bot down, with a confirmation prompt first (passcode-gated) |
| `/clear <amount>` | Bulk-deletes up to 100 recent messages from the current channel |
| `/warn <user> <reason>` | Issues a warning: DMs the user, logs it to `#lionbyte-logs`, and adds a record to their moderation history |
| `/kick <user> <reason>` | Kicks a member, with the same DM + logging + record behavior as `/warn` |
| `/ban <user> <reason>` | Bans a member, with the same DM + logging + record behavior |
| `/unban <user_id>` | Unbans a user by their Discord ID (they've already left, so a mention won't work) |
| `/mute <user> <duration_minutes> [reason]` | Applies a Discord timeout for the given number of minutes |
| `/announce <channel> <message>` | Posts a formatted announcement embed to a channel, pinging the Student role |
| `/lock <channel>` / `/unlock <channel>` | Disables/restores `@everyone`'s ability to send messages in a channel |
| `/setup-tickets` | Deploys the persistent support-ticket panel to the current channel |
| `/setup_guest_transfer <channel>` | Posts a permanent "Migrate to Student" button for guests ready to convert |
| `/setup_reaction_role <channel> <message_id> <emoji> <role>` | Attaches a new emoji → role mapping to an existing message |
| `/setup_vc_generator <voice_channel> <category>` | Registers a Join-to-Create voice channel generator (see [§4.4](#44-voice-channels--the-same-join-to-create-pattern-as-boilercraftgg)) |
| `/setup_tryout_vc <voice_channel> <category>` | Same as above, but flagged specifically for esports tryout sessions |
| `/list_vc_generators` | Shows every currently configured voice-channel generator |
| `/force-register-all` | DMs the Student/Guest onboarding prompt to every unregistered, non-bot member at once (rate-limited to 2 seconds per DM) |
| `/download-transcript <user>` | Exports a member's full moderation history as a plain `.txt` file |
| `/admin-help` | Shows a paginated reference of every admin-only command |
| `/say <message>` | Makes the bot repeat a message verbatim in the current channel |
| `/userinfo <user>` | Shows a member's complete profile: identity, moderation history, guest timer, varsity status (passcode-gated) |
| `/blacklist-tickets <user>` / `/whitelist-tickets <user>` | Blocks or re-allows a user from opening new support tickets |
| `/addword <word> <tier>` / `/removeword <word>` | Adds/removes a word from the 3-tier flagged-word list (see [§4.3](#43-moderation--the-automod-bridge)), and syncs it to Discord's native AutoMod |

> `/set-activity`, `/restart_service`, and `/stop-service` additionally require passing a
> security-code modal (`SECURITY_CODE` env var, default `146332`) — a second layer of
> protection on top of the Administrator permission check for the most destructive actions.

---

## 4.11 Data Files at a Glance

| File | Contains |
|---|---|
| `data/bot_status.json` | Live latency/guild/member counts — read by Nova |
| `data/bot.pid` | Process ID, used for clean stop/restart from the dashboard |
| `data/members_cache.json` / `channels_cache.json` | Cached Discord state for Nova |
| `data/vc-generators.json` / `vc_live_cache.json` | Voice-channel generator config + live status |
| `data/watchlist.json` | Watched users + activity log |
| `data/join_times.json` | Tracks incomplete onboarding for the 4-day kick |
| `data/moderation_queue.json` / `bot_control.json` / `discord_notification_queue.json` | Nova → bot task queues |
| `data/live_notifications.json` | Dashboard bell notifications |
| `data/reaction_roles.json` | Emoji → role mappings |
| `data/ticket_log.json` | Open/closed/blacklisted tickets |
| `data/teams.json` / `rosters.json` | Varsity team + player data (PII encrypted) |
| `user_records.db` | Every moderation record ever issued |
