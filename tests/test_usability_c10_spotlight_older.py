"""C-10 — the athlete spotlight was buried and silently limited to 31 days.

Two fixes under test:
1. The spotlight meet picker's 31-day window is now a stated, toggleable choice:
   the hint names the cutoff and links a "Show older meets" toggle (?older=1)
   that lifts it; the empty state offers the same escape hatch.
2. Every processed meet's row on Activity carries an explicit
   "Spotlight a swimmer" link, so the spotlight is reachable without the
   Review view-switch or a hand-typed URL.
"""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta, timezone

import pytest

ORG = "org-c10"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    if not wm._club_platform_ok:
        pytest.skip("club_platform extra not available")

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=ORG, display_name="Test Club"))
    app = wm.create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    assert c.post("/api/organisation/active", data={"profile_id": ORG}).status_code == 200
    return {"client": c, "wm": wm, "tmp": tmp_path}


def _seed_done_run(env, run_id, meet_name, *, days_ago):
    (env["tmp"] / "runs_v4" / f"{run_id}.json").write_text(
        json.dumps({"run_id": run_id, "profile_id": ORG, "recognition_report": {}})
    )
    created = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    conn = env["wm"]._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, ?, 'done', ?, ?, ?)",
        (run_id, created, ORG, meet_name, f"{run_id}.hy3"),
    )
    conn.commit()
    conn.close()


def test_recent_view_hides_old_meets_but_states_cutoff_and_links_toggle(env):
    _seed_done_run(env, "c10recent01", "Fresh Gala", days_ago=2)
    _seed_done_run(env, "c10older001", "Winter Gala", days_ago=60)
    html = env["client"].get("/spotlight").get_data(as_text=True)
    assert "Fresh Gala" in html
    assert "Winter Gala" not in html
    # The window is stated, not silent — and the toggle is one click away.
    assert "last 31 days" in html
    assert "Show older meets" in html
    assert "older=1" in html


def test_older_toggle_lifts_the_cutoff(env):
    _seed_done_run(env, "c10recent01", "Fresh Gala", days_ago=2)
    _seed_done_run(env, "c10older001", "Winter Gala", days_ago=60)
    html = env["client"].get("/spotlight?older=1").get_data(as_text=True)
    assert "Fresh Gala" in html
    assert "Winter Gala" in html
    # The all-meets view offers the way back to the recent window…
    assert "Show the last 31 days only" in html
    # …and the picker form keeps the mode across its own GET submit.
    assert '<input type="hidden" name="older" value="1">' in html


def test_empty_recent_window_offers_older_escape_hatch(env):
    _seed_done_run(env, "c10older001", "Winter Gala", days_ago=60)
    html = env["client"].get("/spotlight").get_data(as_text=True)
    # Nothing in the window → the hero still routes to the older meets.
    assert "Show older meets" in html


def test_activity_row_links_processed_meet_to_spotlight(env):
    _seed_done_run(env, "c10recent01", "Fresh Gala", days_ago=2)
    html = env["client"].get("/activity").get_data(as_text=True)
    assert "Spotlight a swimmer" in html
    assert "/spotlight?" in html
    assert "run_id=c10recent01" in html


def test_activity_row_skips_spotlight_link_for_unfinished_runs(env):
    conn = env["wm"]._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, ?, 'error', ?, ?, ?)",
        (
            "c10failed01",
            datetime.now(timezone.utc).isoformat(),
            ORG,
            "Broken Gala",
            "broken.hy3",
        ),
    )
    conn.commit()
    conn.close()
    html = env["client"].get("/activity").get_data(as_text=True)
    assert "Broken Gala" in html
    assert "Spotlight a swimmer" not in html
