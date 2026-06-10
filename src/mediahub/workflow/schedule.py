"""mediahub/workflow/schedule.py — scheduled-task model + atomic-claim store.

The persistence + correctness core of the in-process scheduler (the autonomy
substrate). Two tables live in the shared ``data.db``:

- ``scheduled_tasks`` — what to run and on what cadence (once / daily / weekly /
  monthly / cron, via croniter), in a named timezone.
- ``scheduled_runs`` — one row per (task, fire-time) execution, with a
  ``UNIQUE(task_id, fire_time_utc)`` constraint that IS the concurrency control.

**The correctness primitive (council-decided): a per-(task, fire-time) atomic
claim.** MediaHub runs 2 Gunicorn workers that also recycle every ~200 requests,
so a naive "scheduler thread per worker" would fire every job twice. Instead any
worker may tick, but a job slot is *claimed* with ``INSERT OR IGNORE`` against
the unique row: exactly one worker's insert succeeds, everyone else is ignored.
No leader election, no file lock, and crucially **no TTL reaping** — auto-
resetting a stuck ``running`` row is the double-fire vector, so it is never done.
``fire_time_utc`` is the canonical scheduled slot in **UTC** (DST-safe), so every
worker computes the identical dedup key.

This module is pure persistence + slot maths; the runner (``mediahub.scheduler``)
drives the tick and dispatch.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

try:  # stdlib on 3.9+; tasks default to UTC if a zone is unavailable
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

# Same derivation web.py uses, so we hit the SAME data.db without importing the
# (heavy, cycle-prone) web module. In production DATA_DIR is set in the env.
DATA_DIR = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))
DB_PATH = DATA_DIR / "data.db"

SCHEDULE_KINDS = ("once", "daily", "weekly", "monthly", "cron")
RUN_RUNNING = "running"
RUN_DONE = "done"
RUN_FAILED = "failed"
RUN_INTERRUPTED = "interrupted"


@dataclass
class ScheduledTask:
    id: str
    name: str
    task_type: str  # dispatch key in the runner's registry
    params: dict = field(default_factory=dict)
    schedule_kind: str = "cron"
    schedule_expr: str = ""  # cron string | "HH:MM" | "DOW HH:MM" | "DOM HH:MM" | ISO datetime
    timezone: str = "UTC"
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        return d


@dataclass
class ScheduledTaskRun:
    id: str
    task_id: str
    fire_time_utc: str
    status: str
    worker: Optional[str] = None
    started_at: str = ""
    finished_at: Optional[str] = None
    error: Optional[str] = None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a short-lived connection to the shared db with the same busy_timeout
    web.py uses, so two workers racing a claim wait briefly rather than erroring."""
    conn = sqlite3.connect(str(db_path or DB_PATH), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
    except Exception:
        pass
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            task_type     TEXT NOT NULL,
            params        TEXT NOT NULL DEFAULT '{}',
            schedule_kind TEXT NOT NULL,
            schedule_expr TEXT NOT NULL,
            timezone      TEXT NOT NULL DEFAULT 'UTC',
            enabled       INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scheduled_runs (
            id            TEXT PRIMARY KEY,
            task_id       TEXT NOT NULL,
            fire_time_utc TEXT NOT NULL,
            status        TEXT NOT NULL,
            worker        TEXT,
            started_at    TEXT NOT NULL,
            finished_at   TEXT,
            error         TEXT,
            UNIQUE(task_id, fire_time_utc)
        );
        CREATE INDEX IF NOT EXISTS idx_scheduled_runs_task
            ON scheduled_runs(task_id, fire_time_utc);
        """
    )
    conn.commit()


def _ensure_schema(db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        init_schema(conn)
    finally:
        conn.close()


# ── cron normalisation + slot maths ────────────────────────────────────────


def _to_cron(kind: str, expr: str) -> str:
    """Map a schedule kind to a 5-field cron string (used for raw cron validation
    and as the croniter input for the ``cron`` kind only)."""
    expr = (expr or "").strip()
    if kind == "cron":
        return expr
    if kind == "daily":  # "HH:MM"
        hh, mm = expr.split(":")
        return f"{int(mm)} {int(hh)} * * *"
    if kind == "weekly":  # "DOW HH:MM"  (DOW 0-6, Sun=0)
        dow, hm = expr.split(" ", 1)
        hh, mm = hm.split(":")
        return f"{int(mm)} {int(hh)} * * {int(dow)}"
    if kind == "monthly":  # "DOM HH:MM"
        dom, hm = expr.split(" ", 1)
        hh, mm = hm.split(":")
        return f"{int(mm)} {int(hh)} {int(dom)} * *"
    raise ValueError(f"unsupported schedule kind: {kind}")


def _prev_daily_slot(expr: str, tz, now_utc: datetime) -> datetime:
    """Most-recent 'HH:MM' slot that is <= now_utc, returned as UTC."""
    hh, mm = expr.strip().split(":")
    now_local = now_utc.astimezone(tz)
    slot = now_local.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    if slot > now_local:
        slot -= timedelta(days=1)
    return slot.astimezone(timezone.utc)


def _prev_weekly_slot(expr: str, tz, now_utc: datetime) -> datetime:
    """Most-recent 'DOW HH:MM' slot (DOW 0=Sun) <= now_utc, returned as UTC."""
    dow_str, hm = expr.strip().split(" ", 1)
    hh, mm = hm.split(":")
    cron_dow = int(dow_str)  # 0=Sun … 6=Sat
    # Python isoweekday: Mon=1 … Sun=7; convert cron DOW
    py_dow = 7 if cron_dow == 0 else cron_dow
    now_local = now_utc.astimezone(tz)
    days_back = (now_local.isoweekday() - py_dow) % 7
    candidate = now_local - timedelta(days=days_back)
    slot = candidate.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    if slot > now_local:
        slot -= timedelta(weeks=1)
    return slot.astimezone(timezone.utc)


def _prev_monthly_slot(expr: str, tz, now_utc: datetime) -> datetime:
    """Most-recent 'DOM HH:MM' slot (DOM 1-28+) <= now_utc, returned as UTC."""
    dom_str, hm = expr.strip().split(" ", 1)
    hh, mm = hm.split(":")
    dom = int(dom_str)
    now_local = now_utc.astimezone(tz)
    # Try this month's slot; if it doesn't exist (e.g. DOM 31 in April) fall back.
    try:
        slot = now_local.replace(day=dom, hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if slot <= now_local:
            return slot.astimezone(timezone.utc)
    except ValueError:
        pass
    # Go to last day of the previous month and try there.
    first_of_month = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_prev = first_of_month - timedelta(days=1)
    try:
        slot = last_prev.replace(day=dom, hour=int(hh), minute=int(mm), second=0, microsecond=0)
    except ValueError:
        # DOM doesn't exist in that month either — use last day of that month.
        slot = last_prev.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    return slot.astimezone(timezone.utc)


def _tz(name: str):
    if not name or ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def due_slot_utc(task: ScheduledTask, now_utc: datetime, catchup_secs: int) -> Optional[str]:
    """The canonical UTC fire-time that is currently DUE for ``task`` and within
    the catch-up window, or None. For recurring kinds this is the most-recent
    scheduled instant <= now (so a slot missed during a brief outage is still
    caught up exactly once); for ``once`` it is the configured datetime.

    Returns an ISO-8601 UTC string (the dedup key) — never a wall-clock time.
    """
    if task.schedule_kind == "once":
        try:
            dt = datetime.fromisoformat(task.schedule_expr.strip())
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_tz(task.timezone))
        slot = dt.astimezone(timezone.utc).replace(microsecond=0)
        if now_utc >= slot and (now_utc - slot).total_seconds() <= catchup_secs:
            return slot.isoformat()
        return None

    tz = _tz(task.timezone)
    try:
        if task.schedule_kind == "daily":
            prev_utc = _prev_daily_slot(task.schedule_expr, tz, now_utc)
        elif task.schedule_kind == "weekly":
            prev_utc = _prev_weekly_slot(task.schedule_expr, tz, now_utc)
        elif task.schedule_kind == "monthly":
            prev_utc = _prev_monthly_slot(task.schedule_expr, tz, now_utc)
        else:  # "cron" — requires croniter
            try:
                from croniter import croniter  # noqa: PLC0415
            except Exception:
                return None
            cron = _to_cron(task.schedule_kind, task.schedule_expr)
            base_local = now_utc.astimezone(tz)
            prev_local = croniter(cron, base_local).get_prev(datetime)
            prev_utc = prev_local.astimezone(timezone.utc).replace(microsecond=0)
    except Exception:
        return None
    prev_utc = prev_utc.replace(microsecond=0)
    if (now_utc - prev_utc).total_seconds() <= catchup_secs:
        return prev_utc.isoformat()
    return None


def next_fire_utc(task: ScheduledTask, after_utc: Optional[datetime] = None) -> Optional[str]:
    """The next scheduled UTC instant strictly after ``after_utc`` (for display
    / a future 'week ahead' view). None for a ``once`` task already in the past."""
    after = after_utc or _now_utc()
    if task.schedule_kind == "once":
        try:
            dt = datetime.fromisoformat(task.schedule_expr.strip())
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_tz(task.timezone))
        slot = dt.astimezone(timezone.utc).replace(microsecond=0)
        return slot.isoformat() if slot > after else None
    tz = _tz(task.timezone)
    try:
        if task.schedule_kind == "daily":
            prev = _prev_daily_slot(task.schedule_expr, tz, after)
            nxt = prev + timedelta(days=1)
        elif task.schedule_kind == "weekly":
            prev = _prev_weekly_slot(task.schedule_expr, tz, after)
            nxt = prev + timedelta(weeks=1)
        elif task.schedule_kind == "monthly":
            # Advance by ~31 days then compute the prev slot from there.
            candidate = after + timedelta(days=32)
            nxt = _prev_monthly_slot(task.schedule_expr, tz, candidate)
            if nxt <= after:
                nxt = _prev_monthly_slot(task.schedule_expr, tz, candidate + timedelta(days=32))
        else:  # "cron" — requires croniter
            try:
                from croniter import croniter  # noqa: PLC0415
            except Exception:
                return None
            cron = _to_cron(task.schedule_kind, task.schedule_expr)
            nxt_local = croniter(cron, after.astimezone(tz)).get_next(datetime)
            nxt = nxt_local.astimezone(timezone.utc).replace(microsecond=0)
    except Exception:
        return None
    return nxt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


# ── task CRUD ──────────────────────────────────────────────────────────────


def _row_to_task(r: sqlite3.Row) -> ScheduledTask:
    return ScheduledTask(
        id=r["id"],
        name=r["name"],
        task_type=r["task_type"],
        params=json.loads(r["params"] or "{}"),
        schedule_kind=r["schedule_kind"],
        schedule_expr=r["schedule_expr"],
        timezone=r["timezone"],
        enabled=bool(r["enabled"]),
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


def create_task(
    name: str,
    task_type: str,
    schedule_kind: str,
    schedule_expr: str,
    *,
    params: Optional[dict] = None,
    timezone_name: str = "UTC",
    enabled: bool = True,
    db_path: Optional[Path] = None,
) -> ScheduledTask:
    if schedule_kind not in SCHEDULE_KINDS:
        raise ValueError(f"unsupported schedule kind: {schedule_kind}")
    # Validate the expression up front so a bad cron can't silently never fire.
    if schedule_kind != "once":
        _to_cron(schedule_kind, schedule_expr)
    _ensure_schema(db_path)
    now = _iso(_now_utc())
    task = ScheduledTask(
        id=uuid.uuid4().hex,
        name=name,
        task_type=task_type,
        params=params or {},
        schedule_kind=schedule_kind,
        schedule_expr=schedule_expr,
        timezone=timezone_name,
        enabled=enabled,
        created_at=now,
        updated_at=now,
    )
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO scheduled_tasks(id,name,task_type,params,schedule_kind,"
            "schedule_expr,timezone,enabled,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                task.id,
                task.name,
                task.task_type,
                json.dumps(task.params),
                task.schedule_kind,
                task.schedule_expr,
                task.timezone,
                1 if task.enabled else 0,
                task.created_at,
                task.updated_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return task


def list_tasks(
    *, enabled_only: bool = False, db_path: Optional[Path] = None
) -> list[ScheduledTask]:
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        sql = "SELECT * FROM scheduled_tasks"
        if enabled_only:
            sql += " WHERE enabled=1"
        return [_row_to_task(r) for r in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def get_task(task_id: str, *, db_path: Optional[Path] = None) -> Optional[ScheduledTask]:
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        r = conn.execute("SELECT * FROM scheduled_tasks WHERE id=?", (task_id,)).fetchone()
        return _row_to_task(r) if r else None
    finally:
        conn.close()


def set_enabled(task_id: str, enabled: bool, *, db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE scheduled_tasks SET enabled=?, updated_at=? WHERE id=?",
            (1 if enabled else 0, _iso(_now_utc()), task_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_task(task_id: str, *, db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM scheduled_tasks WHERE id=?", (task_id,))
        conn.execute("DELETE FROM scheduled_runs WHERE task_id=?", (task_id,))
        conn.commit()
    finally:
        conn.close()


# ── the atomic claim + run lifecycle ───────────────────────────────────────


def claim_run(
    task_id: str, fire_time_utc: str, worker: str, *, db_path: Optional[Path] = None
) -> Optional[str]:
    """Atomically claim (task_id, fire_time_utc) for execution. Exactly one
    caller across all workers/threads wins; everyone else gets None. Returns the
    new run id on success. This single ``INSERT OR IGNORE`` against the unique
    row is the entire concurrency control — no leader, no lock, no TTL."""
    _ensure_schema(db_path)
    run_id = uuid.uuid4().hex
    now = _iso(_now_utc())
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO scheduled_runs(id,task_id,fire_time_utc,status,worker,started_at)"
            " VALUES(?,?,?,?,?,?)",
            (run_id, task_id, fire_time_utc, RUN_RUNNING, worker, now),
        )
        conn.commit()
        return run_id if cur.rowcount == 1 else None
    finally:
        conn.close()


def _finish(run_id: str, status: str, error: Optional[str], db_path: Optional[Path]) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE scheduled_runs SET status=?, finished_at=?, error=? WHERE id=?",
            (status, _iso(_now_utc()), error, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_done(run_id: str, *, db_path: Optional[Path] = None) -> None:
    _finish(run_id, RUN_DONE, None, db_path)


def mark_failed(run_id: str, error: str, *, db_path: Optional[Path] = None) -> None:
    _finish(run_id, RUN_FAILED, (error or "")[:500], db_path)


def mark_interrupted_for_worker(worker: str, *, db_path: Optional[Path] = None) -> int:
    """Mark THIS worker's still-running runs as interrupted (called on graceful
    shutdown). Never touches another worker's rows, and never auto-resets a row
    to be re-run — an interrupted slot stays claimed, so it is never double-fired
    (the council's 'no TTL reaping' rule). Returns the number marked."""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE scheduled_runs SET status=?, finished_at=?, error=? "
            "WHERE status=? AND worker=?",
            (RUN_INTERRUPTED, _iso(_now_utc()), "worker shutdown", RUN_RUNNING, worker),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def has_run(task_id: str, fire_time_utc: str, *, db_path: Optional[Path] = None) -> bool:
    """True if any run row exists for this (task, slot) — i.e. it was already
    claimed/executed and must not fire again."""
    conn = _connect(db_path)
    try:
        r = conn.execute(
            "SELECT 1 FROM scheduled_runs WHERE task_id=? AND fire_time_utc=? LIMIT 1",
            (task_id, fire_time_utc),
        ).fetchone()
        return r is not None
    finally:
        conn.close()


def list_runs(task_id: str, *, limit: int = 50, db_path: Optional[Path] = None) -> list[dict]:
    """Recent run history for a task (newest first) — the audit ledger."""
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM scheduled_runs WHERE task_id=? ORDER BY started_at DESC LIMIT ?",
            (task_id, int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


__all__ = [
    "ScheduledTask",
    "ScheduledTaskRun",
    "SCHEDULE_KINDS",
    "RUN_RUNNING",
    "RUN_DONE",
    "RUN_FAILED",
    "RUN_INTERRUPTED",
    "DB_PATH",
    "init_schema",
    "create_task",
    "list_tasks",
    "get_task",
    "set_enabled",
    "delete_task",
    "due_slot_utc",
    "next_fire_utc",
    "claim_run",
    "mark_done",
    "mark_failed",
    "mark_interrupted_for_worker",
    "has_run",
    "list_runs",
]
