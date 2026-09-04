# Chapter 5: Nova — Auth, Admin & Core Pages

**Location:** `LionByteGG/web/app.py` (Flask) · **Run:** `python run.py --production` (waitress) · **Default URL:** `http://127.0.0.1:5000`

## What "Nova" Is

Nova is the name of the web dashboard — one Flask application that every staff member logs
into to control every bot in the suite. This chapter covers the foundation everything else
is built on: how login works, how permissions are checked on every single request, the admin
panel where accounts and groups are managed, and the everyday pages (Dashboard, Moderation,
Users, Tickets, Settings, Logs, Members, Varsity, Analytics, Reaction Roles, VC System).

---

## 5.1 The Two Kinds of Login

Nova supports two completely different authentication paths, and understanding both matters
because they behave slightly differently in a few places:

1. **Dashboard users** — real accounts created in `/admin`, each belonging to a **permission
   group**. This is what almost everyone should be using day to day. Their session stores
   `dashboard_user` (their profile) and `dashboard_permissions` (their resolved permission
   list).
2. **Legacy login** — an older, security-code-based login that predates the group system and
   grants **full access to absolutely everything**. It still exists for break-glass
   emergency access, but new staff should always get a proper dashboard account instead.

There's also a **Bearer token** path (`Authorization: Bearer {SECURITY_CODE}`) for API-only
access — used by external scripts/tests, never by a human clicking around in a browser.

### The Permission-Checking Decorators
Every single route in `app.py` is wrapped in one of these, and it's worth knowing the
difference since it explains a lot of "why can I see this page but not use this button"
situations:

| Decorator | Used on | What happens if you fail the check |
|---|---|---|
| `@login_required` | Page routes | Redirected to `/login` |
| `@api_auth_required` | API routes | `401 Unauthorized` JSON response |
| `@admin_required` | Admin-only routes | `403 Forbidden` |
| `@page_permission_required(key)` | Page routes needing a specific permission | Redirected to smart-landing (`/home`) |
| `@api_perm_required(key)` | API routes needing a specific permission | `403 Forbidden` JSON response |

Full-access users (legacy login, or a dashboard admin) skip every one of these checks
automatically — they're never blocked by a missing permission key.

---

## 5.2 Logging In, and Where You Land

Visiting `/` redirects you to `/home` if you're logged in, or `/login` if not. `/login`
itself has a client-side pre-flight check — `POST /api/validate-login` verifies your
credentials **without creating a session yet**, so the form can show an inline error before
committing to a real login.

`/home` (function name `smart_landing`) is the interesting part: it doesn't just dump you on
one fixed page. It checks your resolved permissions against every bot section in priority
order — LionByteGG → BoilerCraft → LionShift → LionBeats → Arena — and lands you on the
**first page within the first section** you actually have access to. A full-access user goes
straight to `/dashboard` (or `/admin`, if they have `admin.panel`). If you have *no* matching
permission anywhere, you're bounced back to `/login?error=no_dashboard_access`.

> **The one gotcha everyone eventually hits:** each section needs its own specific "main
> dashboard" permission for `smart_landing` (and the bot-switcher dropdown) to route into it
> at all — `page.dashboard` for LionByteGG, `page.boilercraft` for BoilerCraft,
> `page.shift_dashboard` for LionShift, `page.music_dashboard` for LionBeats. A group can
> have every individual page permission for a section and still get routed *past* it if this
> one specific key is missing. If someone reports "the section switcher doesn't work for
> me," check this first.

---

## 5.3 The Permission System, in Full

Every permission key follows one of four patterns:

| Pattern | Meaning | Example |
|---|---|---|
| `section.NAME` | Shows an entire bot's section header in the sidebar | `section.arena` |
| `page.NAME` | Makes one specific page's nav link render, and makes its route reachable | `page.rosters` |
| `NAME.action` | A specific in-page capability, independent from just viewing | `arena.manage`, `moderation.warn` |
| `admin.panel` | Full bypass — reserved for true administrators | — |

**Why split view-permissions from action-permissions?** So you can build a "read-only"
volunteer role. A good real example from the Arena section: `page.arena_students` lets
someone *view* student profiles, but `arena.ban` (adding someone to the watch/ban list) and
`arena.students_manage` (deleting a student's whole history) are separate keys — you can
give a new staff member visibility without also giving them the ability to permanently erase
records.

### Groups
Everything is managed through **groups** in `/admin` — you don't assign permissions to
individual users directly, you put them in a group and edit the group's permission list.
Built-in presets exist (e.g. "Student Workers", "Supervisors") as sensible starting points.

> **Historical note, fixed:** an early version of the seeding logic used to hard-reset every
> preset group's permissions back to its default on *every server restart*, silently undoing
> any customization an admin had made. This was fixed — seeding now only ever touches a group
> that currently has **zero** permissions or doesn't exist yet. Once a preset group has any
> permissions saved, a restart will never touch it again.

---

## 5.4 The Admin Panel (`/admin`)

Requires `admin.panel` (or full access). This single page manages:

- **Users** — `GET/POST/PUT/DELETE /api/admin/users`, plus a dedicated
  `PUT /api/admin/users/<id>/password` for forcing a reset. Safeguards are baked in: you
  cannot delete your own account, and you cannot delete the last remaining admin account —
  Nova refuses both with a clear error rather than letting you lock yourself out.
- **Groups** — `GET/POST/PUT/DELETE /api/admin/groups`, and `GET /api/admin/permissions`
  returns every valid permission key so the group editor can render checkboxes for all of
  them automatically (no code changes needed when you add a new group).
- **Self-service password change** — any dashboard user (not legacy-login) can change their
  own password via `POST /api/account/change-password`, which requires re-entering their
  current password first.

---

## 5.5 The Everyday Pages

| Page | Permission | What you can do there |
|---|---|---|
| **Dashboard** | `page.dashboard` | Bot status, quick moderation stats, recent activity feed, a patch-notes banner, and a global search bar |
| **Moderation** | `page.moderation` | Search any user's record, issue warnings, remove specific past entries, bulk actions, CSV export |
| **Users** | `page.users` | Full member directory, full profile view (records/guest status/varsity status), send a DM, add a note |
| **Tickets** | `page.tickets` | See [Chapter 7](07_nova_web_music_tickets.md) |
| **Settings** | `page.settings` | Arena hours, esports game list, team→role mapping, the 3-tier flagged-word lists, bot presence text |
| **Logs** | `page.logs` | The unified activity log — every login, every moderation action, every admin change, every bot action, filterable and exportable |
| **Members** | `page.members` | The guild member directory |
| **Varsity** | `page.varsity` | The registration approval queue |
| **Analytics** | `page.analytics` | Member counts, moderation totals, varsity approval breakdown, top roles |
| **Reaction Roles** | `page.reaction_roles` | Build/edit reaction-role panels |
| **VC System** | `page.vc_system` | View/manage voice channel generators |
| **Rosters** | `page.rosters` | See [Chapter 6](06_nova_web_rosters_varsity.md) |
| **Arena Inventory** | `page.arena_inventory` | See [Chapter 8 §3](08_nova_web_lionshift_boilercraft_equipment.md) |

### The Global Search
`GET /api/search?q=...` (2+ characters) is one query that searches **members, moderation
records, guest passes, and varsity registrations** all at once, returning up to 10 combined
results — genuinely handy when you only half-remember whether the person you're looking for
is a student, a guest, or a varsity applicant.

### The Unified Activity Log
Every meaningful action anywhere in Nova — logins, moderation, admin changes, settings edits
— funnels through one `log_activity()` helper into a single append-only log
(`GET /api/activity-log`, filterable by category/action/source/target, with
`GET /api/activity-log/stats` for aggregate counts). This is the single best place to answer
"who did this and when."

---

## 5.6 Bot Control From the Browser

`GET`/`POST /api/bot/activity` lets you view or override the bot's Discord presence text
directly from Settings. `POST /api/bot/control/restart` and `POST /api/bot/control/stop`
queue a restart/stop request for the LionByteGG bot to pick up and act on within seconds —
remember the golden rule from the [Troubleshooting guide](11_troubleshooting_and_operations_guide.md):
**never trigger one of these while a bulk sync job is mid-flight.**

---

## 5.7 Example Data Shapes

**A dashboard user record (`GET /api/admin/users` entry)**
```json
{
  "id": 4, "username": "jkim", "display_name": "Jordan Kim",
  "is_admin": false, "is_active": true, "group_id": 2,
  "created_at": "2026-02-10T00:00:00Z", "last_login": "2026-09-04T14:02:00Z"
}
```

**A group record (`GET /api/admin/groups` entry)**
```json
{
  "id": 2, "name": "Arena Staff", "description": "Front-desk arena workers",
  "permissions": ["page.dashboard", "section.arena", "page.arena_live", "page.arena_sessions", "arena.manage"],
  "member_count": 6
}
```

**An activity log entry (`GET /api/activity-log`)**
```json
{
  "timestamp": "2026-09-04T18:00:00Z",
  "user": { "type": "dashboard", "name": "Jordan Kim", "id": 4 },
  "ip_address": "10.0.0.42",
  "action": "warn_user", "category": "moderation", "success": true,
  "details": "Issued a warning to SomeUser for spam",
  "target_id": "123456789012345678", "target_name": "SomeUser",
  "source": "website", "path": "/api/warn-user", "method": "POST"
}
```

---

## 5.8 Frequently Asked Questions

**"I'm an admin but I still get a 403 on some action — why?"**
Full-access users bypass `@page_permission_required`/`@api_perm_required` checks
automatically, so a genuine admin account (or the legacy login) should never see this. If it
does happen, double-check the account actually has `is_admin: true` set — a dashboard user
in an "Administrators"-named group without the literal `is_admin` flag ticked is **not**
treated as full-access; the group name is cosmetic, only the flag matters.

**"Can one person belong to more than one group?"**
No — each dashboard user belongs to exactly one group at a time (`group_id` is a single
value, not a list). If someone needs a blend of two roles' permissions, either create a new
combined group, or add the extra individual permission keys they need directly (if the admin
UI supports per-user overrides in your version) — otherwise, the practical approach is a
purpose-built group for that hybrid role.

**"How do I find out who has admin.panel access, for a security review?"**
`/admin`'s Groups view + `/api/admin/groups` lets you see which groups include
`admin.panel`, and `/api/admin/users` shows each user's assigned group — cross-reference the
two, or just check each user's `is_admin` flag directly since that's the actual gate that
matters, independent of group permissions.

**"I changed a group's permissions — does an already-logged-in user see the change immediately?"**
Not necessarily. `session['dashboard_permissions']` is set at login time; a user who's
already logged in when you change their group's permissions may need to log out and back in
(or wait for their session to naturally expire and refresh) before the new permissions take
effect, **except** when the update happens to their own account through the admin panel's
self-edit path, which explicitly refreshes the current session immediately.

**"What's the actual session timeout?"**
12 hours (`PERMANENT_SESSION_LIFETIME`), after which a user is automatically logged out and
needs to sign back in.
