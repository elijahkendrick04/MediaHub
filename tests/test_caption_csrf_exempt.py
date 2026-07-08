"""tests/test_caption_csrf_exempt.py — the caption tone POST survives CSRF
enforcement (audit finding A-3).

The tone buttons (Warm / Hype / Precise) fire a POST to the caption endpoint.
The client used to send a bare ``fetch(url, {method:'POST'})`` with no CSRF
token and no JSON content-type. Under CSRF enforcement (i.e. production) the
server answered 403 ``{"error":"csrf"}`` and the UI, not recognising that
error shape, rendered a *blank* caption with no message.

The fix makes the client send ``Content-Type: application/json`` (the same
same-origin-write exemption every other fetch on the page uses). This test
pins the server contract the client now relies on: a bare POST is rejected,
a JSON-content-type POST is accepted and returns a caption.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _make_fake_run(run_id: str, runs_dir: Path) -> None:
    achievement = {
        "swim_id": "swim_csrf_001",
        "swimmer_name": "Emma Davies",
        "event": "200m Backstroke",
        "time": "2:23.45",
        "pb": True,
        "type": "pb",
        "headline": "New PB in 200m Backstroke",
        "confidence_label": "high",
        "place": "1st",
    }
    ranked = [{
        "rank": 1, "priority": 0.95, "quality_band": "elite",
        "suggested_post_type": "individual",
        "achievement": achievement, "factors": [],
    }]
    run_data = {
        "run_id": run_id,
        "profile_display": "City Aquatics",
        "meet": {"name": "Winter Champs", "start_date": "2024-01-20"},
        "recognition_report": {"n_achievements": 1, "ranked_achievements": ranked},
    }
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text(json.dumps(run_data), encoding="utf-8")


@pytest.fixture
def csrf_client(tmp_path, monkeypatch):
    """App with CSRF enforced (but the org gate off) and a fake run present."""
    runs_dir = tmp_path / "runs_v4"
    _make_fake_run("run_csrf", runs_dir)
    import mediahub.web.web as web_module

    original = web_module.RUNS_DIR
    web_module.RUNS_DIR = runs_dir
    app = web_module.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_CSRF"] = True
    try:
        with app.test_client() as c:
            yield c
    finally:
        web_module.RUNS_DIR = original


CAPTION_URL = "/api/runs/run_csrf/swim/swim_csrf_001/caption?tone=warm_club"


def test_bare_post_is_csrf_rejected(csrf_client):
    """The old client behaviour (no token, no JSON content-type) is a 403 —
    which is exactly what silently blanked the caption."""
    r = csrf_client.post(CAPTION_URL)
    assert r.status_code == 403, r.status_code
    assert r.get_json().get("error") == "csrf"


def test_json_content_type_post_is_accepted(csrf_client):
    """The fixed client sends application/json, which the CSRF layer exempts —
    so the caption is generated normally."""
    r = csrf_client.post(CAPTION_URL, data="{}", content_type="application/json")
    assert r.status_code == 200, r.status_code
    body = r.get_json()
    assert body.get("tone") == "warm_club"
    assert body.get("caption", "").strip() != "", "a voice caption should come back"
