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

`views/varsity_view.py` runs a genuinely multi-step registration and approval pipeline —
this is one of the most elaborate single workflows in the whole bot, so this section walks
through it start to finish, including **every single question that's asked by default** and
exactly how to change any of them.

### 4.5.1 How a Registration Gets Started

There are two ways a registration begins:

1. **An admin or staff member initiates it manually** — either directly with the
   `PlayerTypeSelectView` dropdown (Varsity / JV / Substitute Varsity / Substitute JV), or via
   the "Register Varsity" button inside the User Info panel (`cogs/userinfo.py`'s
   `ClearRecordView`, see [§ moderation](#43-moderation--the-automod-bridge)).
2. **A staff member sends it from Nova** — clicking "Send Registration" on the Rosters page
   (see [Chapter 6 §6.3](06_nova_web_rosters_varsity.md#63-the-registration--approval-pipeline))
   queues a `send_varsity_registration` notification, which the bot picks up and DMs to the
   target member on the admin's behalf. In this case the "admin" on record is technically the
   **bot itself** (its own user ID is stored as `admin_user`), which matters later — see
   §4.5.5.

Either way, the target member receives a DM containing a **persistent "Start Registration"
button** — persistent meaning it uses a fixed `custom_id`
(`PersistentVarsityRegistrationView`) so it keeps working even if the bot restarts between
the moment the DM was sent and the moment the recruit actually clicks it. Without this, a bot
restart at the wrong moment would silently break every pending registration link ever sent.

### 4.5.2 Step 1 — Choosing a Game

The recruit sees a dropdown (`GameSelectView`) populated live from `data/esports_games.json`
(up to Discord's 25-option select limit) — whatever games are currently configured in Nova's
Settings page appear here automatically, with no code change required. Selecting a game
stores it as `"Primary Game Title"` in an in-memory dict on the bot
(`bot.varsity_registrations[user_id]`) that accumulates every answer as the recruit
progresses through the three modals below.

### 4.5.3 Steps 2–4 — The Three Modals (Every Default Question, In Order)

Discord limits a single modal to **5 text fields**, which is exactly why this registration
is split into three separate modals rather than one long form. Here is the complete,
unabridged list of every question asked by default, in the exact order they're presented:

**Modal 1 — "Personal Information"**

| # | Field label | Placeholder / hint shown | Required? |
|---|---|---|---|
| 1 | Full Name | *e.g. John Smith* | Yes |
| 2 | Purdue Email Address | *e.g. smith123@purdue.edu* | Yes |
| 3 | Personal Email Address | *e.g. johnsmith@gmail.com* | Yes |
| 4 | Phone Number | *e.g. 123-456-7890* | Yes |
| 5 | Purdue ID (PUID) | *e.g. 0012345678* | Yes |

**Modal 2 — "Academic & Player Details"**

| # | Field label | Placeholder / hint shown | Required? |
|---|---|---|---|
| 6 | Current GPA | *Minimum 2.5 GPA required (e.g. 3.2)* | Yes |
| 7 | Home Town/City (State) | *e.g. Hammond, IN* | Yes |
| 8 | Year in School | *e.g. Freshman, Sophomore, Junior, Senior* | Yes |
| 9 | Major/Field of Study | *e.g. Computer Science* | Yes |
| 10 | Jersey Details (Size & Name) | *e.g. Large - SMITH* (multi-line field) | Yes |

**Modal 3 — "Gaming Information"**

| # | Field label | Placeholder / hint shown | Required? |
|---|---|---|---|
| 11 | In-Game Name (IGN) | *e.g. ProGamer123* | Yes |
| 12 | Current Rank | *e.g. Diamond 2, Immortal, Masters, Grand Champion* | Yes |
| 13 | Primary Role in Game | *e.g. DPS, Support, Tank, Jungle, ADC, Duelist* | Yes |
| 14 | Stats Tracker Link | *e.g. tracker.gg/valorant/profile/...* | Yes |
| 15 | Additional Notes | *Anything else we should know?* (multi-line field) | **No** — the only optional question in the whole form |

Between each modal, the recruit sees a short "great, click to continue" button
(`VarsityContinueView`, then `VarsityFinalContinueView`) rather than the next modal opening
automatically — Discord requires a fresh button interaction to open a *new* modal, you can't
chain modal → modal directly.

> **The "GPA minimum 2.5" and every other requirement-style hint is a soft ask, not an
> enforced rule.** Discord modal fields can only validate length and whether a value was
> entered at all — there's no server-side numeric or format validation on GPA, phone number,
> tracker link, etc. A reviewing admin (or coach) is expected to catch anything that looks
> wrong during the approval step in §4.5.6.

### 4.5.4 Step 5 — The Schedule Photo

After the third modal is submitted, the recruit is **not done yet** — a fourth, non-modal
step follows: the bot asks them to send a **photo of their class schedule** as a direct
message attachment, and literally waits for it (`bot.wait_for('message', ...)`) with a
**180-second timeout**. If they don't send an image within 3 minutes, this wait silently
times out and the registration is never finalized or saved anywhere — nothing gets posted to
the review channel and nothing is written to disk. If a recruit reports "I filled out the
form but nothing happened," this is almost always the cause: they either took too long to
send the schedule photo, or never sent one at all. There is currently no reminder or retry
mechanism for this specific step — if it times out, they need to be sent a fresh
registration link and start over from §4.5.1.

Once an image is received, it's downloaded and saved **permanently** to
`data/user_records/schedule_images/` (a subfolder inside `USER_RECORDS_DIR`), named
`{discord_id}_{timestamp}_{index}.ext`, and the original Discord CDN URL is also kept as a
backup reference in case the local file is ever lost.

### 4.5.5 Where the Data Goes

Once the schedule photo comes in, everything collected across all three modals plus the game
selection is bundled into one record and:

1. **Saved to disk** at `data/user_records/varsity_registrations/{discord_id}_varsity.json` —
   an array (a person can have more than one registration attempt over time), each entry
   shaped like:
   ```json
   {
     "type": "VarsityRegistration",
     "status": "Pending",
     "data": { "Full Name": "...", "Purdue Email": "...", "...": "..." },
     "timestamp": "2026-09-04T18:22:00+00:00"
   }
   ```
2. **Posted to the `#varsity-registrations` review channel** as an embed with an
   Approve/Deny button attached (`VarsityApproveView`), so any admin watching that channel
   can act on it immediately without needing to be the specific person who sent the
   original DM.
3. **Also DMed directly to whichever admin initiated it** — *unless* the registration was
   sent from Nova (in which case the "admin" on record is the bot itself, so this DM step is
   skipped — the review channel post and the Nova dashboard are the only places to see it).
4. **A dashboard bell notification is queued** (`add_varsity_notification`) linking straight
   to `/varsity` in Nova.

The recruit gets one of two different confirmation messages depending on how their
registration started — a slightly warmer "the coaching staff will review your application"
message if it came from the website, or "please wait for approval from the recruiter" if an
admin sent it directly — a small but deliberate touch so the message always makes sense in
context.

### 4.5.6 Step 6 — Review & Approval

`VarsityApproveView` gives an admin three choices: **Approve** (adds the player to the
roster and queues the correct Discord role assignment — see
[Chapter 6 §6.2](06_nova_web_rosters_varsity.md#62-assigning-players-to-teams--and-how-discord-roles-stay-in-sync)
for exactly which roles that means), **Deny** (opens `VarsityDenyReasonModal` for a reason,
which gets DMed back to the recruit), or **Request Changes** (sends a follow-up prompt asking
them to re-submit specific information). Player types are always shown using friendly labels
— internally `varsity`/`jv`/`sub_varsity`/`sub_jv`/`coach` map to "Varsity" / "JV" /
"Substitute Varsity" / "Substitute JV" / "Coach" wherever they're displayed to a human.

### 4.5.7 How to Change the Registration Questions

**There is no admin UI or config file for this — the 15 questions above are hardcoded
Python code**, not data. To add, remove, reword, or reorder a question, a developer needs to
edit `LionByteGG/views/varsity_view.py` directly:

1. Find the relevant modal class — `VarsityRegistrationModal1`, `Modal2`, or `Modal3` — each
   one is a `discord.ui.Modal` subclass with up to 5 `discord.ui.TextInput` class attributes.
2. To add a question, add a new `discord.ui.TextInput(label="...", placeholder="...",
   required=True/False)` line — **but remember Discord hard-caps a single modal at 5 fields**,
   so if a modal is already full you'll need to either replace an existing question or add a
   brand-new fourth modal (which means adding one more "continue" button/view step, following
   the exact same pattern as the existing `VarsityContinueView` → `VarsityFinalContinueView`
   chain).
3. Update that modal's `on_submit()` method to save the new field into `reg_data` under
   whatever key name you want it stored as (this is the key that will show up in the JSON
   file and the review embed).
4. If you want the new answer visible to reviewers, also add a line to the relevant
   `embed.add_field(...)` call in `VarsityRegistrationModal3.on_submit()` (this is what
   actually builds the "📝 Registration Received" embed both admins and the review channel
   see) — an easy step to forget, which would leave the new answer saved to disk but
   invisible to anyone reviewing the application.
5. Restart the LionByteGG bot for the change to take effect — like everything else in this
   suite, there's no hot-reload for cog/view code (see [Chapter 11 §11.5](11_troubleshooting_and_operations_guide.md#115-restarting-after-a-code-change)).

> **A subtle existing quirk worth knowing if you go digging in this file:** Modal 1's
> `TextInput` variable is literally named `ign` even though it collects the PUID (`Purdue ID`),
> and Modal 3 *also* has a variable named `ign` that collects the actual in-game name. They're
> two separate class attributes on two separate modal classes, so there's no real bug — but
> if you're skimming the source and see `self.ign.value` twice, know that they mean two
> completely different things depending on which modal you're looking at.

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

---

## 4.12 Example Data Shapes

**A `user_records.db` row (as JSON, via `get_records()`)**
```json
{
  "user_id": "123456789012345678", "type": "Warning",
  "reason": "Spam in #general", "moderator": "StaffName", "moderator_id": "987...",
  "source": "discord", "timestamp": "2026-09-01T18:22:00+00:00"
}
```

**`data/watchlist.json`**
```json
{
  "123456789012345678": {
    "level": "high", "reason": "Suspected alt account of a banned user",
    "added_by": "StaffName", "added_at": "2026-08-20T00:00:00Z",
    "activity_log": [
      { "type": "message", "channel": "general", "preview": "first 100 chars of the message...", "timestamp": "2026-09-01T18:00:00Z" },
      { "type": "voice_join", "channel": "Lounge", "timestamp": "2026-09-01T18:05:00Z" }
    ]
  }
}
```

**`data/flagged_words.json` (the 3-tier moderation list)**
```json
{
  "bannable": ["slur1", "slur2"],
  "kickable": ["spam_phrase"],
  "warning": ["mild_word"]
}
```

**`data/vc-generators.json`**
```json
{
  "normal": [1403788867424747620],
  "tryout": [1403788867424747999],
  "generated": [1429893450811314257, 1429893450811399999]
}
```

---

## 4.13 Frequently Asked Questions

**"A new member never got the Student/Guest setup DM — what happened?"**
The onboarding prompt is posted as a channel embed in the onboarding channel (not a DM) with
buttons on it, so first check they didn't just miss the message in a busy channel. If the
embed itself is missing, check the bot actually has permission to post in that channel, and
check `data/join_times.json` to see if a join event was even recorded (if it wasn't, the bot
may have been offline at the exact moment they joined).

**"Someone completed setup but immediately got auto-kicked."**
This should only happen via `registration_timeout_check` (the 4-day incomplete-setup kick) —
check `data/join_times.json` doesn't still have a stale entry for them after they finished
onboarding; a record that isn't cleared properly could, in rare timing edge cases, still get
swept up in the next hourly check. In practice this is very rare since the entry is removed
the moment either modal is submitted.

**"How long does a Guest actually have before their access expires?"**
Exactly 30 days from when they picked "Guest Access," tracked per-user in
`guest_times/{user_id}_guest_time.json`. `/time` lets a guest check their own countdown at
any point, and a staff member can extend it by another 30 days from a member's profile in
Nova (`POST /api/guests/<id>/reset`) or cancel it early (`POST /api/guests/<id>/cancel`).

**"Can a Guest become a Student without waiting out their 30 days?"**
Yes — that's exactly what `/setup_guest_transfer`'s "Migrate" button and the general
Student/Guest setup flow are for; a Guest can convert to Student at any time, which removes
the Guest role and clears their expiring timer entirely.

**"Why did AutoMod ban someone before a human even saw the message?"**
Any word in the `bannable` tier of `data/flagged_words.json` triggers an automatic ban the
instant it's detected — by design, for the most severe category, there's no human-in-the-loop
delay. If a word shouldn't be that severe, move it down to the `kickable` or `warning` tier
with `/removeword` + `/addword`.

**"The bot's presence text is stuck on something weird and won't update."**
Check whether a custom override is currently active — `/set-activity` and Nova's Bot Activity
control both set a *manual override* that takes priority over the automatic arena
open/closed status. Run `/reset-activity` (or clear it from Nova) to hand control back to
the automatic arena-hours-based presence.
