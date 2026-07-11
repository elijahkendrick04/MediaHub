"""B-5 — all four motion cuts of one card render as ONE background batch job.

The reel already had an "All 4 formats" batch; per-card motion made the user
click four separate renders (four waits, four progress bars). Now:

* ``POST /api/runs/<id>/card/<id>/motion-batch-job`` mirrors
  ``api_run_reel_batch`` over the motion job store — one job, kind
  ``motion-batch`` in ``api_reel_job_status``'s allowlist, rendering
  story/portrait/square/landscape sequentially, each cut under its OWN
  render-slot acquire/release with the queue timeout (never holding the gate
  across the batch), per-cut progress via ``total``/``done``/``current``;
* on ``done``, ``video_urls`` maps each produced cut to its persistent
  ``motion-file`` URL and ``formats_failed`` carries the honest reason for
  any cut that could not render (partial success is success);
* the client ships an "All 4 formats" button in the motion panel next to the
  existing format chips, on the shared job idiom (synchronous panel claim,
  D-13 localStorage record + resume, per-cut progress label).
"""

from __future__ import annotations

import contextlib
import importlib
import json
import pathlib
import re
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

ALL_FORMATS = ("story", "portrait", "square", "landscape")


def _run_payload(profile_id: str) -> dict:
    return {
        "run_id": "r1",
        "profile_id": profile_id,
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


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.media_library.store as mls
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    mls._default_store = None
    app = wm.create_app()
    app.config["TESTING"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    save_profile(ClubProfile(profile_id="beta", display_name="Beta SC"))
    (wm.RUNS_DIR / "r1.json").write_text(json.dumps(_run_payload("alpha")), encoding="utf-8")
    return app, wm, tmp_path


def _poll_until_settled(client, poll_url, tries=80, delay=0.2):
    j = {}
    for _ in range(tries):
        j = client.get(poll_url).get_json()
        if j.get("status") != "running":
            return j
        time.sleep(delay)
    return j


def _fake_render_ok(card, brand_kit, out_path, **kw):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"0" * 2048)
    return out_path


class TestMotionBatchJob:
    def test_one_job_renders_all_four_cuts(self, app_env):
        app, wm, _ = app_env
        import mediahub.visual.motion as motion

        seen_formats = []

        def _fake(card, brand_kit, out_path, **kw):
            seen_formats.append(kw.get("format_name"))
            return _fake_render_ok(card, brand_kit, out_path, **kw)

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(motion, "render_story_card", _fake):
                resp = c.post("/api/runs/r1/card/swim-1/motion-batch-job")
                assert resp.status_code == 202
                body = resp.get_json()
                assert body["ok"] is True
                assert re.fullmatch(r"[0-9a-f]{32}", body["job_id"])
                assert body["poll_url"]
                j = _poll_until_settled(c, body["poll_url"])
            assert j["status"] == "done", j
            assert j["kind"] == "motion-batch"
            # Sequential story→portrait→square→landscape, one job.
            assert seen_formats == list(ALL_FORMATS)
            assert j["total"] == 4 and j["done"] == 4
            assert sorted(j["video_urls"]) == sorted(ALL_FORMATS)
            assert j["formats_failed"] == {}
            # Story keeps its suffix-free URL; other cuts carry ?format=.
            assert "format=" not in j["video_urls"]["story"]
            assert "format=portrait" in j["video_urls"]["portrait"]
            # The legacy single field stays populated (story cut).
            assert j["video_url"] == j["video_urls"]["story"]
            # Every produced cut streams from the persistent motion-file route.
            for fmt in ALL_FORMATS:
                f = c.get(j["video_urls"][fmt])
                assert f.status_code == 200, fmt
                assert "video/mp4" in (f.headers.get("Content-Type") or "")
        # The files land under the run's motion dir with per-format names.
        mdir = wm.RUNS_DIR / "r1" / "motion"
        assert (mdir / "swim-1.mp4").exists()
        for fmt in ("portrait", "square", "landscape"):
            assert (mdir / f"swim-1_{fmt}.mp4").exists()

    def test_each_cut_gets_its_own_render_slot_with_queue_timeout(self, app_env, monkeypatch):
        app, wm, _ = app_env
        import mediahub.visual.motion as motion

        slots = []

        @contextlib.contextmanager
        def _fake_slot(kind, label="", *, timeout):
            slots.append((kind, label, timeout))
            yield

        monkeypatch.setattr(wm, "_render_slot", _fake_slot)
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(motion, "render_story_card", _fake_render_ok):
                resp = c.post("/api/runs/r1/card/swim-1/motion-batch-job")
                j = _poll_until_settled(c, resp.get_json()["poll_url"])
        assert j["status"] == "done"
        # One acquire/release per cut — the gate is never held across the
        # batch — and each waits its turn with the queue timeout.
        assert slots == [
            ("motion", f"swim-1:{fmt}", wm._RENDER_QUEUE_TIMEOUT) for fmt in ALL_FORMATS
        ]

    def test_partial_failure_is_honest_not_fatal(self, app_env):
        app, wm, _ = app_env
        import mediahub.visual.motion as motion

        def _fake(card, brand_kit, out_path, **kw):
            if kw.get("format_name") == "square":
                raise RuntimeError("square renderer exploded")
            return _fake_render_ok(card, brand_kit, out_path, **kw)

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(motion, "render_story_card", _fake):
                resp = c.post("/api/runs/r1/card/swim-1/motion-batch-job")
                j = _poll_until_settled(c, resp.get_json()["poll_url"])
        assert j["status"] == "done"  # partial success is success
        assert sorted(j["video_urls"]) == ["landscape", "portrait", "story"]
        assert "square renderer exploded" in (j["formats_failed"].get("square") or "")

    def test_nothing_rendered_is_an_error_with_the_real_reason(self, app_env):
        app, wm, _ = app_env
        import mediahub.visual.motion as motion

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(
                motion, "render_story_card", side_effect=RuntimeError("boom")
            ):
                resp = c.post("/api/runs/r1/card/swim-1/motion-batch-job")
                assert resp.status_code == 202
                j = _poll_until_settled(c, resp.get_json()["poll_url"])
        assert j["status"] == "error"
        assert j["error"]

    def test_foreign_org_cannot_start_or_poll(self, app_env):
        app, wm, _ = app_env
        import mediahub.visual.motion as motion

        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(motion, "render_story_card", _fake_render_ok):
                resp = c.post("/api/runs/r1/card/swim-1/motion-batch-job")
                poll_url = resp.get_json()["poll_url"]
                _poll_until_settled(c, poll_url)
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "beta"})
            # Fail-fast tenant gate: the enqueue itself 404s…
            assert c.post("/api/runs/r1/card/swim-1/motion-batch-job").status_code == 404
            # …and the other org's finished job is invisible.
            assert c.get(poll_url).status_code == 404

    def test_unknown_card_is_404_before_any_job(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.post("/api/runs/r1/card/nope/motion-batch-job")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Source-level: the client wiring (JS inside the shared template block)
# ---------------------------------------------------------------------------

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


def _fn(name: str) -> str:
    """The source slice of one top-level JS function (brace-matched)."""
    m = re.search(rf"function {re.escape(name)}\([^)]*\) \{{", _SRC)
    assert m, f"function {name} not found"
    i = m.end() - 1
    depth = 0
    for j in range(i, len(_SRC)):
        if _SRC[j] == "{":
            depth += 1
        elif _SRC[j] == "}":
            depth -= 1
            if depth == 0:
                return _SRC[m.start() : j + 1]
    raise AssertionError(f"unbalanced braces in {name}")


def test_motion_batch_kind_is_in_the_job_status_allowlist():
    assert '"motion-batch",' in _SRC


def test_all_4_formats_button_sits_next_to_the_chips():
    body = _fn("mhRenderMotion")
    assert "_motionFmtChips(motionUrl, cardId, fmt)" in body
    assert "generateMotionBatch(this, " in body
    assert "All 4 formats" in body


def test_batch_client_follows_the_shared_job_idiom():
    body = _fn("generateMotionBatch")
    # JS-4: the panel is claimed synchronously before the 202 round-trip.
    assert "panel.dataset.mhWatching = '1';" in body
    # D-13: the job is remembered per (kind, url) and resumed, not restarted.
    assert "mhJobRemember('motion-batch', motionUrl" in body
    assert "mhJobRecall('motion-batch', motionUrl)" in body
    assert "j.status === 'running'" in body
    assert "'-batch-job'" in body


def test_batch_watch_narrates_per_cut_progress_and_clears_records():
    body = _fn("_mhMotionBatchWatch")
    # Per-cut progress label + real progress floor from total/done/current.
    assert "ctx.prog.setPhase(" in body and "j.total" in body
    assert "ctx.prog.setProgress(" in body
    # done + error/timeout terminal paths clear the stored record.
    assert body.count("mhJobForget('motion-batch',") >= 2
    # The renderer-busy recall idiom (CON-6) rides along.
    assert "j.error === 'renderer_busy'" in body
    assert "rec.poll_url !== pollUrl" in body


def test_resume_on_load_covers_the_batch_kind():
    body = _fn("mhResumeMotionJobs")
    assert "'motion', 'motion-batch'" in body
    assert "mhRenderMotion(panel, motionUrl" in body
    assert "mhRenderMotionBatch(panel, motionUrl" in body


def test_finished_batch_panel_is_honest_about_failed_cuts():
    body = _fn("mhRenderMotionBatch")
    assert "These cuts failed to render:" in body
    # Reasons are escaped before touching innerHTML.
    assert "window.safeText(reason)" in body
