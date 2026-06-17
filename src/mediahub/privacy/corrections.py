"""Post-publication correction / takedown log (accuracy & defamation duty).

When a club discovers a published card is wrong (wrong result, misidentified
athlete), the in-product flow must do everything the system CAN do and be
honest about what it can't:

- record the correction request (timestamped, reasoned, per card) in
  ``data.db`` so there is an auditable trail;
- pull the card off every surface MediaHub controls (the public wall, via
  the profile's ``public_wall_excluded_cards``) — done by the web route;
- tell the operator what remains manual: deleting/editing the post on the
  social platform itself. MediaHub does not publish on the operator's behalf,
  so a correction never reaches an already-posted item — the checklist says so
  plainly.

Exception-safe SQLite conventions throughout (errors are swallowed and logged,
never raised at the caller).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS content_corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id   TEXT NOT NULL,
    run_id       TEXT NOT NULL,
    card_id      TEXT NOT NULL,
    reason       TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    status       TEXT NOT NULL,
    resolved_at  TEXT,
    resolution   TEXT
);
CREATE INDEX IF NOT EXISTS idx_corrections_profile
    ON content_corrections(profile_id, requested_at DESC);
"""

STATUS_OPEN = "open"
STATUS_RESOLVED = "resolved"

# What the club must still do by hand once MediaHub has done its part.
TAKEDOWN_CHECKLIST = (
    "Delete or edit the post on each social platform it was published to "
    "(MediaHub cannot edit or remove a post after it has shipped).",
    "If the wrong content named an individual, consider telling them or "
    "their parent what was published and what has been corrected.",
    "Re-generate and re-approve a corrected card if a replacement is needed.",
)


def _db_path() -> Path:
    base = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))
    return base / "data.db"


def _connect() -> sqlite3.Connection:
    p = _db_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema() -> None:
    try:
        conn = _connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        log.warning("corrections: schema bootstrap failed: %s", exc)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def open_correction(*, profile_id: str, run_id: str, card_id: str, reason: str) -> int:
    """Record a correction request. Returns the row id (0 on failure)."""
    if not all(str(v or "").strip() for v in (profile_id, run_id, card_id, reason)):
        return 0
    _ensure_schema()
    try:
        conn = _connect()
        try:
            cur = conn.execute(
                "INSERT INTO content_corrections "
                "(profile_id, run_id, card_id, reason, requested_at, status) "
                "VALUES (?,?,?,?,?,?)",
                (profile_id, run_id, card_id, reason.strip()[:2000], _now(), STATUS_OPEN),
            )
            conn.commit()
            return int(cur.lastrowid or 0)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("corrections: open failed: %s", exc)
        return 0


def resolve_correction(*, profile_id: str, correction_id: int, resolution: str = "") -> bool:
    """Mark a correction resolved (tenant-scoped)."""
    _ensure_schema()
    try:
        conn = _connect()
        try:
            cur = conn.execute(
                "UPDATE content_corrections "
                "SET status=?, resolved_at=?, resolution=? "
                "WHERE id=? AND profile_id=? AND status=?",
                (
                    STATUS_RESOLVED,
                    _now(),
                    (resolution or "").strip()[:2000],
                    int(correction_id),
                    profile_id,
                    STATUS_OPEN,
                ),
            )
            conn.commit()
            return bool(cur.rowcount)
        finally:
            conn.close()
    except (sqlite3.Error, ValueError) as exc:
        log.warning("corrections: resolve failed: %s", exc)
        return False


def list_corrections(profile_id: str, *, status: str = "") -> list[dict]:
    """Newest-first corrections for one org (optionally filtered by status)."""
    if not (profile_id or "").strip():
        return []
    _ensure_schema()
    try:
        conn = _connect()
        try:
            if status:
                rows = conn.execute(
                    "SELECT * FROM content_corrections "
                    "WHERE profile_id=? AND status=? ORDER BY requested_at DESC, id DESC",
                    (profile_id, status),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM content_corrections "
                    "WHERE profile_id=? ORDER BY requested_at DESC, id DESC",
                    (profile_id,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("corrections: list failed: %s", exc)
        return []


__all__ = [
    "STATUS_OPEN",
    "STATUS_RESOLVED",
    "TAKEDOWN_CHECKLIST",
    "list_corrections",
    "open_correction",
    "resolve_correction",
]
