"""Uptime heartbeat log — SQLite store backing the public /status page.

Every call into ``/healthz`` (cheap liveness) and ``/health`` (deep
dep-check) lands one row here. Render's own health probe pings
``/healthz`` once a minute as part of its platform contract, so we
get an honest, free heartbeat trickle without standing up an external
monitor. External monitors (UptimeRobot, BetterUptime, Pingdom) also
poll these endpoints when configured, and contribute to the same log.

The store is observability-only:

* It is never on the request-blocking failure mode of the health
  check itself. DB writes are best-effort; failures are swallowed.
* It is intentionally lossy: a retention sweep trims the table down
  to ~90,000 rows whenever it crosses 100,000 (so ~35 days of
  one-per-minute pings are retained, which is plenty of context
  for a public status page).
* It is honest: ``uptime_stats`` returns a real number derived from
  heartbeat density, not a constant 100%. If pings stop, the number
  drops; if a heartbeat row was recorded with ``ok=False`` (from the
  deep /health check), that failure counts against uptime too.

Public API:

    record_heartbeat(*, ok, source, response_ms, error)  — insert one row
    uptime_stats(window_hours)                           — aggregate stats
    recent_gaps(window_hours, min_gap_seconds, limit)    — longest outages
    latest_heartbeat()                                   — most recent row

Every public function is exception-safe — DB issues yield a safe
default (None / [] / a zeroed dict) rather than raising.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Storage paths — same convention as publishing/posting_log.py
# ---------------------------------------------------------------------------

DATA_DIR = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))
DB_PATH = DATA_DIR / "data.db"


# ---------------------------------------------------------------------------
# Retention sweep thresholds — overridable from tests via monkeypatch.
# At 1 ping/min from Render alone, 100k rows ≈ 70 days of heartbeats.
# ---------------------------------------------------------------------------

_PRUNE_THRESHOLD = 100_000
_PRUNE_TARGET = 90_000


# ---------------------------------------------------------------------------
# Gap detection — what counts as a downtime window for /status.
# Render pings /healthz every 60s; we treat any gap > 5 minutes as a
# downtime interval. This is conservative: a real 1-minute outage
# probably won't show up; a real 5+ minute outage will.
# ---------------------------------------------------------------------------

_DOWNTIME_GAP_SECONDS = 300


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS uptime_heartbeats (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT    NOT NULL,
    ok            INTEGER NOT NULL,
    source        TEXT    NOT NULL,
    response_ms   INTEGER,
    error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_heartbeats_ts
    ON uptime_heartbeats(ts DESC);
"""


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    """Open a connection to DB_PATH with WAL journaling enabled.

    Caller is responsible for closing. Raises sqlite3.Error on failure
    so the public API can catch and degrade gracefully.
    """
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    return conn


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

def _ensure_schema() -> None:
    """Create the uptime_heartbeats table + index if missing.

    Idempotent — safe to call on every operation. Errors are swallowed
    so import never crashes if DATA_DIR is unwritable.
    """
    try:
        conn = _connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("uptime: schema bootstrap failed: %s", exc)
    except OSError as exc:
        log.warning("uptime: schema bootstrap OS error: %s", exc)


_ensure_schema()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_heartbeat(
    *,
    ok: bool,
    source: str = "healthz",
    response_ms: Optional[float] = None,
    error: Optional[str] = None,
    ts: Optional[str] = None,
) -> int:
    """Insert one heartbeat row. Returns the new row id (0 on any failure).

    Parameters
    ----------
    ok : bool
        True if the health probe succeeded, False if it found a problem.
        The ``/healthz`` cheap probe always passes True (the fact that
        the request was answered IS the success); ``/health`` deep probe
        passes the real ``ok_all`` flag.
    source : str
        Tag identifying which endpoint fed the heartbeat
        (``healthz`` / ``health`` / external monitor name). Free-form;
        helpful for debugging but not consumed by the aggregate stats.
    response_ms : float, optional
        How long the health check itself took, in milliseconds. Used by
        the status page to show a current latency number.
    error : str, optional
        Truncated error message if ``ok`` is False. Capped at 200 chars
        so a single broken row can't flood the table.
    ts : str, optional
        ISO-8601 UTC timestamp. Defaults to ``datetime.now(timezone.utc)``;
        tests can pass an explicit ts to seed deterministic data.

    Never raises.
    """
    when = ts or datetime.now(timezone.utc).isoformat()
    src = str(source or "healthz")[:50]
    rms = None if response_ms is None else max(0, int(response_ms))
    err = None if error is None else str(error)[:200]

    sql = (
        "INSERT INTO uptime_heartbeats "
        "(ts, ok, source, response_ms, error) "
        "VALUES (?, ?, ?, ?, ?)"
    )
    try:
        _ensure_schema()
        conn = _connect()
        try:
            cur = conn.execute(sql, (when, 1 if ok else 0, src, rms, err))
            new_id = int(cur.lastrowid or 0)
            conn.commit()
            _maybe_prune(conn)
            return new_id
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("uptime: record_heartbeat failed: %s", exc)
        return 0
    except OSError as exc:
        log.warning("uptime: record_heartbeat OS error: %s", exc)
        return 0


def uptime_stats(window_hours: int = 24) -> dict:
    """Aggregate stats for the trailing ``window_hours`` window.

    Returns a dict with:

      * ``window_hours``       — the window the stats cover
      * ``window_start``       — ISO timestamp of the window's lower bound
      * ``samples``            — total heartbeat rows in the window
      * ``ok_count``           — rows with ok=1
      * ``failed_count``       — rows with ok=0
      * ``uptime_pct``         — heartbeat-density derived uptime %
                                 (1.0 = perfect, 0.0 = silent for the
                                 whole window)
      * ``downtime_seconds``   — total seconds covered by gaps > 5 min
      * ``has_data``           — False if the table has no rows at all
                                 (lets the status page show "no data
                                 yet" instead of a misleading 0%)

    Uptime is computed as ``1 - (downtime_seconds / window_seconds)``
    where ``downtime_seconds`` is the sum of:
      * any ``ok=0`` rows (counts the heartbeat's own minute as down), and
      * any gap > 5 minutes between consecutive heartbeats (rounded down
        to the gap length minus the 5-minute grace window).

    A window with no heartbeats at all returns ``has_data=False`` and
    ``uptime_pct=0.0`` so the status page can render "no data yet" rather
    than a fake 100%.
    """
    try:
        window_hours = max(1, int(window_hours))
    except (TypeError, ValueError):
        window_hours = 24
    window_start = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    window_start_iso = window_start.isoformat()
    window_seconds = float(window_hours * 3600)

    default = {
        "window_hours": window_hours,
        "window_start": window_start_iso,
        "samples": 0,
        "ok_count": 0,
        "failed_count": 0,
        "uptime_pct": 0.0,
        "downtime_seconds": 0,
        "has_data": False,
    }

    try:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT ts, ok FROM uptime_heartbeats "
                "WHERE ts >= ? ORDER BY ts ASC",
                (window_start_iso,),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("uptime: stats query failed: %s", exc)
        return default
    except OSError as exc:
        log.warning("uptime: stats OS error: %s", exc)
        return default

    if not rows:
        return default

    samples = len(rows)
    ok_count = sum(1 for r in rows if r["ok"])
    failed_count = samples - ok_count

    downtime_s = 0.0
    # Sum gaps > _DOWNTIME_GAP_SECONDS between consecutive heartbeats.
    # We anchor the gap walk at the window start so a long pre-window
    # silence followed by recent pings doesn't get credit for "100%".
    last_ts = window_start
    for r in rows:
        try:
            ts_val = _parse_ts(r["ts"])
        except ValueError:
            continue
        gap = (ts_val - last_ts).total_seconds()
        if gap > _DOWNTIME_GAP_SECONDS:
            # Subtract the 5-minute grace window — anything shorter is
            # within the expected ping cadence and shouldn't count.
            downtime_s += (gap - _DOWNTIME_GAP_SECONDS)
        last_ts = ts_val

    # Tail gap — from the last heartbeat to "now".
    now = datetime.now(timezone.utc)
    tail_gap = (now - last_ts).total_seconds()
    if tail_gap > _DOWNTIME_GAP_SECONDS:
        downtime_s += (tail_gap - _DOWNTIME_GAP_SECONDS)

    # Any ok=0 rows add their own minute of downtime — a deep-health
    # failure didn't actually take the server down, but it indicates a
    # real degradation that should count against uptime.
    downtime_s += failed_count * 60

    # Clamp: downtime can't exceed the window.
    downtime_s = min(downtime_s, window_seconds)
    uptime_pct = 1.0 - (downtime_s / window_seconds)
    uptime_pct = max(0.0, min(1.0, uptime_pct))

    return {
        "window_hours": window_hours,
        "window_start": window_start_iso,
        "samples": samples,
        "ok_count": ok_count,
        "failed_count": failed_count,
        "uptime_pct": round(uptime_pct, 6),
        "downtime_seconds": int(round(downtime_s)),
        "has_data": True,
    }


def latest_heartbeat() -> Optional[dict]:
    """Return the most recent heartbeat row as a plain dict, or None.

    Used by the public status page to render a "last seen" timestamp
    and the current backend pill (green if last seen < 5 min ago).
    """
    try:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT id, ts, ok, source, response_ms, error "
                "FROM uptime_heartbeats ORDER BY ts DESC LIMIT 1"
            )
            row = cur.fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("uptime: latest_heartbeat failed: %s", exc)
        return None
    except OSError as exc:
        log.warning("uptime: latest_heartbeat OS error: %s", exc)
        return None
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "ts": row["ts"],
        "ok": bool(row["ok"]),
        "source": row["source"],
        "response_ms": row["response_ms"],
        "error": row["error"],
    }


def recent_gaps(
    window_hours: int = 168,
    min_gap_seconds: int = _DOWNTIME_GAP_SECONDS,
    limit: int = 10,
) -> list[dict]:
    """Return the longest heartbeat gaps in the window (most-recent first).

    Each gap is a dict with ``from_ts``, ``to_ts``, and ``duration_seconds``.
    A gap is the silent interval between two consecutive heartbeats; the
    first heartbeat is the start of the gap, the next is the end.

    Used by the public ``/status`` page to surface "Last incident: X days
    ago, Y minutes long" without needing a separate incidents table.
    """
    try:
        window_hours = max(1, int(window_hours))
    except (TypeError, ValueError):
        window_hours = 168
    try:
        min_gap_seconds = max(60, int(min_gap_seconds))
    except (TypeError, ValueError):
        min_gap_seconds = _DOWNTIME_GAP_SECONDS
    try:
        safe_limit = max(1, int(limit))
    except (TypeError, ValueError):
        safe_limit = 10

    window_start = datetime.now(timezone.utc) - timedelta(hours=window_hours)

    try:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT ts FROM uptime_heartbeats WHERE ts >= ? ORDER BY ts ASC",
                (window_start.isoformat(),),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("uptime: recent_gaps failed: %s", exc)
        return []
    except OSError as exc:
        log.warning("uptime: recent_gaps OS error: %s", exc)
        return []

    if len(rows) < 2:
        return []

    gaps: list[dict] = []
    prev = None
    for r in rows:
        try:
            this_ts = _parse_ts(r["ts"])
        except ValueError:
            continue
        if prev is not None:
            duration = (this_ts - prev).total_seconds()
            if duration >= min_gap_seconds:
                gaps.append({
                    "from_ts": prev.isoformat(),
                    "to_ts": this_ts.isoformat(),
                    "duration_seconds": int(duration),
                })
        prev = this_ts

    gaps.sort(key=lambda g: g["to_ts"], reverse=True)
    return gaps[:safe_limit]


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _parse_ts(value: str) -> datetime:
    """Parse an ISO-8601 timestamp; tolerate the trailing 'Z' shorthand."""
    if not value:
        raise ValueError("empty ts")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _maybe_prune(conn: sqlite3.Connection) -> None:
    """Trim the oldest rows when row count crosses ``_PRUNE_THRESHOLD``."""
    try:
        cur = conn.execute("SELECT COUNT(*) FROM uptime_heartbeats")
        n = int(cur.fetchone()[0])
        if n <= _PRUNE_THRESHOLD:
            return
        to_delete = n - _PRUNE_TARGET
        if to_delete <= 0:
            return
        conn.execute(
            "DELETE FROM uptime_heartbeats WHERE id IN ("
            "  SELECT id FROM uptime_heartbeats "
            "  ORDER BY ts ASC, id ASC LIMIT ?"
            ")",
            (to_delete,),
        )
        conn.commit()
    except sqlite3.Error as exc:
        log.warning("uptime: retention sweep failed: %s", exc)


__all__ = [
    "DATA_DIR",
    "DB_PATH",
    "record_heartbeat",
    "uptime_stats",
    "latest_heartbeat",
    "recent_gaps",
    "_ensure_schema",
]
