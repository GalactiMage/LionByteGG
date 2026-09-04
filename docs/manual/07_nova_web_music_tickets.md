# Chapter 7: Nova — Music Dashboard & Ticket System

## Part 1 — Music Dashboard

**Location:** `LionByteGG/web/app.py` (routes `/music/*` and `/api/music/*`)

### How This Page Is Different From Every Other Page in Nova

Every other feature area in this manual stores its data in a JSON file or a SQLite database
that Nova reads and writes directly. The Music Dashboard doesn't — it's a **live proxy**.
Every request it makes is immediately forwarded to LionBeatsGG's own REST API
(`http://127.0.0.1:3847` by default, see [Chapter 2 §2.6](02_lionbeatsgg.md#26-the-rest-api--how-nova-talks-to-this-bot))
and the response is passed straight back to your browser. There's no caching layer and no
separate database — what you see is exactly what the music bot is doing *right now*.

This has one important consequence: **if LionBeatsGG or Lavalink isn't running, the whole
page will report the bot as offline** rather than showing stale data. That's by design —
every proxied call has a 5-second timeout and gracefully returns
`{"status": "offline", "error": "..."}` instead of throwing an error page.

### Pages
- **`/music/dashboard`**, **`/music/nowplaying`**, **`/music/settings`** — all three render
  the same `music_dashboard.html` template with different default tabs.
- **`/music/features`** — quiz song management, play statistics, history, and panel/command
  reference, on its own template (`music_features.html`).

### What You Can Do From Here
| Action | Route | Notes |
|---|---|---|
| See what's playing everywhere | `GET /api/music/status` | Adds a computed `totalListeners` across all active players |
| Control playback | `POST /api/music/command/<pause\|resume\|skip\|stop>` | Targets the first currently-active player found |
| Fine-grained player control | `POST /api/music/player/<guildId>/<action>` | Volume, shuffle, etc. — body passed straight through to the bot |
| See top tracks / recent activity | `GET /api/music/top-tracks`, `GET /api/music/recent-activity` | Falls back to aggregating raw history client-side if the bot's pre-computed stats are empty |
| Manage quiz songs | `GET/POST/DELETE /api/music/quiz/songs` | Add or remove songs per genre without touching a JSON file by hand |
| Clear history / stats | `POST /api/music/history/clear`, `POST /api/music/stats/clear` | Irreversible — there's no undo |
| Manage locked channels | `GET /api/music/panels`, `DELETE /api/music/panels/<guildId>` | Remove a stale control-panel registration |
| Change bot settings | `GET/PUT /api/music/settings` | Presence text/type, default/max volume, auto-disconnect timer, DJ role |

---

## Part 2 — Ticket System

**Location:** `LionByteGG/web/app.py` (routes `/tickets` and `/api/tickets/*`) · **Data:** `ticket_log.json`

### The Shape of a Ticket

Every ticket — regardless of which Discord bot created it — is stored as one JSON object:

```json
{
  "id": 42,
  "channel_name": "ticket-0042",
  "user": "SomeUser", "user_id": "1234567890",
  "type": "Player Support",
  "first_name": "Alex", "email": "alex@purdue.edu",
  "explanation": "I can't join the tryout voice channel",
  "status": "open",
  "staff_assisting": null,
  "created_at": "2026-09-01T14:22:00Z"
}
```

`data/ticket_log.json` holds three arrays: `open`, `closed`, and `blacklist`. **Important:**
the LionByteGG bot and the BoilerCraftGG bot each maintain their *own* separate
`ticket_log.json` file — the dashboard's main `/tickets` page (this chapter) talks to
LionByteGG's; the BoilerCraft Dashboard's ticket page (see
[Chapter 8 §2](08_nova_web_lionshift_boilercraft_equipment.md#part-2--boilercraft-dashboard))
talks to BoilerCraftGG's. They look identical but are entirely independent data.

### How an Action Here Actually Reaches Discord

The dashboard never talks to the Discord API directly. Every action you take — closing a
ticket, sending a message into one, assigning staff, blacklisting a user — updates
`ticket_log.json` **and** appends an entry to `data/discord_notification_queue.json` with a
`status: "pending"`. The LionByteGG bot polls that same queue every 10 seconds
(`process_discord_notifications`), performs the real Discord action (closing the channel,
posting the message, etc.), and flips the entry's status to `completed` or `failed`. This is
why an action can sometimes take a couple of seconds to visibly happen in Discord after you
click the button in Nova — that's the queue being processed, not a bug.

### What You Can Do
| Action | Route | What happens |
|---|---|---|
| List everything | `GET /api/tickets` | Returns open/closed/blacklist + summary stats |
| Look up one ticket | `GET /api/tickets/<id>` | Matches by numeric ID or channel name |
| Read the full transcript | `GET /api/tickets/transcripts/<id>` | Checks closed tickets first, then open |
| Close a ticket | `POST /api/tickets/<id>/close` | Moves it from `open` to `closed`, queues the Discord channel close |
| Reply inside a ticket | `POST /api/tickets/<id>/message` | Queues the message; optionally pings the original user |
| Assign staff | `POST /api/tickets/<id>/assign` | Sets `staff_assisting` and notifies the ticket channel |
| Blacklist / unblacklist | `POST /api/tickets/blacklist/{add,remove}` | Prevents/re-allows a user from opening new tickets |
| Bulk-delete closed tickets | `DELETE /api/tickets/closed/<id>/delete`, `.../delete-all` | Permanent — there's no recovery for a deleted ticket record |

### Permission Keys Used on This Page
`tickets.close`, `tickets.blacklist`, `tickets.delete_closed`, `tickets.send_message`,
`tickets.assign` — each gates one specific button, so you can give someone the ability to
reply inside tickets without also giving them the ability to permanently delete history.
