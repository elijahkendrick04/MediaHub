"""G-2 — four surfaces rendered the same result history: /activity,
/activity/feed, /season, plus a third table inside Settings → Activity
("Mirrors /activity"); /status rendered at both /status and /settings/status.

Consolidated:
- one shared Table · Feed · Season strip cross-links the three lenses with
  an active state on each page
- Settings → Activity is a link card to the canonical /activity (per-row
  delete, failure explainers, search/filters and bulk clear all live there)
- /settings/status redirects to the canonical /status; the Settings tile
  links straight there
"""

from __future__ import annotations

import importlib
import json
import re
from datetime import datetime, timezone

import pytest

ORG = "org-g2"


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

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=ORG, display_name="Test Club"))
    app = wm.create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    assert c.post("/api/organisation/active", data={"profile_id": ORG}).status_code == 200

    # One processed meet so none of the three lenses early-return empty.
    (tmp_path / "runs_v4" / "rung2a.json").write_text(
        json.dumps({"run_id": "rung2a", "profile_id": ORG, "recognition_report": {}})
    )
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, ?, 'done', ?, 'Spring Gala', 'spring.hy3')",
        ("rung2a", datetime.now(timezone.utc).isoformat(), ORG),
    )
    conn.commit()
    conn.close()
    return {"client": c, "wm": wm}


def _strip_state(html: str) -> dict:
    """Extract {label: aria-current} from the shared Activity-view strip."""
    m = re.search(r'<nav class="mh-segmented" aria-label="Activity view".*?</nav>', html, re.S)
    assert m, "shared view strip missing"
    strip = m.group(0)
    return dict(re.findall(r'aria-current="([^"]+)"[^>]*>([^<]+)</a>', strip)) | dict(
        (label, cur) for cur, label in re.findall(r'aria-current="([^"]+)"[^>]*>([^<]+)</a>', strip)
    )


def test_all_three_lenses_carry_the_shared_strip_with_active_state(env):
    c = env["client"]
    for path, active_label in (
        ("/activity", "Results table"),
        ("/activity/feed", "Feed"),
        ("/season", "Season"),
    ):
        html = c.get(path).get_data(as_text=True)
        state = _strip_state(html)
        assert set(state) >= {"Results table", "Feed", "Season"}, (path, state)
        assert state[active_label] == "page", (path, state)
        others = {"Results table", "Feed", "Season"} - {active_label}
        for o in others:
            assert state[o] == "false", (path, o, state)


def test_settings_activity_is_a_link_card_not_a_mirror_table(env):
    html = env["client"].get("/settings/activity").get_data(as_text=True)
    # Pointer to the canonical page…
    assert "Open Activity" in html
    assert "/activity" in html
    # …not a second copy of the results table (the class name also appears
    # in the site-wide CSS comments, so match the actual table markup).
    assert "Queue / Total" not in html
    assert '<table class="mh-table-stack">' not in html


def test_settings_activity_capability_lives_on_canonical_page(env):
    # The mirror's per-row delete + failure explainer exist on /activity, so
    # nothing was lost by replacing the table with a link.
    html = env["client"].get("/activity").get_data(as_text=True)
    assert "mh-run-delete" in html
    assert "Clear all runs" in html


def test_settings_status_redirects_to_canonical_status(env):
    r = env["client"].get("/settings/status", follow_redirects=False)
    assert r.status_code in (301, 302, 303, 307, 308)
    assert r.headers["Location"].endswith("/status")


def test_settings_tile_links_straight_to_status(env):
    html = env["client"].get("/settings").get_data(as_text=True)
    assert "System status" in html
    assert "/settings/status" not in html
