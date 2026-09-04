# Chapter 3: LionShiftGG — The Arena Shift-Scheduling Bot

**Location:** `LionShiftGG/` · **Language:** Python (discord.py 2.3+) · **Storage:** JSON files

## What This Bot Is For

LionShiftGG runs the entire operational side of staffing the PNW Esports Arena: posting
schedules, letting student workers clock in and out, letting them offer or trade shifts
amongst themselves (with director approval), handling time-off requests, and nagging people
who are late. Almost everything a student worker does with this bot happens through button
panels rather than typed commands, because most of them are using it from their phone in
between tasks.

---

## 3.1 The Shared Files That Make Everything Work

Every feature in this bot revolves around a small set of JSON files, all loaded/saved through
`safe_json.py`'s atomic write helpers (write to a temp file, then swap it in — a crash mid-write
can never corrupt the real file). It's worth knowing what each one is for before diving into
the features that use them:

| File | What lives in it |
|---|---|
| `schedules.json` | Every posted schedule (date range, spreadsheet link, whether trading is allowed) and every shift inside it — who's assigned, what type, what time, what room. Keeps the last 3 schedules. |
| `shift_board.json` | Shifts currently offered up for someone else to take, plus a rolling history of the last 100 taken offers. |
| `shift_logs.json` | Every clock-in/clock-out event ever recorded (capped at the last 100). |
| `trades.json` | Every shift-trade request and its approval status. |
| `timeoff_requests.json` | Every time-off request and its approval status. |
| `workers_cache.json` | A lightweight, always-fresh snapshot of every student worker's live clock-in status, for the Nova dashboard to display. |
| `panels.json` | The message IDs of every deployed button panel, so buttons still work after a bot restart. |
| `settings.json` | Admin-configurable toggles — see the table in §3.5. |
| `rooms.json` | The arena's physical rooms (PC Room, Console Room, ...), each with an id/name/emoji/color. |
| `shift_duties.json` | The checklist of tasks shown to a worker when they clock in or out, per shift type and optionally per room. |

The bot also watches one file it doesn't own: `../LionByteGG/data/lionshift_notification_queue.json`,
written by Nova, which is how the web dashboard tells this bot to post a schedule
announcement or send a broadcast DM (see §3.6).

---

## 3.2 Clocking In and Out — the Full Walkthrough

Clocking in isn't just "press a button" — it's designed to make sure the right person is
actually working the shift they're claiming, and to walk them through the arena's real
opening/closing checklist.

1. Worker presses **🟢 Start Shift** on the persistent clock panel (deployed via
   `/setup_clockpanel`).
2. They pick which posted schedule they're working from a dropdown.
3. The bot figures out their shift for today automatically — checking, in order, whether
   they're directly assigned that shift, whether they picked it up from the shift board, or
   whether an approved trade gave it to them. If none of those apply, it blocks them with a
   clear explanation instead of letting them start an unassigned shift.
4. **Step 1 of 2 — Clock In First:** a link to Purdue's real WebClock system, with a
   "Done — I've Clocked In" confirmation button.
5. **Step 2 of 2 — Your Tasks:** the shift's greeting and checklist from `shift_duties.json`
   (opener/mid/closer, optionally per room). Openers are additionally required to submit the
   real opening-checklist Microsoft Form before this step completes.

Ending a shift mirrors this, but closers get an extra layer: **Step 1 (Clock Out)** → **Step
2 (Closing Form)** → **Step 3 (Final Clock Out)** — because the real-world closing procedure
genuinely has three distinct stages. Every clock event, in either direction, is written to
`shift_logs.json` and immediately reflected in `workers_cache.json` so the dashboard shows
accurate live status.

> If a worker tries to **End Shift** without ever having clocked in, the bot politely refuses
> instead of recording a bogus event — worth remembering if you're troubleshooting "my hours
> look wrong."

---

## 3.3 Offering, Picking Up, and Trading Shifts

Three related but distinct features, all reachable from the same persistent panel
(`/setup_offershift`):

### Offer a Shift (`🟥 Offer Shift` button, or `/offer_shift`)
A worker who can't make an assigned shift picks it from a list of their own upcoming shifts,
gives a reason in a modal, and the bot posts a public embed to the channel (pinging the
Student Worker role) with a **"✅ Take This Shift"** button.

### Pick Up a Shift (`/pickup_shift`, or clicking Take This Shift)
Whoever clicks first gets it — the bot validates the offer hasn't already been claimed and
isn't the claimer's own shift, updates the offer to `taken`, and **transfers the actual
assignment in `schedules.json`** so the new person can clock in for it. The original poster,
the new worker, and the director are all notified. The original message then visibly changes
to "⛔ Shift Claimed" and deletes itself after 30 seconds.

### Trade a Shift (`🟦 Trade Shift` button, or `/trade_shift <worker>`)
A two-person, two-approval process:
1. Requester picks their own shift, then a target student worker, then fills out a modal
   describing "your shift" / "the shift you want" / a reason.
2. The **target student** gets a DM with Accept/Decline buttons.
3. If they accept, the **director** gets a DM with Approve/Decline buttons.
4. Only once the director approves does the trade take effect — both students are notified
   either way, and a decline at either stage includes a reason.

---

## 3.4 Time-Off Requests

`🔴 Make Request` opens a simple modal (from-date, to-date, reason). It's saved to
`timeoff_requests.json` with `status: "pending"`, and the director gets a DM with
Approve/Decline buttons. Approving or declining timestamps the record and, if declined,
records a reason that gets relayed back to the worker.

---

## 3.5 Reminders and Late-Worker Detection

A single background task, `shift_reminder_task`, runs every 5 minutes and does two related
jobs by comparing the current time (in **America/Chicago**, always) against every shift in
every published schedule for today:

- **Reminders:** if a shift starts in roughly `reminder_minutes_before` minutes (default 60),
  DM the assigned worker a heads-up — schedule, date, time, all included.
- **Late detection:** if a shift started roughly `late_alert_minutes` minutes ago (default
  10) and there's *no* matching "start" event in `shift_logs.json` for that worker today, DM
  **both** the worker (a nudge to clock in immediately) and the director (a "worker X hasn't
  clocked in, they're now Y minutes late" alert).

Both behaviors are individually toggleable (`dm_shift_reminders`, `dm_late_alerts`) via
`/dm_settings`, and the bot tracks which (worker, date, shift-start) combinations it's
already alerted on so you never get double-DMed for the same shift.

---

## 3.6 How Nova Talks to This Bot

Nova's LionShift Dashboard (see [Chapter 8](08_nova_web_lionshift_boilercraft_equipment.md))
writes to `../LionByteGG/data/lionshift_notification_queue.json`, and this bot's
`process_notification_queue` task polls it every 2 seconds. Two message types exist today:

- **`schedule_announcement`** — posts a new/updated schedule to a Discord channel, complete
  with a generated schedule-grid image (see §3.7), and optionally DMs every student worker.
- **`dm_workers`** — sends a custom broadcast message to a specific list of workers (or
  everyone, if the list is empty).

---

## 3.7 The Schedule Image Generator

`schedule_image.py` turns a schedule object into an 800px-wide PNG that looks genuinely
designed rather than auto-generated: a dark background (`#0F111A`), an amber gradient header
bar, a stats row (total shifts / days / whether trading is enabled), and then a 7-day grid
with color-coded shift blocks — green for Opener, blue for Mid, purple for Closer — showing
up to 6 shifts per day before collapsing into a "+N more" indicator. This image is what gets
attached to the Discord announcement embed.

---

## 3.8 Slash Commands Reference

| Command | Who | What it does |
|---|---|---|
| `/setup_offershift` | Admin | Deploys the persistent Offer/Trade Shift panel |
| `/setup_requesttimeoff` | Admin | Deploys the persistent Time-Off Request panel |
| `/setup_clockpanel` | Admin | Deploys the persistent Start/End Shift panel |
| `/new-schedule` | Admin | Posts a new schedule (channel, spreadsheet link, dates, trading allowed?) |
| `/delete_schedule` | Admin | Removes a schedule |
| `/view_schedules` | Everyone | Shows schedule details via a dropdown |
| `/dm_settings` | Admin | View or toggle reminder/late-alert DMs |
| `/set_log_channel` | Admin | Sets which channel clock in/out events post to |
| `/restart_service` | Admin | Gracefully restarts the bot process |
| `/about` | Everyone | Feature overview |
| `/offer_shift` / `/pickup_shift` / `/trade_shift` | Student Worker role | See §3.3 |
