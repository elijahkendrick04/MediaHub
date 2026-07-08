"""D-17 — AI-unavailability must be discoverable, not a hover-only tooltip.

The llm-status poller painted a tiny dot red and set a button `title`
("Live AI DISABLED…") — invisible on a touch device — and nothing in Settings
said whether a provider was live. There's now a visible "AI status" row on the
AI-governance settings page and an inline banner on the review page (revealed by
the poller when `live=false`).
"""

from __future__ import annotations

import importlib
import json
import pathlib
import uuid

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    app = wm.create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "club-a"
    return c, tmp_path


def _seed_run(tmp_path):
    run_id = "run-d17-" + uuid.uuid4().hex[:8]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "profile_id": "club-a",
                "meet": {"name": "County Champs"},
                "recognition_report": {
                    "ranked_achievements": [
                        {
                            "achievement": {
                                "swim_id": "s1",
                                "swimmer_name": "Ada",
                                "event": "100 Free",
                            }
                        }
                    ]
                },
            }
        )
    )
    return run_id


def test_governance_page_shows_ai_status_disabled(client):
    c, _ = client
    html = c.get("/settings/governance").get_data(as_text=True)
    assert "AI status" in html
    # No provider key in this env → an honest Disabled row with a next step.
    assert "Disabled" in html
    assert "Ask your operator" in html


def test_llm_status_endpoint_reports_not_live(client):
    c, _ = client
    j = c.get("/api/settings/llm-status").get_json()
    assert j["live"] is False


def test_review_page_carries_ai_disabled_banner(client):
    c, tmp = client
    run_id = _seed_run(tmp)
    html = c.get(f"/review/{run_id}").get_data(as_text=True)
    # The banner element is present (hidden by default; the poller reveals it),
    # visibly worded, and links to the AI-status page.
    assert "ai-disabled-banner" in html
    assert "AI captions are turned off on this deployment" in html
    assert "/settings/governance" in html


def test_poller_toggles_the_banner():
    src = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")
    # The status poller reveals/hides the banner from the live flag.
    assert "querySelectorAll('.ai-disabled-banner')" in src
    assert "b.hidden = !!j.live" in src
