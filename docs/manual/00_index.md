# The LionByteGG Suite — Complete Reference Manual

Welcome to the full technical manual for the LionByteGG ecosystem. This is the deep-dive
companion to [docs/NOVA_COMPLETE_GUIDE.md](../NOVA_COMPLETE_GUIDE.md) (which covers the
website day-to-day) — here you'll find **every bot, every cog, every command, every web
route, and every setting**, explained in plain language with real examples and step-by-step
walkthroughs of how each system actually behaves.

Read it straight through if you're learning the whole system for the first time, or jump
straight to the chapter you need. Each chapter is a self-contained Markdown file, so it
renders cleanly right here on GitHub.

---

## Table of Contents

| # | Chapter | What's Inside |
|---|---|---|
| 1 | [BoilerCraftGG](01_boilercraftgg.md) | The Minecraft/Purdue Network bot — student verification, temp voice channels, ticket system, chat monitoring |
| 2 | [LionBeatsGG](02_lionbeatsgg.md) | The music bot — Lavalink integration, control panel, quiz game, REST API |
| 3 | [LionShiftGG](03_lionshiftgg.md) | The arena shift-scheduling bot — clock in/out, offers, trades, reminders |
| 4 | [LionByteGG Bot](04_lionbytegg_bot.md) | The flagship bot — onboarding, moderation, varsity teams, voice channels |
| 5 | [Nova — Auth, Admin & Core Pages](05_nova_web_auth_admin.md) | The web dashboard's login system, permissions, admin panel, and everyday pages |
| 6 | [Nova — Rosters & Varsity](06_nova_web_rosters_varsity.md) | The team/player manager — multi-team assignment, Discord role sync, stats, CSV |
| 7 | [Nova — Music & Tickets](07_nova_web_music_tickets.md) | The music dashboard proxy and the ticket support system |
| 8 | [Nova — LionShift, BoilerCraft & Equipment](08_nova_web_lionshift_boilercraft_equipment.md) | The shift/Minecraft admin dashboards and the equipment/QR inventory system |
| 9 | [Arena Kiosk System](09_arena_kiosk_system.md) | The full backend behind the physical sign-in kiosks — the most complex subsystem |
| 10 | [Arena Kiosk — Physical Devices](10_arena_kiosk_physical_devices.md) | The actual kiosk screens, floor maps, and hardware notes |
| 11 | [Troubleshooting & Operations Guide](11_troubleshooting_and_operations_guide.md) | Startup/shutdown procedures, a full settings glossary, and every known gotcha with its fix |

---

## 🔎 Find It Fast — Search the Manual by Topic

Looking for one specific thing and don't want to read a whole chapter? This index is
alphabetized by keyword — use your browser's **Ctrl+F / Cmd+F** to jump straight to a term,
then click through to the exact chapter (and section) that covers it in full.

| Keyword / Topic | Where to find it |
|---|---|
| Admin panel (`/admin`, users, groups) | [Ch. 5 §5.4](05_nova_web_auth_admin.md) |
| Analytics (arena traffic, heatmaps) | [Ch. 9 §9.8](09_arena_kiosk_system.md) |
| Analytics (member/moderation stats) | [Ch. 5 §5.5](05_nova_web_auth_admin.md) |
| Analytics export (BoilerCraft, Excel) | [Ch. 8 Part 2](08_nova_web_lionshift_boilercraft_equipment.md) |
| Announcement bar (kiosk banner) | [Ch. 9 §9.7](09_arena_kiosk_system.md) |
| AutoMod (Discord native + word tiers) | [Ch. 4 §4.3](04_lionbytegg_bot.md) |
| Auto-start on boot | [Ch. 11 §11.2](11_troubleshooting_and_operations_guide.md) |
| Ban / watch list (arena guests) | [Ch. 9 §9.6](09_arena_kiosk_system.md) |
| Bass boost (music EQ) | [Ch. 2 §2.3](02_lionbeatsgg.md) |
| BoilerCraft dashboard | [Ch. 8 Part 2](08_nova_web_lionshift_boilercraft_equipment.md) |
| BoilerWatch (Minecraft chat monitor) | [Ch. 1 §1.4](01_boilercraftgg.md), [Ch. 8 Part 2](08_nova_web_lionshift_boilercraft_equipment.md) |
| Bot presence / activity status | [Ch. 5 §5.6](05_nova_web_auth_admin.md) |
| Captains & coaches (multi-team) | [Ch. 6 §6.1](06_nova_web_rosters_varsity.md) |
| Chat monitor / flagged words (Minecraft) | [Ch. 1 §1.4](01_boilercraftgg.md) |
| Clock in / clock out (shifts) | [Ch. 3 §3.2](03_lionshiftgg.md) |
| Discord role sync (varsity/JV) | [Ch. 6 §6.2](06_nova_web_rosters_varsity.md) |
| Ethernet / static IP / network recovery | [Ch. 11 §11.3](11_troubleshooting_and_operations_guide.md) |
| Equipment / inventory / QR codes | [Ch. 8 Part 3](08_nova_web_lionshift_boilercraft_equipment.md) |
| Fernet encryption (PII) | [Ch. 4 §4.7](04_lionbytegg_bot.md), [Ch. 6 §6.8](06_nova_web_rosters_varsity.md), [Ch. 9 §9.5](09_arena_kiosk_system.md), [Ch. 11 §11.9](11_troubleshooting_and_operations_guide.md) |
| Floor map / seat picker (arena PCs) | [Ch. 10 §10.4](10_arena_kiosk_physical_devices.md) |
| GGLeap API (shared cache, quota) | [Ch. 9 §9.2](09_arena_kiosk_system.md) |
| GGLeap games/status panels (Discord) | [Ch. 4 §4.8](04_lionbytegg_bot.md) |
| Guest access (30-day timer) | [Ch. 4 §4.2](04_lionbytegg_bot.md) |
| Incident reports (arena) | [Ch. 9 §9.9](09_arena_kiosk_system.md) |
| Job progress tracking (bulk sync/DM) | [Ch. 6 §6.2](06_nova_web_rosters_varsity.md) |
| Kiosk boot sequence / trap / lockout | [Ch. 10 §10.3](10_arena_kiosk_physical_devices.md) |
| Lavalink (music audio server) | [Ch. 2 §2.1](02_lionbeatsgg.md) |
| Leaderboard (match stats) | [Ch. 6 §6.4](06_nova_web_rosters_varsity.md) |
| Login (dashboard vs. legacy) | [Ch. 5 §5.1](05_nova_web_auth_admin.md) |
| Lyrics (music bot) | [Ch. 2 §2.3](02_lionbeatsgg.md) |
| Master Terminal (GUI control panel) | [Ch. 4 §4.1](04_lionbytegg_bot.md), [Ch. 11 §11.1](11_troubleshooting_and_operations_guide.md) |
| Moderation (warn/kick/ban) | [Ch. 4 §4.3](04_lionbytegg_bot.md), [Ch. 5 §5.5](05_nova_web_auth_admin.md) |
| Multi-team assignment (rosters) | [Ch. 6 §6.1](06_nova_web_rosters_varsity.md) |
| Notification queues (bot ↔ web bridge) | [Ch. 3 §3.6](03_lionshiftgg.md), [Ch. 7 Part 2](07_nova_web_music_tickets.md), [Ch. 11 §11.8](11_troubleshooting_and_operations_guide.md) |
| Onboarding (Student / Guest setup) | [Ch. 4 §4.2](04_lionbytegg_bot.md) |
| Permissions system (keys, groups) | [Ch. 5 §5.3](05_nova_web_auth_admin.md) |
| PC hold / reservation (kiosk) | [Ch. 9 §9.3](09_arena_kiosk_system.md) |
| PC screen-lock automation | [Ch. 9 §9.4](09_arena_kiosk_system.md) |
| Quiz game (music bot) | [Ch. 2 §2.4](02_lionbeatsgg.md) |
| Reaction roles | [Ch. 4 §4.9](04_lionbytegg_bot.md), [Ch. 5 §5.5](05_nova_web_auth_admin.md) |
| Registration (varsity/JV approval flow) | [Ch. 4 §4.5](04_lionbytegg_bot.md), [Ch. 6 §6.3](06_nova_web_rosters_varsity.md) |
| Registration questions (default list, how to change) | [Ch. 4 §4.5.3, §4.5.7](04_lionbytegg_bot.md) |
| Registration schedule-photo step (180s timeout) | [Ch. 4 §4.5.4](04_lionbytegg_bot.md) |
| REST API (LionBeatsGG) | [Ch. 2 §2.6](02_lionbeatsgg.md) |
| Restarting a stuck machine/service | [Ch. 11 §11.3](11_troubleshooting_and_operations_guide.md) |
| Rooms & shift duties (LionShift) | [Ch. 8 Part 1](08_nova_web_lionshift_boilercraft_equipment.md) |
| Schedule image generator | [Ch. 3 §3.7](03_lionshiftgg.md) |
| Search (global, in Nova) | [Ch. 5 §5.5](05_nova_web_auth_admin.md) |
| Settings glossary (every config key) | [Ch. 11 §11.7](11_troubleshooting_and_operations_guide.md) |
| Shift offers & trades | [Ch. 3 §3.3](03_lionshiftgg.md) |
| Sign-in guard (anti-spam) | [Ch. 9 §9.6](09_arena_kiosk_system.md) |
| Starting/stopping services | [Ch. 11 §11.1, §11.4](11_troubleshooting_and_operations_guide.md) |
| Student profiles (arena) | [Ch. 9 §9.9](09_arena_kiosk_system.md) |
| Temp voice channels / Join-to-Create | [Ch. 1 §1.4](01_boilercraftgg.md), [Ch. 4 §4.4](04_lionbytegg_bot.md) |
| Tickets (support system) | [Ch. 1 §1.5](01_boilercraftgg.md), [Ch. 4 §4.9](04_lionbytegg_bot.md), [Ch. 7 Part 2](07_nova_web_music_tickets.md) |
| Time-off requests | [Ch. 3 §3.4](03_lionshiftgg.md) |
| Verification (Discord ↔ Minecraft) | [Ch. 1 §1.4](01_boilercraftgg.md) |
| Watchlist (member surveillance) | [Ch. 4 §4.6](04_lionbytegg_bot.md) |
| Worker hours calculation | [Ch. 8 Part 1](08_nova_web_lionshift_boilercraft_equipment.md) |

---

## How This Manual Is Organized

The LionByteGG suite is really **four separate Discord bots plus one web dashboard**, all
talking to each other through a shared folder of JSON "mailbox" files (and, for the music
bot, a small REST API). Understanding that shape makes the rest of this manual much easier
to follow:

```
┌───────────────┐     ┌────────────────┐     ┌───────────────┐     ┌──────────────┐
│  BoilerCraftGG │     │  LionShiftGG   │     │  LionByteGG    │     │ LionBeatsGG  │
│  (Minecraft)   │     │  (Shifts)      │     │  (Flagship bot)│     │  (Music)     │
└───────┬───────┘     └───────┬────────┘     └───────┬───────┘     └──────┬───────┘
        │  dashboard_commands   │ notification_queue     │ notification_queue │ REST API
        │  .json (its own data/)│ .json (shared data/)    │ .json (shared data/)│ :3847
        └──────────┐            └──────────┐              └──────────┐         │
                    ▼                       ▼                        ▼         ▼
              ┌─────────────────────────────────────────────────────────────────┐
              │                     Nova — the web dashboard                    │
              │                 (LionByteGG/web/app.py, Flask)                  │
              └─────────────────────────────────────────────────────────────────┘
```

Each bot **writes** status/cache files that Nova reads to show live information, and Nova
**writes** small "please do this" queue files that each bot polls every few seconds and
acts on. Nothing talks to the Discord API directly from the browser — every Discord action
a staff member takes in Nova is actually queued and carried out by the relevant bot. Keep
this pattern in mind; it explains almost every "why does it work this way" question in the
chapters that follow.

---

## Who Should Read What

- **New student worker / staff member** learning the website → start with
  [docs/NOVA_COMPLETE_GUIDE.md](../NOVA_COMPLETE_GUIDE.md), then come back here for anything
  you want to understand more deeply.
- **Developer picking up the codebase** → read this whole manual once, front to back. It's
  written to be a complete mental model of the system, not just an API reference.
- **Someone debugging a specific bot** → jump straight to that bot's chapter (1–4).
- **Someone debugging the website** → chapters 5–10 cover every page and feature area.
- **Something broke and you need an answer fast** → [Chapter 11](11_troubleshooting_and_operations_guide.md).
- **Sending out varsity/JV registrations** → read [Chapter 4 §4.5](04_lionbytegg_bot.md) in
  full before sending your first one — it explains all 15 default questions, the easy-to-miss
  schedule-photo step with its 3-minute timeout, and exactly how to customize the questions
  if your program needs different ones.

---

## A Note on How This Manual Was Written

Every fact in this manual was verified directly against the actual source code, not guessed
or inferred from naming conventions alone — file paths, function names, default values,
timeouts, and permission keys are all taken from the real files as they exist in this
repository at the time each chapter was written. Where something is a genuine known
limitation of a third-party platform (like GGLeap's lack of a clean PC-unlock API, see
[Chapter 9 §9.4](09_arena_kiosk_system.md)) rather than a bug in this codebase, that
distinction is called out explicitly rather than left ambiguous.

If you make a code change that affects behavior described here, please update the relevant
chapter in the same change — a manual that drifts out of sync with the actual system is
worse than no manual at all. Each chapter is a plain Markdown file; there's no build step,
no special syntax beyond standard GitHub-flavored Markdown, and no reason not to keep it
current.
