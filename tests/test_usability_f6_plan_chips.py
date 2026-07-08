"""F-6 — plan items must not wear internal signal vocabulary.

Each ranked item showed unexplained OWN/EXTERNAL/DIRECT chips (the engine's
signal-source taxonomy), a bare "baseline" fallback, an "approval required"
autonomy tag (alarming in a product that never auto-posts), and "horizon 14d",
none defined on the page. These are now plain language.
"""

from __future__ import annotations

import importlib
import json

import pytest

ORG = "club-a"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=ORG, display_name="Club A"))

    # Seed a persisted plan the planner will load.
    from mediahub.content_engine import planner

    d = planner._plans_dir(ORG, data_dir=tmp_path)
    d.mkdir(parents=True, exist_ok=True)
    plan = {
        "profile_id": ORG,
        "sport": "swimming",
        "sport_display": "Swimming",
        "generated_at": "2026-07-08T10:00:00",
        "horizon_days": 14,
        "source_counts": {"own": 3, "external": 1, "direct": 2},
        "items": [
            {
                "title": "Celebrate Ada's PB",
                "post_type": "feed",
                "sources_used": ["own"],
                "reasons": ["A confirmed personal best"],
                "score": 88,
                "implemented": True,
                "default_autonomy": "approval_required",
            },
            {
                "title": "General idea",
                "post_type": "feed",
                "sources_used": [],
                "reasons": [],
                "score": 20,
                "implemented": False,
            },
        ],
        "notes": [],
    }
    (d / "latest.json").write_text(json.dumps(plan))

    app = wm.create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = ORG
    return c


def test_plan_chips_are_plain_language(client):
    html = client.get("/plan").get_data(as_text=True)
    assert "From your results" in html
    assert ">OWN<" not in html and ">EXTERNAL<" not in html and ">DIRECT<" not in html
    # The "baseline" fallback is now "General suggestion".
    assert "General suggestion" in html
    assert ">baseline<" not in html


def test_no_autonomy_tag_and_plain_horizon(client):
    html = client.get("/plan").get_data(as_text=True)
    # The alarming "approval required" autonomy tag is gone (everything needs
    # approval), and "horizon 14d" reads "next 14 days".
    assert 'title="Default autonomy for this type"' not in html
    assert "next 14 days" in html
    assert "horizon 14d" not in html
