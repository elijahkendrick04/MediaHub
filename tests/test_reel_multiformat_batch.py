"""R1.15 — multi-format batch reel render.

One request renders + caches all four cuts (story / portrait / square /
landscape) in a single pass: ``visual/motion.py``'s
``render_meet_reel_all_formats`` plus the ``/api/runs/<run_id>/reel-batch``
web route.

Two layers, mirroring the rest of the motion suite:

* **Motion layer** — pure-Python orchestration of the batch (ordering,
  per-cut error capture, props-assembled-once, cache-key reuse with the
  single route, the batch manifest sidecar, the ffmpeg story-only gap). No
  Node: the heavy render is mocked at ``_render_reel_one_format`` /
  ``_run_remotion``.
* **Route layer** — the async ``/reel-batch`` job + the shared status route's
  ``video_urls`` / ``formats_failed`` passthrough, with
  ``render_meet_reel_all_formats`` mocked so no real render runs.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.visual import motion

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _card(swim_id: str = "swim-1") -> dict:
    return {
        "id": swim_id,
        "swim_id": swim_id,
        "achievement": {
            "swim_id": swim_id,
            "swimmer_name": "Eira Hughes",
            "event_name": "100m Freestyle LC",
            "result_time": "00:59.80",
            "type": "NEW PB",
        },
        "meet_name": "Test Open",
    }


def _brand() -> BrandKit:
    return BrandKit(
        profile_id="club",
        display_name="Batch SC",
        primary_colour="#0A2540",
        secondary_colour="#FF6F61",
        accent_colour="#FFFFFF",
        short_name="BSC",
    )


# ---------------------------------------------------------------------------
# reel_format_out_path — the cut-naming the reel-file route already expects.
# ---------------------------------------------------------------------------


def test_reel_format_out_path_naming(tmp_path):
    out = tmp_path / "motion"
    # Story keeps the bare stem; other cuts are suffixed.
    assert motion.reel_format_out_path(out, "story", base_name="reel_3").name == "reel_3.mp4"
    assert (
        motion.reel_format_out_path(out, "portrait", base_name="reel_3").name
        == "reel_3_portrait.mp4"
    )
    assert (
        motion.reel_format_out_path(out, "landscape", base_name="reel_3").name
        == "reel_3_landscape.mp4"
    )
    # Default stem.
    assert motion.reel_format_out_path(out, "square").name == "reel_square.mp4"
    assert motion.reel_format_out_path(out, "story").parent == out


def test_reel_format_out_path_rejects_unknown(tmp_path):
    with pytest.raises(ValueError):
        motion.reel_format_out_path(tmp_path, "imax")


# ---------------------------------------------------------------------------
# Orchestration — _render_reel_one_format mocked so the per-cut render is a
# cheap file write; we test the loop, ordering, and per-cut error handling.
# ---------------------------------------------------------------------------


def _fake_one_format(*, fail_for=frozenset(), unavailable_for=frozenset()):
    """A stand-in for ``_render_reel_one_format`` that just writes the cut
    (or raises for the requested formats)."""

    def _impl(*, out_path, format_name, **_kw):
        if format_name in unavailable_for:
            raise motion.ReelEngineUnavailable(f"engine can't do {format_name}")
        if format_name in fail_for:
            raise RuntimeError(f"render exploded for {format_name}")
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"0" * 2048)
        return p

    return _impl


def test_all_formats_renders_every_cut(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(motion, "_render_reel_one_format", _fake_one_format())
    out_dir = tmp_path / "motion"

    result = motion.render_meet_reel_all_formats(
        [_card("a"), _card("b")], _brand(), out_dir, meet_name="Test Open", base_name="reel_3"
    )

    # Every cut produced, in canonical MOTION_FORMATS order, no errors.
    assert list(result["rendered"]) == list(motion.MOTION_FORMATS)
    assert result["errors"] == {}
    assert result["engine"] == "remotion"
    for fmt, path in result["rendered"].items():
        assert Path(path).exists(), fmt
        expected = motion.reel_format_out_path(out_dir, fmt, base_name="reel_3")
        assert Path(path) == expected


def test_partial_failure_is_captured_not_fatal(tmp_path, monkeypatch):
    """A genuine render failure on one cut records that cut in ``errors`` and
    still ships the cuts that succeeded — a batch must not be all-or-nothing."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(motion, "_render_reel_one_format", _fake_one_format(fail_for={"square"}))

    result = motion.render_meet_reel_all_formats(
        [_card()], _brand(), tmp_path / "motion", base_name="reel_3"
    )

    assert set(result["rendered"]) == {"story", "portrait", "landscape"}
    assert "square" in result["errors"]
    assert "render exploded for square" in result["errors"]["square"]


def test_engine_unavailable_recorded_per_format(tmp_path, monkeypatch):
    """A cut the engine cannot produce is an honest per-cut note, never a fake
    output and never an aborted batch."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        motion,
        "_render_reel_one_format",
        _fake_one_format(unavailable_for={"portrait", "square", "landscape"}),
    )

    result = motion.render_meet_reel_all_formats(
        [_card()], _brand(), tmp_path / "motion", base_name="reel_3"
    )

    assert set(result["rendered"]) == {"story"}
    assert set(result["errors"]) == {"portrait", "square", "landscape"}
    for reason in result["errors"].values():
        assert "engine can't do" in reason


def test_formats_subset_and_ordering(tmp_path, monkeypatch):
    """A caller may request a subset; output always follows MOTION_FORMATS
    order regardless of request order, de-duplicated."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    attempted: list[str] = []

    def _spy(*, out_path, format_name, **_kw):
        attempted.append(format_name)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"0" * 2048)
        return Path(out_path)

    monkeypatch.setattr(motion, "_render_reel_one_format", _spy)

    result = motion.render_meet_reel_all_formats(
        [_card()],
        _brand(),
        tmp_path / "motion",
        formats=["landscape", "story", "landscape"],
        base_name="reel_3",
    )
    assert list(result["rendered"]) == ["story", "landscape"]
    assert attempted == ["story", "landscape"]


def test_unknown_format_raises_before_any_render(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    called = []
    monkeypatch.setattr(
        motion,
        "_render_reel_one_format",
        lambda **kw: called.append(1),
    )
    with pytest.raises(ValueError):
        motion.render_meet_reel_all_formats(
            [_card()], _brand(), tmp_path / "motion", formats=["story", "imax"]
        )
    assert called == [], "no cut should render when a requested format is invalid"


def test_batch_manifest_sidecar_written(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        motion, "_render_reel_one_format", _fake_one_format(unavailable_for={"landscape"})
    )
    out_dir = tmp_path / "motion"

    motion.render_meet_reel_all_formats(
        [_card()], _brand(), out_dir, meet_name="Test Open", base_name="reel_3"
    )

    sidecar = out_dir / "reel_3.batch.json"
    assert sidecar.exists()
    man = json.loads(sidecar.read_text())
    assert man["kind"] == "reel-batch"
    assert man["engine"] == "remotion"
    assert man["rendered"] == ["story", "portrait", "square"]
    assert man["formats"]["story"]["status"] == "ok"
    assert man["formats"]["story"]["file"] == "reel_3.mp4"
    assert man["formats"]["story"]["size"] == [1080, 1920]
    assert man["formats"]["landscape"]["status"] == "unavailable"
    assert "reason" in man["formats"]["landscape"]


def test_props_assembled_once_for_the_whole_batch(tmp_path, monkeypatch):
    """The expensive, format-independent shaping (photo embed, role resolve)
    must happen once per card for the whole batch — not once per (card,
    format). Proven by counting ``_card_to_props`` calls."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    real = motion._card_to_props
    calls: list[int] = []

    def _counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(motion, "_card_to_props", _counting)
    monkeypatch.setattr(motion, "_render_reel_one_format", _fake_one_format())

    motion.render_meet_reel_all_formats(
        [_card("a"), _card("b")], _brand(), tmp_path / "motion", base_name="reel_3"
    )
    # 2 cards, 4 formats: assembled twice (once per card), not 8 times.
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Cache-key parity — the story cut produced by the batch must be byte-identical
# in its cache key to the single route's story cut, so a reel already rendered
# the old way is a cache HIT and only the missing cuts cost a render.
# ---------------------------------------------------------------------------


def test_story_cut_reuses_single_route_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # No audio configured → silent path → cache keys match the pre-audio era.
    monkeypatch.delenv("MEDIAHUB_VOICEOVER", raising=False)
    monkeypatch.delenv("MEDIAHUB_REEL_MUSIC_DIR", raising=False)

    sizes_rendered: list[tuple] = []

    def _fake_run_remotion(*, composition_id, props, out_path, duration_sec=None, size=None, **_kw):
        sizes_rendered.append(tuple(size) if size else None)
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096)
        return p

    monkeypatch.setattr(motion, "_run_remotion", _fake_run_remotion)
    # Keep the finishing pass (poster/audio probe) out of the way.
    monkeypatch.setattr(motion, "_finish_cached_video", lambda *a, **k: {"status": "off"})

    card, brand = _card(), _brand()

    # 1) Single route renders just the story cut.
    motion.render_meet_reel(
        [card], brand, tmp_path / "motion" / "reel_3.mp4", meet_name="Test Open"
    )
    assert sizes_rendered == [(1080, 1920)]

    # 2) Batch renders every cut — story is a cache hit, so _run_remotion is
    #    only invoked for the three remaining sizes.
    result = motion.render_meet_reel_all_formats(
        [card], brand, tmp_path / "motion", meet_name="Test Open", base_name="reel_3"
    )
    assert set(result["rendered"]) == set(motion.MOTION_FORMATS)
    # Story (1080×1920) rendered exactly once across both calls.
    assert sizes_rendered.count((1080, 1920)) == 1
    assert (1080, 1350) in sizes_rendered
    assert (1080, 1080) in sizes_rendered
    assert (1920, 1080) in sizes_rendered


# ---------------------------------------------------------------------------
# ffmpeg fallback engine — every cut (R1.16 made the free fallback multi-format,
# so the batch produces story + portrait + square + landscape, not story only).
# ---------------------------------------------------------------------------


def test_ffmpeg_engine_renders_every_cut(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_REEL_ENGINE", "ffmpeg")

    from mediahub.visual import reel_ffmpeg

    dispatched: list[str] = []

    def _fake_ffmpeg_reel(cards_props, brand_dict, brand_kit, out_path, **kw):
        dispatched.append(kw.get("format_name", "story"))
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"0" * 2048)
        return p

    monkeypatch.setattr(reel_ffmpeg, "render_meet_reel_from_props", _fake_ffmpeg_reel)

    result = motion.render_meet_reel_all_formats(
        [_card()], _brand(), tmp_path / "motion", base_name="reel_3"
    )
    # R1.16 — the free engine renders every cut, so the batch produces all
    # four and records no per-cut errors (the pre-R1.16 story-only restriction
    # is gone). Each cut is dispatched to the ffmpeg engine at its own geometry.
    assert result["engine"] == "ffmpeg"
    assert set(result["rendered"]) == set(motion.MOTION_FORMATS)
    assert result["errors"] == {}
    # …and each cut was dispatched to the ffmpeg engine at its own geometry.
    assert set(dispatched) == set(motion.MOTION_FORMATS)


# ===========================================================================
# Route layer — /api/runs/<run_id>/reel-batch + the status passthrough.
# ===========================================================================


@pytest.fixture
def app_env(app, web_module, tmp_path):
    wm = web_module

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    save_profile(ClubProfile(profile_id="beta", display_name="Beta SC"))

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
    (wm.RUNS_DIR / "r1.json").write_text(json.dumps(run), encoding="utf-8")
    return app, wm, tmp_path


def _poll_until_settled(client, poll_url, tries=60, delay=0.2):
    j = {}
    for _ in range(tries):
        j = client.get(poll_url).get_json()
        if j.get("status") != "running":
            return j
        time.sleep(delay)
    return j


def _fake_all_formats_writing(rendered_formats, errors=None, captured=None):
    """Return a ``render_meet_reel_all_formats`` stand-in that writes the named
    cuts into ``out_dir`` (so the reel-file route can stream them) and reports
    ``errors`` for the rest. ``captured``, when given, records the kwargs the
    route passed (sponsor / next_meet / rhythm / dub_language / base_name)."""
    errors = errors or {}

    def _impl(
        cards,
        brand_kit,
        out_dir,
        *,
        meet_name="",
        briefs=None,
        base_name="reel",
        duration_sec=None,
        formats=None,
        render_slot=None,
        sponsor="",
        next_meet="",
        rhythm=None,
        dub_language="",
        reel_stat_config=None,
        alpha_profile="",
    ):
        if captured is not None:
            captured.update(
                {
                    "base_name": base_name,
                    "sponsor": sponsor,
                    "next_meet": next_meet,
                    "rhythm": rhythm,
                    "dub_language": dub_language,
                    "reel_stat_config": reel_stat_config,
                }
            )
        rendered: dict[str, Path] = {}
        for fmt in motion.MOTION_FORMATS:
            if fmt in rendered_formats:
                p = motion.reel_format_out_path(out_dir, fmt, base_name=base_name)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"0" * 2048)
                rendered[fmt] = p
        return {"engine": "remotion", "rendered": rendered, "errors": dict(errors)}

    return _impl


class TestReelBatchRoute:
    def test_batch_job_renders_and_every_cut_streams(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(
                motion,
                "render_meet_reel_all_formats",
                _fake_all_formats_writing(set(motion.MOTION_FORMATS)),
            ):
                resp = c.post("/api/runs/r1/reel-batch")
                assert resp.status_code == 202
                body = resp.get_json()
                assert body["ok"] and body["poll_url"]
                j = _poll_until_settled(c, body["poll_url"])

            assert j["status"] == "done", j
            # Every cut has a streamable URL.
            assert set(j["video_urls"]) == set(motion.MOTION_FORMATS)
            assert j["formats_failed"] == {}
            # Legacy single field still points at the story cut.
            assert j["video_url"] == j["video_urls"]["story"]
            for fmt, url in j["video_urls"].items():
                f = c.get(url)
                assert f.status_code == 200, (fmt, url)
                assert "video/mp4" in (f.headers.get("Content-Type") or "")

    def test_batch_partial_reports_failed_formats(self, app_env):
        app, wm, _ = app_env
        errs = {
            "portrait": "needs Remotion",
            "square": "needs Remotion",
            "landscape": "needs Remotion",
        }
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(
                motion,
                "render_meet_reel_all_formats",
                _fake_all_formats_writing({"story"}, errors=errs),
            ):
                resp = c.post("/api/runs/r1/reel-batch")
                j = _poll_until_settled(c, resp.get_json()["poll_url"])

        assert j["status"] == "done", j
        assert set(j["video_urls"]) == {"story"}
        assert set(j["formats_failed"]) == {"portrait", "square", "landscape"}

    def test_batch_total_failure_is_an_error_not_a_silent_done(self, app_env):
        """If not a single cut renders, the job is an error — never a 'done'
        with no video."""
        app, wm, _ = app_env
        errs = {f: "engine down" for f in motion.MOTION_FORMATS}
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(
                motion,
                "render_meet_reel_all_formats",
                _fake_all_formats_writing(set(), errors=errs),
            ):
                resp = c.post("/api/runs/r1/reel-batch")
                j = _poll_until_settled(c, resp.get_json()["poll_url"])
        assert j["status"] == "error"
        assert j["error"]

    def test_batch_render_exception_reports_error_not_silence(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(
                motion,
                "render_meet_reel_all_formats",
                side_effect=RuntimeError("boom: batch exploded"),
            ):
                resp = c.post("/api/runs/r1/reel-batch")
                assert resp.status_code == 202
                j = _poll_until_settled(c, resp.get_json()["poll_url"])
        assert j["status"] == "error"
        assert j["error"]

    def test_batch_foreign_org_cannot_see_job_or_start_one(self, app_env):
        app, wm, _ = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(
                motion,
                "render_meet_reel_all_formats",
                side_effect=RuntimeError("x"),
            ):
                resp = c.post("/api/runs/r1/reel-batch")
                poll = resp.get_json()["poll_url"]
                _poll_until_settled(c, poll)

        with app.test_client() as other:
            other.post("/api/organisation/active", data={"profile_id": "beta"})
            assert other.get(poll).status_code == 404
            assert other.post("/api/runs/r1/reel-batch").status_code == 404

    def test_batch_passes_sponsor_rhythm_next_meet_and_dub(self, app_env):
        """The batch worker forwards the same R1.30 sponsor / next-meet, R1.12
        rhythm and 1.24 dub inputs the single route resolves, and lang-suffixes
        its filenames so the reel-file route (given the same lang) finds them.
        Without these the batch cuts lost the sponsor outro / rhythm / dub and
        the story cut's cache key diverged from the single route."""
        app, wm, _ = app_env
        from mediahub.web.club_profile import ClubProfile, save_profile

        save_profile(
            ClubProfile(
                profile_id="alpha",
                display_name="Alpha SC",
                sponsor_name="AquaCorp",
                notes="Next meet: County Champs — 12 Jul",
            )
        )
        captured: dict = {}
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(
                motion,
                "render_meet_reel_all_formats",
                _fake_all_formats_writing(set(motion.MOTION_FORMATS), captured=captured),
            ):
                resp = c.post("/api/runs/r1/reel-batch?lang=es&cover=2.5")
                assert resp.status_code == 202
                j = _poll_until_settled(c, resp.get_json()["poll_url"])

            assert j["status"] == "done", j
            assert captured["sponsor"] == "AquaCorp"
            assert captured["next_meet"].startswith("County Champs")
            assert captured["dub_language"] == "es"
            assert captured["rhythm"] is not None  # cover=2.5 customised the skeleton
            # dubbed batch filenames carry the language suffix on the stem
            assert captured["base_name"] == "reel_3_es"
            # …and the minted file URLs carry lang so the cuts actually stream
            for fmt, url in j["video_urls"].items():
                assert "lang=es" in url, (fmt, url)
                f = c.get(url)
                assert f.status_code == 200, (fmt, url)

    def test_single_reel_status_unaffected_by_batch_fields(self, app_env):
        """The shared status route still serves a single-format ``reel`` job;
        the new passthrough fields default to empty for it."""
        app, wm, _ = app_env
        out_dir = wm.RUNS_DIR / "r1" / "motion"
        out_dir.mkdir(parents=True, exist_ok=True)
        mp4 = out_dir / "reel_3.mp4"
        mp4.write_bytes(b"0" * 2048)
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            with mock.patch.object(motion, "render_meet_reel", return_value=mp4):
                resp = c.post("/api/runs/r1/reel-job")
                j = _poll_until_settled(c, resp.get_json()["poll_url"])
        assert j["status"] == "done", j
        assert j["video_url"]
        assert j["video_urls"] == {}
        assert j["formats_failed"] == {}
