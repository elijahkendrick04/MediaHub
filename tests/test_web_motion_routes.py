"""Web route surface for motion rendering: canvas, template and alpha contracts.

One shared resolver (``web._resolve_motion_canvas``) turns request args into a
single format token for every motion/reel route (render + file + manifest), so
all six sites derive the identical filename. These tests exercise the resolver's
precedence and validation directly (via a request context) and prove the
file/manifest routes re-derive the exact ``_1600x900`` filename the render wrote.

The template/alpha classes below pin the shipped HTTP contracts of the
data-driven-json and alpha-export features at the route surface (the module
layers are covered by ``test_motion_template.py`` / ``test_motion_alpha.py``):
400 ``bad_motion_template`` for bad or route-unsupported template input, the
``_tmpl<hash8>`` preview-slot isolation (a preview must never clobber the
canonical approved artifact), template threading through the sync AND async job
routes, query-rhythm-over-template-weights precedence, 400 ``bad_alpha`` /
503 ``alpha_unsupported_on_engine``, and the alpha file route's container
Content-Type.
"""

from __future__ import annotations

import json
import re
import sys
import time
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
                },
                {
                    "id": "swim-2",
                    "rank": 2,
                    "priority": 0.8,
                    "achievement": {
                        "swim_id": "swim-2",
                        "swimmer_name": "Mabli Rees",
                        "event": "200m Backstroke",
                        "time": "2:19.40",
                    },
                },
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


def _client(run_env):
    app, wm = run_env
    c = app.test_client()
    c.post("/api/organisation/active", data={"profile_id": "alpha"})
    return c, wm


def _motion_module():
    import mediahub.visual.motion as motion

    return motion


def _write_out(path_bytes: bytes):
    """A render mock: write ``path_bytes`` at the requested out_path, return it."""

    def _side_effect(_card_or_cards, _brand, out_path, **_kw):
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(path_bytes)
        return p

    return _side_effect


def _poll_until_settled(client, poll_url, tries=100, delay=0.1):
    j = {}
    for _ in range(tries):
        j = client.get(poll_url).get_json()
        if j.get("status") != "running":
            return j
        time.sleep(delay)
    return j


class TestTemplateBody400s:
    """Bad or route-unsupported template input is an honest 400
    ``bad_motion_template`` — never a validated-then-ignored 200."""

    def test_unknown_key_is_400_on_both_render_routes(self, run_env):
        c, wm = _client(run_env)
        for url in ("/api/runs/r1/card/swim-1/motion", "/api/runs/r1/reel"):
            r = c.post(url, json={"template": {"colour": "#fff"}})
            assert r.status_code == 400, url
            assert r.get_json()["error"] == "bad_motion_template"

    def test_non_dict_template_is_400(self, run_env):
        c, wm = _client(run_env)
        r = c.post("/api/runs/r1/card/swim-1/motion", json={"template": "dots"})
        assert r.status_code == 400
        assert r.get_json()["error"] == "bad_motion_template"

    def test_oversized_junk_value_is_400_with_bounded_detail(self, run_env):
        c, wm = _client(run_env)
        r = c.post(
            "/api/runs/r1/card/swim-1/motion",
            json={"template": {"mood": "x" * 100_000}},
        )
        assert r.status_code == 400
        detail = r.get_json()["detail"]
        # The 100k junk value must NOT be reflected whole into the response.
        assert len(detail) < 600

    def test_template_format_key_is_400_not_silently_ignored(self, run_env):
        # 'format' validates in the module but no route can honour it (the
        # output cut binds out_path/Content-Type from the URL) — it must be a
        # loud 400 pointing at ?format=, never a 200 with the wrong geometry.
        c, wm = _client(run_env)
        for url in ("/api/runs/r1/card/swim-1/motion", "/api/runs/r1/reel"):
            r = c.post(url, json={"template": {"format": "square"}})
            assert r.status_code == 400, url
            body = r.get_json()
            assert body["error"] == "bad_motion_template"
            assert "format" in body["detail"]

    def test_template_weights_key_is_400_on_card_route(self, run_env):
        c, wm = _client(run_env)
        r = c.post("/api/runs/r1/card/swim-1/motion", json={"template": {"weights": [3, 1]}})
        assert r.status_code == 400
        body = r.get_json()
        assert body["error"] == "bad_motion_template"
        assert "weights" in body["detail"]

    def test_templates_must_be_list_is_400(self, run_env):
        c, wm = _client(run_env)
        r = c.post("/api/runs/r1/reel", json={"templates": "notalist"})
        assert r.status_code == 400
        assert r.get_json()["error"] == "bad_motion_template"

    def test_per_beat_render_section_is_400(self, run_env):
        c, wm = _client(run_env)
        r = c.post("/api/runs/r1/reel", json={"templates": [{"fps": 60}]})
        assert r.status_code == 400
        body = r.get_json()
        assert body["error"] == "bad_motion_template"
        assert "art-only" in body["detail"]

    def test_surplus_per_beat_templates_is_400(self, run_env):
        # 2 ranked cards; 3 per-beat templates would silently drop one.
        c, wm = _client(run_env)
        r = c.post(
            "/api/runs/r1/reel",
            json={"templates": [{"mood": "calm"}] * 3},
        )
        assert r.status_code == 400
        assert r.get_json()["error"] == "bad_motion_template"

    def test_reel_level_art_is_400(self, run_env):
        # There is no reel-level art seam — art belongs in per-beat templates.
        c, wm = _client(run_env)
        r = c.post("/api/runs/r1/reel", json={"template": {"mood": "explosive"}})
        assert r.status_code == 400
        body = r.get_json()
        assert body["error"] == "bad_motion_template"
        assert "per-beat" in body["detail"]


class TestTemplateForwarding:
    """A validated template actually reaches the renderer kwargs."""

    def test_card_template_fps_and_toggles_forwarded(self, run_env):
        c, wm = _client(run_env)
        motion = _motion_module()
        tmpl = {"background_style": "dots", "fps": 60, "effect_toggles": ["accent"]}
        with mock.patch.object(
            motion, "render_story_card", side_effect=_write_out(b"P" * 2048)
        ) as m:
            r = c.post("/api/runs/r1/card/swim-1/motion", json={"template": tmpl})
        assert r.status_code == 200, r.get_json()
        kw = m.call_args.kwargs
        assert kw["motion_template"] == tmpl
        assert kw["fps"] == 60
        assert kw["review_ab"] == ["accent"]

    def test_query_rhythm_wins_over_template_weights(self, run_env):
        c, wm = _client(run_env)
        motion = _motion_module()
        with mock.patch.object(
            motion, "render_meet_reel", side_effect=_write_out(b"R" * 2048)
        ) as m:
            r = c.post(
                "/api/runs/r1/reel?n=2&weights=5,1",
                json={"template": {"weights": [1, 3]}},
            )
        assert r.status_code == 200, r.get_json()
        expected = motion.normalise_reel_rhythm({"weights": [5.0, 1.0]}, 2)
        assert m.call_args.kwargs["rhythm"] == expected

    def test_template_weights_apply_when_no_query_rhythm(self, run_env):
        c, wm = _client(run_env)
        motion = _motion_module()
        with mock.patch.object(
            motion, "render_meet_reel", side_effect=_write_out(b"R" * 2048)
        ) as m:
            r = c.post("/api/runs/r1/reel?n=2", json={"template": {"weights": [1, 3]}})
        assert r.status_code == 200, r.get_json()
        expected = motion.normalise_reel_rhythm({"weights": [1.0, 3.0]}, 2)
        assert m.call_args.kwargs["rhythm"] == expected


class TestPreviewSlotIsolation:
    """A templated render is a PREVIEW: it must publish beside — never over —
    the canonical approved artifact the motion-file/manifest routes serve."""

    def test_templated_card_render_leaves_canonical_slot_untouched(self, run_env):
        c, wm = _client(run_env)
        motion = _motion_module()
        motion_dir = wm.RUNS_DIR / "r1" / "motion"
        motion_dir.mkdir(parents=True, exist_ok=True)
        canonical = motion_dir / "swim-1.mp4"
        approved = b"APPROVED" * 256
        canonical.write_bytes(approved)

        with mock.patch.object(
            motion, "render_story_card", side_effect=_write_out(b"PREVIEW!" * 256)
        ):
            r = c.post(
                "/api/runs/r1/card/swim-1/motion",
                json={"template": {"background_style": "dots"}},
            )
        assert r.status_code == 200
        tok = r.headers.get("X-Motion-Preview") or ""
        assert re.fullmatch(r"[0-9a-f]{8}", tok)
        # The canonical approved artifact is byte-identical.
        assert canonical.read_bytes() == approved
        # The preview landed in its own _tmpl slot.
        preview = motion_dir / f"swim-1_tmpl{tok}.mp4"
        assert preview.exists() and preview.read_bytes() != approved

        # The file route serves each slot under its own identity.
        got_preview = c.get(f"/api/runs/r1/card/swim-1/motion-file?tmpl={tok}")
        assert got_preview.status_code == 200
        assert got_preview.data == preview.read_bytes()
        got_canonical = c.get("/api/runs/r1/card/swim-1/motion-file")
        assert got_canonical.status_code == 200
        assert got_canonical.data == approved

        # The preview manifest sidecar is addressable the same way.
        (motion_dir / f"swim-1_tmpl{tok}.json").write_text(
            json.dumps({"kind": "story", "preview": True}), encoding="utf-8"
        )
        man = c.get(f"/api/runs/r1/card/swim-1/motion/manifest?tmpl={tok}")
        assert man.status_code == 200
        assert man.get_json()["preview"] is True

    def test_bad_tmpl_token_is_400_not_traversal(self, run_env):
        c, wm = _client(run_env)
        for bad in ("zzzzzzzz", "../../x", "abcd", "ABCD12345"):
            r = c.get(f"/api/runs/r1/card/swim-1/motion-file?tmpl={bad}")
            assert r.status_code == 400, bad
            assert r.get_json()["error"] == "bad_motion_template"

    def test_default_render_still_targets_canonical_slot(self, run_env):
        # Byte-identical default: no template body → the exact historic name.
        c, wm = _client(run_env)
        motion = _motion_module()
        with mock.patch.object(
            motion, "render_story_card", side_effect=_write_out(b"D" * 2048)
        ) as m:
            r = c.post("/api/runs/r1/card/swim-1/motion")
        assert r.status_code == 200
        assert r.headers.get("X-Motion-Preview") is None
        out_path = Path(m.call_args.args[2])
        assert out_path.name == "swim-1.mp4"

    def test_templated_reel_render_leaves_canonical_slot_untouched(self, run_env):
        c, wm = _client(run_env)
        motion = _motion_module()
        motion_dir = wm.RUNS_DIR / "r1" / "motion"
        motion_dir.mkdir(parents=True, exist_ok=True)
        canonical = motion_dir / "reel_2.mp4"
        approved = b"APPROVEDREEL" * 200
        canonical.write_bytes(approved)

        with mock.patch.object(
            motion, "render_meet_reel", side_effect=_write_out(b"PREVIEWREEL!" * 200)
        ):
            r = c.post(
                "/api/runs/r1/reel?n=2",
                json={"templates": [{"background_style": "dots"}]},
            )
        assert r.status_code == 200
        tok = r.headers.get("X-Motion-Preview") or ""
        assert re.fullmatch(r"[0-9a-f]{8}", tok)
        assert canonical.read_bytes() == approved
        assert (motion_dir / f"reel_2_tmpl{tok}.mp4").exists()
        got = c.get(f"/api/runs/r1/reel-file?n=2&tmpl={tok}")
        assert got.status_code == 200
        assert got.data != approved


class TestAsyncJobTemplate:
    """The job routes honour the same template body as their sync siblings —
    previously it was silently dropped (202 + the DEFAULT render)."""

    def test_motion_job_threads_template_and_preview_url(self, run_env):
        c, wm = _client(run_env)
        motion = _motion_module()
        tmpl = {"background_style": "dots", "fps": 60}
        with mock.patch.object(
            motion, "render_story_card", side_effect=_write_out(b"J" * 2048)
        ) as m:
            r = c.post("/api/runs/r1/card/swim-1/motion-job", json={"template": tmpl})
            assert r.status_code == 202
            j = _poll_until_settled(c, r.get_json()["poll_url"])
        assert j["status"] == "done", j
        assert "tmpl=" in j["video_url"]
        kw = m.call_args.kwargs
        assert kw["motion_template"] == tmpl
        assert kw["fps"] == 60
        # The rendered preview file lands in the _tmpl slot and streams back.
        out_path = Path(m.call_args.args[2])
        assert "_tmpl" in out_path.name
        f = c.get(j["video_url"])
        assert f.status_code == 200

    def test_reel_job_threads_per_beat_templates(self, run_env):
        c, wm = _client(run_env)
        motion = _motion_module()
        beats = [{"background_style": "dots"}, {"mood": "calm"}]
        with mock.patch.object(
            motion, "render_meet_reel", side_effect=_write_out(b"J" * 2048)
        ) as m:
            r = c.post("/api/runs/r1/reel-job?n=2", json={"templates": beats})
            assert r.status_code == 202
            j = _poll_until_settled(c, r.get_json()["poll_url"])
        assert j["status"] == "done", j
        assert "tmpl=" in j["video_url"]
        assert m.call_args.kwargs["motion_templates"] == beats
        f = c.get(j["video_url"])
        assert f.status_code == 200

    def test_job_routes_reject_bad_template_before_202(self, run_env):
        c, wm = _client(run_env)
        for url in ("/api/runs/r1/card/swim-1/motion-job", "/api/runs/r1/reel-job"):
            r = c.post(url, json={"template": {"colour": "#fff"}})
            assert r.status_code == 400, url
            assert r.get_json()["error"] == "bad_motion_template"

    def test_batch_routes_reject_template_body(self, run_env):
        # The batches render the approved artifact's cuts — a template body is
        # an honest 400, never a silent drop.
        c, wm = _client(run_env)
        for url, body in (
            ("/api/runs/r1/card/swim-1/motion-batch-job", {"template": {"mood": "calm"}}),
            ("/api/runs/r1/reel-batch", {"templates": [{"mood": "calm"}]}),
        ):
            r = c.post(url, json=body)
            assert r.status_code == 400, url
            assert r.get_json()["error"] == "bad_motion_template"

    def test_batch_routes_reject_custom_canvas(self, run_env):
        # any-canvas honesty (deep-review finding): the batches render the four
        # preset cuts only — a validated ?size=/?w=&h= custom canvas is an
        # honest 400 here, never validated-then-silently-preset-rendered.
        c, wm = _client(run_env)
        for url in (
            "/api/runs/r1/card/swim-1/motion-batch-job?size=1080x1440",
            "/api/runs/r1/reel-batch?w=1280&h=720",
        ):
            r = c.post(url)
            assert r.status_code == 400, url
            assert r.get_json()["error"] == "bad_canvas"


class TestAlphaRouteContract:
    """The alpha-export HTTP contract at the route surface."""

    def test_bad_alpha_is_400_on_file_routes(self, run_env):
        c, wm = _client(run_env)
        for url in (
            "/api/runs/r1/card/swim-1/motion-file?alpha=junk",
            "/api/runs/r1/reel-file?alpha=junk",
        ):
            r = c.get(url)
            assert r.status_code == 400, url
            body = r.get_json()
            assert body["error"] == "bad_alpha"
            assert body["valid_alpha"]

    def test_bad_alpha_is_400_on_render_routes(self, run_env):
        c, wm = _client(run_env)
        for url in ("/api/runs/r1/card/swim-1/motion?alpha=junk", "/api/runs/r1/reel?alpha=junk"):
            r = c.post(url)
            assert r.status_code == 400, url
            assert r.get_json()["error"] == "bad_alpha"

    def test_alpha_unsupported_engine_is_503(self, run_env):
        c, wm = _client(run_env)
        motion = _motion_module()
        boom = motion.AlphaUnsupportedError("alpha needs the Remotion engine")
        with mock.patch.object(motion, "render_story_card", side_effect=boom):
            r = c.post("/api/runs/r1/card/swim-1/motion?alpha=prores4444")
        assert r.status_code == 503
        assert r.get_json()["error"] == "alpha_unsupported_on_engine"
        with mock.patch.object(motion, "render_meet_reel", side_effect=boom):
            r = c.post("/api/runs/r1/reel?alpha=prores4444")
        assert r.status_code == 503
        assert r.get_json()["error"] == "alpha_unsupported_on_engine"

    def test_alpha_file_served_with_profile_content_type(self, run_env):
        c, wm = _client(run_env)
        motion_dir = wm.RUNS_DIR / "r1" / "motion"
        motion_dir.mkdir(parents=True, exist_ok=True)
        (motion_dir / "swim-1.mov").write_bytes(b"0" * 2048)
        r = c.get("/api/runs/r1/card/swim-1/motion-file?alpha=prores4444")
        assert r.status_code == 200
        assert "video/quicktime" in (r.headers.get("Content-Type") or "")
        # Absent ?alpha= keeps the historic opaque .mp4 slot (404: not written).
        assert c.get("/api/runs/r1/card/swim-1/motion-file").status_code == 404
