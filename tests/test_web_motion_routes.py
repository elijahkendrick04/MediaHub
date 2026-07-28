"""any-canvas — web route surface for the arbitrary motion canvas.

One shared resolver (``web._resolve_motion_canvas``) turns request args into a
single format token for every motion/reel route (render + file + manifest), so
all six sites derive the identical filename. These tests exercise the resolver's
precedence and validation directly (via a request context) and prove the
file/manifest routes re-derive the exact ``_1600x900`` filename the render wrote.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _resolve(app, wm, query: str):
    with app.test_request_context("/x?" + query):
        return wm._resolve_motion_canvas()


class TestResolveCanvas:
    def test_absent_is_story_byte_identical(self, app, web_module):
        token, err = _resolve(app, web_module, "")
        assert err is None
        assert token == "story"

    def test_format_preset_passthrough(self, app, web_module):
        token, err = _resolve(app, web_module, "format=landscape")
        assert err is None and token == "landscape"

    def test_bad_format_is_400(self, app, web_module):
        token, err = _resolve(app, web_module, "format=widescreen")
        assert token is None
        _resp, status = err
        assert status == 400
        assert _resp.get_json()["error"] == "bad_format"

    def test_size_token_and_wh_resolve_identically(self, app, web_module):
        t1, e1 = _resolve(app, web_module, "size=1600x900")
        t2, e2 = _resolve(app, web_module, "w=1600&h=900")
        assert e1 is None and e2 is None
        assert t1 == t2 == "1600x900"

    def test_geometry_wins_over_format(self, app, web_module):
        # Explicit geometry (size / w+h) beats a supplied ?format=.
        token, err = _resolve(app, web_module, "format=square&w=1600&h=900")
        assert err is None and token == "1600x900"
        token, err = _resolve(app, web_module, "format=square&size=1600x900")
        assert err is None and token == "1600x900"

    def test_custom_size_that_equals_preset_collapses(self, app, web_module):
        token, err = _resolve(app, web_module, "w=1080&h=1920")
        assert err is None and token == "story"
        token, err = _resolve(app, web_module, "w=1920&h=1080")
        assert err is None and token == "landscape"

    @pytest.mark.parametrize(
        "query",
        [
            "w=1601&h=900",  # odd
            "w=100&h=100",  # below floor
            "w=3000&h=1000",  # above ceiling
            "size=garbage",  # unparseable
            "size=1601x900",  # regex-hit but odd
            "w=1600",  # half-supplied pair
            "h=900",  # half-supplied pair
            "w=abc&h=900",  # non-int
        ],
    )
    def test_bad_canvas_is_400(self, app, web_module, query):
        token, err = _resolve(app, web_module, query)
        assert token is None
        _resp, status = err
        assert status == 400
        assert _resp.get_json()["error"] == "bad_canvas"


@pytest.fixture
def run_env(app, web_module):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    run = {
        "run_id": "r1",
        "profile_id": "alpha",
        "meet_name": "Test Open",
        "meet": {"name": "Test Open"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "id": "swim-1",
                    "rank": 1,
                    "priority": 0.9,
                    "achievement": {
                        "swim_id": "swim-1",
                        "swimmer_name": "Eira Hughes",
                        "event": "100m Freestyle",
                        "time": "59.80",
                    },
                }
            ]
        },
    }
    (web_module.RUNS_DIR / "r1.json").write_text(json.dumps(run), encoding="utf-8")
    return app, web_module


class TestFileRouteReDerivesFilename:
    def test_card_file_route_finds_custom_size_file(self, run_env):
        app, wm = run_env
        motion_dir = wm.RUNS_DIR / "r1" / "motion"
        motion_dir.mkdir(parents=True, exist_ok=True)
        # The render route writes the custom-cut file with the validated-int token.
        (motion_dir / "swim-1_1600x900.mp4").write_bytes(b"0" * 2048)

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            # Both param shapes re-derive the identical _1600x900 filename.
            for q in ("w=1600&h=900", "size=1600x900"):
                f = c.get(f"/api/runs/r1/card/swim-1/motion-file?{q}")
                assert f.status_code == 200, q
                assert "video/mp4" in (f.headers.get("Content-Type") or "")
            # A bad canvas is an honest 400, not a silent story fallback.
            bad = c.get("/api/runs/r1/card/swim-1/motion-file?w=1601&h=900")
            assert bad.status_code == 400
            assert bad.get_json()["error"] == "bad_canvas"
            # Absent params → the byte-identical bare story filename (404 here
            # because only the custom cut was written).
            absent = c.get("/api/runs/r1/card/swim-1/motion-file")
            assert absent.status_code == 404

    def test_reel_file_route_finds_custom_size_file(self, run_env):
        app, wm = run_env
        motion_dir = wm.RUNS_DIR / "r1" / "motion"
        motion_dir.mkdir(parents=True, exist_ok=True)
        (motion_dir / "reel_3_1600x900.mp4").write_bytes(b"0" * 2048)

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            f = c.get("/api/runs/r1/reel-file?size=1600x900")
            assert f.status_code == 200
            assert "video/mp4" in (f.headers.get("Content-Type") or "")
