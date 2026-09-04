# Chapter 6: Nova — Rosters & Varsity Team Manager

**Location:** `LionByteGG/web/app.py` (roster routes) + `templates/rosters.html`

## What This Page Is For

Rosters is where every esports team — and every player on it — actually lives. It's the tool
that turns "someone filled out a varsity registration form" into "they're on the roster, have
the right Discord roles, and show up in match stats and the leaderboard." It's the single
most feature-dense page in Nova, so this chapter walks through it feature by feature rather
than just listing routes.

---

## 6.1 Players, Teams, and the Multi-Team Model

A player isn't locked to one team. Every player has a `team_ids` list (not just a single
`team_id`) — a coach or a genuinely multi-game player can belong to several teams at once.
The older singular `team_id` field is kept around purely for backward compatibility (it's
automatically kept in sync as "whichever team is first in the list") so nothing that reads
the old field breaks.

**Coaches are a special case.** A player tagged `player_type: "coach"` keeps that type no
matter how many teams they're attached to. Everyone else's type (varsity vs. JV) is inherited
per-team — so the same person could show up as varsity on one roster and JV on another,
which matters for role sync (below).

Team management itself is straightforward CRUD: create a team (`POST /api/rosters/team`,
auto-generates an ID like `team_3_1725480000`), update its fields, delete it (which also
cleans up every player's reference to it so nobody's left pointing at a ghost team), and
drag-and-drop reorder the display order.

---

## 6.2 Assigning Players to Teams — and How Discord Roles Stay in Sync

`POST /api/rosters/assign-team` is the one endpoint that does the real work: given an
`action` of `add`, `remove`, or `set`, it updates a player's `team_ids`, applies the
coach/non-coach type-inheritance rule described above, and **immediately queues a Discord
role-sync notification** for that one player — no separate button needed for a single
assignment.

### The Role Mapping
`data/team_role_settings.json` defines the mapping once:

```json
{
  "mapping": {
    "Valorant": { "varsity": "1234...", "jv": "5678..." }
  },
  "varsity_role_id": "9999...",
  "captain_role_id": "1111...",
  "coach_role_id": "2222..."
}
```

The assignment rules that flow from this are simple once you see them written out:
- **Everyone** on any roster gets the general `varsity_role_id` (think of it as "Esports
  Team Member").
- **Varsity players** additionally get `mapping[game].varsity`.
- **JV players** additionally get `mapping[game].jv`.
- **Captains** additionally get `captain_role_id`.
- **Coaches** get `coach_role_id` **plus** `varsity_role_id`, but never the varsity/JV
  game-specific role (since they're not a player).

### Bulk Syncing
For a full re-sync across the entire roster (say, after a season restructure), use
`POST /api/rosters/sync-roles/preview` first — it's completely read-only and shows you
exactly which roles would be added or removed for every player, with optional game/type
filters, before anything actually happens. Once you're happy, `.../sync-roles/execute` queues
the real job and gives you back a `job_id`. The job runs on the **LionByteGG bot's** side
(it's the one with a live Discord connection), and reports live progress —
completed/added/removed/skipped counts, any errors, current step — into
`data/job_progress.json`, which the dashboard polls so you get a real progress bar instead of
a spinner that might be stuck or might just be slow.

> **This is exactly the kind of job the [Rules to Live By](../NOVA_COMPLETE_GUIDE.md#5-rules-to-live-by--do-this-never-do-that)
> warn you about.** Never stop or restart the LionByteGG bot while a sync job's status is
> still `in_progress` — you'll leave some players with roles half-applied and the job stuck
> forever at "in progress" with no way to resume it, only start over.

---

## 6.3 The Registration → Approval Pipeline

This is the same flow described from the bot's side in
[Chapter 4 §4.5](04_lionbytegg_bot.md#45-varsity--jv-team-registration), but here's what it
looks like from the dashboard:

1. `POST /api/rosters/send-registration` queues a DM to a specific person and hands you back
   a `job_id` so you can poll `GET /api/rosters/registration-status/<job_id>` and confirm the
   DM actually delivered (Discord DMs silently fail if someone has them turned off).
2. Once they've filled out the form on their end, it shows up as a **pending registration**
   in Rosters.
3. `POST /api/rosters/approve` decrypts the submitted PII, adds the player to the roster, and
   queues the correct Discord role assignment. `POST /api/rosters/deny` marks it denied with
   a reason and queues a denial DM.

> **The other Rule to Live By that lives here:** only send one registration DM to a given
> person at a time. Check their pending status before clicking Send again — a second link
> sent while the first is still pending just creates confusion about which one is current,
> and can race against the first submission.

---

## 6.4 Match History, Player Stats, and the Leaderboard

Beyond roster management, this page also tracks actual competitive performance:

- `POST /api/rosters/matches` logs a match result with per-player stats (kills, deaths,
  assists, and whether they were MVP).
- `GET /api/rosters/player/<id>/stats` returns one player's full statistical picture plus
  their recent form.
- `GET /api/rosters/leaderboard` ranks the whole roster by wins, matches played, win rate, or
  MVP count — whichever you ask for.

All of this data lives in `data/match_history.json` and is completely independent of the
registration/role-sync system — you can track stats for a team without ever touching Discord
roles, and vice versa.

---

## 6.5 Announcements, Webhooks, and Bulk DMs

- `GET/POST/DELETE /api/rosters/announcements` — team-wide announcements, optionally posted
  through a configured Discord webhook (`GET/POST /api/rosters/notification-settings`
  manages the webhook URL and which notification types are enabled).
- `POST /api/rosters/send-webhook` sends a real test embed through a webhook so you can
  verify it's configured correctly before relying on it.
- `POST /api/rosters/dm-players` queues a bulk DM to a selected subset of players.

---

## 6.6 Import & Export

`GET /api/rosters/export/csv?type=players|teams` and `POST /api/rosters/import/csv` (with a
`mode` of `merge` or `replace`) let you round-trip the entire roster through a spreadsheet —
useful for bulk edits that are easier to do in Excel than one field at a time in the UI, or
for archiving a season's final roster outside the live system.

---

## 6.7 The Audit Log

Every meaningful change on this page — add, remove, approve, deny, sync — is written to
`data/roster_audit_log.json`, an **immutable, append-only** record capped at roughly 500
entries. `GET /api/rosters/audit-log` supports filtering by action or target, which makes it
the fastest way to answer "who changed this roster and when."

---

## 6.8 Personal Data Is Always Encrypted

Every PII field on a player — Purdue email, personal email, PUID, phone, hometown, year in
school, GPA, major, jersey details, extra notes, uploaded schedule images — is Fernet
encrypted into a single `encrypted_pii` blob before it's ever written to `data/rosters.json`.
`load_rosters()`/`save_rosters()` handle the decrypt/encrypt transparently, so the rest of
the codebase just works with plain dictionaries — but if you ever `cat` the raw JSON file on
disk, you should see ciphertext, never a real email address or phone number. If you ever see
plaintext PII in a JSON file anywhere in this project, that's a bug — flag it immediately.

---

## 6.9 Quick Route Reference

| Area | Routes |
|---|---|
| Core | `GET /api/rosters` |
| Players | `POST/DELETE /api/rosters/player`, `POST /api/rosters/captain`, `POST /api/rosters/player/status`, `POST /api/rosters/bulk/{status,type,team,delete}` |
| Teams | `POST /api/rosters/team`, `POST /api/rosters/team/update`, `POST /api/rosters/teams/reorder`, `DELETE /api/rosters/team` |
| Assignment | `POST /api/rosters/assign-team`, `GET /api/rosters/coaches`, `GET /api/rosters/captains` |
| Registration | `POST /api/rosters/send-registration`, `GET /api/rosters/registration-status/<job_id>`, `POST /api/rosters/approve`, `POST /api/rosters/deny` |
| Stats | `GET/POST/DELETE /api/rosters/matches`, `GET /api/rosters/player/<id>/stats`, `GET /api/rosters/leaderboard` |
| Role Sync | `POST /api/rosters/sync-roles/preview`, `POST /api/rosters/sync-roles/execute` |
| Comms | `GET/POST/DELETE /api/rosters/announcements`, `GET/POST /api/rosters/notification-settings`, `POST /api/rosters/send-webhook`, `POST /api/rosters/dm-players` |
| Import/Export | `GET /api/rosters/export/csv`, `POST /api/rosters/import/csv` |
| Audit | `GET /api/rosters/audit-log` |
