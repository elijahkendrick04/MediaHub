"""SEC-27 — durable, cross-worker brute-force brakes backed by SQLite.

Account lockout, the per-IP auth limiter, and the TOTP replay guard used to be
per-worker in-process dicts. Under gunicorn's two workers that let an attacker
get ~2x the intended budget, and ``--max-requests`` worker recycling wiped the
counters mid-attack. This module moves all three into the shared SQLite database
(``DATA_DIR/data.db`` — the same file the runs index uses and that
``publish_website`` snapshots across deploys), so a lockout is consistent across
workers and survives a worker recycle / restart. See
``docs/adr/0030-durable-cross-worker-bruteforce-brakes.md``.

Design (full rationale in the ADR):

- **Sliding-window counters** (account lockout + per-IP limiter) are stored as
  one row per event in ``auth_events``; a count is ``COUNT(*)`` of rows for the
  key inside the window. One row per event is inherently race-free (each INSERT
  commits independently — no read-modify-write) and is an exact translation of
  the old in-memory ``list[timestamp]`` window.
- **The TOTP replay guard** is a read-modify-write (accept only a counter newer
  than the last accepted one), so it runs inside a ``BEGIN IMMEDIATE``
  transaction; SQLite's single-writer lock serialises it across workers, so the
  same code can never be accepted twice even under a concurrent race. The secret
  is hashed (``sha256``) before use as a key — the raw secret must never enter
  ``data.db`` (which is snapshotted).
- **Timestamps** are real unix seconds supplied by the caller (``now=``) so
  tests inject a clock exactly like ``totp_verify(at=...)``. Every worker shares
  the one host clock, so cross-worker comparison is sound.
- **The DB path is resolved at call time** from ``DATA_DIR`` (mirrors
  ``auth._data_dir``) so per-test ``DATA_DIR`` overrides isolate cleanly.
- **Every operation is best-effort**: a locked/corrupt DB must never 500 the
  login path, so each function fails toward the same decision an empty in-memory
  dict would have made (open for the counters, accept for the replay guard —
  the code it guards was already cryptographically verified).
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("mediahub.auth_brakes")

# GC: keep the tables from accumulating rows for keys that are never touched
# again. Correctness never depends on this — the count queries are window-bounded
# regardless — so it is opportunistic and process-local.
_GC_MIN_INTERVAL_SECS = 60.0
_EVENT_MAX_AGE_SECS = 3600.0  # > the longest brake window (15 min); safety margin
_TOTP_MAX_AGE_SECS = 86_400.0  # a secret idle for a day: its ~90s replay window is long gone

# Process-local GC clock + the set of DB paths whose schema we've ensured this
# process. Neither is durable; both are best-effort caches, guarded for the
# threaded worker.
_STATE_LOCK = threading.Lock()
_last_gc: dict[str, float] = {}
_schema_ready: set[str] = set()


def _data_dir() -> Path:
    """Resolve DATA_DIR at call time (tests monkeypatch the env var) — mirrors
    ``auth._data_dir`` and ``web.DATA_DIR`` so all three resolve the same file."""
    src_root = Path(__file__).resolve().parents[2]
    return Path(os.environ.get("DATA_DIR", str(src_root)))


def _db_path() -> Path:
    # Deliberately the SAME file as the runs index (web.DB_PATH) so the brakes
    # ride the deploy snapshot and share one store.
    return _data_dir() / "data.db"


def _connect() -> sqlite3.Connection:
    """Open a brakes connection with the same contention tuning as ``_db()``.

    ``isolation_level=None`` (autocommit) so we manage the replay guard's
    transaction explicitly with ``BEGIN IMMEDIATE``. Journal mode is left at the
    file default (rollback journal) — NOT WAL — so we don't add ``-wal``/``-shm``
    sidecars the deploy snapshot doesn't capture.
    """
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0, isolation_level=None)
    try:
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.Error:
        pass
    _ensure_schema(conn, str(path))
    return conn


def _ensure_schema(conn: sqlite3.Connection, path_key: str) -> None:
    with _STATE_LOCK:
        if path_key in _schema_ready:
            return
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS auth_events (
            scope TEXT NOT NULL,   -- 'fail' (account lockout) | 'ip:<bucket>' (per-IP)
            ident TEXT NOT NULL,   -- normalised email | client IP
            ts    REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_auth_events ON auth_events(scope, ident, ts);
        CREATE TABLE IF NOT EXISTS totp_replay (
            secret_hash  TEXT PRIMARY KEY,  -- sha256(secret); the secret is NEVER stored
            last_counter INTEGER NOT NULL,
            updated_at   REAL NOT NULL
        );
        """
    )
    with _STATE_LOCK:
        _schema_ready.add(path_key)


def _maybe_gc(conn: sqlite3.Connection, now: float) -> None:
    """Delete long-expired rows, at most once per minute per process."""
    path_key = str(_db_path())
    with _STATE_LOCK:
        if now - _last_gc.get(path_key, 0.0) < _GC_MIN_INTERVAL_SECS:
            return
        _last_gc[path_key] = now
    try:
        conn.execute("DELETE FROM auth_events WHERE ts < ?", (now - _EVENT_MAX_AGE_SECS,))
        conn.execute("DELETE FROM totp_replay WHERE updated_at < ?", (now - _TOTP_MAX_AGE_SECS,))
    except sqlite3.Error:
        pass


# --------------------------------------------------------------------------
# Sliding-window event counters (account lockout + per-IP limiter)
# --------------------------------------------------------------------------


def count_events(scope: str, ident: str, *, now: float, window_secs: float) -> int:
    """Number of events for ``(scope, ident)`` within the trailing window.

    Read-only (no prune, no insert) so the on-every-attempt ``login_locked`` /
    lock probes cost one indexed SELECT. Fails to ``0`` on any DB error.
    """
    try:
        conn = _connect()
    except sqlite3.Error as exc:  # pragma: no cover - DB unavailable
        log.warning("auth_brakes: count_events connect failed: %s", exc)
        return 0
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM auth_events WHERE scope=? AND ident=? AND ts >= ?",
            (scope, ident, now - window_secs),
        ).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        log.warning("auth_brakes: count_events failed: %s", exc)
        return 0
    finally:
        conn.close()


def record_event(scope: str, ident: str, *, now: float, window_secs: float) -> int:
    """Record one event for ``(scope, ident)`` and return the in-window count
    *after* recording (the caller compares it to the limit).

    Prunes this key's stale rows first, so a hot key never accumulates. Fails to
    ``0`` on any DB error (fail-open: the caller treats 0 as "not limited").
    """
    try:
        conn = _connect()
    except sqlite3.Error as exc:  # pragma: no cover - DB unavailable
        log.warning("auth_brakes: record_event connect failed: %s", exc)
        return 0
    try:
        conn.execute(
            "DELETE FROM auth_events WHERE scope=? AND ident=? AND ts < ?",
            (scope, ident, now - window_secs),
        )
        conn.execute(
            "INSERT INTO auth_events(scope, ident, ts) VALUES (?, ?, ?)",
            (scope, ident, now),
        )
        row = conn.execute(
            "SELECT COUNT(*) FROM auth_events WHERE scope=? AND ident=? AND ts >= ?",
            (scope, ident, now - window_secs),
        ).fetchone()
        _maybe_gc(conn, now)
        return int(row[0]) if row else 0
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        log.warning("auth_brakes: record_event failed: %s", exc)
        return 0
    finally:
        conn.close()


def clear_events(scope: str, ident: str) -> None:
    """Drop every event for ``(scope, ident)`` (a successful login clears the
    account's failure history). Best-effort; never raises."""
    try:
        conn = _connect()
    except sqlite3.Error:  # pragma: no cover - DB unavailable
        return
    try:
        conn.execute("DELETE FROM auth_events WHERE scope=? AND ident=?", (scope, ident))
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        log.warning("auth_brakes: clear_events failed: %s", exc)
    finally:
        conn.close()


# --------------------------------------------------------------------------
# TOTP replay guard (RFC 6238 §5.2) — accept a counter only once
# --------------------------------------------------------------------------


def totp_replay_ok(secret: str, counter: int, *, now: Optional[float] = None) -> bool:
    """Return True if ``counter`` is newer than the last accepted counter for
    ``secret`` (recording it), False if it is a replay of an already-used (or
    older) counter.

    Runs inside ``BEGIN IMMEDIATE`` so the read-compare-write is serialised
    across both workers — two concurrent verifies of the same code can never
    both succeed. On any DB error it **accepts** (returns True): the code has
    already passed the HMAC check, and failing open costs at most the ~90-second
    replay window the old in-process guard also forfeited on every restart.
    """
    if now is None:
        now = time.time()
    secret_hash = hashlib.sha256((secret or "").encode("utf-8")).hexdigest()
    try:
        conn = _connect()
    except sqlite3.Error as exc:  # pragma: no cover - DB unavailable
        log.warning("auth_brakes: totp_replay_ok connect failed: %s", exc)
        return True
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT last_counter FROM totp_replay WHERE secret_hash=?", (secret_hash,)
        ).fetchone()
        last = int(row[0]) if row else None
        if last is None or counter > last:
            conn.execute(
                "INSERT INTO totp_replay(secret_hash, last_counter, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(secret_hash) DO UPDATE SET "
                "last_counter=excluded.last_counter, updated_at=excluded.updated_at",
                (secret_hash, int(counter), now),
            )
            accepted = True
        else:
            accepted = False
        conn.execute("COMMIT")
        _maybe_gc(conn, now)
        return accepted
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        log.warning("auth_brakes: totp_replay_ok failed: %s", exc)
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        return True  # fail open: the code already passed the HMAC check
    finally:
        conn.close()


__all__ = [
    "count_events",
    "record_event",
    "clear_events",
    "totp_replay_ok",
]
