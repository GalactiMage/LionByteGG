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
looks like from the dashboard, plus what the actual form looks like on the recruit's end —
worth reading both halves together if you're the one sending these out.

1. `POST /api/rosters/send-registration` queues a DM to a specific person and hands you back
   a `job_id` so you can poll `GET /api/rosters/registration-status/<job_id>` and confirm the
   DM actually delivered (Discord DMs silently fail if someone has them turned off — a
   `job_id` stuck at "pending" or "failed" instead of "delivered" is exactly that scenario).
2. The recruit receives a DM with a **"Start Registration"** button, picks their primary
   game from a dropdown (pulled live from whatever's configured in Settings → Esports Games),
   and then works through **15 questions across 3 separate pop-up forms** — full name, both
   a Purdue and a personal email, phone, PUID, GPA, hometown, year in school, major, jersey
   size/name, in-game name, rank, primary role, a stats-tracker link, and an optional
   free-text notes field. See [Chapter 4 §4.5.3](04_lionbytegg_bot.md#453-steps-24--the-three-modals-every-default-question-in-order)
   for the complete question-by-question list with the exact wording shown to the recruit.
3. **There's one more step after the forms that's easy to forget about:** the recruit is
   asked to DM the bot a photo of their class schedule, with a strict 3-minute window to do
   so. If they miss that window, the registration silently never completes — nothing shows
   up in Rosters at all, and no error is shown to you. If someone insists they finished the
   form but you don't see a pending registration for them, this is almost always why —
   re-send them a fresh link rather than troubleshooting further.
4. Once they do send the schedule photo, it shows up as a **pending registration** in
   Rosters, along with a matching post in the `#varsity-registrations` Discord channel with
   its own Approve/Deny buttons — either surface can be used to review it, they both operate
   on the same underlying record.
5. `POST /api/rosters/approve` decrypts the submitted PII, adds the player to the roster, and
   queues the correct Discord role assignment. `POST /api/rosters/deny` marks it denied with
   a reason and queues a denial DM back to the recruit explaining why.

### Changing What Gets Asked
The 15 default questions are **not configurable from Nova** — there's no settings page or
config file for this. They're hardcoded Discord modal forms defined directly in the
LionByteGG bot's source code (`views/varsity_view.py`). If your organization needs to
add, remove, or reword a question, that requires a code change and a bot restart — the exact
steps (including Discord's hard 5-fields-per-modal limit and where to also update the review
embed so reviewers can actually see a newly added answer) are documented in
[Chapter 4 §4.5.7](04_lionbytegg_bot.md#457-how-to-change-the-registration-questions).

> **The other Rule to Live By that lives here:** only send one registration DM to a given
> person at a time. Check their pending status before clicking Send again — a second link
> sent while the first is still pending just creates confusion about which one is current,
> and can race against the first submission. This matters even more now that you know the
> schedule-photo step has a hard timeout — a recruit who's slow to respond to the first link
> might still complete it after you've already sent a second one, and now there are two
> competing registrations to sort out.

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

---

## 6.10 Example Data Shapes

**A player record (`rosters.json`, decrypted view)**
```json
{
  "id": "player_9f2a", "name": "Alex Smith", "ign": "ProGamer123",
  "game": "Valorant", "rank": "Diamond 2",
  "team_ids": ["team_3_1725480000"], "team_id": "team_3_1725480000",
  "player_type": "varsity", "position": "Duelist", "status": "active",
  "is_captain": false,
  "encrypted_pii": "gAAAAABm...(Fernet ciphertext, truncated)..."
}
```
The PII fields you'd see if you decrypted `encrypted_pii` for the record above:
```json
{
  "purdue_email": "asmith@purdue.edu", "personal_email": "alexsmith@gmail.com",
  "puid": "0012345678", "phone": "123-456-7890",
  "hometown": "Hammond, IN", "year_in_school": "Sophomore",
  "major": "Computer Science", "gpa": "3.4",
  "jersey_details": "Large - SMITH"
}
```

**A team record (`teams.json`)**
```json
{
  "id": "team_3_1725480000", "name": "Valorant Varsity A", "game": "Valorant",
  "logo_url": "https://.../valorant-logo.png", "coach": "555666777888999000",
  "members": ["player_9f2a", "player_1b3c"], "created_at": "2026-01-15T00:00:00Z"
}
```

**A match history entry (`match_history.json`)**
```json
{
  "id": "match_0042", "team_id": "team_3_1725480000", "opponent": "Rival University",
  "result": "win", "date": "2026-09-01",
  "player_stats": [
    { "player_id": "player_9f2a", "kills": 22, "deaths": 14, "assists": 5, "mvp": true }
  ]
}
```

---

## 6.11 Frequently Asked Questions

**"I approved a registration but the player didn't get any Discord roles."**
Check `data/team_role_settings.json` actually has a mapping entry for that player's specific
game — if the game name doesn't exactly match a key in `mapping`, the sync has nothing to
apply for the game-specific varsity/JV role (they'd still get the general `varsity_role_id`,
but not the per-game one). Game names are matched by exact string, so a typo or casing
mismatch between the roster's `game` field and the settings mapping is the most common cause.

**"Can I un-approve someone after the fact?"**
There's no dedicated "un-approve" endpoint — removing someone from the team entirely is done
via `DELETE /api/rosters/player`, and reversing their Discord roles would need a manual
`sync-roles` pass after removing them from every `team_ids` entry (since the sync only grants
roles for teams they're currently on).

**"What happens to match stats if I delete a player?"**
`match_history.json` records reference players by `player_id`, and deleting a player doesn't
retroactively scrub historical match entries — their past stats remain in the match history
(useful for season records), they just won't appear in the live roster or current
leaderboard rankings tied to an active player.

**"Does the CSV export include encrypted PII in plain text?"**
Yes, intentionally — the export is meant for legitimate administrative use (e.g., handing a
real roster to a coach), so PII fields are decrypted for the export. Treat exported CSV
files with the same care as any other document containing personal information; they are
**not** automatically re-encrypted or protected once outside the system.

**"Why does `sync-roles/preview` sometimes show a role change I didn't expect?"**
It's genuinely comparing every player's *current* Discord roles against what they *should*
have based on today's roster/team-settings configuration — if `team_role_settings.json` was
edited recently (e.g. a role ID changed), the preview will show a full recalculation against
the new mapping, including changes unrelated to whatever specific edit you just made. Read
the whole preview before executing a bulk sync, not just the part you expected to change.
