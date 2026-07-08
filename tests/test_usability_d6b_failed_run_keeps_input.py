"""D-6 (review follow-up) — a REAL failed run must keep its saved launch input so
it can be re-run.

The original D-6 tests hand-wrote input.bin for a status='error' run — a state
the worker never actually leaves behind, because _execute_run's finally block
reclaimed the input on every terminal (including error). This drives the real
worker path (a raising pipeline) and asserts the input survives a failure, so
the "Run this file again" recovery is actually functional.
"""

from __future__ import annotations

import importlib
import json

import pytest

ORG = "club-a"


@pytest.fixture
def wm(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as _wm

    importlib.reload(cp)
    importlib.reload(_wm)
    return _wm


def _seed_queued(wm, run_id):
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, file_name) "
        "VALUES (?, datetime('now'), 'queued', ?, ?)",
        (run_id, ORG, "meet.hy3"),
    )
    conn.commit()
    conn.close()


def _run_status(wm, run_id):
    conn = wm._db()
    row = conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def test_failed_worker_run_keeps_launch_input(wm, monkeypatch):
    run_id = "runworkerfail"
    _seed_queued(wm, run_id)
    wm._store_run_input(
        run_id,
        b"real meet bytes",
        "meet.hy3",
        ORG,
        True,
        True,
        None,
        None,
    )
    assert wm._resume_input_exists(run_id) is True

    def _boom(*a, **k):
        raise RuntimeError("pipeline exploded on a corrupt file")

    monkeypatch.setattr(wm, "run_pipeline_v4", _boom)
    wm._execute_run(
        run_id=run_id,
        file_bytes=b"real meet bytes",
        file_name="meet.hy3",
        profile_id=ORG,
        use_pb_cache=True,
        fetch_pbs=True,
        club_filter=None,
    )

    # The run failed…
    assert _run_status(wm, run_id) == "error"
    # …and its launch input is STILL on disk, so the D-6 rerun works for real.
    assert wm._resume_input_exists(run_id) is True


def test_mark_run_errored_keeps_launch_input(wm):
    run_id = "runstalefail"
    _seed_queued(wm, run_id)
    wm._store_run_input(run_id, b"bytes", "meet.hy3", ORG, True, True, None, None)
    wm._mark_run_errored(run_id, "resume budget exhausted")
    assert _run_status(wm, run_id) == "error"
    assert wm._resume_input_exists(run_id) is True
