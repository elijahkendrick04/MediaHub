"""M31 (UX-3) — the reel composer's request assembly + the reel manifest route.

The composer picks moments (``?cards=``), a rhythm preset (R1.12 params) and
an audio mix; the route assembles the SELECTED cards in rank order, caps at 5,
rejects unknown ids honestly, and — the hard invariant — an untouched default
request produces byte-identical reel inputs (same cards, same ``reel_3``
naming, no rhythm dict), so the default top-3 reel's cache key never moves.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _run_payload(profile_id: str, n: int = 5) -> dict:
    return {
        "run_id": "r1",
        "profile_id": profile_id,
        "meet_name": "Test Open",
        "meet": {"name": "Test Open"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "id": f"swim-{i + 1}",
                    "rank": i + 1,
                    "priority": 0.9 - i * 0.1,
                    "achievement": {
                        "swim_id": f"swim-{i + 1}",
                        "swimmer_name": f"Swimmer {i + 1}",
                        "event": "100m Freestyle",
                        "headline": "PB set",
                        "time": "59.80",
                    },
                }
                for i in range(n)
            ]
        },
    }


@pytest.fixture
def app_env(app, web_module, tmp_path):
    import mediahub.media_library.store as mls

    # The media store is a module-level singleton; drop it so each test's
    # DATA_DIR gets a fresh DB instead of accumulating across tests.
    mls._default_store = None

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    save_profile(ClubProfile(profile_id="beta", display_name="Beta SC"))
    (web_module.RUNS_DIR / "r1.json").write_text(
        json.dumps(_run_payload("alpha")), encoding="utf-8"
    )
    return app, web_module, tmp_path


def _capture_reel(app, url):
    """POST the sync reel route with render_meet_reel mocked; capture inputs."""
    import mediahub.visual.motion as motion

    captured = {}

    def _fake(cards, brand_kit, out_path, **kw):
        captured["cards"] = cards
        captured["out_path"] = Path(out_path)
        captured["kw"] = kw
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"0" * 2048)
        return out_path

    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "alpha"})
        with mock.patch.object(motion, "render_meet_reel", _fake):
            resp = c.post(url)
    return resp, captured


class TestSelectionAssembly:
    def test_default_request_is_byte_identical_top3(self, app_env):
        app, wm, _ = app_env
        resp, cap = _capture_reel(app, "/api/runs/r1/reel")
        assert resp.status_code == 200
        assert [c["id"] for c in cap["cards"]] == ["swim-1", "swim-2", "swim-3"]
        assert cap["out_path"].name == "reel_3.mp4"  # no _sel marker
        assert cap["kw"]["rhythm"] is None  # default skeleton untouched

    def test_explicit_default_selection_keeps_default_naming(self, app_env):
        app, wm, _ = app_env
        resp, cap = _capture_reel(app, "/api/runs/r1/reel?cards=swim-1,swim-2,swim-3")
        assert resp.status_code == 200
        assert [c["id"] for c in cap["cards"]] == ["swim-1", "swim-2", "swim-3"]
        assert cap["out_path"].name == "reel_3.mp4"

    def test_custom_selection_assembles_in_rank_order(self, app_env):
        app, wm, _ = app_env
        # Requested out of order — assembled by rank, with a _sel marker so
        # the default reel_2 file is never clobbered.
        resp, cap = _capture_reel(app, "/api/runs/r1/reel?cards=swim-4,swim-2")
        assert resp.status_code == 200
        assert [c["id"] for c in cap["cards"]] == ["swim-2", "swim-4"]
        assert cap["out_path"].name.startswith("reel_2_sel")

    def test_unknown_card_is_honest_400(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post("/api/runs/r1/reel?cards=swim-1,ghost-9")
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["error"] == "bad_cards"
        assert "ghost-9" in body["detail"]

    def test_more_than_five_is_400(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post("/api/runs/r1/reel?cards=swim-1,swim-2,swim-3,swim-4,swim-5,swim-6")
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "bad_cards"

    def test_rhythm_preset_params_reach_the_render(self, app_env):
        app, wm, _ = app_env
        # Punchy = heavier top beat via ?weights=; Showcase = cover/outro.
        resp, cap = _capture_reel(app, "/api/runs/r1/reel?weights=1.5,1,1")
        assert resp.status_code == 200
        assert cap["kw"]["rhythm"]["beatWeights"] == [1.5, 1.0, 1.0]
        resp, cap = _capture_reel(app, "/api/runs/r1/reel?cover=3.5&outro=3.5")
        assert resp.status_code == 200
        assert cap["kw"]["rhythm"]["coverSec"] == 3.5
        assert cap["kw"]["rhythm"]["outroSec"] == 3.5

    def test_mix_rides_every_card_payload(self, app_env):
        app, wm, _ = app_env
        resp, cap = _capture_reel(app, "/api/runs/r1/reel?mix=voice_lead")
        assert resp.status_code == 200
        assert all(c["audio_mix_profile"] == "voice_lead" for c in cap["cards"])

    def test_job_route_mints_cards_aware_file_url(self, app_env):
        app, wm, _ = app_env
        import time as _time

        import mediahub.visual.motion as motion

        def _fake(cards, brand_kit, out_path, **kw):
            out_path = Path(out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"0" * 2048)
            return out_path

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(motion, "render_meet_reel", _fake):
                resp = c.post("/api/runs/r1/reel-job?cards=swim-4,swim-2")
                assert resp.status_code == 202
                poll = resp.get_json()["poll_url"]
                j = {}
                for _ in range(60):
                    j = c.get(poll).get_json()
                    if j.get("status") != "running":
                        break
                    _time.sleep(0.2)
            assert j["status"] == "done", j
            assert "cards=" in j["video_url"]
            # The minted URL finds the selection-suffixed file.
            f = c.get(j["video_url"])
            assert f.status_code == 200
            assert "video/mp4" in (f.headers.get("Content-Type") or "")


class TestReelManifestRoute:
    def test_manifest_served_and_gated(self, app_env):
        app, wm, _ = app_env
        mdir = wm.RUNS_DIR / "r1" / "motion"
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / "reel_3.json").write_text(
            json.dumps({"kind": "reel", "engine": "ffmpeg", "notes": {"engine_note": "hi"}}),
            encoding="utf-8",
        )
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.get("/api/runs/r1/reel-manifest")
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["engine"] == "ffmpeg"
            assert body["notes"]["engine_note"] == "hi"
            # Unrendered cuts 404 honestly.
            assert c.get("/api/runs/r1/reel-manifest?format=square").status_code == 404
        with app.test_client() as other:
            other.post("/api/organisation/active", data={"profile_id": "beta"})
            assert other.get("/api/runs/r1/reel-manifest").status_code == 404


class TestComposerMarkup:
    def _builder_html(self, app, wm, tmp_path):
        from mediahub.workflow.status import CardStatus
        from mediahub.workflow.store import WorkflowStore

        ws = WorkflowStore(Path(tmp_path / "runs_v4"))
        for i in range(1, 5):
            ws.set_status("r1", f"swim-{i}", CardStatus.APPROVED)
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.get("/pack/r1")
        assert resp.status_code == 200
        return resp.get_data(as_text=True)

    def test_composer_renders_with_top3_prechecked(self, app_env, tmp_path):
        app, wm, _ = app_env
        html = self._builder_html(app, wm, tmp_path)
        assert 'id="mh-reel-composer"' in html
        assert 'data-default-cards="swim-1,swim-2,swim-3"' in html
        # Rank-ordered checkboxes; the top three are pre-checked.
        assert html.count('class="mh-reel-pick"') == 4
        assert html.count("mh-reel-pick") >= 4
        assert 'value="swim-1" checked' in html
        assert 'value="swim-4" ' in html and 'value="swim-4" checked' not in html
        # Duration readout + rhythm presets + format-independent JS maths.
        assert 'id="mh-reel-duration"' in html
        assert 'id="mh-reel-rhythm"' in html
        assert "MH_REEL_MATHS" in html
        assert "outro: 2.5" in html  # mirrors visual/motion.py REEL_OUTRO_SEC

    def test_mix_select_only_when_voiceover_enabled(self, app_env, tmp_path, monkeypatch):
        app, wm, _ = app_env
        html = self._builder_html(app, wm, tmp_path)
        assert 'id="mh-reel-mix"' not in html  # voiceover off in this env
