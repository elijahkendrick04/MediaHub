"""Regression test: ``_start_run``'s worker callback must record each
progress line exactly once.

Two near-identical merge artefacts (commits ``b1bdc177`` and
``27e33614``) both added log-trimming logic to the same callback,
so every ``progress_cb(msg)`` call appended ``msg`` twice. The
visible symptom was the run-status page's "Show technical log"
panel displaying every step as a doubled pair, which made the
pipeline look broken even on successful runs.
"""
from __future__ import annotations

import threading
import time

import pytest


def test_worker_callback_records_each_message_once(monkeypatch, tmp_path):
    """Drive the public ``_start_run`` entry point with a stubbed
    pipeline that just emits ``progress_cb(msg)`` for known
    messages, then assert the recorded log is a clean list with no
    duplicates."""
    # Isolate DB / runs on disk so this test never touches the real
    # data directory.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    # Reimport with the patched DATA_DIR so module-level constants
    # bind to the tmp path.
    import importlib
    import mediahub.web.web as web
    importlib.reload(web)

    sent = ["queued", "Interpreting document", "Filtered to club",
            "Recognition: 3 achievements", "Done"]

    pipeline_done = threading.Event()

    class _FakeRun:
        error = None

    def _fake_pipeline(*, file_bytes, filename, profile_id,
                      use_pb_cache, fetch_pbs, progress_cb, run_id,
                      club_filter):
        for msg in sent:
            progress_cb(msg)
        pipeline_done.set()
        return _FakeRun()

    monkeypatch.setattr(web, "run_pipeline_v4", _fake_pipeline)
    monkeypatch.setattr(web, "_persist_run", lambda *a, **k: None)

    run_id = web._start_run(
        file_bytes=b"x", file_name="dummy.pdf",
        profile_id=None, use_pb_cache=False, fetch_pbs=False,
    )

    assert pipeline_done.wait(timeout=5.0), "pipeline worker hung"
    # Allow the worker thread to finish writing its final status.
    for _ in range(50):
        snapshot = web._active_runs.copy_value(run_id) or {}
        if snapshot.get("status") in ("done", "error"):
            break
        time.sleep(0.05)
    else:
        pytest.fail("worker never reached terminal status")

    log_lines = snapshot["log"]
    # Bootstrap line "Run queued" is added by _start_run before the
    # worker spins up; everything else must come from the callback
    # and must appear exactly once each.
    assert log_lines[0] == "Run queued"
    callback_lines = log_lines[1:]
    assert callback_lines == sent, (
        "expected each progress line recorded exactly once, "
        f"got {callback_lines!r}"
    )
    assert snapshot["status"] == "done"


def test_healthz_memory_does_not_crash_with_active_runs(monkeypatch, tmp_path):
    """``/healthz/memory`` walks ``_active_runs.values()`` to count
    in-flight pipelines. The bounded cache had no ``.values()``
    method, so the endpoint 500'd whenever any run was active —
    breaking operator monitoring."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    import importlib
    import mediahub.web.web as web
    importlib.reload(web)

    web._active_runs["seed-run"] = {"status": "running", "log": []}

    app = web.create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    r = client.get("/healthz/memory")
    assert r.status_code == 200
    payload = r.get_json()
    assert payload["ok"] is True
    assert payload["active_runs_running"] >= 1
