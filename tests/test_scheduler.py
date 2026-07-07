"""Tests for the in-process single-fire scheduler (Section 6 step 4).

Exercise the engine directly (the daemon auto-start is intentionally inert under
pytest): the atomic per-(task, slot) claim, the tick/dispatch, UTC/DST slot
maths, the catch-up window, and the interrupted-on-shutdown marking. All against
an isolated tmp ``data.db`` — nothing touches the real database.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

from mediahub import scheduler as run
from mediahub.workflow import schedule as s


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    run._REGISTRY.clear()
    run._started = False
    run._stop.clear()
    for k in (
        "MEDIAHUB_SCHEDULER",
        "MEDIAHUB_SCHEDULER_INTERVAL",
        "MEDIAHUB_SCHEDULER_CATCHUP_SECS",
    ):
        monkeypatch.delenv(k, raising=False)
    yield
    run._REGISTRY.clear()


def _db(tmp_path):
    return tmp_path / "data.db"


# --- the correctness primitive: exactly-one claim under concurrency ---------


def test_atomic_claim_fires_exactly_once(tmp_path):
    """8 threads (2 workers x 4) race the same (task, slot); exactly one wins."""
    db = _db(tmp_path)
    s.create_task("t", "noop", "daily", "06:00", db_path=db)  # ensures schema
    slot = "2026-06-02T06:00:00+00:00"
    results: list = []
    lock = threading.Lock()

    def worker(i):
        r = s.claim_run("task1", slot, f"w-{i}", db_path=db)
        with lock:
            results.append(r)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [r for r in results if r is not None]
    assert len(winners) == 1
    assert results.count(None) == 7


def test_second_claim_on_same_slot_is_refused(tmp_path):
    db = _db(tmp_path)
    slot = "2026-06-02T06:00:00+00:00"
    rid = s.claim_run("task1", slot, "wA", db_path=db)
    assert rid is not None
    assert s.claim_run("task1", slot, "wB", db_path=db) is None  # already claimed
    s.mark_done(rid, db_path=db)
    # even after completion, the slot never re-fires
    assert s.claim_run("task1", slot, "wC", db_path=db) is None


# --- slot maths: recurring, catch-up window, timezone/DST, once -------------


def test_due_slot_recurring_within_and_outside_window(tmp_path):
    task = s.ScheduledTask(
        id="x", name="n", task_type="rec", schedule_kind="daily", schedule_expr="06:00"
    )
    now = datetime(2026, 6, 2, 6, 5, tzinfo=timezone.utc)
    assert s.due_slot_utc(task, now, 3600) == "2026-06-02T06:00:00+00:00"
    # 3h after the slot, with a 1h catch-up window -> stale, skip
    later = datetime(2026, 6, 2, 9, 0, tzinfo=timezone.utc)
    assert s.due_slot_utc(task, later, 3600) is None


def test_due_slot_timezone_resolves_to_utc(tmp_path):
    # 09:00 America/New_York in July (EDT, UTC-4) == 13:00 UTC — the dedup key
    # is UTC so a DST shift can't double-fire or skip.
    task = s.ScheduledTask(
        id="x",
        name="n",
        task_type="rec",
        schedule_kind="daily",
        schedule_expr="09:00",
        timezone="America/New_York",
    )
    now = datetime(2026, 7, 1, 13, 5, tzinfo=timezone.utc)
    assert s.due_slot_utc(task, now, 3600) == "2026-07-01T13:00:00+00:00"


def test_due_slot_once(tmp_path):
    task = s.ScheduledTask(
        id="x",
        name="n",
        task_type="rec",
        schedule_kind="once",
        schedule_expr="2026-06-02T06:00:00+00:00",
    )
    assert (
        s.due_slot_utc(task, datetime(2026, 6, 2, 6, 1, tzinfo=timezone.utc), 3600)
        == "2026-06-02T06:00:00+00:00"
    )
    # not yet due
    assert s.due_slot_utc(task, datetime(2026, 6, 2, 5, 59, tzinfo=timezone.utc), 3600) is None
    # long past the window -> stale
    assert s.due_slot_utc(task, datetime(2026, 6, 2, 8, 0, tzinfo=timezone.utc), 3600) is None


# --- tick + dispatch --------------------------------------------------------


def test_tick_executes_due_task_once_and_marks_done(tmp_path, monkeypatch):
    db = _db(tmp_path)
    monkeypatch.setenv("MEDIAHUB_SCHEDULER_CATCHUP_SECS", "86400")
    calls: list = []
    run.register_task_type("rec", lambda params: calls.append(params))
    now = datetime.now(timezone.utc)
    task = s.create_task(
        "t", "rec", "daily", f"{now.hour:02d}:{now.minute:02d}", params={"k": 1}, db_path=db
    )
    assert run.tick(db_path=db, in_thread=False) == 1
    assert calls == [{"k": 1}]
    assert s.list_runs(task.id, db_path=db)[0]["status"] == "done"
    # second tick: the slot is already claimed -> no re-fire
    assert run.tick(db_path=db, in_thread=False) == 0
    assert calls == [{"k": 1}]


def test_disabled_task_does_not_fire(tmp_path, monkeypatch):
    db = _db(tmp_path)
    monkeypatch.setenv("MEDIAHUB_SCHEDULER_CATCHUP_SECS", "86400")
    calls: list = []
    run.register_task_type("rec", lambda p: calls.append(p))
    now = datetime.now(timezone.utc)
    s.create_task(
        "t", "rec", "daily", f"{now.hour:02d}:{now.minute:02d}", enabled=False, db_path=db
    )
    assert run.tick(db_path=db, in_thread=False) == 0
    assert calls == []


def test_unknown_task_type_marks_failed_not_crash(tmp_path):
    db = _db(tmp_path)
    task = s.create_task("t", "no_such_handler", "daily", "00:00", db_path=db)
    rid = s.claim_run(task.id, "2026-06-02T00:00:00+00:00", "w", db_path=db)
    run._execute(task, rid, db)  # no handler registered
    runs = s.list_runs(task.id, db_path=db)
    assert runs[0]["status"] == "failed"
    assert "no handler" in (runs[0]["error"] or "")


def test_handler_exception_marks_failed(tmp_path):
    db = _db(tmp_path)

    def boom(_params):
        raise RuntimeError("kaboom")

    run.register_task_type("boom", boom)
    task = s.create_task("t", "boom", "daily", "00:00", db_path=db)
    rid = s.claim_run(task.id, "2026-06-02T00:00:00+00:00", "w", db_path=db)
    run._execute(task, rid, db)
    runs = s.list_runs(task.id, db_path=db)
    assert runs[0]["status"] == "failed"
    assert "kaboom" in (runs[0]["error"] or "")


# --- shutdown safety: interrupted, never auto-retried -----------------------


def test_interrupted_marking_does_not_refire(tmp_path):
    db = _db(tmp_path)
    slot = "2026-06-02T06:00:00+00:00"
    rid = s.claim_run("t1", slot, "wA", db_path=db)
    assert rid is not None
    # a different worker's in-flight runs are untouched
    assert s.claim_run("t2", slot, "wB", db_path=db) is not None
    assert s.mark_interrupted_for_worker("wA", db_path=db) == 1
    assert s.list_runs("t1", db_path=db)[0]["status"] == "interrupted"
    # an interrupted slot keeps its row -> never re-claimed (no double-fire)
    assert s.claim_run("t1", slot, "wC", db_path=db) is None


# --- DATA_DIR resolution -----------------------------------------------------


def test_default_db_path_follows_data_dir_set_after_import(tmp_path, monkeypatch):
    """The default db path is resolved from DATA_DIR per call, never frozen at
    import — a DATA_DIR exported after this module loads is still honoured."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert s._db_path() == tmp_path / "data.db"
    task = s.create_task("late-env", "noop", "daily", "06:00")  # no db_path
    assert (tmp_path / "data.db").exists()
    assert any(t.id == task.id for t in s.list_tasks())

    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.setenv("DATA_DIR", str(other))
    assert s._db_path() == other / "data.db"


# --- production wiring is inert under pytest --------------------------------


def test_start_scheduler_is_noop_under_pytest():
    # The daemon must never auto-start inside the test process.
    assert run.start_scheduler() is False


def test_scheduler_kill_switch(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    assert run.start_scheduler() is False
