# Chapter 2: LionBeatsGG — The Music Bot

**Location:** `LionBeatsGG/` · **Language:** Node.js (discord.js v14.25.1) · **Audio Engine:** Lavalink (Java)

## What This Bot Is For

LionBeatsGG plays music in voice channels — YouTube, Spotify, and SoundCloud — with a
persistent on-screen control panel, bass boost, synced lyrics, and a genuinely fun
music-guessing quiz game. Unlike the other three bots, it's built in JavaScript on top of
**discord.js**, and it depends on a separate process called **Lavalink** to actually decode
and stream audio. If Lavalink isn't running, the bot itself will start fine but every
`/play` will fail — that's the #1 thing to check when music "just doesn't work."

---

## 2.1 The Two-Process Architecture

```
LionBeatsGG/
├── bot/            ← the Discord bot itself (Node.js)
└── lavalink/        ← the audio server (Java) — Lavalink.jar + plugins
```

Both processes must be running together. `start-all.bat` handles this correctly: it launches
`Lavalink.jar` in its own window first, waits 5 seconds for it to finish initializing, *then*
starts the bot via `run-bot.bat`. `stop-all.bat` reverses it — kills the bot process (window
titled `LionBeatsGG Bot*`, or any `node.exe` running `index.js`) and then Lavalink (window
titled `Lavalink*`, or any `java.exe`).

`bot/run-bot.bat` is itself a tiny auto-restart wrapper: it loops `node src/index.js` forever,
waiting 5 seconds between restarts if the process ever exits unexpectedly. Press Ctrl+C to
actually stop it for good.

### Configuration (`bot/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `DISCORD_TOKEN` | *(required)* | Bot token |
| `LAVALINK_HOST` | `127.0.0.1` | Where Lavalink is listening |
| `LAVALINK_PORT` | `2333` | Lavalink's port |
| `LAVALINK_PASSWORD` | *(required)* | Shared secret between bot and Lavalink — must match `lavalink/application.yml` exactly |
| `BOT_NAME` | `LionBeatsGG` | Cosmetic |
| `PREFIX` | `!` | Prefix-command character |
| `API_PORT` | `3847` | The port Nova's Music Dashboard talks to (see §2.6) |

Lavalink's own config (`lavalink/application.yml`) controls which audio sources are enabled
(YouTube and Spotify search via the `lavasrc` plugin, plus SoundCloud and direct HTTP URLs
are on; Bandcamp/Twitch/Vimeo/local files are off), the Spotify search chain (tries an ISRC
match first, then falls back to a YouTube search), and playlist/album load limits (100 tracks
each).

---

## 2.2 Slash & Prefix Commands

| Command | Type | What it does |
|---|---|---|
| `/play <query>` | slash | Validates you're in a voice channel, searches YouTube/Spotify via Lavalink, handles both single tracks and full playlists, starts playing if nothing else is queued |
| `/quiz <genre> <rounds?>` | slash | Starts the music-guessing game (see §2.4) |
| `/set-activity <activity> <type?>` | slash, passcode-gated | Overrides the bot's Discord status text |
| `/set-default` | slash, passcode-gated | Resets the status back to "Listening to LionBeatsGG 🎵" |
| `/restart` | slash, Administrator only | `process.exit(0)` — the run-bot.bat wrapper auto-restarts it |
| `!play <query>` | prefix | Same as `/play`, with a 5-second per-user cooldown |
| `!skip` / `!stop` / `!queue` / `!nowplaying` (or `!np`) | prefix | Standard playback controls |

**The passcode:** `/set-activity` and `/set-default` are gated behind a 6-digit code modal
(hardcoded `146332`) rather than a Discord permission check — a deliberate, lightweight
guard against someone accidentally fat-fingering the bot's status.

---

## 2.3 The Persistent Control Panel

Running **`/lock-channel <channel>`** turns a text channel into a dedicated music request
channel: the bot posts a live-updating embed (refreshed every 15 seconds, paused during an
active quiz round) with two rows of buttons —

**Row 1:** ⏮️ Previous · ▶️/⏸️ Play/Pause · ⏹️ Stop · ⏭️ Skip · 📜 Queue
**Row 2:** 🔁 Loop (cycles Off → Track → Queue) · 🗑️ Clear Queue · 🔊 Volume (cycles
100%→75%→50%→25%) · 🎚️ Bass Boost · 📝 Lyrics

Once locked, **any plain text message** typed in that channel (that isn't a command) is
treated as a song search or URL and queued automatically — you don't even need to type
`/play`. Non-command messages get auto-deleted 5 seconds later to keep the channel tidy.
Every button requires the clicker to actually be in the same voice channel as the bot, and
enforces a 5-second per-user cooldown to prevent spam-clicking.

`/unlock-channel` removes the lock and stops the message-interception behavior.

### Bass Boost, Volume, and Lyrics — the details worth knowing
- **Bass boost** applies a 4-band EQ boost (+0.2, +0.15, +0.1, +0.05 gain on the lowest four
  bands) via Lavalink's filter API — it's a real audio filter, not a fake "louder" toggle.
- **Volume is scaled.** The button shows friendly percentages (100/75/50/25%) but the actual
  value sent to Lavalink is capped at 40 (Lavalink's scale runs 0–200, but this bot
  deliberately caps the effective ceiling to avoid blasting audio at max gain).
- **Lyrics** are fetched from `lrclib.net` first (free, no API key, best match accuracy),
  falling back to a secondary lrclib search and then the Lyrist API if the exact
  artist/title combination doesn't match. Track titles are cleaned of clutter like
  `(Official Video)` or `[Lyrics]` before searching. Long lyrics get truncated around 3,900
  characters with a "continued" marker (Discord embeds have a hard character limit).

---

## 2.4 The Music Quiz Game

`/quiz <genre> <rounds>` (genres: pop, anime, romance, rock, rnb, hiphop, edm; 1–10 rounds,
default 5) is a proper party game, not a gimmick:

1. The bot fetches more candidate songs than it needs (accounting for some inevitably
   failing to find a match on Lavalink) and searches each one — anime songs search YouTube
   first (better match rate for OSTs), everything else tries Spotify first.
2. For each round, it plays a 30-second clip and opens a message collector that listens for
   guesses in chat.
3. Answers are matched with real fuzzy logic, not exact string matching: it accepts the
   title, the artist, the anime name (for anime genre), or any individual significant word
   from a multi-word title, and tolerates roughly 20% character-level typos via Levenshtein
   distance.
4. The first three correct guessers each round score points — 🥇 3, 🥈 2, 🥉 1 — and a full
   leaderboard is announced at the end.

---

## 2.5 Error Handling & Resilience

The bot is built to never crash from a bad track or a flaky connection:
- `trackError` and `trackStuck` events log the failure, notify the channel, and
  automatically skip to the next track.
- `unhandledRejection` and `uncaughtException` are caught at the process level and logged —
  they never bring the whole bot down.
- If the bot ends up alone in a voice channel, or the queue runs out entirely, a 20-minute
  inactivity timer kicks in before it auto-disconnects (clearing history/queue state as it
  goes).
- On a Discord gateway reconnect (`shardResume`), the bot reloads all its saved music panels
  so the control-panel embeds keep working seamlessly.

---

## 2.6 The REST API — How Nova Talks to This Bot

Unlike the other three bots, LionBeatsGG doesn't communicate with the web dashboard through
shared JSON files — it runs its own small HTTP server (default port **3847**, CORS-enabled)
that Nova's Music Dashboard calls directly and proxies through to your browser. This means
the dashboard is always showing genuinely live data, not a stale cache.

| Method & Path | What it returns / does |
|---|---|
| `GET /api/status` | Uptime, active player count, current track + queue per guild |
| `GET /api/health` | Simple heartbeat check |
| `GET /api/history?limit=N` | Recent play history |
| `POST /api/history/clear` | Wipes play history |
| `GET /api/stats` | Total plays, top 20 songs, top 20 requesters, hourly/daily activity |
| `POST /api/stats/clear` | Resets all statistics |
| `GET`/`POST`/`DELETE /api/quiz/songs` | View, add, or remove quiz songs by genre |
| `GET /api/panels` / `DELETE /api/panels/<guildId>` | Manage locked control-panel channels |
| `POST /api/player/<guildId>/<action>` | Remote control: pause/resume/skip/stop/volume/shuffle/clear |
| `GET`/`PUT /api/settings` | Bot presence text/type, default/max volume, auto-disconnect timer, DJ role |
| `GET /api/commands` | Full command reference, used to render the in-dashboard command list |

If the Music Dashboard ever shows "Music bot is not running" or "did not respond in time,"
it's this HTTP server that's unreachable — check that both the bot process *and* Lavalink are
actually running, and that nothing else on the machine is using port 3847.

---

## 2.7 Data Files

| File | Contains |
|---|---|
| `bot/data/music-panels.json` | Which channel/message each guild's control panel lives in |
| `bot/data/play-history.json` | Last 1,000 plays (title, artist, artwork, requester, timestamp) |
| `bot/data/music-stats.json` | Aggregated top songs/requesters + hourly/daily activity |
| `bot/data/bot-settings.json` | Presence text/type, volume defaults, auto-disconnect minutes, DJ role |
| `bot/data/quiz-songs.json` | The full quiz question bank, organized by genre |
