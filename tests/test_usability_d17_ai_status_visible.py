"""D-17 — AI-unavailability must be discoverable, not a hover-only tooltip.

The llm-status poller painted a tiny dot red and set a button `title`
("Live AI DISABLED…") — invisible on a touch device — and nothing in Settings
said whether a provider was live. There's now a visible "AI status" row on the
AI-governance settings page and an inline banner on the review page (revealed by
the poller when `live=false`).
"""

from __future__ import annotations

import json
import uuid

import pytest

from mediahub.web.club_profile import ClubProfile, save_profile


@pytest.fixture
def client(app, tmp_path, monkeypatch):
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
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


def test_review_page_shows_ai_off_banner(client):
    c, tmp = client
    run_id = _seed_run(tmp)
    html = c.get(f"/review/{run_id}").get_data(as_text=True)
    # With no provider configured, the review page renders the server-side
    # AI-unavailable banner (no client poller needed), so AI-off is visible
    # inline where the volunteer works.
    assert "mh-ai-unavailable" in html
    assert "AI provider not configured" in html
