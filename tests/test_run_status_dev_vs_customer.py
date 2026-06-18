"""The meet-recap progress page must show a customer a friendly percentage bar
+ plain-English phase, and show the signed-in developer the raw step log +
technical detail. The status endpoint additionally exposes percent/phase.

Regression for the reported issue: customers were seeing raw engineer-facing
step lines (including "PB lookup error for NAME: …") on the progress screen.
"""

from __future__ import annotations

import importlib
import time

import pytest


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)

    import mediahub.web.web as web
    importlib.reload(web)
    app = web.create_app()
    app.config["TESTING"] = True
    return web, app.test_client()


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
