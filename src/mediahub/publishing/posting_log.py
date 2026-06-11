"""Posting-attempt log — SQLite store for every publish attempt.

Every call into the publishing layer (Buffer today, future schedulers
tomorrow) lands one row here, regardless of whether the call succeeded
or failed. The log is observability, not critical path:

  * It is never on the request-blocking failure mode for posting itself.
    If the DB write fails, we swallow the error and log a warning via
    the stdlib logging module — the caller is unaffected.
  * It is intentionally lossy: a retention sweep trims the table down
    to ~4,500 rows whenever it crosses 5,000, so the log never grows
    unbounded on a long-running deploy.

The store reuses the same SQLite file as the rest of MediaHub
(``DATA_DIR/data.db``) so the posting_attempts table sits alongside
``runs`` and is included in any future publish-snapshot workflow.

Public API:
    record_attempt(...)            — insert one attempt; returns row id
    recent_attempts(profile_id)    — newest-first list of rows
    attempts_summary_for_run(...)  — ok/failed counts + last attempted_at

All public functions are exception-safe — DB issues yield a safe default
(0 / [] / a default dict) rather than raising.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Storage paths — same convention as web.py / media_library/store.py
# ---------------------------------------------------------------------------


def _db_path() -> Path:
    """The shared data.db, resolved from the LIVE environment on every call.

    Previously frozen at import time — which silently pinned the log to
    whichever DATA_DIR happened to be set when the module first loaded
    (wrong under tests, env reconfiguration, or any pre-env import). The
    posting log must always land beside the data it describes.
    """
    base = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))
    return base / "data.db"


# ---------------------------------------------------------------------------
# Retention sweep thresholds (overridable from tests via monkeypatch)
# ---------------------------------------------------------------------------

_PRUNE_THRESHOLD = 5000  # row count that trips the sweep
_PRUNE_TARGET = 4500  # row count we trim down to


# ---------------------------------------------------------------------------
# Field validation buckets
# ---------------------------------------------------------------------------

_VALID_STATUSES = {"ok", "failed"}
_CAPTION_EXCERPT_LEN = 200


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS posting_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id      TEXT NOT NULL,
    run_id          TEXT NOT NULL,
    card_id         TEXT NOT NULL,
    channel_id      TEXT,
    channel_name    TEXT,
    service         TEXT,
    attempted_at    TEXT NOT NULL,
    scheduled_at    TEXT,
    status          TEXT NOT NULL,
    error_kind      TEXT,
    error_message   TEXT,
    update_id       TEXT,
    caption_excerpt TEXT,
    media_url       TEXT
);
CREATE INDEX IF NOT EXISTS idx_attempts_profile_at
    ON posting_attempts(profile_id, attempted_at DESC);
CREATE INDEX IF NOT EXISTS idx_attempts_run_card
    ON posting_attempts(run_id, card_id);
"""


_ROW_FIELDS = (
    "id",
    "profile_id",
    "run_id",
    "card_id",
    "channel_id",
    "channel_name",
    "service",
    "attempted_at",
    "scheduled_at",
    "status",
    "error_kind",
    "error_message",
    "update_id",
    "caption_excerpt",
    "media_url",
)


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------


def _connect() -> sqlite3.Connection:
    """Open a connection to the live data.db with WAL journaling enabled.

    Caller is responsible for closing. Raises sqlite3.Error on failure so
    the public API can catch and degrade gracefully.
    """
    db_path = _db_path()
    # Best-effort parent dir creation so the very first call doesn't
    # error if DATA_DIR has just been pointed at a fresh tmpdir.
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        # If even the mkdir fails, sqlite3.connect below will raise
        # and the public wrapper will swallow it. No need to be louder.
        pass
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        # WAL is a performance optimisation, not a correctness requirement.
        pass
    return conn


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------


def _ensure_schema() -> None:
    """Create the posting_attempts table + indexes if missing.

    Idempotent — safe to call on every operation, but in practice we call
    it once at import time and again defensively inside record_attempt.
    Swallows errors so import never crashes if DATA_DIR is wonky.
    """
    try:
        conn = _connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("posting_log: schema bootstrap failed: %s", exc)
    except OSError as exc:
        log.warning("posting_log: schema bootstrap OS error: %s", exc)


# Best-effort schema bootstrap on import. If this fails (e.g. DATA_DIR
# points somewhere unwritable) the public API will still degrade safely.
_ensure_schema()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record_attempt(
    *,
    profile_id: str,
    run_id: str,
    card_id: str,
    channel_id: str = "",
    channel_name: str = "",
    service: str = "",
    status: str,
    error_kind: Optional[str] = None,
    error_message: Optional[str] = None,
    update_id: Optional[str] = None,
    caption: str = "",
    media_url: Optional[str] = None,
    scheduled_at: Optional[str] = None,
    attempted_at: Optional[str] = None,
) -> int:
    """Insert one attempt row. Returns the new row id (0 on any failure).

    Validates: status must be one of {'ok','failed'}; profile_id, run_id,
    and card_id must all be non-empty. caption is truncated to a 200-char
    excerpt before persistence.

    After a successful insert, if the table holds more than
    ``_PRUNE_THRESHOLD`` rows we trim it back to ``_PRUNE_TARGET`` so
    the log can't grow unbounded.

    Never raises — DB failures are swallowed and logged. Returns 0 on
    any validation or storage error.
    """
    # ---- validation ----------------------------------------------------
    if status not in _VALID_STATUSES:
        return 0
    if not profile_id or not str(profile_id).strip():
        return 0
    if not run_id or not str(run_id).strip():
        return 0
    if not card_id or not str(card_id).strip():
        return 0

    when = attempted_at or datetime.now(timezone.utc).isoformat()
    caption_text = caption or ""
    excerpt = caption_text[:_CAPTION_EXCERPT_LEN]

    sql = (
        "INSERT INTO posting_attempts ("
        "profile_id, run_id, card_id, channel_id, channel_name, service, "
        "attempted_at, scheduled_at, status, error_kind, error_message, "
        "update_id, caption_excerpt, media_url"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    params = (
        str(profile_id).strip(),
        str(run_id).strip(),
        str(card_id).strip(),
        str(channel_id or ""),
        str(channel_name or ""),
        str(service or ""),
        when,
        scheduled_at,
        status,
        error_kind,
        error_message,
        update_id,
        excerpt,
        media_url,
    )

    try:
        # Defensive: ensure schema exists in case the import-time
        # bootstrap was racing or DATA_DIR changed between calls.
        _ensure_schema()
        conn = _connect()
        try:
            cur = conn.execute(sql, params)
            new_id = int(cur.lastrowid or 0)
            conn.commit()
            _maybe_prune(conn)
            return new_id
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("posting_log: record_attempt failed: %s", exc)
        return 0
    except OSError as exc:
        log.warning("posting_log: record_attempt OS error: %s", exc)
        return 0


def recent_attempts(
    profile_id: str,
    *,
    limit: int = 20,
    run_id: Optional[str] = None,
    card_id: Optional[str] = None,
) -> list[dict]:
    """Return the most recent attempts for ``profile_id``, newest first.

    Optional ``run_id`` and ``card_id`` filters tighten the query. Each
    returned row is a dict containing all schema fields. Returns ``[]``
    on any DB error or if ``profile_id`` is empty.
    """
    if not profile_id or not str(profile_id).strip():
        return []
    try:
        safe_limit = int(limit) if limit is not None else 20
    except (TypeError, ValueError):
        safe_limit = 20
    if safe_limit <= 0:
        return []

    sql_parts = [
        "SELECT id, profile_id, run_id, card_id, channel_id, channel_name, "
        "service, attempted_at, scheduled_at, status, error_kind, "
        "error_message, update_id, caption_excerpt, media_url "
        "FROM posting_attempts WHERE profile_id = ?"
    ]
    args: list = [str(profile_id).strip()]
    if run_id:
        sql_parts.append("AND run_id = ?")
        args.append(str(run_id).strip())
    if card_id:
        sql_parts.append("AND card_id = ?")
        args.append(str(card_id).strip())
    sql_parts.append("ORDER BY attempted_at DESC, id DESC LIMIT ?")
    args.append(safe_limit)
    sql = " ".join(sql_parts)

    try:
        conn = _connect()
        try:
            cur = conn.execute(sql, args)
            rows = cur.fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("posting_log: recent_attempts failed: %s", exc)
        return []
    except OSError as exc:
        log.warning("posting_log: recent_attempts OS error: %s", exc)
        return []

    return [_row_to_dict(r) for r in rows]


def attempts_summary_for_run(profile_id: str, run_id: str) -> dict:
    """Return ``{ok: int, failed: int, last_attempted_at: str|None}``.

    Returns a zeroed default dict on any error or missing identifiers.
    """
    default = {"ok": 0, "failed": 0, "last_attempted_at": None}
    if not profile_id or not str(profile_id).strip():
        return default
    if not run_id or not str(run_id).strip():
        return default

    try:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT status, COUNT(*) AS n FROM posting_attempts "
                "WHERE profile_id = ? AND run_id = ? GROUP BY status",
                (str(profile_id).strip(), str(run_id).strip()),
            )
            counts = {row["status"]: int(row["n"]) for row in cur.fetchall()}
            cur = conn.execute(
                "SELECT MAX(attempted_at) AS last_at FROM posting_attempts "
                "WHERE profile_id = ? AND run_id = ?",
                (str(profile_id).strip(), str(run_id).strip()),
            )
            row = cur.fetchone()
            last_at = row["last_at"] if row else None
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("posting_log: attempts_summary_for_run failed: %s", exc)
        return default
    except OSError as exc:
        log.warning("posting_log: attempts_summary_for_run OS error: %s", exc)
        return default

    return {
        "ok": int(counts.get("ok", 0)),
        "failed": int(counts.get("failed", 0)),
        "last_attempted_at": last_at,
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _maybe_prune(conn: sqlite3.Connection) -> None:
    """Trim the oldest rows when row count crosses ``_PRUNE_THRESHOLD``.

    Best-effort: any failure here is logged and swallowed because the
    caller has already persisted the new row successfully.
    """
    try:
        cur = conn.execute("SELECT COUNT(*) FROM posting_attempts")
        n = int(cur.fetchone()[0])
        if n <= _PRUNE_THRESHOLD:
            return
        to_delete = n - _PRUNE_TARGET
        if to_delete <= 0:
            return
        conn.execute(
            "DELETE FROM posting_attempts WHERE id IN ("
            "  SELECT id FROM posting_attempts "
            "  ORDER BY attempted_at ASC, id ASC LIMIT ?"
            ")",
            (to_delete,),
        )
        conn.commit()
    except sqlite3.Error as exc:
        log.warning("posting_log: retention sweep failed: %s", exc)


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Normalise a sqlite3.Row into a plain dict keyed by schema field."""
    return {field: row[field] for field in _ROW_FIELDS}


__all__ = [
    "record_attempt",
    "recent_attempts",
    "attempts_summary_for_run",
    "_ensure_schema",
]
