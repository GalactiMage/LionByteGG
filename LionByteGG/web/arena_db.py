"""
Arena Sign-in Database — SQLite-backed, PII-encrypted.

Stores kiosk / manual arena check-ins in a real database instead of a flat
JSON file. Student PII (name, first, last, email) is encrypted at rest with the
same Fernet key Nova uses for roster PII, so the database file is useless
without the key. Non-identifying fields (kiosk, room, reason, staff, times) are
stored in the clear so they can be indexed and filtered quickly.
"""

import os
import json
import uuid
import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

from cryptography.fernet import Fernet

# Same data dir as app.py's DATA_DIR (repo-root/data) so we share the PII key.
DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_PATH = os.path.join(DB_DIR, "arena.db")
KEY_FILE = os.path.join(DB_DIR, ".roster_encrypt_key")

_fernet = None


def _key():
    """Load (or create) the shared Fernet PII key."""
    global _fernet
    if _fernet is not None:
        return _fernet
    os.makedirs(DB_DIR, exist_ok=True)
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            key = f.read().strip()
    else:
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(key)
    _fernet = Fernet(key)
    return _fernet


def _enc(value):
    """Encrypt a string to a Fernet token; empty stays empty (nothing to hide)."""
    value = value or ""
    if value == "":
        return ""
    return _key().encrypt(value.encode("utf-8")).decode("utf-8")


def _dec(token):
    if not token:
        return ""
    try:
        return _key().decrypt(token.encode("utf-8")).decode("utf-8")
    except Exception:
        return ""


def _email_hash(email):
    """Non-reversible lookup key for an email (so returning guests can be found
    without storing or scanning plaintext emails)."""
    norm = (email or "").strip().lower()
    if not norm:
        return ""
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")     # concurrent reads, fast writes
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_arena_db(legacy_json=None):
    """Create the schema, migrate a legacy JSON file once (if the DB is empty),
    and prune anything past retention."""
    os.makedirs(DB_DIR, exist_ok=True)
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS signins (
                id            TEXT PRIMARY KEY,
                name_enc      TEXT,
                first_enc     TEXT,
                last_enc      TEXT,
                email_enc     TEXT,
                kiosk_id      TEXT,
                kiosk_label   TEXT,
                room          TEXT,
                reason        TEXT DEFAULT '',
                checked_in_by TEXT DEFAULT '',
                accepted_rules INTEGER DEFAULT 1,
                manual        INTEGER DEFAULT 0,
                signed_in_at  TEXT,
                day           TEXT,
                kind          TEXT DEFAULT 'guest',
                machine       TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_signins_day ON signins(day);
            CREATE INDEX IF NOT EXISTS idx_signins_at  ON signins(signed_in_at);
            CREATE INDEX IF NOT EXISTS idx_signins_kiosk ON signins(kiosk_id);

            CREATE TABLE IF NOT EXISTS student_notes (
                id          TEXT PRIMARY KEY,
                email_hash  TEXT,
                email_enc   TEXT,
                name_enc    TEXT,
                note_enc    TEXT,
                note_type   TEXT DEFAULT 'general',
                author      TEXT DEFAULT '',
                created_at  TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_notes_emailhash ON student_notes(email_hash);

            CREATE TABLE IF NOT EXISTS incident_reports (
                id            TEXT PRIMARY KEY,
                title         TEXT,
                type          TEXT DEFAULT 'other',
                severity      TEXT DEFAULT 'low',
                status        TEXT DEFAULT 'open',
                involved_hash TEXT DEFAULT '',
                involved_name_enc  TEXT,
                involved_email_enc TEXT,
                description_enc TEXT,
                author        TEXT DEFAULT '',
                created_at    TEXT,
                resolved_at   TEXT,
                resolved_by   TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_incidents_at ON incident_reports(created_at);

            CREATE TABLE IF NOT EXISTS watchlist (
                email_hash  TEXT PRIMARY KEY,
                email_enc   TEXT,
                mode        TEXT DEFAULT 'watch',
                reason_enc  TEXT,
                added_by    TEXT DEFAULT '',
                added_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS signin_flags (
                id          TEXT PRIMARY KEY,
                at          TEXT,
                kind        TEXT,
                severity    TEXT,
                email_hash  TEXT,
                email_enc   TEXT,
                name_enc    TEXT,
                kiosk_id    TEXT,
                kiosk_label TEXT,
                reason_enc  TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_flags_at ON signin_flags(at);
        """)
        # Add the returning-guest lookup column to older databases, then backfill.
        cols = [r[1] for r in conn.execute("PRAGMA table_info(signins)").fetchall()]
        if "email_hash" not in cols:
            conn.execute("ALTER TABLE signins ADD COLUMN email_hash TEXT DEFAULT ''")
            for r in conn.execute("SELECT id, email_enc FROM signins").fetchall():
                h = _email_hash(_dec(r["email_enc"]))
                if h:
                    conn.execute("UPDATE signins SET email_hash=? WHERE id=?", (h, r["id"]))
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signins_emailhash ON signins(email_hash)")
        if "kind" not in cols:
            conn.execute("ALTER TABLE signins ADD COLUMN kind TEXT DEFAULT 'guest'")
        if "machine" not in cols:
            conn.execute("ALTER TABLE signins ADD COLUMN machine TEXT DEFAULT ''")
    if legacy_json and os.path.exists(legacy_json) and count() == 0:
        migrate_json(legacy_json)


def _insert(conn, rec):
    sid = rec.get("id") or uuid.uuid4().hex
    signed = rec.get("signed_in_at") or datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """INSERT OR REPLACE INTO signins
           (id, name_enc, first_enc, last_enc, email_enc, kiosk_id, kiosk_label,
            room, reason, checked_in_by, accepted_rules, manual, signed_in_at, day, email_hash, kind, machine)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            sid,
            _enc(rec.get("name")), _enc(rec.get("first_name")),
            _enc(rec.get("last_name")), _enc(rec.get("email")),
            rec.get("kiosk_id"), rec.get("kiosk_label"), rec.get("room"),
            rec.get("reason", "") or "", rec.get("checked_in_by", "") or "",
            1 if rec.get("accepted_rules") else 0,
            1 if rec.get("manual") else 0,
            signed, (signed or "")[:10],
            _email_hash(rec.get("email")),
            rec.get("kind") or "guest",
            rec.get("machine") or "",
        ),
    )
    return sid


def add_signin(rec):
    """Insert one sign-in (single indexed write). Returns the record id."""
    with get_db() as conn:
        return _insert(conn, rec)


def _row_to_dict(r):
    rec = {
        "id": r["id"],
        "name": _dec(r["name_enc"]),
        "first_name": _dec(r["first_enc"]),
        "last_name": _dec(r["last_enc"]),
        "email": _dec(r["email_enc"]),
        "kiosk_id": r["kiosk_id"],
        "kiosk_label": r["kiosk_label"],
        "room": r["room"],
        "reason": r["reason"] or "",
        "checked_in_by": r["checked_in_by"] or "",
        "accepted_rules": bool(r["accepted_rules"]),
        "signed_in_at": r["signed_in_at"],
    }
    try:
        if r["machine"]:
            rec["machine"] = r["machine"]
    except (IndexError, KeyError):
        pass
    try:
        if r["kind"] and r["kind"] != "guest":
            rec["kind"] = r["kind"]
    except (IndexError, KeyError):
        pass
    if r["manual"]:
        rec["manual"] = True
    return rec


def get_all():
    """Return all sign-ins (decrypted) oldest-first — same shape as the old JSON list."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM signins ORDER BY signed_in_at ASC").fetchall()
    return [_row_to_dict(r) for r in rows]


def replace_all(records):
    """Replace the whole table with the given list (used by retention prune)."""
    with get_db() as conn:
        conn.execute("DELETE FROM signins")
        for rec in records:
            _insert(conn, rec)


def prune(days=30):
    """Delete sign-ins older than `days`. Returns rows removed."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_db() as conn:
        cur = conn.execute("DELETE FROM signins WHERE day < ?", (cutoff,))
        return cur.rowcount


def clear_all():
    """Wipe every sign-in (irreversible)."""
    with get_db() as conn:
        conn.execute("DELETE FROM signins")


def count():
    with get_db() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM signins").fetchone()["c"]


def find_recent_guest(email):
    """Look up a returning guest by email for kiosk fast-check-in.
    Returns {name, first_name, last_name, room, reason, visits, last_at} or None.
    Uses the non-reversible email hash so no plaintext email scan is needed."""
    h = _email_hash(email)
    if not h:
        return None
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM signins WHERE email_hash=? ORDER BY signed_in_at DESC",
            (h,),
        ).fetchall()
    if not rows:
        return None
    latest = rows[0]
    return {
        "name": _dec(latest["name_enc"]),
        "first_name": _dec(latest["first_enc"]),
        "last_name": _dec(latest["last_enc"]),
        "room": latest["room"] or "",
        "reason": latest["reason"] or "",
        "visits": len(rows),
        "last_at": latest["signed_in_at"],
    }


def migrate_json(json_path):
    """One-time import of a legacy arena_signins.json, then archive the file."""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = []
    if isinstance(data, list) and data:
        with get_db() as conn:
            for rec in data:
                _insert(conn, rec)
    try:
        os.replace(json_path, json_path + ".migrated")
    except Exception:
        pass
    return len(data) if isinstance(data, list) else 0


# ───────────────────────── Student profiles / notes ─────────────────────────

def get_visits(email, limit=50):
    """All sign-ins for one email (decrypted, most recent first)."""
    h = _email_hash(email)
    if not h:
        return []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM signins WHERE email_hash=? ORDER BY signed_in_at DESC LIMIT ?",
            (h, limit),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def add_note(email, name, note, note_type="general", author=""):
    """Attach a note to a student (keyed by email)."""
    nid = uuid.uuid4().hex
    with get_db() as conn:
        conn.execute(
            """INSERT INTO student_notes
               (id, email_hash, email_enc, name_enc, note_enc, note_type, author, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (nid, _email_hash(email), _enc(email), _enc(name), _enc(note),
             note_type or "general", author or "",
             datetime.now().isoformat(timespec="seconds")),
        )
    return nid


def get_notes(email):
    """All notes for a student, newest first."""
    h = _email_hash(email)
    if not h:
        return []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM student_notes WHERE email_hash=? ORDER BY created_at DESC", (h,)
        ).fetchall()
    return [{
        "id": r["id"],
        "note": _dec(r["note_enc"]),
        "type": r["note_type"] or "general",
        "author": r["author"] or "",
        "created_at": r["created_at"],
    } for r in rows]


def delete_note(note_id):
    with get_db() as conn:
        cur = conn.execute("DELETE FROM student_notes WHERE id=?", (note_id,))
        return cur.rowcount


def _note_counts():
    """Map of email_hash -> note count (for the students list)."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT email_hash, COUNT(*) AS c FROM student_notes GROUP BY email_hash"
        ).fetchall()
    return {r["email_hash"]: r["c"] for r in rows}


def list_students(query="", limit=500):
    """Aggregate every distinct student from the sign-in history (decrypted).
    Returns [{name, email, visits, last_at, first_at, notes}]. Single query."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT email_hash,
                      COUNT(*) AS visits,
                      MAX(signed_in_at) AS last_at,
                      MIN(signed_in_at) AS first_at,
                      (SELECT name_enc  FROM signins x WHERE x.email_hash = s.email_hash ORDER BY signed_in_at DESC LIMIT 1) AS name_enc,
                      (SELECT email_enc FROM signins x WHERE x.email_hash = s.email_hash ORDER BY signed_in_at DESC LIMIT 1) AS email_enc
               FROM signins s WHERE email_hash != '' GROUP BY email_hash
               ORDER BY last_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    notes = _note_counts()
    q = (query or "").strip().lower()
    out = []
    for r in rows:
        name, email = _dec(r["name_enc"]), _dec(r["email_enc"])
        if q and q not in (name or "").lower() and q not in (email or "").lower():
            continue
        out.append({
            "name": name, "email": email,
            "visits": r["visits"], "last_at": r["last_at"], "first_at": r["first_at"],
            "notes": notes.get(r["email_hash"], 0),
        })
    return out


def delete_student(email):
    """Delete a student's entire record: all sign-ins and notes for that email."""
    h = _email_hash(email)
    if not h:
        return (0, 0)
    with get_db() as conn:
        v = conn.execute("DELETE FROM signins WHERE email_hash=?", (h,)).rowcount
        n = conn.execute("DELETE FROM student_notes WHERE email_hash=?", (h,)).rowcount
    return (v, n)


def update_student(email, new_name=None, new_email=None):
    """Rename a student and/or change their email across ALL of their sign-in
    records and notes. Re-encrypts the affected fields and re-indexes the email
    hash so their history stays merged under one identity. Returns rows touched."""
    h = _email_hash(email)
    if not h:
        return 0
    touched = 0
    with get_db() as conn:
        if new_name is not None:
            parts = (new_name or "").strip().split()
            first = parts[0] if parts else ""
            last = " ".join(parts[1:]) if len(parts) > 1 else ""
            touched = conn.execute(
                "UPDATE signins SET name_enc=?, first_enc=?, last_enc=? WHERE email_hash=?",
                (_enc(new_name), _enc(first), _enc(last), h),
            ).rowcount
            conn.execute("UPDATE student_notes SET name_enc=? WHERE email_hash=?", (_enc(new_name), h))
        if new_email:
            nh = _email_hash(new_email)
            conn.execute("UPDATE signins SET email_enc=?, email_hash=? WHERE email_hash=?",
                         (_enc(new_email), nh, h))
            conn.execute("UPDATE student_notes SET email_enc=?, email_hash=? WHERE email_hash=?",
                         (_enc(new_email), nh, h))
    return touched


def clear_students():
    """Wipe ALL sign-in history and student notes (fresh start)."""
    with get_db() as conn:
        conn.execute("DELETE FROM signins")
        conn.execute("DELETE FROM student_notes")
        conn.execute("DELETE FROM signin_flags")


# ───────────────────────── Incident reports ─────────────────────────

def add_incident(title, itype, severity, description, author,
                 involved_name="", involved_email=""):
    rid = uuid.uuid4().hex
    with get_db() as conn:
        conn.execute(
            """INSERT INTO incident_reports
               (id, title, type, severity, status, involved_hash,
                involved_name_enc, involved_email_enc, description_enc,
                author, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, title or "Untitled", itype or "other", severity or "low", "open",
             _email_hash(involved_email), _enc(involved_name), _enc(involved_email),
             _enc(description), author or "",
             datetime.now().isoformat(timespec="seconds")),
        )
    return rid


def _incident_to_dict(r):
    return {
        "id": r["id"],
        "title": r["title"] or "",
        "type": r["type"] or "other",
        "severity": r["severity"] or "low",
        "status": r["status"] or "open",
        "involved_name": _dec(r["involved_name_enc"]),
        "involved_email": _dec(r["involved_email_enc"]),
        "description": _dec(r["description_enc"]),
        "author": r["author"] or "",
        "created_at": r["created_at"],
        "resolved_at": r["resolved_at"],
        "resolved_by": r["resolved_by"] or "",
    }


def list_incidents(limit=300):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM incident_reports ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_incident_to_dict(r) for r in rows]


def get_incidents_for(email):
    """Incident reports that name a given student."""
    h = _email_hash(email)
    if not h:
        return []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM incident_reports WHERE involved_hash=? ORDER BY created_at DESC", (h,)
        ).fetchall()
    return [_incident_to_dict(r) for r in rows]


def resolve_incident(rid, resolved_by, status="resolved"):
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE incident_reports SET status=?, resolved_at=?, resolved_by=? WHERE id=?",
            (status, datetime.now().isoformat(timespec="seconds"), resolved_by or "", rid),
        )
        return cur.rowcount


def delete_incident(rid):
    with get_db() as conn:
        cur = conn.execute("DELETE FROM incident_reports WHERE id=?", (rid,))
        return cur.rowcount


# ───────────────────────── Watch / ban list (encrypted) ─────────────────────────

def watchlist_set(email, mode, reason, added_by):
    """Add or update a ban/watch entry (one per email)."""
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO watchlist
               (email_hash, email_enc, mode, reason_enc, added_by, added_at)
               VALUES (?,?,?,?,?,?)""",
            (_email_hash(email), _enc(email), "ban" if mode == "ban" else "watch",
             _enc(reason or ""), added_by or "", datetime.now().isoformat(timespec="seconds")),
        )


def _watch_to_dict(r):
    return {
        "email": _dec(r["email_enc"]),
        "mode": r["mode"] or "watch",
        "reason": _dec(r["reason_enc"]),
        "added_by": r["added_by"] or "",
        "added_at": r["added_at"],
    }


def watchlist_get(email):
    h = _email_hash(email)
    if not h:
        return None
    with get_db() as conn:
        r = conn.execute("SELECT * FROM watchlist WHERE email_hash=?", (h,)).fetchone()
    return _watch_to_dict(r) if r else None


def watchlist_all():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM watchlist ORDER BY added_at DESC").fetchall()
    return [_watch_to_dict(r) for r in rows]


def watchlist_remove(email):
    h = _email_hash(email)
    if not h:
        return 0
    with get_db() as conn:
        cur = conn.execute("DELETE FROM watchlist WHERE email_hash=?", (h,))
        return cur.rowcount


# ───────────────────────── Sign-in flags (encrypted) ─────────────────────────

def _flag_to_dict(r):
    return {
        "id": r["id"], "at": r["at"], "kind": r["kind"], "severity": r["severity"],
        "email": _dec(r["email_enc"]), "name": _dec(r["name_enc"]),
        "kiosk_id": r["kiosk_id"] or "", "kiosk_label": r["kiosk_label"] or "",
        "reason": _dec(r["reason_enc"]),
    }


def add_flag(kind, severity, email, name, kiosk_id, kiosk_label, reason, cap=200):
    """Record a sign-in flag; keeps only the newest `cap` rows."""
    fid = uuid.uuid4().hex
    now = datetime.now().isoformat(timespec="seconds")
    with get_db() as conn:
        conn.execute(
            """INSERT INTO signin_flags
               (id, at, kind, severity, email_hash, email_enc, name_enc, kiosk_id, kiosk_label, reason_enc)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (fid, now, kind, severity, _email_hash(email), _enc(email), _enc(name or ""),
             kiosk_id or "", kiosk_label or "", _enc(reason or "")),
        )
        conn.execute(
            "DELETE FROM signin_flags WHERE id NOT IN (SELECT id FROM signin_flags ORDER BY at DESC LIMIT ?)",
            (cap,),
        )
    return {"id": fid, "at": now, "kind": kind, "severity": severity,
            "email": email, "name": name or "", "kiosk_id": kiosk_id or "",
            "kiosk_label": kiosk_label or "", "reason": reason or ""}


def recent_flags(limit=60, since_minutes=None):
    with get_db() as conn:
        if since_minutes:
            cutoff = (datetime.now() - timedelta(minutes=since_minutes)).isoformat(timespec="seconds")
            rows = conn.execute(
                "SELECT * FROM signin_flags WHERE at >= ? ORDER BY at DESC LIMIT ?", (cutoff, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM signin_flags ORDER BY at DESC LIMIT ?", (limit,)
            ).fetchall()
    return [_flag_to_dict(r) for r in rows]


def clear_flags():
    with get_db() as conn:
        conn.execute("DELETE FROM signin_flags")


def migrate_watchlist(items):
    """One-time import of a legacy watchlist array (from the kiosk config JSON)."""
    n = 0
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        email = (it.get("email") or "").strip().lower()
        if not email or "@" not in email:
            continue
        with get_db() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO watchlist
                   (email_hash, email_enc, mode, reason_enc, added_by, added_at)
                   VALUES (?,?,?,?,?,?)""",
                (_email_hash(email), _enc(email), "ban" if it.get("mode") == "ban" else "watch",
                 _enc(it.get("reason") or ""), it.get("added_by") or "",
                 it.get("added_at") or datetime.now().isoformat(timespec="seconds")),
            )
        n += 1
    return n


def migrate_flags(items):
    """One-time import of a legacy arena_signin_flags.json list."""
    n = 0
    for f in (items or []):
        if not isinstance(f, dict):
            continue
        with get_db() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO signin_flags
                   (id, at, kind, severity, email_hash, email_enc, name_enc, kiosk_id, kiosk_label, reason_enc)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (f.get("id") or uuid.uuid4().hex, f.get("at") or "", f.get("kind") or "",
                 f.get("severity") or "", _email_hash(f.get("email")), _enc(f.get("email") or ""),
                 _enc(f.get("name") or ""), f.get("kiosk_id") or "", f.get("kiosk_label") or "",
                 _enc(f.get("reason") or "")),
            )
        n += 1
    return n
