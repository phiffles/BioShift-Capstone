import sqlite3
import datetime
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.db")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = _connect()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS scans (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT    NOT NULL,
            case_name       TEXT,
            notes           TEXT,
            person_age      INTEGER,
            legacy_photo    TEXT,
            live_photo      TEXT,
            generated_photo TEXT,
            current_age     INTEGER,
            target_age      INTEGER,
            direction       TEXT    DEFAULT 'older',
            similarity_score REAL,
            distance        REAL,
            threshold_used  REAL,
            verified        INTEGER,
            status          TEXT    DEFAULT 'pending',
            resolution      TEXT,
            reviewer_note   TEXT,
            consent_given      INTEGER DEFAULT 0,
            consent_timestamp  TEXT,
            consent_text_hash  TEXT
        )
    ''')

    # ── Migration: add consent columns to existing tables ──
    for col, typedef in [
        ("consent_given",     "INTEGER DEFAULT 0"),
        ("consent_timestamp", "TEXT"),
        ("consent_text_hash", "TEXT"),
    ]:
        try:
            c.execute(f"ALTER TABLE scans ADD COLUMN {col} {typedef}")
        except Exception:
            pass  # column already exists

    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    # Seed default threshold if not set
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('threshold', '75')")

    c.execute('''
        CREATE TABLE IF NOT EXISTS scan_legacy_photos (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id           INTEGER NOT NULL,
            photo_path        TEXT,
            generated_photo   TEXT,
            similarity_score  REAL,
            is_primary        INTEGER DEFAULT 0,
            FOREIGN KEY (scan_id) REFERENCES scans(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS training_submissions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id        INTEGER,
            timestamp      TEXT    NOT NULL,
            old_photo      TEXT,
            current_photo  TEXT,
            note           TEXT,
            status         TEXT    DEFAULT 'sent',
            FOREIGN KEY (scan_id) REFERENCES scans(id)
        )
    ''')

    conn.commit()
    conn.close()


# ── Scans ─────────────────────────────────────────────────────

def create_scan(legacy_photo, live_photo, person_age, case_name=None, notes=None,
                consent_given=False):
    """Create a new scan record with the two input photos. Returns the scan id."""
    conn = _connect()
    c = conn.cursor()
    c.execute('''
        INSERT INTO scans (timestamp, case_name, notes, person_age, legacy_photo, live_photo,
                           status, consent_given, consent_timestamp)
        VALUES (?, ?, ?, ?, ?, ?, 'processing', ?, ?)
    ''', (
        datetime.datetime.now().isoformat(),
        case_name,
        notes,
        person_age,
        legacy_photo,
        live_photo,
        int(consent_given),
        datetime.datetime.now().isoformat() if consent_given else None,
    ))
    scan_id = c.lastrowid
    conn.commit()
    conn.close()
    return scan_id


def set_scan_photos(scan_id, legacy_photo, live_photo):
    """Fill in the input photo paths after they've been written to the
    scan's own output folder (which is named after scan_id, so the row has
    to exist before the files can be placed)."""
    conn = _connect()
    conn.execute(
        'UPDATE scans SET legacy_photo = ?, live_photo = ? WHERE id = ?',
        (legacy_photo, live_photo, scan_id)
    )
    conn.commit()
    conn.close()


def update_scan_results(scan_id, generated_photo, current_age, target_age,
                        direction, similarity_score, distance, threshold_used, verified):
    """Fill in the AI results after the pipeline finishes."""
    # Determine status based on threshold
    if verified:
        status = "pass"
    elif similarity_score is None:
        # No score at all means face verification was unavailable, not that the
        # faces failed to match — that is a human-review case, not a rejection.
        status = "pending_review"
    elif similarity_score >= (threshold_used - 10):
        status = "pending_review"   # borderline → discrepancy queue
    else:
        status = "fail"

    conn = _connect()
    c = conn.cursor()
    c.execute('''
        UPDATE scans SET
            generated_photo  = ?,
            current_age      = ?,
            target_age       = ?,
            direction        = ?,
            similarity_score = ?,
            distance         = ?,
            threshold_used   = ?,
            verified         = ?,
            status           = ?
        WHERE id = ?
    ''', (
        generated_photo, current_age, target_age, direction,
        similarity_score, distance, threshold_used, int(verified),
        status, scan_id,
    ))
    conn.commit()
    conn.close()
    return status


def resolve_scan(scan_id, resolution, reviewer_note=None):
    """Admin resolves a queued scan."""
    conn = _connect()
    c = conn.cursor()
    c.execute('''
        UPDATE scans SET
            status        = 'resolved',
            resolution    = ?,
            reviewer_note = ?
        WHERE id = ?
    ''', (resolution, reviewer_note, scan_id))
    conn.commit()
    conn.close()


def get_scan(scan_id):
    conn = _connect()
    row = conn.execute('SELECT * FROM scans WHERE id = ?', (scan_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_scan(scan_id):
    conn = _connect()
    # Clear child rows first — scan_legacy_photos/training_submissions have a
    # foreign key on scan_id (PRAGMA foreign_keys=ON), so the parent scan
    # can't be deleted while they still reference it.
    conn.execute('DELETE FROM scan_legacy_photos WHERE scan_id = ?', (scan_id,))
    conn.execute('UPDATE training_submissions SET scan_id = NULL WHERE scan_id = ?', (scan_id,))
    conn.execute('DELETE FROM scans WHERE id = ?', (scan_id,))
    conn.commit()
    conn.close()


def get_all_scans(limit=50):
    conn = _connect()
    rows = conn.execute(
        'SELECT * FROM scans ORDER BY timestamp DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_queue():
    """Scans awaiting admin review (failed or borderline)."""
    conn = _connect()
    rows = conn.execute('''
        SELECT * FROM scans
        WHERE status IN ('fail', 'pending_review')
        ORDER BY timestamp DESC
    ''').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats():
    """Dashboard KPIs."""
    conn = _connect()
    c = conn.cursor()
    total = c.execute('SELECT COUNT(*) FROM scans').fetchone()[0]
    passed = c.execute("SELECT COUNT(*) FROM scans WHERE status = 'pass'").fetchone()[0]
    flagged = c.execute(
        "SELECT COUNT(*) FROM scans WHERE status IN ('fail', 'pending_review')"
    ).fetchone()[0]
    resolved = c.execute("SELECT COUNT(*) FROM scans WHERE status = 'resolved'").fetchone()[0]
    conn.close()
    return {
        "total_scans": total,
        "passed": passed,
        "pass_rate": round((passed / total * 100) if total > 0 else 0, 1),
        "flagged": flagged,
        "resolved": resolved,
    }


# ── Legacy Reference Photos (multi-photo upload) ───────────────

def add_legacy_photo(scan_id, photo_path, generated_photo, similarity_score, is_primary=False):
    conn = _connect()
    c = conn.cursor()
    c.execute('''
        INSERT INTO scan_legacy_photos (scan_id, photo_path, generated_photo, similarity_score, is_primary)
        VALUES (?, ?, ?, ?, ?)
    ''', (scan_id, photo_path, generated_photo, similarity_score, int(is_primary)))
    photo_id = c.lastrowid
    conn.commit()
    conn.close()
    return photo_id


def get_legacy_photos(scan_id):
    conn = _connect()
    rows = conn.execute(
        'SELECT * FROM scan_legacy_photos WHERE scan_id = ? ORDER BY id', (scan_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Training Data Submissions ──────────────────────────────────

def create_training_submission(scan_id, old_photo, current_photo, note=None):
    """Admin submits a corrected labeled photo pair for retraining."""
    conn = _connect()
    c = conn.cursor()
    c.execute('''
        INSERT INTO training_submissions (scan_id, timestamp, old_photo, current_photo, note, status)
        VALUES (?, ?, ?, ?, ?, 'sent')
    ''', (scan_id, datetime.datetime.now().isoformat(), old_photo, current_photo, note))
    sub_id = c.lastrowid
    conn.commit()
    conn.close()
    return sub_id


def set_training_photos(sub_id, old_photo, current_photo):
    """Fill in the training pair's photo paths after they've been written to
    image_folder/training/<sub_id>/ (folder is named after the row id)."""
    conn = _connect()
    conn.execute(
        'UPDATE training_submissions SET old_photo = ?, current_photo = ? WHERE id = ?',
        (old_photo, current_photo, sub_id)
    )
    conn.commit()
    conn.close()


def get_training_submissions():
    conn = _connect()
    rows = conn.execute('''
        SELECT training_submissions.*, scans.case_name AS scan_case_name
        FROM training_submissions
        LEFT JOIN scans ON scans.id = training_submissions.scan_id
        ORDER BY training_submissions.timestamp DESC
    ''').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_training_status(sub_id, status):
    conn = _connect()
    conn.execute('UPDATE training_submissions SET status = ? WHERE id = ?', (status, sub_id))
    conn.commit()
    conn.close()


def delete_training_submission(sub_id):
    conn = _connect()
    conn.execute('DELETE FROM training_submissions WHERE id = ?', (sub_id,))
    conn.commit()
    conn.close()


# ── Settings ──────────────────────────────────────────────────

def get_setting(key, default=None):
    conn = _connect()
    row = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
    conn.close()
    return row[0] if row else default


def set_setting(key, value):
    conn = _connect()
    conn.execute(
        'INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?',
        (key, str(value), str(value))
    )
    conn.commit()
    conn.close()


# ── Legacy compatibility (keep old app.py working) ────────────

def log_generation(input_path, output_path, current_age, target_age, direction="older"):
    """Backward-compatible wrapper for the old Gradio app."""
    conn = _connect()
    c = conn.cursor()
    c.execute('''
        INSERT INTO scans (timestamp, legacy_photo, generated_photo, current_age, target_age, direction, status)
        VALUES (?, ?, ?, ?, ?, ?, 'pass')
    ''', (
        datetime.datetime.now().isoformat(),
        input_path, output_path, current_age, target_age, direction,
    ))
    row_id = c.lastrowid
    conn.commit()
    conn.close()
    return row_id


def get_history():
    """Backward-compatible wrapper for the old Gradio app."""
    return get_all_scans()
