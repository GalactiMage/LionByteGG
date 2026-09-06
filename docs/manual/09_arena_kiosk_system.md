# Chapter 9: The Arena Kiosk System

**Location:** `LionByteGG/web/app.py` (arena routes) + `templates/arena*.html`

## Why This Is the Most Complex Part of the Whole Project

Every other feature in this manual manages *data*. This one manages **two physical rooms in
the real world** — a PC/Island room and a console room — plus every touchscreen kiosk bolted
to a wall in front of them, plus the arena staff who need to see what's happening in real
time. It has to be simultaneously reliable enough to run unattended 12+ hours a day, secure
enough that a guest can't spoof someone else's sign-in, and fast enough that a student worker
glancing at a dashboard sees the truth *right now*, not from 30 seconds ago. This chapter
explains how all of that actually holds together.

---

## 9.1 The Big Picture — How a Kiosk Sign-In Actually Happens

Here's the full journey, start to finish, for someone walking up to a PC-room kiosk:

1. **The kiosk is idle**, showing an attract screen with live "X of Y PCs Available" pulled
   from `GET /api/arena/pcs` (polled roughly every 12 seconds).
2. They tap the screen, choose **Visiting** or **Play on a PC**.
3. If they chose **Play on a PC**, they see a real top-down floor map of the room (see
   [Chapter 10](10_arena_kiosk_physical_devices.md) for exactly how this is drawn) and tap an
   available seat.
4. They fill in name + email. The kiosk submits this to `POST /api/arena/kiosk/book` (for a
   PC pick) or `POST /api/arena/signin` (for a plain visit).
5. The backend re-validates the machine is still actually available (someone else could have
   grabbed it in the few seconds since the picker rendered), checks the email against the
   arena's approved domain list, and runs it through the **sign-in guard** (§9.4).
6. If everything passes: a **hold** is placed on that PC (§9.3), a sign-in record is written
   to the encrypted database (§9.5), and — if PC screen-lock automation is enabled — that
   specific PC is unlocked immediately so they can walk over and log in.
7. The success screen shows a wayfinding route drawn from the kiosk to their exact seat.

Every one of those steps has its own section below, because each one has real subtlety.

---

## 9.2 Live PC Status — Where the Numbers Actually Come From

The arena's PCs are managed by a third-party platform called **GGLeap**. Nova polls its
`machines/get-all` endpoint to find out which PCs are on, off, or logged into.

### The Single Shared Cache (Read This Before Adding Anything New)
Early in this project's life, **two independent polling loops** both called `get-all`
constantly — the kiosk status endpoint and the PC-lock automation loop — and together they
blew through GGLeap's roughly 10,000-calls-per-day quota, causing a full outage until the
quota reset. The fix was architectural: there is now exactly **one** shared cache
(`_ggleap_get_machines()`), and every single consumer in the codebase — the public status
endpoint, the lock-loop, the lock-status endpoint — reads from it. Nobody is allowed to call
GGLeap directly anymore.

**If you're adding a new feature that needs PC status, use the shared cache. Do not add
your own polling loop.** This exact mistake has already caused one real outage.

The cache is adaptive: it refreshes every 15 seconds while the arena is open (kiosks need
fresh data) and backs off to every 120 seconds while closed (nobody's watching, no reason to
spend API calls). If GGLeap itself is slow or returns an error, the cache serves the last
good result instead of showing "0 machines" — a kiosk should never flash empty just because
one API call hiccuped.

A live usage meter (`GET /api/arena/ggleap-usage`, shown in the Kiosk Manager UI) tracks
today's call count against the 10,000 limit, broken down by call type, so you can catch a
runaway consumer before it becomes an outage. There's also an emergency kill-switch —
setting the `ggleap_paused` config flag to `true` stops **every** GGLeap call instantly,
read live with no restart required, for the rare moment you need to buy time.

### The Public Endpoint
`GET /api/arena/pcs` (no login required — kiosks need this) returns available/in-use/offline
counts and a full per-machine list with area groupings. "Stage" machines are deliberately
filtered out entirely — they're varsity-only and never shown to a walk-in guest.

---

## 9.3 PC Reservations — Why There's No Real "Booking"

An earlier version of this feature actually created real GGLeap bookings (with a 4-digit
unlock code) when someone picked a PC. It was fully removed. The problem: GGLeap bookings
can only start on a 15-minute-aligned clock boundary, so a guest could tap a seat and then
have to wait up to 15 minutes for their booking to actually begin — unacceptable for a
walk-up kiosk.

**What replaced it is much simpler:** picking a PC just sets an **in-memory hold**
(`pc_hold_minutes`, default 10) on that machine. Nothing is "booked" with GGLeap at all —
availability is driven purely by whether the PC shows `UserLoggedIn` in GGLeap's own state.
This means play time is genuinely unlimited (there's no session to expire), and the PC frees
up the instant someone logs out. If a guest picks a seat and then never actually walks over
and logs in, the hold simply expires and — if PC locking is enabled — the PC gets re-locked
automatically as a no-show.

---

## 9.4 The Screen-Lock Automation — Keeping Unattended PCs Secure

If enabled (`pc_lock_enabled`), every idle PC in the room gets automatically screen-locked
with the message *"Must be checked in on Kiosk to use system"* via GGLeap's
`set-screen-lock` API. A background loop re-evaluates every 12 seconds. The logic sounds
simple but has one crucial rule that took real trial and error to get right:

> **A PC that a human (a worker, or a Nova "Unlock All") manually unlocked is never
> automatically re-locked — not until that PC actually reboots.**

Without this rule, the automation would constantly fight a worker who unlocked a machine to
help a guest, re-locking it out from under them seconds later. Three separate tracking sets
make this possible: PCs the automation itself locked, PCs a human unlocked (left alone until
reboot), and PCs a guest's kiosk check-in unlocked (which *can* be automatically re-locked,
but only if the guest never actually shows up before their hold expires — a genuine no-show,
not a human override).

Because every lock/unlock call also goes through the same 4.5-second write-rate throttle
that protects the GGLeap quota, locking or unlocking an entire room of ~24 PCs takes roughly
1.5–2 minutes to complete — this is expected and by design, not a performance bug.

**One hard platform limitation worth knowing:** GGLeap has no clean way to release a PC lock
back to a normal idle state once it's been *applied* on the machine side — the only clean
release is a genuine login session starting, or a GGLeap-dashboard-side manual unlock. This
is a limitation of the third-party platform itself, not something this codebase can fix.

---

## 9.5 Sign-Ins: How the Data Is Stored, and Why It's Encrypted

Every sign-in — kiosk or manual — is written to a dedicated SQLite database
(`data/arena.db`, via `web/arena_db.py`), not a JSON file. All personal fields (name, first
name, last name, email) are Fernet-encrypted at rest, using the *same* encryption key as the
roster PII described in [Chapter 6 §6.8](06_nova_web_rosters_varsity.md#68-personal-data-is-always-encrypted).
Non-PII fields (which kiosk, which room, the stated reason, who checked them in, timestamps)
are stored in plain columns so the database can still be efficiently filtered and indexed
without ever exposing a name or email in a raw table scan.

**Duplicate check-ins are allowed on purpose.** Someone can sign in multiple times in a day
and each one shows up as its own card on the Live Feed — a deliberate choice made after
staff wanted to see every individual visit, not a de-duplicated count.

Two sign-in endpoints exist: the public kiosk one (`POST /api/arena/signin`, or
`POST /api/arena/kiosk/book` for a PC pick) and a staff-facing manual one
(`POST /api/arena/manual-signin`) that bypasses the normal hours/domain restrictions and
additionally records a free-text reason plus who checked the guest in — useful for the "the
kiosk is broken, let me sign you in myself" situation.

---

## 9.6 The Sign-In Guard — Anti-Spam Protection

To stop someone from hammering the kiosk with fake sign-ins (or a bot script doing the
same), a configurable guard sits in front of every sign-in:

| Setting | Default | What it does |
|---|---|---|
| `cooldown_minutes` | `0` (off) | Minimum time between two sign-ins from the same email |
| `max_per_day` | `0` (off) | Caps total sign-ins per email per day |
| `max_active_pc` | `1` (on) | Caps how many PCs one email can hold at once |

> **These defaults exist because an earlier, stricter configuration (15-minute cooldown,
> 8-per-day cap) accidentally blocked *legitimate* repeat visitors** — someone leaving to
> grab lunch and coming back an hour later got locked out. If you ever tighten these values,
> test a real repeat check-in afterward before trusting it in production.

Separately from the numeric guards, a **ban/watch list** always applies regardless of
whether the numeric guards are even turned on: an email on the list in `ban` mode is blocked
outright with a configurable message; in `watch` mode it's allowed through but flagged for
staff attention. Every guard trigger — ban, watch, cooldown, daily cap — is logged as a
"flag," and the Live Feed shows a live, dismissible banner with a distinct audio cue (a
proper layered three-note bell for a ban attempt, a softer rising two-note tone for a watch
hit) so staff working the floor notice immediately without needing to stare at a screen.

---

## 9.7 Hours, Announcements, and the Closed Screen

Arena hours are configured **per weekday**, not as one blanket open/close time — each day of
the week has its own `{open: bool, start: "HH:MM", end: "HH:MM"}`. This directly drives:
whether the kiosk shows its normal sign-in flow or a "we're closed" screen, a human-readable
weekly summary shown on the closed screen (e.g. *"Mon–Fri 9:00 AM – 5:00 PM · Sat–Sun
Closed"*), and a full 7-day schedule list with today's row visibly highlighted.

A separate **announcement bar** (`announcement: {enabled, text, color, scroll}`) can show a
scrolling or static banner across the top of every kiosk — useful for "tournament tonight at
7pm" style messages without needing a code change.

---

## 9.8 Analytics — Turning Sign-Ins Into Insight

`/arena/activity` and its backing endpoint (`GET /api/arena/analytics`) compute genuinely
useful traffic intelligence, not just raw counts: totals with day-over-day/week-over-week
trend comparisons, the single busiest hour and busiest weekday, a full 7-day × 24-hour
traffic heatmap, a top-visitors leaderboard, and a new-vs-returning-guest split. Everything
respects the same date-range/kiosk filters as the Live Feed. `GET /api/arena/analytics/export`
turns the same data into a 6-sheet styled Excel workbook (including a real
conditionally-color-scaled heatmap sheet) — something you could genuinely hand to a director
for a board meeting.

---

## 9.9 Student Profiles & Incident Reports

Every unique email that's ever signed in gets an aggregated **student profile** (`GET
/api/arena/student?email=...`) — total visits, first/last visit, every staff note ever left
on them, every incident report they're mentioned in, and their current ban/watch status.
Staff can leave typed notes (`general`, `behavior`, `warning`, `positive`) and file/track
formal incident reports. Incident visibility is deliberately scoped: by default you only see
incidents *you personally* filed, unless you hold the `arena.reports_all` permission — this
keeps sensitive behavioral write-ups from being broadly readable by every staff member with
basic dashboard access.

---

## 9.10 Multi-Kiosk Support

The system isn't hardcoded to exactly two kiosks. Each configured kiosk has a `type` —
`"pc"` (renders the full PC-picker experience) or `"console"` (a simpler visiting/play flow)
— and new kiosks can be added or removed entirely from the Nova UI
(`POST/DELETE /api/arena/kiosks`) without touching a single line of code. Every kiosk gets a
stable `kiosk-N` ID and its own room/label, and the system refuses to let you delete the
last remaining kiosk.

---

## 9.11 Permission Keys Used in This Section

| Key | Grants |
|---|---|
| `section.arena` | Shows the Arena Staff section at all |
| `page.arena_live` | View the Live Feed |
| `page.arena_sessions` | View & control the PC room map |
| `page.arena_logs` | View sign-in logs |
| `page.arena_controls` | View the Kiosk Manager |
| `arena.manage` | Actually lock/unlock/check-in/cancel/restart/shutdown a PC |
| `arena.unlock` | Remotely unlock a locked kiosk |
| `page.arena_students` | View student profiles |
| `arena.notes` | Add/remove notes on a student |
| `arena.ban` | Add/remove someone from the watch/ban list |
| `arena.students_manage` | Permanently delete a student's history |
| `page.arena_reports` | View incident reports (your own, by default) |
| `arena.reports_all` | View *everyone's* incident reports |
| `arena.reports` | File/resolve/delete incident reports |
| `page.arena_inventory`, `equipment.use`, `equipment.manage` | The equipment/inventory system — see [Chapter 8 §3](08_nova_web_lionshift_boilercraft_equipment.md#part-3--equipment--inventory-with-qr-codes) |

---

## 9.12 A Feature That Was Built and Then Fully Removed

Worth documenting for posterity: a "Digital Signage" feature — an admin-configurable
slideshow for the arena's two 75-inch TVs, showing live PC counts, weather, and event
slides — was fully built, briefly tested with real live data, and then **completely deleted**
at the requester's decision before it was ever polished or deployed. If a similar feature is
requested again, confirm the exact scope carefully before building — this exact idea has
already been built once and fully scrapped.

---

## 9.13 Example Data Shapes

**`arena_kiosk_config.json` (abbreviated, showing the shape not every key)**
```json
{
  "arena_name": "PNW Esports Arena",
  "day_hours": [
    { "open": true,  "start": "10:00", "end": "17:00" },
    { "open": true,  "start": "10:00", "end": "17:00" },
    { "open": true,  "start": "10:00", "end": "17:00" },
    { "open": true,  "start": "10:00", "end": "17:00" },
    { "open": true,  "start": "10:00", "end": "17:00" },
    { "open": false, "start": "10:00", "end": "17:00" },
    { "open": true,  "start": "10:00", "end": "14:00" }
  ],
  "announcement": { "enabled": true, "text": "Tournament tonight at 7pm!", "color": "#CFB991", "scroll": true },
  "signin_guard": { "enabled": true, "cooldown_minutes": 0, "max_per_day": 0, "max_active_pc": 1, "ban_message": "You are not permitted to sign in at this time." },
  "pc_lock_enabled": true, "pc_hold_minutes": 10, "ggleap_paused": false,
  "kiosks": {
    "kiosk-1": { "label": "Main Kiosk", "room": "Island Room", "type": "pc" },
    "kiosk-2": { "label": "Console Kiosk", "room": "Console Room", "type": "console" }
  }
}
```

**A sign-in record (`arena.db`, decrypted view — non-PII columns shown alongside)**
```json
{
  "id": "sign_9f2a1c", "kiosk_id": "kiosk-1", "room": "Island Room",
  "name": "Alex Smith", "email": "asmith@purdue.edu",
  "reason": null, "checked_in_by": null,
  "signed_in_at": "2026-09-04T15:02:00Z", "accepted_rules": true
}
```

**A signin-guard flag (`arena.db`)**
```json
{
  "id": 118, "at": "2026-09-04T15:10:00Z", "kind": "watch", "severity": "med",
  "kiosk_id": "kiosk-1", "kiosk_label": "Main Kiosk", "reason": "Email is on the watch list"
}
```

**`GET /api/arena/pcs` response (abbreviated)**
```json
{
  "available": 18, "in_use": 5, "offline": 1, "total": 24,
  "pcs": [
    { "uuid": "abc-123", "name": "Island1S1", "status": "available", "area": "Island 1", "state": "ReadyForUser", "locked": false }
  ],
  "error": null, "last_updated": "2026-09-04T15:11:00Z"
}
```

---

## 9.14 Frequently Asked Questions

**"A guest says they can't sign in and the kiosk shows a generic error."**
Check three things in order: is the arena actually configured as open right now for today's
`day_hours` entry, is their email on the ban/watch list (a ban blocks outright with the
configured `ban_message`), and has the sign-in guard's `cooldown_minutes`/`max_per_day`
kicked in for them specifically (only relevant if those are set above `0`).

**"The floor map shows a PC as available but a guest walked up and it was actually in use."**
This is almost always a brief staleness window — the shared GGLeap cache refreshes every 15
seconds while the arena is open, so there's up to a 15-second lag between a PC's real state
changing and the kiosk reflecting it. This is an intentional trade-off to stay within
GGLeap's API rate limits (see §9.2) — it is not a bug, just the cost of not hammering the
API every second.

**"Can I make a specific PC completely unavailable to guests without turning it off?"**
Not directly through the kiosk system today — the closest option is placing an ongoing hold
on it (which is normally guest-driven) or coordinating with GGLeap directly to mark it in
maintenance mode there, since that state isn't something Nova's config exposes a toggle for.

**"An incident report I filed isn't showing up for another staff member."**
That's expected behavior, not a bug — by default, incident reports are only visible to the
staff member who filed them, unless the viewer has `arena.reports_all`. Confirm the other
staff member actually holds that permission if they're meant to see everyone's reports.

**"Why does the Live Feed sometimes show the same person twice in a row?"**
Duplicate check-ins are allowed on purpose (see §9.5) — if a guest taps the kiosk twice by
accident, or a staff member manually signs someone in who already used the kiosk themselves
minutes earlier, both attempts show up as separate, real entries. This was a deliberate
design choice so staff can see every individual tap, not a de-duplicated summary.

**"How do I completely wipe a specific kiosk's local state (test data, stuck holds, etc.)?"**
There's no single "reset kiosk" button — holds are in-memory and clear themselves on the
next server restart or naturally expire after `pc_hold_minutes`; sign-in records need to be
removed at the student-profile level (`DELETE /api/arena/student?email=...`) if they were
test data that shouldn't count toward analytics.

---

## 9.15 The PC Manager Tab — Layout, Colors & Quick Actions

The staff-facing PC room map (`/arena/sessions`, gated by `page.arena_sessions`) is labeled
**"PC Manager"** in the sidebar and tab bar (its URL/permission key still say "sessions"
internally for backward compatibility — only the display name changed).

### Status colors, explained
Every seat uses a distinct color + icon so a status is readable at a glance without hovering:

| State | Color | Icon | Meaning |
|---|---|---|---|
| Logged In | Green | person | A real student is actively playing |
| Reserved | Amber | hourglass | Held for a guest walking over from the kiosk |
| Varsity (Logged In) | Gold | person | Same as Logged In, but a varsity/JV player |
| **Secured & Ready** | Teal, with a green checkmark | check-circle | Idle, no one signed in, and the kiosk screen-lock has it gated — everything is working correctly, it's just waiting for someone to check in |
| Open / Unlocked | Blue | unlock | Idle and NOT locked — anyone could sit down without checking in first |
| Admin / Maintenance | Purple | gear / wrench | In Admin Mode, restarting, starting up, or shutting down |
| **Offline** | Red, pulsing | warning triangle | Not reporting to GGLeap at all — almost always means the machine is fully powered off |

A machine that's offline is now clickable (it wasn't before) — clicking it opens an
informational panel explaining there's no remote power-on available and showing its last
known state/last-seen time, rather than doing nothing.

### Right-click quick actions
Right-clicking any seat opens a small context menu with the actions relevant to that
specific machine's current state — e.g. Check In Student + Lock/Unlock for an idle machine,
Cancel & Restart for a logged-in session, Restart/Power Off for Admin Mode, and (if the seat
has a signed-in student and you hold `page.arena_students`) a direct **View Student
Profile** shortcut. Every machine's menu also offers **Copy Machine Name** for quickly
pasting a station name elsewhere (a support ticket, a Discord message, etc.). Left-click
still opens the full detail drawer as before; right-click is a purely additive shortcut.

### Faster updates without breaking the GGLeap budget
This tab's auto-refresh cadence scales with the arena's own open/closed schedule instead
of using one flat number: **8 seconds while open** — the exact same cadence the public
kiosks have always used, so an open tab adds zero *incremental* GGLeap load beyond what
the system already runs safely every day — and **45 seconds while closed** (vs the kiosk's
120s), fast enough for an after-hours restart-test to see a real update in under a minute
without an aggressive cadence around the clock. It still flows through the single shared
GGLeap cache described in §9.2, so this can only ever *shorten* the effective refresh rate
while a staff member has the tab open; it never opens a second polling loop or calls
GGLeap outside that shared cache. Even the unrealistic worst case of this tab being left
open and visible 24 hours a day, every day, stays comfortably under half the 10,000/day
budget by design — there's no need to rely on the emergency circuit breaker described in
§9.2 for this to be safe, it's simply an extra backstop for the unexpected.

### Floor layout matches the physical kiosks
Each island renders as a 2-column × 3-row grid in the real physical seating order —
`(1,6) / (2,5) / (3,4)` — the same `SEAT_ORDER` used by the actual kiosk floor map (see
[Chapter 10 §10.4](10_arena_kiosk_physical_devices.md)), instead of a generic ascending
split. A small front-of-room reference strip (Kiosk chip on the left, Admin Desk chip on the
right) sits below the islands purely for spatial orientation, mirroring the kiosk's own
"Kiosk / Door / Stage / Door / Admin Desk" landmarks.
