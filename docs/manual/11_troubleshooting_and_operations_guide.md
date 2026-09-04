# Chapter 11: Troubleshooting & Operations Guide

This chapter is the one to open first when something's actually broken. It covers how to
start and stop every service correctly, a complete settings glossary so you know what every
config key actually controls, and a running list of every known gotcha this project has hit
in production along with the fix — written so the *next* time it happens, you recognize it
immediately instead of re-diagnosing from scratch.

---

## 11.1 Starting Everything

The recommended way to start the whole suite is a single double-click:

```
LionByteGG\Start LionServices.bat
```

It's **single-instance guarded** — before doing anything, it checks whether port 5000 is
already listening (i.e., Nova is already running) and refuses to double-launch the entire
suite if so. When it does run, it launches all six pieces in this order, each minimized:
LionByteGG bot → LionShiftGG bot → BoilerCraftGG bot → LionBeatsGG bot → Lavalink → Nova web
dashboard — then finally opens the **Master Terminal** GUI for ongoing monitoring.

### Starting One Service at a Time

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
pieces at once without six separate terminal windows open.

---

## 11.2 Stopping Everything

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

## 11.3 Restarting After a Code Change

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

## 11.4 Known Gotchas & Their Fixes

### "Login keeps bouncing me back to the login page"
**Cause:** two `run.py` processes are both bound to port 5000 and fighting over sessions.
**Fix:** `run.py` now auto-kills any other `run.py` instance on every launch, but if it ever
recurs, confirm with the PowerShell command in §11.2 that exactly one process is running.

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

---

## 11.5 Settings Glossary

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

---

## 11.6 The Shared Data Directory Map

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

## 11.7 Encryption & Personal Data

Both the roster PII (emails, phone numbers, PUIDs) and the arena sign-in PII (names, emails)
are Fernet-encrypted using the **same key**, stored at `data/.roster_encrypt_key`
(gitignored — never commit it). As of the project's PII-hardening pass, the standing rule is:
**no plaintext personal data should ever exist in a plain JSON file anywhere in this
project.** If you ever find one, treat it as a regression and fix it immediately, either by
encrypting the field or moving that data into SQLite.

---

## 11.8 Quick Reference — Ports

| Service | Port |
|---|---|
| Nova web dashboard | `5000` (HTTP, served by waitress) |
| Lavalink audio server | `2333` |
| LionBeatsGG REST API | `3847` |

---

## 11.9 Where to Go From Here

If you've read this whole manual and still can't find your answer, the next-best places to
look are: the relevant bot's own cog/util source file (this manual tells you exactly which
file to open for almost every feature), the unified Activity Log inside Nova
(`/logs` — it records who did what and when for nearly everything), and the
[docs/NOVA_COMPLETE_GUIDE.md](../NOVA_COMPLETE_GUIDE.md) companion document for a friendlier,
narrative walkthrough of daily usage.
