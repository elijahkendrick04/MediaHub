"""mediahub/scheduler/__init__.py — in-process, single-fire job runner.

Capability: Scheduler (Section 6 step 4 — the autonomy substrate). A tiny daemon
tick, started once per Gunicorn worker, that fires each due ``ScheduledTask``
EXACTLY ONCE across all workers by atomically claiming its (task, UTC-slot) row
(see ``mediahub.workflow.schedule``). Stays inside MediaHub's architecture:
Flask + sync + ``threading.Thread``, SQLite only, no Celery/Redis, no new infra.

Task work is dispatched through a NARROW registry — handlers are registered by
the app (ingest / report / …); there is deliberately no shell / file / generic
tool here. An unknown task type fails loudly rather than doing anything unsafe.

Safety (council-decided): a claimed run is marked ``done`` only after its handler
returns; a recycling worker marks its OWN in-flight runs ``interrupted`` via
``atexit``; nothing auto-resets a ``running``/``interrupted`` row, so a job is
never double-fired.
"""

from __future__ import annotations

import atexit
import logging
import os
import socket
import threading
from datetime import datetime, timezone
from typing import Callable, Optional

from mediahub.workflow import schedule as sched

log = logging.getLogger(__name__)

TaskHandler = Callable[[dict], None]

# Identifies this worker process for run ownership (interrupted-marking).
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"

DEFAULT_INTERVAL = 45.0
DEFAULT_CATCHUP_SECS = 6 * 60 * 60  # 6h: a slot missed during a brief outage is
# caught up once; older than this is stale and skipped.

_REGISTRY: dict[str, TaskHandler] = {}
_started = False
_start_lock = threading.Lock()
_stop = threading.Event()


def register_task_type(name: str, handler: TaskHandler) -> None:
    """Register a handler for a ``task_type``. Handlers take the task's params
    dict and do the work; they must be idempotent where the effect is external."""
    _REGISTRY[name] = handler


def registered_task_types() -> list[str]:
    return sorted(_REGISTRY)


def _interval() -> float:
    raw = os.environ.get("MEDIAHUB_SCHEDULER_INTERVAL", "").strip()
    try:
        return max(5.0, float(raw)) if raw else DEFAULT_INTERVAL
    except ValueError:
        return DEFAULT_INTERVAL


def _catchup_secs() -> int:
    raw = os.environ.get("MEDIAHUB_SCHEDULER_CATCHUP_SECS", "").strip()
    try:
        return max(0, int(raw)) if raw else DEFAULT_CATCHUP_SECS
    except ValueError:
        return DEFAULT_CATCHUP_SECS


def _enabled() -> bool:
    return os.environ.get("MEDIAHUB_SCHEDULER", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _execute(task: sched.ScheduledTask, run_id: str, db_path=None) -> None:
    handler = _REGISTRY.get(task.task_type)
    if handler is None:
        sched.mark_failed(run_id, f"no handler for task_type {task.task_type!r}", db_path=db_path)
        return
    try:
        handler(dict(task.params or {}))
        sched.mark_done(run_id, db_path=db_path)
    except Exception as e:  # a handler failure is terminal for this slot (no auto-retry)
        log.warning("scheduled task %s (%s) failed: %s", task.id, task.task_type, e)
        sched.mark_failed(run_id, str(e), db_path=db_path)


def tick(db_path=None, *, in_thread: bool = True) -> int:
    """Fire all currently-due tasks once; return the number of slots THIS worker
    claimed and dispatched. Safe to call concurrently from every worker — the
    atomic claim dedups. ``in_thread=False`` runs handlers inline (for tests)."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    catchup = _catchup_secs()
    fired = 0
    for task in sched.list_tasks(enabled_only=True, db_path=db_path):
        try:
            slot = sched.due_slot_utc(task, now, catchup)
        except Exception:
            continue
        if not slot:
            continue
        try:
            run_id = sched.claim_run(task.id, slot, WORKER_ID, db_path=db_path)
        except Exception as e:
            # A claim hiccup (e.g. transient DB lock) must not abort the tick
            # for every remaining task — skip this one; the slot stays
            # claimable on the next tick within the catch-up window.
            log.warning("scheduler claim failed for task %s: %s", task.id, e)
            continue
        if run_id is None:
            continue  # another worker, or an earlier run of this slot, already owns it
        fired += 1
        if in_thread:
            threading.Thread(
                target=_execute,
                args=(task, run_id, db_path),
                daemon=True,
                name=f"sched-{task.task_type}",
            ).start()
        else:
            _execute(task, run_id, db_path)
    return fired


def _run_loop(db_path, interval: float) -> None:
    # Tick promptly once (catch up anything due at boot), then on the interval.
    while not _stop.is_set():
        try:
            tick(db_path)
        except Exception as e:  # never let the loop thread die
            log.warning("scheduler tick error: %s", e)
        _stop.wait(interval)


def _on_exit(db_path=None) -> None:
    try:
        sched.mark_interrupted_for_worker(WORKER_ID, db_path=db_path)
    except Exception:
        pass


def start_scheduler(db_path=None, interval: Optional[float] = None) -> bool:
    """Start the tick loop once per process (idempotent). Returns True iff it
    started here. No-op when disabled via ``MEDIAHUB_SCHEDULER=0``."""
    global _started
    if not _enabled() or _started:
        return False
    # Never auto-start during a pytest run: the engine (tick / claim) is tested
    # directly, and a live daemon ticking the shared db would be a test hazard.
    import sys  # noqa: PLC0415

    if "pytest" in sys.modules:
        return False
    with _start_lock:
        if _started:
            return False
        # Mark our own in-flight runs interrupted on graceful shutdown — never a
        # TTL reaper that could double-fire (council).
        atexit.register(_on_exit, db_path)
        threading.Thread(
            target=_run_loop,
            args=(db_path, interval or _interval()),
            daemon=True,
            name="scheduler",
        ).start()
        _started = True
        return True


def stop_scheduler() -> None:
    """Signal the tick loop to stop (used by tests; production relies on the
    daemon thread dying with the process)."""
    _stop.set()


__all__ = [
    "register_task_type",
    "registered_task_types",
    "start_scheduler",
    "stop_scheduler",
    "tick",
    "WORKER_ID",
    "TaskHandler",
]
