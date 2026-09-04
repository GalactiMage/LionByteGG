"""
SQLite-backed user records store.

Replaces the per-user *_record.json files with a single database file.
All functions are thread-safe (SQLite WAL mode + per-call connections).
"""

import sqlite3
import os
from datetime import datetime, timezone

# DB lives alongside the rest of bot data
_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "user_records.db")


def _connect():
    """Return a connection with WAL mode and row_factory set."""
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Create the user_records table if it doesn't exist. Call once at startup."""
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_records (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT    NOT NULL,
                type         TEXT    NOT NULL,
                reason       TEXT,
                moderator    TEXT,
                moderator_id TEXT,
                source       TEXT    DEFAULT 'discord',
                timestamp    TEXT    NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON user_records (user_id)")
        conn.commit()


def add_record(user_id, type_, reason, moderator=None, moderator_id=None, source="discord"):
    """Insert a new record row. Returns the new row id."""
    ts = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO user_records (user_id, type, reason, moderator, moderator_id, source, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (str(user_id), type_, reason,
             moderator or "Moderation Team",
             str(moderator_id) if moderator_id else None,
             source, ts)
        )
        conn.commit()
        return cur.lastrowid


def get_records(user_id):
    """Return all records for a user as a list of dicts, oldest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM user_records WHERE user_id = ? ORDER BY timestamp ASC",
            (str(user_id),)
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_records():
    """Return every record grouped by user_id: {user_id: [record_dict, ...]}."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM user_records ORDER BY user_id, timestamp ASC"
        ).fetchall()
    result = {}
    for r in rows:
        d = dict(r)
        uid = d["user_id"]
        result.setdefault(uid, []).append(d)
    return result


def clear_records(user_id):
    """Delete all records for a user."""
    with _connect() as conn:
        conn.execute("DELETE FROM user_records WHERE user_id = ?", (str(user_id),))
        conn.commit()


def remove_record_by_id(record_id):
    """Delete a single record by its primary key id."""
    with _connect() as conn:
        conn.execute("DELETE FROM user_records WHERE id = ?", (record_id,))
        conn.commit()


def remove_record_by_index(user_id, index):
    """
    Remove the record at position `index` (0-based) in the user's record list
    (sorted by timestamp ASC). Returns the removed record dict, or None if not found.
    """
    records = get_records(user_id)
    if index < 0 or index >= len(records):
        return None
    target = records[index]
    remove_record_by_id(target["id"])
    return target


def remove_warning_by_index(user_id, index):
    """
    Remove the warning at position `index` among only Warning-type records.
    Returns the removed record dict, or None if not found.
    """
    records = get_records(user_id)
    warnings = [r for r in records if r.get("type") == "Warning"]
    if index < 0 or index >= len(warnings):
        return None
    target = warnings[index]
    remove_record_by_id(target["id"])
    return target


def remove_watch_records(user_id):
    """Remove all Watch-type records for a user (used when removing from watchlist)."""
    with _connect() as conn:
        conn.execute(
            "DELETE FROM user_records WHERE user_id = ? AND type = 'Watch'",
            (str(user_id),)
        )
        conn.commit()


def has_records(user_id):
    """Return True if the user has any records at all."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM user_records WHERE user_id = ? LIMIT 1",
            (str(user_id),)
        ).fetchone()
    return row is not None
