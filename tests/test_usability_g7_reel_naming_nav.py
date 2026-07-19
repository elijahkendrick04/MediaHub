"""G-7 — two features were both called just "reel" (the pack page's Meet reel
built from cards, and the Video Studio's reel built from footage), neither
cross-linked the other, and the studio's active='video' matched no nav item so
nothing highlighted.

- the studio's user-facing reel is now labelled "Footage reel" (copy only)
- the studio hero cross-links "Build a Meet reel" (latest pack, else Activity)
  and the pack reel composer cross-links the Video Studio
- active='video' highlights Create in both navs
"""

from __future__ import annotations

import json
import pathlib
import re
from datetime import datetime, timezone

import pytest
from tests._helpers import web_surface_src

ORG = "org-g7"


@pytest.fixture
def env(client, web_module, tmp_path):
    if not web_module._v8_ok:
        pytest.skip("V8 media engine not available")

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=ORG, display_name="Test Club"))
    assert client.post("/api/organisation/active", data={"profile_id": ORG}).status_code == 200
    return {"client": client, "wm": web_module, "tmp": tmp_path}


def _seed_done_run(env, run_id="rung7a"):
    (env["tmp"] / "runs_v4" / f"{run_id}.json").write_text(
        json.dumps({"run_id": run_id, "profile_id": ORG, "recognition_report": {}})
    )
    conn = env["wm"]._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, ?, 'done', ?, 'Spring Gala', 'spring.hy3')",
        (run_id, datetime.now(timezone.utc).isoformat(), ORG),
    )
    conn.commit()
    conn.close()


def test_studio_reel_is_labelled_footage_reel(env):
    html = env["client"].get("/video").get_data(as_text=True)
    assert "Footage reel" in html
    assert "AI reel" not in html


def test_studio_cross_links_meet_reel_to_latest_pack(env):
    _seed_done_run(env, "rung7a")
    html = env["client"].get("/video").get_data(as_text=True)
    assert "Build a Meet reel" in html
    assert "/pack/rung7a" in html


def test_studio_cross_links_meet_reel_to_activity_without_a_pack(env):
    html = env["client"].get("/video").get_data(as_text=True)
    assert "Build a Meet reel" in html
    assert "/activity" in html


def test_active_video_highlights_create_in_both_navs(env):
    html = env["client"].get("/video").get_data(as_text=True)
    # Top bar: the Create link carries the active class.
    assert re.search(
        r'<a href="/make" class="active">', html
    ), "top-nav Create should highlight on the Video Studio"
    # Mobile bottom nav too.
    assert re.search(
        r'<a href="/make" class="is-active"', html
    ), "bottom-nav Create should highlight on the Video Studio"


def test_pack_reel_composer_cross_links_video_studio():
    # The pack page needs a full approved pack to render, so the composer's
    # one-line hint is pinned at source level (same idiom as other JS-in-
    # template guards).
    src = web_surface_src()
    assert "Working from race footage?" in src
    i = src.index("Working from race footage?")
    frag = src[i : i + 220]
    assert 'url_for("video_studio_page")' in frag
    assert "Try the Video Studio" in frag
