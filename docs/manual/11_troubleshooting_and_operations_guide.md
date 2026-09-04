# Chapter 11: Troubleshooting & Operations Guide

This chapter is the one to open first when something's actually broken. It covers how to
start and stop every service correctly, a complete settings glossary so you know what every
config key actually controls, and a running list of every known gotcha this project has hit
in production along with the fix — written so the *next* time it happens, you recognize it
immediately instead of re-diagnosing from scratch.

---

## 11.1 Starting Everything

> **The one command to remember: `LionByteGG\Start LionServices.bat`.** This is the
> supported, correct way to start the entire suite — every bot, Lavalink, and the Nova web
> dashboard — with one double-click. Don't start the six pieces individually unless you have
> a specific reason to (e.g. only one bot crashed and the rest are fine); starting everything
> through this one script is faster, safer, and guarantees the right order.

Double-clicking `LionByteGG\Start LionServices.bat` does the following, in order:

1. **Checks port 5000 first** (the single-instance guard) — if Nova is already listening,
   it refuses to launch a second copy of everything and just tells you the services are
   already running. This prevents the single most common self-inflicted problem in this
   whole project: two copies of the same service fighting each other.
2. Plays a short intro animation, then launches all six pieces **in this order**, each
   minimized to the taskbar: **[1/6]** LionByteGG bot → **[2/6]** LionShiftGG bot →
   **[3/6]** BoilerCraftGG bot → **[4/6]** LionBeatsGG bot → **[5/6]** Lavalink →
   **[6/6]** Nova web dashboard.
3. Opens the **Master Terminal** GUI last, once everything else is up, so you have one place
   to watch all six services at a glance.

### Starting One Service at a Time

Only do this if you specifically need to bring back a single service that crashed while
everything else is healthy:

| Service | Script |
|---|---|
| LionByteGG bot | `LionByteGG\start_bot.bat` |
| LionShiftGG bot | `LionShiftGG\start_bot.bat` |
| BoilerCraftGG bot | `BoilerCraftGG\start.bat` |
| LionBeatsGG bot + Lavalink | `LionBeatsGG\start-all.bat` |
| Nova web dashboard (production) | `cd LionByteGG\web` then `python run.py --production` |

### The Master Terminal

`LionByteGG\master_terminal.py` is a PyQt6 GUI that doesn't replace the scripts above — it
wraps them, giving you one window with a colored status card per service, live CPU/RAM/disk
usage, and a single aggregated log feed. It's the easiest way to keep an eye on all six
pieces at once without six separate terminal windows open, and it's also the fastest way to
restart just one misbehaving service without touching the other five.

---

## 11.2 Auto-Start on Machine Boot

The machine that physically hosts LionByteGG (the on-site server/laptop running all six
services) is configured to **automatically launch `Start LionServices.bat` when Windows
starts up** — normally via a shortcut in the Windows Startup folder, or a Task Scheduler
entry set to run at logon/boot. In everyday operation, this means the whole suite comes back
online by itself after a normal Windows restart or a power outage, with no one needing to
manually double-click anything.

**What to check if auto-start doesn't seem to have worked:**
- Confirm the machine actually finished booting all the way to the desktop — the script
  can't run before Windows has logged in.
- Check the Windows **Startup folder** (`shell:startup` in the Run dialog) for a shortcut to
  `Start LionServices.bat`, or open **Task Scheduler** and look for a task pointing at that
  same script, set to trigger "At log on" or "At startup." If the shortcut/task is missing
  or disabled, that's why nothing launched — re-create or re-enable it, then just run the
  script manually for that session.
- If in doubt, just double-click `Start LionServices.bat` yourself — it's completely safe to
  run manually at any time; the single-instance guard means it will simply refuse to start a
  second copy if auto-start already succeeded.

---

## 11.3 If Something Goes Wrong: The Recovery Ladder

When a service — or the whole machine — stops responding, work through these steps **in
order**, starting with the least disruptive:

1. **Check the Master Terminal first.** If only one service shows as down, restart just
   that one from there rather than touching anything else.
2. **Re-run `Start LionServices.bat`.** If it says everything is already running but
   something clearly isn't working right, close the misbehaving service's window (or all of
   them via the Master Terminal) and run the script again.
3. **If that doesn't resolve it, restart the physical machine.** For **unforeseen
   circumstances** — a genuinely stuck process, a Windows-level hang, or anything the steps
   above didn't fix — a full restart of the host machine is the most reliable recovery.
   Auto-start (§11.2) will bring everything back up again once it reboots.
   > **Make sure the machine is connected via a wired Ethernet cable (not Wi-Fi) before and
   > after the restart.** The host machine's network configuration
   > (`set_static_ip.bat`, at the repo root) assigns a **static IP address specifically to
   > the "Ethernet" network adapter** — not Wi-Fi. If the machine reconnects over Wi-Fi
   > instead, it won't have that static IP, and anyone relying on the known LAN address to
   > reach Nova (or a kiosk relying on a fixed hostname/IP) will suddenly be unable to
   > connect. A wired Ethernet connection is what gives this whole setup its best, most
   > consistent experience.
4. **If a restart still doesn't fix it,** try these, roughly in order of how disruptive they
   are:
   - **A full shutdown and cold boot**, not just a restart — occasionally a restart alone
     doesn't clear a truly stuck driver or network state, while a complete power-off does.
   - **Re-run `set_static_ip.bat`** (as Administrator) if the machine seems to have the wrong
     IP address after reconnecting — this re-applies the static IP/DNS configuration to the
     Ethernet adapter.
   - **Check for a port conflict.** If Nova refuses to start at all, confirm nothing else on
     the machine is already using port 5000 (see the single-instance guard note in §11.1) —
     use the PowerShell command in §11.4 to check for stray `python.exe` processes.
   - **Check the physical network, not just the machine.** If the machine itself looks
     healthy but nothing can reach it, check the Ethernet cable is fully seated, and check
     whether the switch/router it's plugged into needs a power cycle too — not every
     connectivity problem is the host machine's fault.
   - **As an absolute last resort**, reboot the router/network switch the host machine is
     connected to, then the host machine again, in that order.

---

## 11.4 Stopping Everything

| Service | Script |
|---|---|
| LionByteGG bot | `LionByteGG\stop_bot.bat` |
| LionShiftGG bot | `LionShiftGG\stop_bot.bat` |
| BoilerCraftGG bot | `BoilerCraftGG\stop_bot.bat` |
| LionBeatsGG bot + Lavalink | `LionBeatsGG\stop-all.bat` |
| Nova web dashboard | `LionByteGG\stop_website.bat` |
| Master Terminal | `LionByteGG\stop_master_terminal.bat` |

If a script ever fails to find the right process, the manual fallback for Nova specifically
is:

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*run.py*' } |
  ForEach-Object { taskkill /F /PID $_.ProcessId }
```

---

## 11.5 Restarting After a Code Change

This is the single most common source of "I fixed it but it's still broken" confusion, so
memorize this rule: **Nova runs in production mode with no hot-reload.** Editing `app.py` or
any file in `web/templates/` does **nothing** until you restart the Nova process. The
Discord bots are the same — a cog edit needs either a bot restart, a targeted `/reload`
command (where available), or the dashboard's queued restart feature to actually take
effect.

On top of that, your **browser** can cache templates, JavaScript, and CSS. After restarting
the server, hard-refresh with **Ctrl+F5** before concluding a fix didn't work. The one
exception: Nova's static JavaScript files (like the diagnostics console) are served directly
and only need a browser hard-refresh, not a server restart, to pick up changes.

---

## 11.6 Known Gotchas & Their Fixes

### "Login keeps bouncing me back to the login page"
**Cause:** two `run.py` processes are both bound to port 5000 and fighting over sessions.
**Fix:** `run.py` now auto-kills any other `run.py` instance on every launch, but if it ever
recurs, confirm with the PowerShell command in §11.4 that exactly one process is running.

### "A user's bot-switcher dropdown routes them to the wrong section, or nowhere"
**Cause:** `smart_landing()` requires each section's own specific "main dashboard"
permission (`page.dashboard`, `page.boilercraft`, `page.shift_dashboard`,
`page.music_dashboard`) — having every individual page permission for a section isn't
enough if this one key is missing.
**Fix:** grant the missing key to their group in `/admin`.

### "I edited a preset group's permissions in /admin and they reverted after a restart"
**Cause (historical, already fixed):** the old seeding logic used to hard-reset every preset
group back to its factory default on every server startup.
**Fix:** seeding is now non-destructive — it only ever touches a group with zero permissions
or that doesn't exist yet. If you ever see this behavior again, it's a real regression worth
reporting immediately.

### "I added a new Settings field and it shows correctly in the live preview but doesn't actually save"
**Cause:** `POST /api/arena/config` (and similar save handlers) rebuild nested config objects
from a **hardcoded field whitelist** before writing to disk — a new field only shows up in
the *read* path until the *write* path's whitelist is updated too.
**Fix:** when adding a new nested config field, update both the read-side normalizer
function **and** the save handler's whitelist. Always verify by re-fetching the config after
saving and diffing it against what you expected.

### "A multi-team coach or captain isn't getting Discord roles for every team they're on"
**Cause:** role-sync code that only reads the legacy singular `team_id` field instead of the
full `team_ids` array.
**Fix:** confirm the sync logic loops the entire array, not just the first team.

### "PC screen locks won't engage even with the toggle flipped on"
**Cause:** `pc_lock_enabled` is actually `false` in `arena_kiosk_config.json` — a stale save
can leave this mismatched from what the UI shows.
**Fix:** check the config file directly, or just re-flip the toggle in Nova → Arena →
Controls → PC Screen Locks.

### "GGLeap calls start failing with 429 errors / kiosks show '0 machines'"
**Cause:** the daily 10,000-call quota is exhausted, almost always because a new feature
added its own independent polling loop instead of using the shared cache (this has happened
once already — see [Chapter 9 §9.2](09_arena_kiosk_system.md#92-live-pc-status--where-the-numbers-actually-come-from)).
**Fix:** check `GET /api/arena/ggleap-usage` for today's count; if it's near the cap, set
`ggleap_paused: true` temporarily to stop the bleeding, then audit for a redundant polling
loop.

### "The sign-in guard is blocking legitimate repeat check-ins"
**Cause:** `cooldown_minutes` / `max_per_day` set too aggressively.
**Fix:** the tested-safe defaults are `cooldown_minutes: 0`, `max_per_day: 0`,
`max_active_pc: 1`. Only raise these deliberately, and test with a genuine repeat check-in
immediately afterward.

### "A big PowerShell text edit corrupted special characters (em-dashes, etc.) in a Python file"
**Cause:** PowerShell's `Get-Content`/`Set-Content`, even with `-Encoding UTF8` specified in
some versions, can silently mangle multi-byte UTF-8 characters (em-dash, en-dash, ellipsis,
middle-dot, × sign) into invalid single-byte characters when piping a large source file
through them.
**Fix:** never pipe a large source file through PowerShell's text cmdlets for bulk edits —
do binary-safe edits in Python instead (open in `'rb'`/`'wb'` mode). Always run
`python -c "import app"` immediately after any large PowerShell-based edit to app.py to
catch a `UnicodeDecodeError` before it causes a confusing downstream failure.

### "The host machine reconnected to the network but Nova/the kiosks aren't reachable at the usual address"
**Cause:** the machine came back up on Wi-Fi instead of its wired Ethernet connection, so the
static IP configured by `set_static_ip.bat` (which targets the "Ethernet" adapter
specifically) never got applied.
**Fix:** plug the Ethernet cable back in and reconnect it that way — see §11.3, step 3.

---

## 11.7 Settings Glossary

### `arena_kiosk_config.json` (in the shared data directory)
| Key | Meaning |
|---|---|
| `arena_name` | Display name shown on kiosk screens |
| `welcome_message` | The big welcome text on the attract screen |
| `day_hours[7]` | Per-weekday `{open, start, end}` — replaces the legacy single open/close time |
| `announcement` | `{enabled, text, color, scroll}` — the scrolling/static banner |
| `signin_guard` | `{enabled, cooldown_minutes, max_per_day, max_active_pc, ban_message}` |
| `pc_lock_enabled` | Master switch for the PC screen-lock automation loop |
| `pc_hold_minutes` | How long a kiosk reservation holds a PC before release/re-lock |
| `ggleap_paused` | Emergency kill-switch — stops all GGLeap calls when `true` |
| `live_cleared_at` | Timestamp powering the Live Feed's "Clear Feed" cutoff |
| `kiosks` | Dict of `kiosk_id → {label, room, type}` |

### Other config files
| File | Purpose |
|---|---|
| `team_role_settings.json` | Discord role ID mapping for varsity/JV/captain/coach sync ([Chapter 6](06_nova_web_rosters_varsity.md)) |
| `LionShiftGG/settings.json` | Shift reminder/late-alert timing, form URLs ([Chapter 3](03_lionshiftgg.md)) |
| `BoilerCraftGG/data/bot_config.json` | Ticket panel channel, staff role, FAQ channel, support categories ([Chapter 1](01_boilercraftgg.md)) |
| `flagged_words.json` (LionByteGG bot) | The 3-tier bannable/kickable/warning word lists, synced to Discord's native AutoMod |
| `set_static_ip.bat` (repo root) | Assigns the host machine's Ethernet adapter a fixed IP + DNS servers, so its LAN address never changes |

---

## 11.8 The Shared Data Directory Map

Everything lives under `LionByteGG\data\` (referred to as `DATA_DIR` in the code) — this is
**not** the same folder as `LionByteGG\web\data\`, which is a separate, web-only data store
used for a few equipment/auth features.

| Direction | Files |
|---|---|
| Bot → Web (status/cache) | `bot_status.json`, `members_cache.json`, `channels_cache.json`, `vc_live_cache.json`, `live_notifications.json` |
| Web → Bot (task queues) | `discord_notification_queue.json` (LionByteGG bot), `lionshift_notification_queue.json` (LionShiftGG bot), `moderation_queue.json`, `bot_control.json` |
| BoilerCraft (isolated) | `BoilerCraftGG/data/dashboard_commands.json` — its own separate queue, not shared |
| LionBeatsGG (not file-based) | Talks over its own REST API on `localhost:3847` instead of shared files |

---

## 11.9 Encryption & Personal Data

Both the roster PII (emails, phone numbers, PUIDs) and the arena sign-in PII (names, emails)
are Fernet-encrypted using the **same key**, stored at `data/.roster_encrypt_key`
(gitignored — never commit it). As of the project's PII-hardening pass, the standing rule is:
**no plaintext personal data should ever exist in a plain JSON file anywhere in this
project.** If you ever find one, treat it as a regression and fix it immediately, either by
encrypting the field or moving that data into SQLite.

---

## 11.10 Quick Reference — Ports

| Service | Port |
|---|---|
| Nova web dashboard | `5000` (HTTP, served by waitress) |
| Lavalink audio server | `2333` |
| LionBeatsGG REST API | `3847` |

---

## 11.11 More Gotchas Worth Knowing

A few additional, smaller lessons that don't fit neatly into §11.4 but are worth remembering:

### "A varsity registration DM never got answered, and the recruit says they finished it"
Almost always the schedule-photo step — see
[Chapter 4 §4.5.4](04_lionbytegg_bot.md#454-step-5--the-schedule-photo). The recruit has
only **180 seconds** after submitting the third modal to DM the bot a photo of their class
schedule; if they miss that window, the whole registration silently fails to save anywhere.
There's no partial-save and no automatic retry — just send them a brand-new registration
link and remind them to have their schedule photo ready *before* they start this time.

### "Two different service scripts both seem to think a bot is/isn't running"
This can happen if a bot process was killed abruptly (e.g., Task Manager, a power loss)
rather than through its own stop script — the PID file it wrote on startup (`data/bot.pid`
for LionByteGG) can go stale. Prefer the provided stop scripts over manually killing
processes whenever possible, and if you do have to kill something manually, expect to
double-check with the Master Terminal or a process list afterward.

### "A CSV export (rosters, BoilerCraft analytics) opens with garbled special characters in Excel"
This is a classic UTF-8-without-BOM-vs-Excel issue, not a bug in the export itself — if you
hit it, open the CSV in a text editor first to confirm the underlying data is correct UTF-8,
then import it into Excel via Data → From Text/CSV (which lets you explicitly pick UTF-8)
rather than double-clicking to open it directly.

### "I want to test a change without affecting real production data"
There's no built-in "staging mode" in this system — everything reads and writes the same
live data files and databases. The safest way to test a risky change is on a separate clone
of the repository pointed at its own `data/` folder, never directly against the arena's live
`data/` directory.

---

## 11.12 Where to Go From Here

If you've read this whole manual and still can't find your answer, the next-best places to
look are: the relevant bot's own cog/util source file (this manual tells you exactly which
file to open for almost every feature), the unified Activity Log inside Nova
(`/logs` — it records who did what and when for nearly everything), and the
[docs/NOVA_COMPLETE_GUIDE.md](../NOVA_COMPLETE_GUIDE.md) companion document for a friendlier,
narrative walkthrough of daily usage. And remember the golden rule that applies to nearly
every "it's not working" report in this whole system: **restart the relevant service, hard
refresh the browser, and check the Activity Log** before assuming something is broken at a
deeper level — the overwhelming majority of reported issues in this project's history have
turned out to be exactly one of those three things.
