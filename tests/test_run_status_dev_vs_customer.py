"""The meet-recap progress page must show a customer a friendly percentage bar
+ plain-English phase, and show the signed-in developer the raw step log +
technical detail. The status endpoint additionally exposes percent/phase.

Regression for the reported issue: customers were seeing raw engineer-facing
step lines (including "PB lookup error for NAME: …") on the progress screen.
"""

from __future__ import annotations

import json
import time

import pytest


@pytest.fixture
def app_client(web_module, client):
    return web_module, client


_PB_LOG = [
    "Interpreting document",
    "Filtered to 'Test SC': 12 swims by 4 swimmers, 30 excluded.",
    "Looking up personal bests for 4 swimmers (4 in parallel)…",
    "Looking up personal bests 2/4: Isabelle David",
    "PB lookup error for Cadi Evans: connection reset",
]


def _seed_running(web, run_id):
    web._active_runs[run_id] = {
        "status": "running",
        "error": None,
        "log": list(_PB_LOG),
        "started_at": "2026-01-01T00:00:00Z",
        "heartbeat": time.time(),
    }
    return run_id


def test_customer_page_hides_raw_log_and_shows_percent(app_client):
    web, client = app_client
    run_id = _seed_running(web, "run-cust")
    html = client.get(f"/runs/{run_id}").get_data(as_text=True)
    assert "IS_DEV = false" in html
    assert 'id="mh-percent"' in html
    # The raw, engineer-facing surfaces must NOT be present for a customer.
    # (Check element ids/text, not class names — the steploader CSS rule ships
    # in the global stylesheet on every page.)
    assert "Show technical log" not in html
    assert 'id="mh-steps"' not in html
    assert 'id="mh-step-count"' not in html


def test_developer_page_shows_raw_step_log(app_client, monkeypatch):
    web, client = app_client
    monkeypatch.setattr(web._auth, "is_dev_operator", lambda: True)
    run_id = _seed_running(web, "run-dev")
    html = client.get(f"/runs/{run_id}").get_data(as_text=True)
    assert "IS_DEV = true" in html
    assert "Show technical log" in html
    assert 'id="mh-steps"' in html
    assert 'id="mh-step-count"' in html


def test_status_endpoint_exposes_percent_and_phase(app_client):
    web, client = app_client
    run_id = _seed_running(web, "run-status")
    j = client.get(f"/api/runs/{run_id}/status").get_json()
    assert isinstance(j.get("percent"), int)
    assert 0 <= j["percent"] <= 100
    # A PB-stage log maps to the friendly phase, never a raw step string.
    assert j.get("phase") == "Researching personal bests"
    assert "PB lookup error" not in (j.get("phase") or "")


def test_progress_page_clamps_percent_and_steps_monotonically(app_client):
    """QA-005: status polls round-robin across the 2 gunicorn workers, and the
    worker that isn't running the pipeline serves the throttled (lagging) DB
    progress log — so a single poll's percent / step count can read LOWER than
    an earlier one. The page is the one consistent observer across polls, so it
    must hold a high-water mark: the bar and the step count never go backwards.

    Pin the monotonic clamp in the page's poll JS (a raw ``j.percent`` /
    ``j.log.length`` straight onto the bar is exactly the regression).
    """
    web, client = app_client
    run_id = _seed_running(web, "run-mono")
    html = client.get(f"/runs/{run_id}").get_data(as_text=True)

    # A percent high-water mark, declared AND applied (not just present once).
    assert html.count("maxPct") >= 2, "progress percent has no monotonic high-water clamp"
    # …and the step count / raw log is held to the longest log seen, so it can't
    # drop when a lagging cross-worker poll returns fewer lines.
    assert (
        "bestLog" in html and html.count("maxSteps") >= 2
    ), "step count has no monotonic high-water clamp"


# --- Post-run processing log: PB-lookup / store errors are surfaced to the
#     developer on the finished review page, never to the customer.

_DONE_LOG = [
    "Interpreting document",
    "Looking up personal bests 1/2: Isabelle David",
    "PB lookup error for Cadi Evans: source unreachable",
    "Club discovery store warning: [Errno 13] Permission denied",
    "V5 recognition: 0 achievements.",
]


def _seed_done_run(tmp_path, run_id):
    payload = {
        "run_id": run_id,
        "meet": {"name": "Test Meet"},
        "cards": [],
        "trust": {},
        "recognition_report": {"n_achievements": 0, "ranked_achievements": []},
        "parse_warnings": [],
        "self_check": {},
        "detector_summary": {},
        "dispatch_log": {},
        "progress_log": list(_DONE_LOG),
    }
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(payload))
    return run_id


def test_review_processing_log_hidden_from_customer(app_client, tmp_path):
    web, client = app_client
    run_id = _seed_done_run(tmp_path, "run-review-cust")
    html = client.get(f"/review/{run_id}").get_data(as_text=True)
    # The operator processing log and the raw error/warning lines must NOT
    # appear for a customer.
    assert "operator only" not in html
    assert "PB lookup error for Cadi Evans" not in html
    assert "Club discovery store warning" not in html


def test_review_processing_log_visible_to_developer(app_client, tmp_path, monkeypatch):
    web, client = app_client
    monkeypatch.setattr(web._auth, "is_dev_operator", lambda: True)
    run_id = _seed_done_run(tmp_path, "run-review-dev")
    html = client.get(f"/review/{run_id}").get_data(as_text=True)
    # The developer sees the persisted processing log, including the genuine
    # PB-lookup error and the club-discovery store warning — so failures never
    # silently vanish once the live progress screen redirects here.
    assert "Processing log" in html
    assert "PB lookup error for Cadi Evans" in html
    assert "Club discovery store warning" in html


# --- Issue A: a long, progress-silent step (the heavy LLM interpretation of a
#     large fresh/uncached PDF) ran past _RUN_STALE_SECS without emitting a
#     progress line, so the heartbeat — which used to advance ONLY on a progress
#     line — went stale and the status poller falsely declared the still-working
#     run dead ("Processing stopped responding…"). The worker now runs a liveness
#     ticker that advances the heartbeat for as long as the thread is alive,
#     independent of progress emissions; a genuinely dead worker still goes stale
#     because its ticker dies with it.


def _seed_running_stale(web, run_id):
    """A running run whose heartbeat is older than the staleness window — what a
    long progress-silent interpretation step looks like to the status poller."""
    web._active_runs[run_id] = {
        "status": "running",
        "error": None,
        "log": list(_PB_LOG),
        "started_at": "2026-01-01T00:00:00Z",
        "heartbeat": time.time() - (web._RUN_STALE_SECS + 30),
    }
    return run_id


def test_stale_heartbeat_reports_dead_then_liveness_tick_rescues(app_client):
    web, client = app_client
    run_id = _seed_running_stale(web, "run-stale")
    # Before a tick: a stale heartbeat is surfaced as a terminal error — the
    # exact false-death the large-PDF run hit mid-interpretation.
    j = client.get(f"/api/runs/{run_id}/status").get_json()
    assert j["status"] == "error"
    assert "stopped responding" in (j.get("error") or "")
    # One liveness tick (what the worker's background ticker does on a timer)
    # advances the heartbeat even though NO new progress line was emitted…
    assert web._advance_run_heartbeat(run_id) is True
    # …so the still-working run is no longer mistaken for dead.
    j2 = client.get(f"/api/runs/{run_id}/status").get_json()
    assert j2["status"] == "running"
    assert "stopped responding" not in (j2.get("error") or "")


def test_advance_heartbeat_refreshes_running_run(app_client):
    web, _client = app_client
    old = time.time() - 500
    web._active_runs["run-live"] = {
        "status": "running",
        "error": None,
        "log": [],
        "started_at": "2026-01-01T00:00:00Z",
        "heartbeat": old,
    }
    assert web._advance_run_heartbeat("run-live") is True
    assert web._active_runs["run-live"]["heartbeat"] > old


def test_advance_heartbeat_noop_for_terminal_and_missing(app_client):
    web, _client = app_client
    # A missing run is a no-op (a tick can't resurrect an evicted run).
    assert web._advance_run_heartbeat("does-not-exist") is False
    # A terminal run is a no-op — the ticker must never flip a finished/errored
    # run back to looking alive.
    old = time.time() - 999
    web._active_runs["run-terminal"] = {
        "status": "done",
        "error": None,
        "log": [],
        "started_at": "2026-01-01T00:00:00Z",
        "heartbeat": old,
    }
    assert web._advance_run_heartbeat("run-terminal") is False
    assert web._active_runs["run-terminal"]["heartbeat"] == old
