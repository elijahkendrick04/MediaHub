"""D-20 — data-hub bulk generate must not dead-end.

After "Generate & queue" the user got a toast naming an internal slug ("Queued
24 card(s) from certificate.") with no link to where the cards now live, and the
"Recent bulk jobs" rows were plain text — no path from "I just made 24 cards"
into reviewing them. The success banner now links to the run's review queue, the
job rows link too, and the slug is humanised.
"""

from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, wm, tmp_path


def _login(c):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    with c.session_transaction() as s:
        s["active_profile_id"] = "club-a"


def _seed_run(tmp, run_id="r1"):
    payload = {
        "run_id": run_id,
        "profile_id": "club-a",
        "meet": {"name": "Spring Open"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "achievement": {
                        "swim_id": "s1",
                        "swimmer_name": "Ada",
                        "event": "100m Freestyle",
                        "headline": "PB!",
                        "type": "pb_confirmed",
                        "raw_facts": {"time_str": "1:05.32"},
                    },
                    "post_angle": "personal_best",
                    "rank": 1,
                    "quality_band": "strong",
                }
            ]
        },
    }
    (tmp / "runs_v4" / f"{run_id}.json").write_text(json.dumps(payload))


def test_generate_redirect_links_to_review_and_humanises_slug(app_env):
    app, _wm, tmp = app_env
    _seed_run(tmp)
    with app.test_client() as c:
        _login(c)
        r = c.post(
            "/api/data-hub/bulk",
            data={"run_id": "r1", "format_slug": "certificate", "pb_only": "1"},
        )
        assert r.status_code == 302
        loc = r.headers["Location"]
        assert "review_run=r1" in loc
        assert "Certificate" in loc  # humanised, not the raw "certificate"
        # The landed page shows a direct link into the review queue.
        page = c.get(loc).get_data(as_text=True)
        assert "Review these cards" in page
        assert "/review/r1" in page


def test_job_rows_link_to_review(app_env):
    app, _wm, tmp = app_env
    _seed_run(tmp)
    with app.test_client() as c:
        _login(c)
        c.post(
            "/api/data-hub/bulk",
            data={"run_id": "r1", "format_slug": "certificate", "pb_only": "1"},
        )
        page = c.get("/data-hub").get_data(as_text=True)
        assert "Recent bulk jobs" in page
        # The job title is a link into the run's review queue.
        assert 'href="/review/r1"' in page
