"""Governance 1.23 — the caption route meters and enforces (Build 2).

Exercises the real /api/runs/<id>/swim/<id>/caption endpoint end-to-end with the
LLM mocked, proving (a) a successful AI caption records one feature-use against
the run's org, and (b) once a configured caption quota is reached the route
hard-blocks with an honest 'quota_reached' error and never calls the LLM.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

ORG = "club-x"
SWIM = "swim-001"


@pytest.fixture
def app_with_run(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MEDIAHUB_QUOTA_CAPTION", raising=False)
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    from mediahub.web.club_profile import ClubProfile, save_profile
    import mediahub.web.web as web_module

    save_profile(
        ClubProfile(profile_id=ORG, display_name="Club X", org_type="swimming_club")
    )

    achievement = {
        "swim_id": SWIM,
        "swimmer_name": "Emma Davies",
        "event": "200m Backstroke",
        "time": "2:23.45",
        "pb": True,
        "type": "pb",
        "headline": "New PB",
        "place": "1st",
    }
    run = {
        "run_id": "run-1",
        "profile_id": ORG,
        "profile_display": "Club X",
        "meet": {"name": "Winter Champs"},
        "recognition_report": {
            "n_achievements": 1,
            "ranked_achievements": [{"rank": 1, "achievement": achievement, "factors": []}],
        },
    }
    runs_dir = tmp_path / "runs_v4"
    monkeypatch.setattr(web_module, "RUNS_DIR", runs_dir, raising=False)
    (runs_dir / "run-1.json").write_text(json.dumps(run), encoding="utf-8")

    app = web_module.create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"
    return app


def _client(app):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["active_profile_id"] = ORG
    return c


def _caption_url():
    return f"/api/runs/run-1/swim/{SWIM}/caption?tone=ai"


def _ledger_count():
    from mediahub.observability import feature_quota

    return feature_quota.count_for_org(ORG, feature="caption")


def test_successful_caption_is_metered(app_with_run):
    client = _client(app_with_run)
    bundle = {
        "caption": "Emma smashed a new PB!",
        "alt_text": "Emma at the wall",
        "caption_secondary": None,
        "secondary_language": None,
    }
    with mock.patch("mediahub.media_ai.llm.is_available", return_value=True), mock.patch(
        "mediahub.web.ai_caption.generate_caption_bundle", return_value=bundle
    ):
        resp = client.post(_caption_url())
    assert resp.status_code == 200
    j = resp.get_json()
    assert j["live"] is True
    assert j["caption"] == "Emma smashed a new PB!"
    # One caption-feature use recorded against the run's org.
    assert _ledger_count() == 1


def test_quota_reached_hard_blocks_without_calling_llm(app_with_run, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_QUOTA_CAPTION", "1")
    client = _client(app_with_run)
    bundle = {
        "caption": "first",
        "alt_text": "",
        "caption_secondary": None,
        "secondary_language": None,
    }

    gen = mock.Mock(return_value=bundle)
    with mock.patch("mediahub.media_ai.llm.is_available", return_value=True), mock.patch(
        "mediahub.web.ai_caption.generate_caption_bundle", gen
    ):
        # First call consumes the single allowed caption.
        r1 = client.post(_caption_url())
        assert r1.status_code == 200 and r1.get_json()["caption"] == "first"
        assert _ledger_count() == 1
        assert gen.call_count == 1

        # Second call is over the limit → honest block, LLM untouched.
        r2 = client.post(_caption_url())
        j2 = r2.get_json()
        assert j2["error"] == "quota_reached"
        assert j2["live"] is False
        assert "quota reached" in j2["message"].lower()
        assert gen.call_count == 1  # generation was NOT attempted again
        assert _ledger_count() == 1  # blocked call was not recorded


def test_no_limit_never_blocks(app_with_run):
    """With no configured caption limit, many generations all succeed (meter-only)."""
    client = _client(app_with_run)
    bundle = {
        "caption": "ok",
        "alt_text": "",
        "caption_secondary": None,
        "secondary_language": None,
    }
    with mock.patch("mediahub.media_ai.llm.is_available", return_value=True), mock.patch(
        "mediahub.web.ai_caption.generate_caption_bundle", return_value=bundle
    ):
        for _ in range(5):
            assert client.post(_caption_url()).status_code == 200
    assert _ledger_count() == 5


def test_voice_tone_is_not_metered(app_with_run):
    """Deterministic voice renders spend no AI budget, so they aren't metered."""
    client = _client(app_with_run)
    resp = client.post(f"/api/runs/run-1/swim/{SWIM}/caption?tone=warm_club")
    assert resp.status_code == 200
    assert _ledger_count() == 0
