"""C-1/C-2 — the volunteer's loop is in the nav, and home resumes their work.

The desktop top-nav spent a slot on browse-only "Elements" while Activity/Review
(where you resume approving a pack) had none, and the signed-in home had no
recent runs / resume link. Now Activity holds the primary slot (matching the
mobile bottom nav) and the signed-in home shows a "Pick up where you left off"
strip linking straight into /review/<id>.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(profile_id="club-a", display_name="Riverside SC", brand_voice_summary="x")
    )
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, wm


def _client(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "club-a"
    return c


def _seed_run(wm, rid="run-1", n_queue=5, meet="County Champs"):
    conn = wm._db()
    conn.execute(
        "INSERT INTO runs (id, created_at, finished_at, status, profile_id, "
        "meet_name, file_name, our_swims, n_cards, n_queue, n_achievements, error) "
        "VALUES (?, datetime('now'), datetime('now'), 'done', 'club-a', ?, "
        "'m.pdf', 3, 0, ?, 8, NULL)",
        (rid, meet, n_queue),
    )
    conn.commit()
    conn.close()


def test_nav_has_activity_not_elements(app_env):
    app, _ = app_env
    c = _client(app)
    html = c.get("/").get_data(as_text=True)
    # Activity is now a primary nav item; Elements no longer holds a nav slot.
    assert 'href="/activity"' in html
    assert ">Elements</a>" not in html


def test_home_resume_strip_links_into_review(app_env):
    app, wm = app_env
    _seed_run(wm, meet="County Champs", n_queue=5)
    c = _client(app)
    html = c.get("/").get_data(as_text=True)
    assert "Pick up where you left off" in html
    assert "County Champs" in html
    assert "5 awaiting review" in html
    assert "/review/run-1" in html


def test_home_resume_strip_absent_with_no_runs(app_env):
    app, _ = app_env
    c = _client(app)
    html = c.get("/").get_data(as_text=True)
    assert "Pick up where you left off" not in html
