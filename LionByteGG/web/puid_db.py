"""
Secure PUID store — encrypted at rest.

Purdue University IDs (PUIDs) are highly sensitive. They live in a dedicated
SQLite database, encrypted with the same Fernet key Nova uses for roster/PII.
A PUID is located by a one-way SHA-256 hash and is NEVER returned to any
caller — only the student profile linked to it is ever exposed.
"""

import os
import sqlite3
import hashlib
import hmac
import secrets
import stat
from contextlib import contextmanager
from datetime import datetime

from arena_db import _enc, _dec, _email_hash  # share the Fernet PII key + email hashing

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_PATH = os.path.join(DB_DIR, "puid.db")
PEPPER_FILE = os.path.join(DB_DIR, ".puid_pepper")

_pepper_cache = None


def _pepper():
    """Secret 'pepper' for the keyed PUID hash. Loaded from the NOVA_PUID_PEPPER
    env var if set, otherwise from a dedicated file that is kept SEPARATE from the
    database — so an attacker with only puid.db can't brute-force the 10-digit
    hashes back into PUIDs."""
    global _pepper_cache
    if _pepper_cache is not None:
        return _pepper_cache
    env = os.environ.get("NOVA_PUID_PEPPER")
    if env:
        _pepper_cache = env.encode("utf-8")
        return _pepper_cache
    os.makedirs(DB_DIR, exist_ok=True)
    if os.path.exists(PEPPER_FILE):
        with open(PEPPER_FILE, "rb") as f:
            _pepper_cache = f.read().strip()
    else:
        _pepper_cache = secrets.token_hex(32).encode("utf-8")
        with open(PEPPER_FILE, "wb") as f:
            f.write(_pepper_cache)
        try:
            os.chmod(PEPPER_FILE, stat.S_IRUSR | stat.S_IWUSR)  # owner-only (best effort)
        except Exception:
            pass
    return _pepper_cache


def normalize_puid(raw):
    """Keep only digits — barcode scanners can prepend/append control chars."""
    return "".join(ch for ch in str(raw or "") if ch.isdigit())


def is_valid_puid(puid):
    return len(normalize_puid(puid)) == 10


def _hash(puid):
    """Keyed HMAC-SHA256 lookup key. Unlike a plain hash, this is infeasible to
    brute-force without the secret pepper even though a PUID is only 10 digits."""
    p = normalize_puid(puid)
    if not p:
        return ""
    return hmac.new(_pepper(), ("puid:" + p).encode("utf-8"), hashlib.sha256).hexdigest()


@contextmanager
def get_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_puid_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS puids (
                puid_hash   TEXT PRIMARY KEY,
                puid_enc    TEXT,
                name_enc    TEXT,
                first_enc   TEXT,
                last_enc    TEXT,
                email_enc   TEXT,
                email_hash  TEXT,
                created_at  TEXT,
                last_seen   TEXT,
                visits      INTEGER DEFAULT 0
            );
        """)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(puids)").fetchall()]
        if "email_hash" not in cols:
            conn.execute("ALTER TABLE puids ADD COLUMN email_hash TEXT")


def _row_to_profile(r):
    if not r:
        return None
    return {
        "name": _dec(r["name_enc"]),
        "first_name": _dec(r["first_enc"]),
        "last_name": _dec(r["last_enc"]),
        "email": _dec(r["email_enc"]),
        "created_at": r["created_at"],
        "last_seen": r["last_seen"],
        "visits": r["visits"] or 0,
    }


def lookup(puid):
    """Return the student profile linked to a PUID, or None. Never returns the PUID itself."""
    h = _hash(puid)
    if not h:
        return None
    with get_db() as conn:
        r = conn.execute("SELECT * FROM puids WHERE puid_hash=?", (h,)).fetchone()
    return _row_to_profile(r)


def register(puid, first_name="", last_name="", name="", email=""):
    """Create or update the profile linked to a PUID. Returns the stored profile."""
    h = _hash(puid)
    if not h:
        return None
    now = datetime.now().isoformat(timespec="seconds")
    full = name or (first_name + " " + last_name).strip()
    with get_db() as conn:
        prev = conn.execute("SELECT created_at, visits FROM puids WHERE puid_hash=?", (h,)).fetchone()
        created = prev["created_at"] if prev else now
        visits = prev["visits"] if prev else 0
        conn.execute(
            """INSERT OR REPLACE INTO puids
               (puid_hash, puid_enc, name_enc, first_enc, last_enc, email_enc, email_hash, created_at, last_seen, visits)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (h, _enc(normalize_puid(puid)), _enc(full), _enc(first_name), _enc(last_name),
             _enc(email), _email_hash(email), created, now, visits))
    return lookup(puid)


def delete_by_email(email):
    """Remove the PUID registration linked to an email (used to 'reset' an
    account so the student re-registers on their next scan). Returns rows removed."""
    eh = _email_hash(email)
    if not eh:
        return 0
    with get_db() as conn:
        return conn.execute("DELETE FROM puids WHERE email_hash=?", (eh,)).rowcount


def update_by_email(email, new_name=None, new_email=None):
    """Keep a PUID profile in sync when a student's info is edited in Nova."""
    eh = _email_hash(email)
    if not eh:
        return 0
    with get_db() as conn:
        row = conn.execute("SELECT * FROM puids WHERE email_hash=?", (eh,)).fetchone()
        if not row:
            return 0
        name = new_name if new_name is not None else _dec(row["name_enc"])
        parts = (name or "").strip().split()
        first = parts[0] if parts else ""
        last = " ".join(parts[1:]) if len(parts) > 1 else ""
        em = new_email or _dec(row["email_enc"])
        conn.execute(
            "UPDATE puids SET name_enc=?, first_enc=?, last_enc=?, email_enc=?, email_hash=? WHERE puid_hash=?",
            (_enc(name), _enc(first), _enc(last), _enc(em), _email_hash(em), row["puid_hash"]))
    return 1


def touch(puid):
    """Bump last_seen + visit count for a known PUID."""
    h = _hash(puid)
    if not h:
        return
    now = datetime.now().isoformat(timespec="seconds")
    with get_db() as conn:
        conn.execute("UPDATE puids SET last_seen=?, visits=visits+1 WHERE puid_hash=?", (now, h))


def count():
    with get_db() as conn:
        return conn.execute("SELECT COUNT(*) c FROM puids").fetchone()["c"]
