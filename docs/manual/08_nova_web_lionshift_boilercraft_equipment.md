# Chapter 8: Nova — LionShift, BoilerCraft & Equipment Dashboards

## Part 1 — LionShift Dashboard

**Location:** `LionByteGG/web/app.py` (routes `/lionshift/*` and `/api/lionshift/*`)

This is the admin-facing counterpart to everything described from the bot's side in
[Chapter 3](03_lionshiftgg.md) — if that chapter explained what a student worker experiences,
this section explains what a supervisor sees.

### Pages
All served from one template (`lionshift.html`) with a different active tab per route:
`/lionshift` (calendar), `/lionshift/schedules`, `/lionshift/workers`, `/lionshift/activity`
(and its aliases `/lionshift/offers`, `/lionshift/trades`, `/lionshift/timeoff` — these all
point at the same "activity" tab, just pre-filtered), `/lionshift/logs`, `/lionshift/tasks`,
and `/lionshift/bot-settings`.

### Creating and Publishing a Schedule
`POST /api/lionshift/schedules` creates either a **draft** or a **published** schedule. If
you publish immediately without setting a future `announce_at`, the schedule announcement is
queued right away; if you save it as a draft, `POST /api/lionshift/schedules/<index>/publish`
later triggers the announcement. Either way, "announcing" means writing an entry to
`../LionByteGG/data/lionshift_notification_queue.json`, which the LionShiftGG bot picks up
within 2 seconds, posts to Discord with a generated schedule-grid image, and optionally DMs
every student worker (see [Chapter 3 §3.6–3.7](03_lionshiftgg.md#36-how-nova-talks-to-this-bot)
for exactly how that image gets made). You can also manually re-announce an already-published
schedule at any time with `POST /api/lionshift/schedules/<index>/announce`.

### Approving Trades & Time-Off
`POST /api/lionshift/trades/<id>/approve` and `.../decline` (with an optional reason)
directly resolve a trade that a student worker already accepted on their end — approving
queues confirmation DMs to both people involved. Time-off works identically via
`/api/lionshift/timeoff/<id>/approve` / `.../decline`.

### Worker Hours
`GET /api/lionshift/worker-hours` is worth calling out specifically: it calculates each
worker's total/weekly/monthly hours **preferring real logged clock-in/out events** from
`shift_logs.json`, and only falling back to scheduled-shift durations if no logged data
exists for that period. The response tells you which source it used (`"logged"` vs.
`"scheduled"`) per worker, so you can tell at a glance whether a number is measured or
estimated.

### Configuring Rooms & Duties
`POST /api/lionshift/rooms` replaces the entire room list in one call — it slugifies IDs,
validates every color is a real `#RRGGBB` hex code, and caps names at 40 characters, so a
malformed submission can't silently corrupt the room list. `POST /api/lionshift/shift-duties`
similarly replaces the entire duty checklist (per room, per shift type), where each task has
a `show_on` (`start`, `end`, or `both`) and a `required` flag.

### Bot Settings
`GET/POST /api/lionshift/bot-settings` controls the same toggles the bot itself reads:
`dm_shift_reminders`, `dm_late_alerts`, `reminder_minutes_before` (5–480), `late_alert_minutes`
(1–60), `dm_new_schedule`, `allow_shift_trading`.

---

## Part 2 — BoilerCraft Dashboard

**Location:** `LionByteGG/web/app.py` (routes `/boilercraft/*` and `/api/boilercraft/*`)

### How Actions Reach the Minecraft Bot
Just like the Ticket System in [Chapter 7](07_nova_web_music_tickets.md), every action here
that needs to actually happen in Discord gets queued — but to a **different** file:
`BoilerCraftGG/data/dashboard_commands.json` (note: this lives inside BoilerCraftGG's own
data folder, not the shared LionByteGG one). BoilerCraftGG's `poll_dashboard_commands` loop
picks these up every 5 seconds. Command types include `ticket_close`, `ticket_message`,
`deploy_panel`, `refresh_panel`, `faq_post`/`faq_edit`/`faq_delete`/`faq_renumber`, and
`member_kick`/`ban`/`timeout`/`unban`.

### Pages
`/boilercraft/dashboard` (server status + overview), `/boilercraft/faq` (FAQ management),
`/boilercraft/verified-players` (linked Discord↔Minecraft accounts), `/boilercraft/boilerwatch`
(flagged chat log — the dashboard view of the chat-monitor cog from
[Chapter 1 §1.4](01_boilercraftgg.md)), `/boilercraft/members`, and `/boilercraft/analytics`.

### Live Minecraft Server Status
`GET /api/boilercraft/server-status` calls the free public
[mcsrvstat.us](https://mcsrvstat.us) API for `mc.esports.purdue.edu` and returns whether it's
online, current/max players (with the actual player name list), the version string, and the
server MOTD/icon — genuinely live, not cached.

### Verified Players & Exports
`GET /api/boilercraft/verified-players` reads directly from BoilerCraftGG's SQLite database
(`verified_users` table) and enriches each row with the person's current Discord display
name/avatar. `GET /api/boilercraft/verified-players/export` turns that into a properly
styled `.xlsx` workbook — not a raw CSV dump — ready to hand to someone who just wants a
spreadsheet.

### BoilerWatch
`GET /api/boilercraft/boilerwatch/stats` aggregates the flagged-message log into a genuinely
useful summary: total flags, the whisper/public split, how many unique players triggered a
flag, today's count, and the top 10 most-flagged words and players. `POST
/api/boilercraft/boilerwatch/logs/clear` wipes the log — there's no undo, so use it
deliberately (e.g. at the start of a new semester).

### Analytics Export
`GET /api/boilercraft/analytics/export?range=24h|7d|14d|30d` produces a **6-sheet** Excel
workbook: an executive summary with KPI cards, a player-count timeline with a real line
chart, peak-hours analysis with a bar chart, a daily-summary sheet, a top-players
leaderboard, and the raw underlying data for anyone who wants to build their own pivot
table.

---

## Part 3 — Equipment & Inventory (with QR Codes)

**Location:** `LionByteGG/web/app.py` (routes `/api/equipment/*`) · reached from **Arena
Staff → Inventory** (`/arena/inventory`)

### What Problem This Solves
Physical arena equipment — controllers, headsets, cables, whatever gets checked out to
students — needs a paper trail. This system gives every item a running expected-vs-current
quantity, a full checkout/checkin history, and a way to flag something as missing or stolen
without losing track of it.

### The Checkout Flow
1. An item is added once (`POST /api/equipment`) with a name, category, and expected
   quantity.
2. `POST /api/equipment/<id>/checkout` records who took it (name + an ID type/number for
   accountability), how many units, and an optional purpose — this decrements
   `current_quantity`.
3. `POST /api/equipment/<id>/checkin` reverses it, optionally recording the condition it came
   back in (good/fair/damaged) — this increments `current_quantity` back.
4. If something never comes back, `POST /api/equipment/<id>/report` files a missing/stolen
   report against it, which a supervisor later resolves with `POST
   /api/equipment/reports/<id>/resolve` (optionally marking it as recovered).

### QR-Code Self-Service Checkout
Every item can have one or more QR codes generated for it (`POST
/api/equipment/<id>/qrcode`). Each QR code encodes a URL
(`/onduty/equipment?checkout={item_id}&qr={qr_id}`) that a student can scan with their own
phone to jump straight to that item's checkout form — no need for staff to manually look the
item up. Deactivating a QR code (`DELETE /api/equipment/qrcode/<qr_id>`) doesn't delete the
record, it just makes the public redirect (`GET /qr/<qr_id>`) return a 404 instead of routing
anywhere, which is the safer default if a printed QR code goes missing.

### Exporting the Full Inventory
`GET /api/equipment/export` produces a single CSV with four clearly-labeled sections: an
item summary (flagging anything missing, partially checked out, or low stock), every active
checkout, every open/resolved report, and the full activity history — everything a real
physical inventory audit would need in one file.

### Permission Keys
`equipment.manage` (add/edit/delete items, deactivate QR codes), `equipment.checkout`,
`equipment.checkin`, `equipment.reports` (file and resolve), `equipment.export`.
