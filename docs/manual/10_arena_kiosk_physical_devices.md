# Chapter 10: Arena Kiosk — Physical Devices, Templates & Deployment

## Two Things Both Called "Kiosk" — Don't Mix Them Up

There are two genuinely different sets of files in this project that both relate to the
physical arena kiosks, and it's an easy mix-up to make when editing:

1. **The live, currently-deployed templates** served by Nova at `/arena/kiosk/<id>` — these
   are what the real hardware actually loads, and they're the ones documented in
   [Chapter 9](09_arena_kiosk_system.md).
2. **A folder called `Arena Kiosks/`** at the top of the repo, containing two standalone
   single-file HTML prototypes (`Kiosks 1/Kiosk 1.html`, `Kiosks 2/Kiosk 2.html`) — these are
   an **earlier design reference**, kept for history, and are **not wired to the live
   backend at all** (no API calls to anything). If you're asked to change "the kiosk," always
   confirm which of these two you actually mean before editing.

---

## 10.1 The Live Templates

| File | Room | What it renders |
|---|---|---|
| `arena_kiosk.html` | — | The kiosk picker/selection screen, listing every configured kiosk |
| `arena_kiosk1.html` | PC / Island room | Full attract → choose → floor-map picker → sign-in → success flow |
| `arena_kiosk2.html` | Console room | Simpler attract → choose → sign-in → success flow (no seat picker) |

**These two kiosk template files must be kept in sync manually.** Any shared feature — the
announcement bar, the language toggle, the boot sequence, the admin panel — exists as
near-duplicate code in both files. Several real bugs in this project's history came from a
fix being applied to only one of the two.

---

## 10.2 General Kiosk UI Principles

Every kiosk screen shares the same foundational design choices, all deliberate:
- **No accidental navigation.** `overscroll-behavior: none`, no text selection, no iOS
  copy/paste callouts, and a pre-render script that checks for an active lockout *before* the
  page even paints, so a locked-out kiosk never flashes the sign-in form for a split second
  first.
- **Large, glanceable UI.** Fonts and buttons scale with the viewport using `clamp()` so the
  same code looks right whether it's on a 10-inch tablet or a 24-inch monitor.
- **A consistent brand identity** — Purdue gold (`#CFB991`), dark navy (`#0E1730`), and a
  success green (`#34D399`) — so every screen, on every kiosk, feels like part of one system.

---

## 10.3 Boot Sequence, Trap, and Lockout

When a kiosk first loads (or is power-cycled), it runs through a visible boot sequence:
checking connectivity to the server, loading its configuration, confirming input is ready,
and finally **arming the trap**. The trap is what keeps the kiosk from being casually backed
out of — it requests fullscreen, blocks the browser's back/reload navigation, and requests a
wake lock so the screen doesn't dim mid-use. It can only be released through the
passcode-gated Admin Panel's "Release Kiosk" button, which also flips the kiosk back into a
full re-boot sequence when re-locked.

Separately, a **lockout screen** appears after 5 failed sign-in attempts, backed by both
`localStorage` and a cookie specifically so a simple page refresh can't be used to bypass it.

> **Hardware note:** the physical kiosk devices were originally iPads and later switched to
> laptops. This is why an earlier "Guided Access" boot step (an iOS-only anti-tamper feature)
> was removed from the live boot sequence, and why the on-screen keyboard was disabled in
> favor of the laptops' real physical keyboards.

---

## 10.4 The PC Floor Map — How the Seat Picker Actually Works

This is one of the more visually distinctive pieces of the whole project, so it's worth
explaining in detail. The PC-room kiosk doesn't show a plain list of machine names — it draws
a genuine top-down floor plan:

- **Five islands**, stacked vertically to fit a portrait screen, each a 3-column × 2-row
  block of seats.
- **A front row** showing the kiosk itself, two doors, a wide central "Stage" area (varsity
  only, shown but never selectable), and the admin desk — all positioned exactly where they
  sit in the real room.
- **Thin vertical rectangles on both side walls** representing the room's TVs, purely for
  spatial accuracy.
- **Seat coloring** that mirrors real machine state: green for available, an amber lock icon
  for a currently-held reservation, a red ✕ overlay for in-use, and a dimmed placeholder for
  a seat not yet wired up in GGLeap.
- **A live wayfinding route** — after picking a seat, the success screen draws an actual
  dashed gold path from the kiosk, along the front walkway, and up into the correct island,
  ending right at the chosen seat, with a subtle marching-ants animation so it reads clearly
  as "walk this way" rather than a static diagram.

All of this sizing is computed with CSS container-query units (`cqw`), which is what lets the
exact same markup fit cleanly on any physical screen size without a single hardcoded pixel
value or a scrollbar ever appearing.

---

## 10.5 Features That Were Tried and Then Removed

Not every idea that gets built stays in the product, and it's worth knowing what was tried
and rolled back so it isn't accidentally rebuilt without re-checking the reasoning:

- **"Welcome back" returning-guest auto-fill** — a chip that looked up a recent visitor by
  email and offered to auto-fill their name. Removed entirely for privacy reasons (the lookup
  endpoint was public and could be used to enumerate who'd visited before). The underlying
  database helper was left in place, unused, in case a properly-authenticated version is
  wanted later.
- **Device health telemetry** (battery %, charging state, network type) — built, then fully
  removed at the requester's explicit instruction. Basic online/offline + last-seen tracking
  was kept since it pre-dated this feature and serves a different purpose (detecting a kiosk
  that's gone offline at all, not monitoring its battery).
- **A gold "Head to the [room]" wayfinding text label** — removed in favor of just the arrow
  icons + the floor-map route line described above, which testing showed was clearer on its
  own.

---

## 10.6 Deploying a Physical Kiosk

Each physical device's browser should be pointed at Nova's live route —
`https://<your-server>/arena/kiosk/<id>` — running in a locked-down, fullscreen kiosk-mode
browser. Do **not** point a real device at the standalone prototype files in `Arena Kiosks/`;
those are historical references only and have no connection to live sign-in data, PC status,
or any of the automation described in [Chapter 9](09_arena_kiosk_system.md).
