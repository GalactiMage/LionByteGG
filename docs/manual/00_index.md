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
