# Nova & the LionByteGG Suite — Complete Guide
### Website, Permissions, Troubleshooting, Rules to Live By, and What Makes It Great

This is the master narrative guide to the LionByteGG ecosystem's website ("Nova") and how to
operate it safely. For an even deeper, chapter-by-chapter dive into every bot, command, and
route, see [docs/manual/](manual/00_index.md) (12 chapters). This document is the fast,
narrative companion: how things work, how to use them, what to never do, and why the whole
thing feels polished.

---

## 1. What Nova Is

**Nova** is the single web dashboard (Flask, served by waitress in production) that controls
**every** bot in the suite from one login:

| Bot | What it does | Nova section |
|---|---|---|
| LionByteGG (flagship) | Onboarding, moderation, varsity/JV teams, voice channels | Dashboard, Moderation, Users, Rosters, Varsity, Reaction Roles, VC System |
| BoilerCraftGG | Minecraft server + Discord verification | BoilerCraft dashboard |
| LionShiftGG | Arena shift scheduling for student workers | LionShift dashboard |
| LionBeatsGG | Music bot (proxied over its own REST API) | Music dashboard |
| Arena Kiosk system | Physical sign-in kiosks, PC booking/locking | Arena Staff |

One login, one sidebar, one permission system gates all of it. Nova runs at `http://127.0.0.1:5000`
by default.

> **To start everything — every bot, Lavalink, and Nova itself — always use
> `LionByteGG\Start LionServices.bat`.** One double-click launches all six services in the
> right order and opens the Master Terminal for monitoring. The host machine is also
> configured to run this same script automatically on startup, so a normal reboot brings
> the whole suite back by itself. See [docs/manual/11_troubleshooting_and_operations_guide.md](manual/11_troubleshooting_and_operations_guide.md)
> for the full startup/recovery guide, including what to do if something doesn't come back
> up on its own.

---

## 2. Logging In & Navigating

- Two kinds of accounts exist: **dashboard users** (created in `/admin`, belong to a permission
  group) and a **legacy admin login** (security-code based, full access to everything).
- After login you land on `/home`, which is smart — it looks at your permissions and drops you
  on the first page you're actually allowed to see, in this priority: LionByteGG → BoilerCraft
  → LionShift → LionBeats → Arena.
- The **bot-switcher dropdown** (top of sidebar) lets you jump between sections you have access
  to without logging out.
- The sidebar auto-collapses to a 72px icon rail below 1024px width and stays that way down to
  mobile widths — Nova is intentionally a **desktop-first** tool, not a responsive phone app.

---

## 3. Page-by-Page Walkthrough

### Core
- **Dashboard** — bot online/offline status, quick moderation stats, recent activity feed, a
  patch-notes banner, and a global search bar (searches members, records, guests, and varsity
  registrations at once).
- **Moderation** — search any user's record, issue warnings, remove specific past
  records, bulk actions, CSV export.
- **Users** — the full member directory: search, view a full profile (join date, roles,
  record summary, guest status, varsity status), send a DM, add a note.
- **Tickets** — every open/closed support ticket from Discord, with the ability to reply,
  assign staff, close, or blacklist a user from opening new ones.
- **Logs** — the unified activity log: every login, moderation action, admin change, and
  bot action in one filterable, exportable table.
- **Settings** — arena hours, esports game list, team→role mapping, flagged-word lists
  (bannable/kickable/warning tiers), bot presence text.
- **Analytics** — member counts, moderation totals, varsity approval breakdown, top roles.

### Rosters & Varsity
- **Rosters** — the team/player manager. Add/remove players, assign them to one or more
  teams, tag captains/coaches, track match stats and a leaderboard, send Discord role syncs,
  import/export CSV, and manage the whole varsity registration approval pipeline.
- **Varsity** — the registration approval queue (pending/approved/denied), separate from
  the full roster editor.

### Arena Staff
- **Live Feed** — real-time sign-ins as they happen at the physical kiosks.
- **Sessions** — a room map of every arena PC with live lock/unlock/power controls.
- **Kiosk Manager (Controls)** — everything about the physical kiosks: hours, announcement
  banner, sign-in anti-spam guard, PC screen-lock automation, add/remove kiosks, GGLeap API
  usage meter.
- **Activity** — full traffic analytics: heatmaps, busiest hours/days, top visitors, exportable.
- **Students** — a searchable profile for every guest who's ever signed in: visit history,
  staff notes, ban/watch status.
- **Incident Reports** — file and track behavioral incidents.
- **Inventory** — arena equipment checkout/checkin with QR-code self-service.

### Other Bot Dashboards
- **LionShift** — shift calendar, schedule creator, worker roster with live clock-in status,
  shift offers/trades/time-off approval queues, bot settings.
- **BoilerCraft** — Minecraft server status, ticket system, verified-player list, chat-monitor
  ("BoilerWatch") flagged-message log, member moderation, analytics export.
- **Music** — now-playing/queue control, play history, stats, quiz song management — this
  page is a live proxy into the LionBeatsGG bot's own REST API, not a separate data store.

---

## 4. The Permissions System (Read This Before Editing Anyone's Access)

Every dashboard user belongs to a **group** with a list of **permission keys**. There are
three kinds of keys:

- `section.NAME` — makes an entire bot's section appear in the sidebar at all (e.g.
  `section.arena`, `section.lionbyte`).
- `page.NAME` — makes one specific page's nav link appear and makes that route reachable
  (e.g. `page.rosters`, `page.arena_students`).
- `NAME.action` — a specific in-page capability, independent of just viewing the page
  (e.g. `arena.manage`, `moderation.warn`, `equipment.checkout`, `arena.ban`).
- `admin.panel` — the full bypass. Only give this to true administrators.

**A page permission alone often isn't enough.** Many features are deliberately split into
"can view" vs. "can act" so you can give someone read-only access. Examples:
- `page.arena_live` (view Live Feed) is separate from `arena.manage` (actually lock/unlock/
  check in a PC).
- `page.arena_students` (view student profiles) is separate from `arena.ban` (add someone to
  the watch/ban list) and `arena.students_manage` (delete a student's history).
- `page.arena_reports` (view incidents) is separate from `arena.reports_all` (see everyone's
  incidents, not just the ones you personally filed).

**The "landing page" gotcha:** every bot section needs its own main page permission
(`page.dashboard` for LionByteGG, `page.boilercraft` for BoilerCraft, `page.shift_dashboard`
for LionShift, `page.music_dashboard` for LionBeats) or the smart landing page and the
bot-switcher dropdown will silently fail to route that user into the section, even if they
have every other permission for it. If someone says "the section switch doesn't work for me,"
check for this first.

**Building a new custom group?** Start from the closest built-in preset (Student Workers,
Supervisors, etc.) in `/admin`, then add or remove individual keys. Preset groups only get
their default permissions auto-seeded once — if a preset group already has any permissions
saved, a server restart will **never** silently reset your customizations back to the preset.

---

## 5. Rules to Live By — Do This, Never Do That

These are hard-won lessons from real incidents in this project. Follow them exactly.

### ✅ Registrations & Bulk Sends
- **Only send ONE varsity registration DM to a person at a time.** Sending a second
  registration link to someone who already has a pending one creates duplicate/racing
  submissions and confuses the player about which link is current. Check their pending
  status in Rosters before clicking Send again.
- **Never fire off `/force-register-all` or a bulk DM more than once in a short window.**
  It already rate-limits itself (2s per DM) — spamming the button just queues duplicates.
- Wait for a `job_id`'s status to reach `completed` before starting another bulk operation
  of the same kind (role sync, bulk DM, registration send).

### ✅ Bots & Sync Processes
- **NEVER stop or restart a bot while a sync process is running** — this includes a Discord
  role sync (`/api/rosters/sync-roles/execute`), an AutoMod word-list sync, a bulk DM send, or
  `/force-register-all`. Killing the process mid-job leaves `job_progress.json` stuck at
  "in_progress" forever, can leave some Discord roles half-applied, and can burn GGLeap API
  quota retrying calls that never got a response.
- If a sync job looks stuck, let it finish or explicitly check its `job_progress.json` status
  before touching the bot process. When in doubt, wait it out.

### ✅ The Web Server
- Nova runs in **production mode with no hot-reload.** After editing `app.py` or any template,
  you MUST restart the server, or your changes simply won't appear.
- **Never run two `run.py` processes at once.** This is the #1 historical cause of "login keeps
  bouncing me back" bugs. `run.py` now auto-kills any other instance on launch, but if you ever
  see login issues, check `Get-CimInstance Win32_Process -Filter "Name='python.exe'"` for
  duplicates first.
- Hard-refresh (Ctrl+F5) the browser after a UI change — templates and static JS/CSS can be
  cached.

### ✅ Data & PII
- **Never hand-edit JSON data files while the matching bot or server is running.** A bot
  loop can overwrite your edit mid-write, or you can corrupt a file it's mid-read on. Use the
  Nova UI or a bot command instead.
- Every piece of personal data (names, emails, PUIDs) in this project is encrypted at rest
  (Fernet) inside SQLite — arena sign-ins, student notes, incident descriptions, and roster
  PII all go through `data/.roster_encrypt_key`. If you ever see plaintext PII show up in a
  new plain JSON file, that's a regression — encrypt it or move it to SQLite instead.
- `.gitignore` is intentionally aggressive about excluding student data, DBs, and secrets.
  **Never weaken it** to "make a commit go through" — fix the actual problem (usually: the
  file shouldn't have been created outside `data/` in the first place).

### ✅ Arena Kiosk & GGLeap
- **Don't lower the sign-in guard's `cooldown_minutes` / `max_per_day` below tested-safe
  values without a real re-entry test.** An earlier default of 15/8 accidentally blocked
  legitimate repeat check-ins; the safe defaults are `cooldown_minutes=0`, `max_per_day=0`,
  `max_active_pc=1`.
- **Don't manually unlock a PC from the GGLeap dashboard and expect the automation to leave
  it alone forever** — a human unlock is respected until that PC reboots, by design.
- Watch the **GGLeap API Usage** meter in Kiosk Manager. If it's climbing fast, check whether
  a new feature accidentally added its own independent polling loop instead of using the
  shared cache (`_ggleap_get_machines`) — this exact mistake once caused a full-day API outage.
- If you must temporarily stop all GGLeap calls (e.g. to save quota), use the `ggleap_paused`
  config flag — it's read live, no restart needed.

### ✅ Git & Deployment
- `.env` files, `*.db` files, and anything under `data/` are gitignored on purpose — never
  force-add them.
- Prefer small, well-described commits over one giant "misc fixes" commit when possible —
  but a single large commit after a long working session is fine as long as the message
  clearly summarizes what changed.

---

## 6. Troubleshooting Quick Reference

| Symptom | Likely Cause | Fix |
|---|---|---|
| Login keeps bouncing back to `/login` | Two `run.py` processes running | Kill duplicates, confirm exactly one python.exe running run.py |
| A user's section-switch / bot-switcher doesn't work | Missing that section's main `page.*` permission | Grant `page.dashboard` / `page.boilercraft` / `page.shift_dashboard` / `page.music_dashboard` as appropriate |
| Edited a group's permissions, they revert after restart | (Historical, fixed) preset seeding used to hard-reset groups | Already fixed — seeding is now non-destructive; if it recurs, check `_seed_preset_permissions()` |
| New nested Settings field shows in the live preview but doesn't save | The POST handler's field whitelist wasn't updated | Update BOTH the read-side normalizer and the save handler's whitelist |
| Multi-team coach/captain missing a Discord role | Role sync only read the legacy single `team_id` | Confirm sync-roles loops the full `team_ids` array |
| PC screen locks won't engage | `pc_lock_enabled` is off in config | Check `arena_kiosk_config.json` or re-toggle in Kiosk Manager |
| GGLeap calls returning 429 / "0 machines" | Daily 10k call quota exhausted | Check `/api/arena/ggleap-usage`; set `ggleap_paused=true` temporarily; find and fix any duplicate polling loop |
| Sign-in guard blocking real repeat check-ins | Cooldown/max-per-day set too strict | Reset to safe defaults (0/0/1) |
| A large PowerShell text edit corrupted special characters (em-dashes, etc.) in a Python file | `Get-Content`/`Set-Content` without `-Encoding UTF8` | Never pipe big source files through PowerShell text cmdlets without explicit UTF-8 encoding; verify with `python -c "import app"` after |
| Template edit doesn't show up in the browser | Production has no hot-reload / browser cache | Restart the server AND hard-refresh (Ctrl+F5) |
| A service — or the whole machine — stops responding | Anything from one crashed process to a full Windows hang | Try the Master Terminal first, then re-run `Start LionServices.bat`; if neither works, restart the physical host machine (see below) |
| Machine restarted but Nova/kiosks aren't reachable at the usual address | It reconnected over Wi-Fi instead of the wired Ethernet connection that has the static IP | Reconnect the Ethernet cable — see § "Restarting the Host Machine" below |

### Restarting the Host Machine (For Unforeseen Circumstances)

The machine running LionByteGG **auto-starts every service on boot** — a normal restart
brings the whole suite back online by itself, no manual steps needed. So when something goes
genuinely wrong and the steps above (Master Terminal restart, re-running
`Start LionServices.bat`) don't fix it, restarting the physical host machine is the next,
most reliable option.

> **Always make sure the machine reconnects over a wired Ethernet cable, not Wi-Fi.** Its
> static IP address (set via `set_static_ip.bat`) is bound specifically to the Ethernet
> adapter — on Wi-Fi it won't have that fixed address, which breaks anything relying on the
> known LAN address (staff bookmarks, kiosks). Ethernet is what gives this setup its best,
> most consistent experience.

If a restart alone doesn't help: try a full **shutdown + cold boot** instead of just a
restart, re-run `set_static_ip.bat` as Administrator if the IP looks wrong, check that
nothing else is squatting on port 5000, and check the physical network (cable seated, switch
powered) before assuming it's the host machine's fault. Full details, including how to
verify auto-start is actually configured, are in
[docs/manual/11_troubleshooting_and_operations_guide.md](manual/11_troubleshooting_and_operations_guide.md).

---

## 7. What Makes Nova Look Amazing

A few deliberate design choices give Nova its polish. Worth knowing so future work doesn't
accidentally undo them:

- **No flash-of-unstyled-content on load or bot-switch.** `base.html` sets a `no-transitions`
  class on `<html>` until the DOM is ready, so the theme/color swap between bot sections never
  flickers. (This must always be wrapped in try/catch with a `window.load` fallback — a JS
  error here once permanently disabled every transition on the page.)
- **A real desktop app feel, not a shrunk phone site.** Below 1024px the sidebar becomes a
  clean 72px icon rail with hover tooltips — it never turns into a hamburger-menu mobile
  drawer, because Nova is meant to be used on staff desktops/monitors, not phones.
- **Per-bot visual themes.** Each bot section gets its own accent color and icon language
  (Arena = gold/navy PNW theme, Music = its own palette, etc.) so staff always know which
  system they're in at a glance.
- **A built-in System Diagnostics console** (stethoscope icon in the header) runs ~140
  live health checks across every category — auth, bot, rosters, tickets, shifts, music,
  arena/kiosks, external APIs — with a live progress bar and exportable JSON report. This is
  what makes "is everything actually working right now" a 10-second answer instead of a
  20-minute manual check.
- **The Arena floor map isn't just a list — it's a real top-down room diagram**, with islands,
  a stage, doors, kiosk and admin-desk positions, and a live wayfinding line drawn from the
  kiosk to your exact reserved seat, walking along the front aisle so the line never crosses
  through another island. Guests can see and follow it before they even leave the kiosk.
- **A layered, tasteful audio alert system** for staff — a genuine 3-note bell chord for a
  banned sign-in attempt, a softer rising 2-note tone for a watch-list hit — built with the
  Web Audio API rather than a jarring stock beep, so it fits the feel of the room instead of
  sounding like a fire alarm.
- **Every export is a real, styled spreadsheet, not a raw CSV dump.** Analytics exports
  (Arena, BoilerCraft) use `openpyxl` to produce multi-sheet workbooks with KPI cards, charts,
  conditional-format heatmaps, and auto-filtered tables — something you could hand directly to
  a director without reformatting it.
- **Bulk operations are trackable, not fire-and-forget.** Long jobs (role sync, bulk DM) return
  a `job_id` and report live progress/errors instead of just spinning a generic loading icon.

---

## 8. Where to Go Deeper

- [docs/manual/00_index.md](manual/00_index.md) — the full deep-dive reference manual, one
  chapter per bot/feature area, covering every route, command, cog, and setting in detail.
- [CHANGELOG.md](../CHANGELOG.md) — chronological history of what's shipped.
