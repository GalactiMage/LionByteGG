"""
Authentication Database Module for LionByteGG Dashboard
Handles users, groups, and permissions using SQLite + bcrypt.
"""

import sqlite3
import os
import bcrypt
from datetime import datetime, timezone
from contextlib import contextmanager

# Database file location
DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "auth.db")

# Default master admin credentials (used on first run only)
DEFAULT_MASTER_USERNAME = "admin"
DEFAULT_MASTER_PASSWORD = "LionByte2026!"

# All available permission keys (consolidated for clarity)
ALL_PERMISSIONS = [
    # =======================================================
    # LIONBYTEGG — Main Discord Bot Dashboard
    # =======================================================
    "section.lionbyte",                   # Show LionByteGG in sidebar

    "page.dashboard",                     # View dashboard
    "dashboard.bot_controls",             # Set activity, restart, stop bot

    "page.analytics",                     # View analytics

    "page.members",                       # View server members
    "members.moderate",                   # Warn, timeout, kick, ban members
    "members.communicate",                # Send DMs and add notes

    "page.users",                         # View guest management
    "users.manage",                       # Reset timers, remove guests

    "page.varsity",                       # View varsity registrations
    "varsity.manage",                     # Approve, deny, delete, send registrations

    "page.rosters",                       # View team rosters
    "rosters.manage",                     # Add/edit/remove players, teams, matches
    "rosters.admin",                      # Bulk actions, sync roles, import/export, announce, DM

    "page.moderation",                    # View moderation tools
    "moderation.manage",                  # Flagged words, records, watchlist, templates

    "page.logs",                          # View activity logs

    "page.tickets",                       # View tickets
    "tickets.manage",                     # Close, reply, assign tickets
    "tickets.admin",                      # Delete closed tickets, manage blacklist

    "page.reaction_roles",                # View reaction roles
    "reaction_roles.manage",              # Create/manage reaction role panels

    "page.vc_system",                     # View VC generators
    "vc.manage",                          # Kick/move users, manage channels
    "vc.generators",                      # Add/remove generator channels

    "page.ggleap",                        # View GGLeap arena

    "page.settings",                      # View bot settings
    "settings.manage",                    # Manage games, team roles, arena hours

    # =======================================================
    # LIONSHIFTGG — Shift Management
    # =======================================================
    "section.lionshift",                  # Show LionShiftGG in sidebar
    "page.shift_dashboard",               # View shift dashboard
    "page.shift_schedules",               # View schedules
    "schedules.manage",                   # Create, edit, delete, publish schedules
    "page.shift_offers",                  # View / manage shift offers
    "page.shift_trades",                  # View / manage trade requests
    "page.shift_timeoff",                 # View / manage time-off requests
    "page.shift_logs",                    # View shift logs
    "page.shift_workers",                 # View / manage workers
    "page.shift_settings",               # View / manage shift settings

    # =======================================================
    # ARENA STAFF — iPad Kiosk Sign-in System
    # =======================================================
    "section.arena",                      # Show Arena Staff in sidebar
    "page.arena_live",                    # View live sign-in feed
    "page.arena_sessions",                # View & control the PC Sessions room map
    "page.arena_logs",                    # View sign-in logs
    "page.arena_controls",                # View Kiosk Manager (admin-only kiosk controls)
    "arena.manage",                       # Manage kiosk settings, force sign-out, reload, clear logs
    "arena.unlock",                       # Remotely unlock a locked kiosk
    "page.arena_inventory",               # View & use the Arena inventory (equipment)
    "equipment.use",                      # Check out / check in equipment
    "equipment.manage",                   # Add/edit/delete items, reports, export
    "page.arena_students",                # View student profiles, visit history & notes
    "arena.notes",                        # Add / remove notes on students
    "arena.ban",                          # Ban / watch-list students
    "arena.students_manage",              # Delete students & their records
    "page.arena_reports",                 # View incident reports (own by default)
    "arena.reports_all",                  # View ALL incident reports (not just your own)
    "arena.reports",                      # File / resolve / delete incident reports

    # =======================================================
    # LIONBEATSGG — Music Bot
    # =======================================================
    "section.lionbeats",                  # Show LionBeatsGG in sidebar
    "page.music_dashboard",               # View music dashboard
    "page.music_features",                # View music features
    "music.controls",                     # Player controls, queue, commands
    "music.manage",                       # Quiz songs, history, stats, panels, settings

    # =======================================================
    # BOILERCRAFTGG — Minecraft Bot
    # =======================================================
    "section.boilercraft",                # Show BoilerCraftGG in sidebar
    "page.boilercraft",                   # View BoilerCraft dashboard
    "boilercraft.tickets",                # Close tickets, send messages
    "boilercraft.admin",                  # Delete closed, blacklist, settings, deploy
    "page.boilercraft_faq",               # View FAQ page
    "boilercraft.faq_manage",             # Add/edit/delete FAQs

    # =======================================================
    # ADMINISTRATION
    # =======================================================
    "admin.panel",                        # Access admin panel
    "admin.manage",                       # Manage users, groups, reset passwords
]

# Maps old granular permission keys to new consolidated keys.
# All existing code references keep working via resolve_perm().
PERMISSION_ALIASES = {
    # Dashboard
    "dashboard.bot_activity":      "dashboard.bot_controls",
    "dashboard.bot_restart":       "dashboard.bot_controls",
    "dashboard.bot_stop":          "dashboard.bot_controls",
    # Members
    "members.view_profiles":       "page.members",
    "members.send_dm":             "members.communicate",
    "members.add_notes":           "members.communicate",
    "members.warn":                "members.moderate",
    "members.timeout":             "members.moderate",
    "members.kick":                "members.moderate",
    "members.ban":                 "members.moderate",
    # Guests
    "users.reset_timer":           "users.manage",
    "users.remove_guest":          "users.manage",
    # Varsity
    "varsity.approve":             "varsity.manage",
    "varsity.deny":                "varsity.manage",
    "varsity.delete":              "varsity.manage",
    "varsity.send_registration":   "varsity.manage",
    # Rosters
    "rosters.manage_players":      "rosters.manage",
    "rosters.manage_teams":        "rosters.manage",
    "rosters.manage_matches":      "rosters.manage",
    "rosters.registrations":       "rosters.manage",
    "rosters.bulk_actions":        "rosters.admin",
    "rosters.announcements":       "rosters.admin",
    "rosters.sync_roles":          "rosters.admin",
    "rosters.import_export":       "rosters.admin",
    "rosters.notification_settings": "rosters.admin",
    "rosters.dm_players":          "rosters.admin",
    # Moderation
    "moderation.flagged_words":    "moderation.manage",
    "moderation.user_records":     "moderation.manage",
    "moderation.quick_actions":    "moderation.manage",
    "moderation.watchlist":        "moderation.manage",
    "moderation.templates":        "moderation.manage",
    # Logs
    "logs.export":                 "page.logs",
    # Tickets
    "tickets.view_open":           "page.tickets",
    "tickets.view_closed":         "page.tickets",
    "tickets.transcripts":         "page.tickets",
    "tickets.close":               "tickets.manage",
    "tickets.send_message":        "tickets.manage",
    "tickets.assign":              "tickets.manage",
    "tickets.delete_closed":       "tickets.admin",
    "tickets.blacklist":           "tickets.admin",
    # VC
    "vc.kick_users":               "vc.manage",
    "vc.move_users":               "vc.manage",
    "vc.manage_channels":          "vc.manage",
    "vc.manage_generators":        "vc.generators",
    # Settings
    "settings.games":              "settings.manage",
    "settings.team_roles":         "settings.manage",
    "settings.arena_hours":        "settings.manage",
    # Equipment
    "equipment.checkout":          "equipment.use",
    "equipment.checkin":           "equipment.use",
    "equipment.reports":           "equipment.manage",
    "equipment.export":            "equipment.manage",
    # Inventory moved from the retired "Worker On Duty" app into Arena Staff
    "page.onduty_equipment":       "page.arena_inventory",
    "page.onduty_dashboard":       "page.arena_inventory",
    "section.onduty":              "section.arena",
    # Music
    "music.player_controls":       "music.controls",
    "music.manage_queue":          "music.controls",
    "music.commands":              "music.controls",
    "music.quiz_manager":          "music.manage",
    "music.history":               "music.manage",
    "music.stats":                 "music.manage",
    "music.panels":                "music.manage",
    "music.settings":              "music.manage",
    # BoilerCraft
    "boilercraft.close_tickets":   "boilercraft.tickets",
    "boilercraft.send_messages":   "boilercraft.tickets",
    "boilercraft.delete_closed":   "boilercraft.admin",
    "boilercraft.blacklist":       "boilercraft.admin",
    "boilercraft.settings":        "boilercraft.admin",
    "boilercraft.deploy_panel":    "boilercraft.admin",
    "boilercraft.manage_categories": "boilercraft.admin",
    # Admin
    "admin.manage_users":          "admin.manage",
    "admin.manage_groups":         "admin.manage",
    "admin.reset_passwords":       "admin.manage",
}


def resolve_perm(key):
    """Resolve a permission key through the alias map. Returns the canonical key."""
    return PERMISSION_ALIASES.get(key, key)


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize the database tables and create master admin if needed."""
    os.makedirs(DB_DIR, exist_ok=True)

    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL,
                group_id INTEGER,
                is_admin INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login TEXT,
                FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS group_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                permission_key TEXT NOT NULL,
                granted INTEGER DEFAULT 1,
                FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE,
                UNIQUE(group_id, permission_key)
            );
        """)

        # Create master admin if no users exist
        row = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()
        if row["cnt"] == 0:
            _create_master_admin(conn)

        # Create preset groups if no groups exist
        row = conn.execute("SELECT COUNT(*) as cnt FROM groups").fetchone()
        if row["cnt"] == 0:
            _create_preset_groups(conn)

        # Migrate old granular permission keys to consolidated keys
        _migrate_permission_keys(conn)

        # Seed preset groups that have never been configured. This is
        # NON-DESTRUCTIVE: a preset group that already has permissions is left
        # exactly as the admin set it, so customizations persist across restarts.
        _seed_preset_permissions(conn)


def _migrate_permission_keys(conn):
    """Migrate old granular permission keys to new consolidated keys in the DB."""
    for old_key, new_key in PERMISSION_ALIASES.items():
        if old_key == new_key:
            continue
        # For each group that has the old key, add the new key (if not already present) then remove the old
        rows = conn.execute(
            "SELECT group_id FROM group_permissions WHERE permission_key = ?", (old_key,)
        ).fetchall()
        for row in rows:
            conn.execute(
                "INSERT OR IGNORE INTO group_permissions (group_id, permission_key, granted) VALUES (?, ?, 1)",
                (row["group_id"], new_key),
            )
            conn.execute(
                "DELETE FROM group_permissions WHERE group_id = ? AND permission_key = ?",
                (row["group_id"], old_key),
            )


def _seed_preset_permissions(conn):
    """Seed permissions for preset groups that have never been configured.

    Non-destructive: a preset group that already has ANY permissions is left
    exactly as the admin set it, so customizations (e.g. revoking a permission
    from Student Workers) persist across restarts. Only empty preset groups, or
    preset groups that don't exist yet, get their default permission set.
    """
    now = datetime.now(timezone.utc).isoformat()
    for preset in PRESET_GROUPS:
        row = conn.execute(
            "SELECT id FROM groups WHERE name = ?", (preset["name"],)
        ).fetchone()
        if row:
            group_id = row["id"]
            has_perms = conn.execute(
                "SELECT COUNT(*) AS c FROM group_permissions WHERE group_id = ?", (group_id,)
            ).fetchone()["c"]
            if has_perms:
                continue  # admin-managed — never overwrite
        else:
            cursor = conn.execute(
                "INSERT INTO groups (name, description, created_at) VALUES (?, ?, ?)",
                (preset["name"], preset.get("description", ""), now),
            )
            group_id = cursor.lastrowid
        for perm in preset["permissions"]:
            if perm in ALL_PERMISSIONS:
                conn.execute(
                    "INSERT OR IGNORE INTO group_permissions (group_id, permission_key, granted) VALUES (?, ?, 1)",
                    (group_id, perm),
                )


def _create_master_admin(conn):
    """Create the initial master admin account."""
    now = datetime.now(timezone.utc).isoformat()
    pw_hash = bcrypt.hashpw(DEFAULT_MASTER_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    conn.execute(
        "INSERT INTO users (username, password_hash, display_name, group_id, is_admin, is_active, created_at) "
        "VALUES (?, ?, ?, NULL, 1, 1, ?)",
        (DEFAULT_MASTER_USERNAME, pw_hash, "Master Admin", now),
    )


# Preset permission groups created on first run
PRESET_GROUPS = [
    {
        "name": "Student Workers",
        "description": "Standard access — equipment check in/out and GGLeap arena management only.",
        "permissions": [
            "section.onduty",
            "page.onduty_dashboard",
            "page.onduty_equipment",
            "equipment.use",
            "page.ggleap",
            "page.arena_sessions",
            "arena.manage",
        ],
    },
    {
        "name": "Supervisors",
        "description": "Elevated access — full Worker On Duty, moderation, tickets, shift oversight, and guest management.",
        "permissions": [
            # Worker On Duty — full access
            "section.onduty",
            "page.onduty_dashboard",
            "page.onduty_equipment",
            "equipment.use",
            "equipment.manage",
            # Arena Staff — kiosk sign-in system
            "section.arena",
            "page.arena_live",
            "page.arena_sessions",
            "page.arena_logs",
            "page.arena_controls",
            "arena.manage",
            # LionByteGG — operational pages
            "section.lionbyte",
            "page.dashboard",
            "dashboard.bot_controls",
            "page.analytics",
            "page.members",
            "members.moderate",
            "members.communicate",
            "page.users",
            "users.manage",
            "page.varsity",
            "varsity.manage",
            "page.rosters",
            "rosters.manage",
            "page.moderation",
            "moderation.manage",
            "page.logs",
            "page.tickets",
            "tickets.manage",
            "tickets.admin",
            "page.ggleap",
            "page.vc_system",
            "vc.manage",
            "vc.generators",
            "page.reaction_roles",
            "reaction_roles.manage",
            "page.settings",
            "settings.manage",
            # LionShiftGG — full shift management
            "section.lionshift",
            "page.shift_dashboard",
            "page.shift_schedules",
            "schedules.manage",
            "page.shift_offers",
            "page.shift_trades",
            "page.shift_timeoff",
            "page.shift_logs",
            "page.shift_workers",
            "page.shift_settings",
            # BoilerCraftGG — full management
            "section.boilercraft",
            "page.boilercraft",
            "boilercraft.tickets",
            "boilercraft.admin",
            "page.boilercraft_faq",
            "boilercraft.faq_manage",
        ],
    },
    {
        "name": "Moderators",
        "description": "Full moderation — member actions, tickets, logs, VC management, and reaction roles.",
        "permissions": [
            "section.lionbyte",
            "page.dashboard",
            "page.analytics",
            "page.members",
            "members.moderate",
            "members.communicate",
            "page.moderation",
            "moderation.manage",
            "page.logs",
            "page.tickets",
            "tickets.manage",
            "tickets.admin",
            "page.reaction_roles",
            "reaction_roles.manage",
            "page.vc_system",
            "vc.manage",
        ],
    },
    {
        "name": "MC Staff",
        "description": "Minecraft server staff — BoilerCraft tickets and FAQ management.",
        "permissions": [
            "section.boilercraft",
            "page.boilercraft",
            "boilercraft.tickets",
            "page.boilercraft_faq",
            "boilercraft.faq_manage",
        ],
    },
    {
        "name": "Directors",
        "description": "Full operational access across all bots and features.",
        "permissions": [
            # LionByteGG
            "section.lionbyte",
            "page.dashboard",
            "dashboard.bot_controls",
            "page.analytics",
            "page.members",
            "members.moderate",
            "members.communicate",
            "page.users",
            "users.manage",
            "page.varsity",
            "varsity.manage",
            "page.rosters",
            "rosters.manage",
            "rosters.admin",
            "page.moderation",
            "moderation.manage",
            "page.logs",
            "page.tickets",
            "tickets.manage",
            "tickets.admin",
            "page.reaction_roles",
            "reaction_roles.manage",
            "page.vc_system",
            "vc.manage",
            "vc.generators",
            "page.ggleap",
            "page.settings",
            "settings.manage",
            # Worker On Duty
            "section.onduty",
            "page.onduty_dashboard",
            "page.onduty_equipment",
            "equipment.use",
            "equipment.manage",
            # Arena Staff — kiosk sign-in system
            "section.arena",
            "page.arena_live",
            "page.arena_sessions",
            "page.arena_logs",
            "page.arena_controls",
            "arena.manage",
            # LionShiftGG
            "section.lionshift",
            "page.shift_dashboard",
            "page.shift_schedules",
            "schedules.manage",
            "page.shift_offers",
            "page.shift_trades",
            "page.shift_timeoff",
            "page.shift_logs",
            "page.shift_workers",
            "page.shift_settings",
            # LionBeatsGG
            "section.lionbeats",
            "page.music_dashboard",
            "page.music_features",
            "music.controls",
            "music.manage",
            # BoilerCraftGG
            "section.boilercraft",
            "page.boilercraft",
            "boilercraft.tickets",
            "boilercraft.admin",
            "page.boilercraft_faq",
            "boilercraft.faq_manage",
            # Admin
            "admin.panel",
            "admin.manage",
        ],
    },
]


def _create_preset_groups(conn):
    """Create default permission groups on first run."""
    now = datetime.now(timezone.utc).isoformat()
    for group in PRESET_GROUPS:
        cursor = conn.execute(
            "INSERT INTO groups (name, description, created_at) VALUES (?, ?, ?)",
            (group["name"], group["description"], now),
        )
        group_id = cursor.lastrowid
        for perm in group["permissions"]:
            if perm in ALL_PERMISSIONS:
                conn.execute(
                    "INSERT INTO group_permissions (group_id, permission_key, granted) VALUES (?, ?, 1)",
                    (group_id, perm),
                )


# ============ User Functions ============

def authenticate_user(username, password):
    """
    Validate username + password. Returns user dict on success, None on failure.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT u.*, g.name as group_name FROM users u "
            "LEFT JOIN groups g ON u.group_id = g.id "
            "WHERE u.username = ? COLLATE NOCASE AND u.is_active = 1",
            (username,),
        ).fetchone()

    if not row:
        return None

    if not bcrypt.checkpw(password.encode("utf-8"), row["password_hash"].encode("utf-8")):
        return None

    # Update last_login
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), row["id"]),
        )

    return _row_to_user(row, include_group_name=True)


def get_user_by_id(user_id):
    """Get a single user by ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_username(username):
    """Get a single user by username (case-sensitive, matches login lookup)."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return _row_to_user(row) if row else None


def get_all_users():
    """Get all users."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT u.*, g.name as group_name FROM users u LEFT JOIN groups g ON u.group_id = g.id ORDER BY u.id"
        ).fetchall()
    return [_row_to_user(r, include_group_name=True) for r in rows]


def create_user(username, password, display_name, group_id=None, is_admin=False):
    """Create a new user. Returns user dict or raises on duplicate."""
    now = datetime.now(timezone.utc).isoformat()
    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, display_name, group_id, is_admin, is_active, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (username, pw_hash, display_name, group_id, 1 if is_admin else 0, now),
        )
        new_user_id = cursor.lastrowid
    # Fetch AFTER the transaction commits (get_db commits on block exit) so the
    # new row is visible to the fresh connection opened inside get_user_by_id().
    return get_user_by_id(new_user_id)


def update_user(user_id, display_name=None, group_id=None, is_admin=None, is_active=None):
    """Update user fields (not password)."""
    with get_db() as conn:
        if display_name is not None:
            conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (display_name, user_id))
        if group_id is not None:
            # Allow setting to None (no group) by passing 0 or None
            gid = group_id if group_id else None
            conn.execute("UPDATE users SET group_id = ? WHERE id = ?", (gid, user_id))
        if is_admin is not None:
            conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (1 if is_admin else 0, user_id))
        if is_active is not None:
            conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (1 if is_active else 0, user_id))
    return get_user_by_id(user_id)


def change_password(user_id, new_password):
    """Change a user's password."""
    pw_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    with get_db() as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pw_hash, user_id))
    return True


def delete_user(user_id):
    """Delete a user. Returns True if deleted, False if not found or is the last admin."""
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            return False
        # Prevent deleting if this is the only admin
        if user["is_admin"]:
            admin_count = conn.execute("SELECT COUNT(*) as cnt FROM users WHERE is_admin = 1").fetchone()["cnt"]
            if admin_count <= 1:
                return False
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return True


def get_user_permissions(user_id):
    """
    Get the resolved list of permission keys for a user.
    Admins get ALL permissions automatically.
    Regular users get permissions from their group.
    """
    user = get_user_by_id(user_id)
    if not user:
        return []

    if user["is_admin"]:
        return list(ALL_PERMISSIONS)

    if not user["group_id"]:
        return []

    return get_group_permissions(user["group_id"])


def _row_to_user(row, include_group_name=False):
    """Convert a sqlite3.Row to a dict, excluding password_hash."""
    if not row:
        return None
    d = {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "group_id": row["group_id"],
        "is_admin": bool(row["is_admin"]),
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "last_login": row["last_login"],
    }
    if include_group_name:
        try:
            d["group_name"] = row["group_name"]
        except (IndexError, KeyError):
            d["group_name"] = None
    return d


# ============ Group Functions ============

def get_all_groups():
    """Get all groups with their permissions."""
    with get_db() as conn:
        groups = conn.execute("SELECT * FROM groups ORDER BY id").fetchall()
        result = []
        for g in groups:
            perms = conn.execute(
                "SELECT permission_key FROM group_permissions WHERE group_id = ? AND granted = 1",
                (g["id"],),
            ).fetchall()
            result.append({
                "id": g["id"],
                "name": g["name"],
                "description": g["description"],
                "created_at": g["created_at"],
                "permissions": [p["permission_key"] for p in perms],
            })
    return result


def get_group_by_id(group_id):
    """Get a single group with permissions."""
    with get_db() as conn:
        g = conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
        if not g:
            return None
        perms = conn.execute(
            "SELECT permission_key FROM group_permissions WHERE group_id = ? AND granted = 1",
            (g["id"],),
        ).fetchall()
        return {
            "id": g["id"],
            "name": g["name"],
            "description": g["description"],
            "created_at": g["created_at"],
            "permissions": [p["permission_key"] for p in perms],
        }


def get_group_permissions(group_id):
    """Get list of granted permission keys for a group."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT permission_key FROM group_permissions WHERE group_id = ? AND granted = 1",
            (group_id,),
        ).fetchall()
    return [r["permission_key"] for r in rows]


def ensure_group_permissions(group_name, perms):
    """Idempotently grant a set of permissions to a named group (adds only what's
    missing; never revokes anything an admin set). Returns the number added."""
    added = 0
    with get_db() as conn:
        row = conn.execute("SELECT id FROM groups WHERE name = ?", (group_name,)).fetchone()
        if not row:
            return 0
        gid = row["id"]
        for perm in perms:
            if perm not in ALL_PERMISSIONS:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO group_permissions (group_id, permission_key, granted) VALUES (?, ?, 1)",
                (gid, perm),
            )
            added += cur.rowcount
    return added


def create_group(name, description="", permissions=None):
    """Create a new group with optional permissions."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO groups (name, description, created_at) VALUES (?, ?, ?)",
            (name, description, now),
        )
        group_id = cursor.lastrowid
        if permissions:
            for perm in permissions:
                if perm in ALL_PERMISSIONS:
                    conn.execute(
                        "INSERT INTO group_permissions (group_id, permission_key, granted) VALUES (?, ?, 1)",
                        (group_id, perm),
                    )
    return get_group_by_id(group_id)


def update_group(group_id, name=None, description=None, permissions=None):
    """Update group details and/or permissions."""
    with get_db() as conn:
        if name is not None:
            conn.execute("UPDATE groups SET name = ? WHERE id = ?", (name, group_id))
        if description is not None:
            conn.execute("UPDATE groups SET description = ? WHERE id = ?", (description, group_id))
        if permissions is not None:
            # Replace all permissions
            conn.execute("DELETE FROM group_permissions WHERE group_id = ?", (group_id,))
            for perm in permissions:
                if perm in ALL_PERMISSIONS:
                    conn.execute(
                        "INSERT INTO group_permissions (group_id, permission_key, granted) VALUES (?, ?, 1)",
                        (group_id, perm),
                    )
    return get_group_by_id(group_id)


def delete_group(group_id):
    """Delete a group. Users in this group will have group_id set to NULL."""
    with get_db() as conn:
        g = conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
        if not g:
            return False
        conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
    return True


