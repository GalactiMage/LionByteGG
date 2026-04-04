"""
Equipment Database Module for Worker On Duty
SQLite-backed inventory management with atomic operations.
"""

import sqlite3
import os
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "equipment.db")


@contextmanager
def get_db():
    """Context manager for database connections with WAL mode."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
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


def init_equipment_db():
    """Initialize equipment tables and seed default items if empty."""
    os.makedirs(DB_DIR, exist_ok=True)

    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS equipment (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'other',
                expected_quantity INTEGER NOT NULL DEFAULT 0,
                current_quantity INTEGER NOT NULL DEFAULT 0,
                checked_out INTEGER NOT NULL DEFAULT 0,
                missing INTEGER NOT NULL DEFAULT 0,
                notes TEXT DEFAULT '',
                added_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                item_name TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'missing',
                quantity INTEGER NOT NULL DEFAULT 1,
                reported_by TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                notes TEXT DEFAULT '',
                resolved INTEGER NOT NULL DEFAULT 0,
                resolved_at TEXT,
                resolution TEXT DEFAULT '',
                FOREIGN KEY (item_id) REFERENCES equipment(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT,
                action TEXT NOT NULL,
                item_name TEXT NOT NULL,
                quantity INTEGER,
                performed_by TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                details TEXT DEFAULT '',
                checked_out_to TEXT DEFAULT '',
                notes TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS active_checkouts (
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                item_name TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                checked_out_to TEXT NOT NULL,
                person_id TEXT NOT NULL DEFAULT '',
                id_type TEXT NOT NULL DEFAULT '',
                purpose TEXT NOT NULL DEFAULT '',
                checked_out_by TEXT NOT NULL,
                checked_out_at TEXT NOT NULL,
                checked_in_at TEXT,
                checked_in_by TEXT,
                status TEXT NOT NULL DEFAULT 'out',
                notes TEXT DEFAULT '',
                FOREIGN KEY (item_id) REFERENCES equipment(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS qr_codes (
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                FOREIGN KEY (item_id) REFERENCES equipment(id) ON DELETE CASCADE
            );
        """)

        # Seed default items if the table is empty
        count = conn.execute("SELECT COUNT(*) FROM equipment").fetchone()[0]
        if count == 0:
            now = datetime.now(timezone.utc).isoformat()
            defaults = [
                ("eq_001", "Headphones", "headset", 32, 32, now),
                ("eq_002", "Keyboards", "keyboard", 32, 32, now),
                ("eq_003", "Mice", "mouse", 32, 32, now),
                ("eq_004", "Nintendo Switch", "console", 1, 1, now),
                ("eq_005", "Pro Controllers", "controller", 4, 4, now),
            ]
            conn.executemany(
                "INSERT INTO equipment (id, name, category, expected_quantity, current_quantity, added_at) VALUES (?, ?, ?, ?, ?, ?)",
                defaults,
            )


# ---- Item CRUD ----

def get_all_items():
    """Return all equipment items as list of dicts."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM equipment ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def get_item(item_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM equipment WHERE id = ?", (item_id,)).fetchone()
        return dict(row) if row else None


def add_item(name, category, expected_quantity, current_quantity, notes, performed_by):
    item_id = f"eq_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO equipment (id, name, category, expected_quantity, current_quantity, notes, added_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (item_id, name, category, expected_quantity, current_quantity, notes, now),
        )
        conn.execute(
            "INSERT INTO activity_log (item_id, action, item_name, performed_by, timestamp, details) VALUES (?, 'added', ?, ?, ?, ?)",
            (item_id, name, performed_by, now, f"Added {expected_quantity}x {name}"),
        )
    return get_item(item_id)


def update_item(item_id, name, category, expected_quantity, current_quantity, notes, performed_by):
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE equipment SET name=?, category=?, expected_quantity=?, current_quantity=?, notes=? WHERE id=?",
            (name, category, expected_quantity, current_quantity, notes, item_id),
        )
        if cur.rowcount == 0:
            return None
        conn.execute(
            "INSERT INTO activity_log (item_id, action, item_name, performed_by, timestamp, details) VALUES (?, 'updated', ?, ?, ?, ?)",
            (item_id, name, performed_by, now, f"Updated {name}"),
        )
    return get_item(item_id)


def delete_item(item_id, performed_by):
    with get_db() as conn:
        row = conn.execute("SELECT name FROM equipment WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return False
        name = row["name"]
        conn.execute("DELETE FROM equipment WHERE id = ?", (item_id,))
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO activity_log (item_id, action, item_name, performed_by, timestamp, details) VALUES (?, 'removed', ?, ?, ?, ?)",
            (item_id, name, performed_by, now, f"Removed {name} from inventory"),
        )
    return True


# ---- Checkout / Checkin ----

def checkout_item(item_id, quantity, checked_out_to, notes, performed_by, person_id="", id_type="", purpose=""):
    now = datetime.now(timezone.utc).isoformat()
    checkout_id = f"co_{uuid.uuid4().hex[:12]}"
    with get_db() as conn:
        row = conn.execute("SELECT * FROM equipment WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return None, "Item not found"
        if row["current_quantity"] < quantity:
            return None, "Not enough available"
        conn.execute(
            "UPDATE equipment SET current_quantity = current_quantity - ?, checked_out = checked_out + ? WHERE id = ?",
            (quantity, quantity, item_id),
        )
        conn.execute(
            "INSERT INTO active_checkouts (id, item_id, item_name, quantity, checked_out_to, person_id, id_type, purpose, checked_out_by, checked_out_at, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (checkout_id, item_id, row["name"], quantity, checked_out_to, person_id, id_type, purpose, performed_by, now, notes),
        )
        details = f"{quantity}x {row['name']} to {checked_out_to}"
        if person_id:
            details += f" (ID: {id_type} {person_id})"
        if purpose:
            details += f" — {purpose}"
        conn.execute(
            "INSERT INTO activity_log (item_id, action, item_name, quantity, checked_out_to, performed_by, timestamp, notes, details) VALUES (?, 'checkout', ?, ?, ?, ?, ?, ?, ?)",
            (item_id, row["name"], quantity, checked_out_to, performed_by, now, notes, details),
        )
    return get_item(item_id), None


def checkin_item(item_id, quantity, notes, performed_by, checkout_id="", condition="good"):
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM equipment WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return None, "Item not found"
        if row["checked_out"] < quantity:
            return None, "Cannot check in more than checked out"
        conn.execute(
            "UPDATE equipment SET current_quantity = current_quantity + ?, checked_out = checked_out - ? WHERE id = ?",
            (quantity, quantity, item_id),
        )
        # Close the active checkout record if provided
        if checkout_id:
            conn.execute(
                "UPDATE active_checkouts SET status = 'returned', checked_in_at = ?, checked_in_by = ?, notes = CASE WHEN notes = '' THEN ? ELSE notes || ' | Return: ' || ? END WHERE id = ?",
                (now, performed_by, notes, notes, checkout_id),
            )
        else:
            # Close the oldest active checkout for this item
            oldest = conn.execute(
                "SELECT id FROM active_checkouts WHERE item_id = ? AND status = 'out' ORDER BY checked_out_at ASC LIMIT 1",
                (item_id,),
            ).fetchone()
            if oldest:
                conn.execute(
                    "UPDATE active_checkouts SET status = 'returned', checked_in_at = ?, checked_in_by = ?, notes = CASE WHEN notes = '' THEN ? ELSE notes || ' | Return: ' || ? END WHERE id = ?",
                    (now, performed_by, notes, notes, oldest["id"]),
                )
        details = f"{quantity}x {row['name']} returned"
        if condition != "good":
            details += f" (condition: {condition})"
        conn.execute(
            "INSERT INTO activity_log (item_id, action, item_name, quantity, performed_by, timestamp, notes, details) VALUES (?, 'checkin', ?, ?, ?, ?, ?, ?)",
            (item_id, row["name"], quantity, performed_by, now, notes, details),
        )
    return get_item(item_id), None


# ---- Active Checkouts ----

def get_active_checkouts():
    """Return all currently checked-out items."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM active_checkouts WHERE status = 'out' ORDER BY checked_out_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_checkouts(limit=200):
    """Return all checkout records (active and returned)."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM active_checkouts ORDER BY checked_out_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---- Reports ----

def report_item(item_id, report_type, quantity, notes, performed_by):
    now = datetime.now(timezone.utc).isoformat()
    report_id = f"rpt_{uuid.uuid4().hex[:12]}"
    with get_db() as conn:
        row = conn.execute("SELECT * FROM equipment WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return None, None, "Item not found"
        conn.execute(
            "UPDATE equipment SET missing = missing + ?, current_quantity = MAX(0, current_quantity - ?) WHERE id = ?",
            (quantity, quantity, item_id),
        )
        conn.execute(
            "INSERT INTO reports (id, item_id, item_name, type, quantity, reported_by, timestamp, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (report_id, item_id, row["name"], report_type, quantity, performed_by, now, notes),
        )
        conn.execute(
            "INSERT INTO activity_log (item_id, action, item_name, quantity, performed_by, timestamp, details) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (item_id, f"reported_{report_type}", row["name"], quantity, performed_by, now, f"{quantity}x {row['name']} reported as {report_type}"),
        )
    report = get_report(report_id)
    item = get_item(item_id)
    return report, item, None


def get_report(report_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        return dict(row) if row else None


def get_all_reports():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM reports ORDER BY timestamp DESC").fetchall()
        return [dict(r) for r in rows]


def resolve_report(report_id, resolution, recovered, performed_by):
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE reports SET resolved = 1, resolved_at = ?, resolution = ? WHERE id = ?",
            (now, resolution, report_id),
        )
        if recovered:
            conn.execute(
                "UPDATE equipment SET missing = MAX(0, missing - ?), current_quantity = current_quantity + ? WHERE id = ?",
                (row["quantity"], row["quantity"], row["item_id"]),
            )
        conn.execute(
            "INSERT INTO activity_log (item_id, action, item_name, performed_by, timestamp, details) VALUES (?, 'report_resolved', ?, ?, ?, ?)",
            (row["item_id"], row["item_name"], performed_by, now, f"Resolved: {resolution}, Recovered: {recovered}"),
        )
    return True


# ---- Activity Log ----

def get_activity_log(limit=200):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM activity_log ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


# ---- Export helpers ----

def get_full_export():
    """Return items, reports, checkouts, and log for CSV export."""
    return {
        "items": get_all_items(),
        "reports": get_all_reports(),
        "checkouts": get_all_checkouts(500),
        "log": get_activity_log(500),
    }


# ---- QR Code helpers ----

def create_qr_code(item_id, created_by):
    """Create a persistent QR code record for an equipment item."""
    qr_id = f"qr_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO qr_codes (id, item_id, created_at, created_by) VALUES (?, ?, ?, ?)",
            (qr_id, item_id, now, created_by),
        )
    return {"id": qr_id, "item_id": item_id, "created_at": now, "created_by": created_by}


def get_qr_code(qr_id):
    """Get a QR code record by its ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM qr_codes WHERE id = ?", (qr_id,)).fetchone()
        return dict(row) if row else None


def get_qr_codes_for_item(item_id):
    """Get all QR codes for an equipment item."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM qr_codes WHERE item_id = ? ORDER BY created_at DESC", (item_id,)).fetchall()
        return [dict(r) for r in rows]


def get_all_qr_codes():
    """Get all QR codes."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT qr_codes.*, equipment.name as item_name FROM qr_codes "
            "LEFT JOIN equipment ON qr_codes.item_id = equipment.id ORDER BY qr_codes.created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def delete_qr_code(qr_id):
    """Delete a QR code (makes it stop working)."""
    with get_db() as conn:
        conn.execute("DELETE FROM qr_codes WHERE id = ?", (qr_id,))
    return True
