"""Tests for parallel reel composition (roadmap R1.28).

Four layers, the first three of which need neither Node, Remotion, nor an
FFmpeg binary:

  - pure frame-partition + FFmpeg-builder maths (the correctness backbone:
    the split must tile every frame exactly once, which is what makes the
    concatenation frame-identical to the serial render);
  - env gating + worker sizing;
  - orchestration with the subprocess seams mocked (manifest shape, fallback
    behaviour, the motion.py seam, cache-key invariance);
  - an opt-in real end-to-end render proving the Node + FFmpeg pipeline, gated
    on availability AND ``MEDIAHUB_RUN_REEL_PARALLEL_E2E=1`` so the default
    suite stays fast and deterministic.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.visual import motion, reel_parallel

# A minimal valid-looking MP4 header so size/poster gates in motion.py pass.
_FAKE_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 8192


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _props(name="Ada Lovelace", event="100m Freestyle LC", result="00:58.31") -> dict:
    first, surname = name.split()[0], name.split()[-1]
    return {
        "athleteFullName": name,
        "athleteFirstName": first,
        "athleteSurname": surname,
        "eventName": event,
        "resultValue": result,
        "achievementLabel": "NEW PB",
        "meetName": "Welsh Winter Nationals 2026",
        "place": "1",
        "variationSeed": 3,
    }


def _brand_dict() -> dict:
    return {
        "primary": "#0A2540",
        "secondary": "#101418",
        "accent": "#D4FF3A",
        "displayName": "City of Swansea Aquatics",
        "shortName": "COSA",
        "logoDataUri": "",
    }


def _brand_kit() -> BrandKit:
    return BrandKit(
        profile_id="parallel-test",
        display_name="City of Swansea Aquatics",
        short_name="COSA",
        primary_colour="#0A2540",
        secondary_colour="#101418",
        accent_colour="#D4FF3A",
    )


def _reel_cards() -> list[dict]:
    return [
        {"id": "c1", "achievement": {"swimmer_name": "Ada Lovelace",
                                     "event_name": "100m Free LC",
                                     "result_time": "00:58.31", "type": "NEW PB"}},
        {"id": "c2", "achievement": {"swimmer_name": "Grace Hopper",
                                     "event_name": "200m Fly LC",
                                     "result_time": "02:14.90", "type": "GOLD"}},
    ]


# ---------------------------------------------------------------------------
# plan_segments — the frame-purity backbone
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "total,n",
    [(450, 4), (210, 4), (690, 4), (100, 3), (61, 2), (63, 4), (7, 4), (1, 1), (1, 4), (450, 1)],
)
def test_plan_segments_tiles_every_frame_exactly_once(total, n):
    """The split must cover [0, total) contiguously with no gaps/overlaps —
    this invariant is exactly what makes concat == the serial render."""
    ranges = reel_parallel.plan_segments(total, n)
    flat: list[int] = []
    for start, end in ranges:
        assert end >= start  # inclusive, non-empty
        flat.extend(range(start, end + 1))
    assert flat == list(range(total)), (total, n, ranges)


@pytest.mark.parametrize("total,n", [(450, 4), (210, 4), (100, 3), (63, 4), (7, 4)])
def test_plan_segments_is_balanced_and_capped(total, n):
    ranges = reel_parallel.plan_segments(total, n)
    sizes = [end - start + 1 for start, end in ranges]
    assert max(sizes) - min(sizes) <= 1  # evenly spread
    assert sum(sizes) == total
    assert len(ranges) == min(n, total)  # never more segments than frames


def test_plan_segments_single_segment_when_n_is_one():
    assert reel_parallel.plan_segments(450, 1) == [(0, 449)]


def test_plan_segments_rejects_empty_timeline():
    with pytest.raises(ValueError):
        reel_parallel.plan_segments(0, 4)


# ---------------------------------------------------------------------------
# FFmpeg builders (pure)
# ---------------------------------------------------------------------------


def test_concat_list_text_one_line_per_segment_in_order():
    paths = [Path("/cache/seg00.mp4"), Path("/cache/seg01.mp4"), Path("/cache/seg02.mp4")]
    text = reel_parallel.concat_list_text(paths)
    lines = text.strip().splitlines()
    assert lines == [
        "file '/cache/seg00.mp4'",
        "file '/cache/seg01.mp4'",
        "file '/cache/seg02.mp4'",
    ]


def test_concat_list_text_escapes_single_quotes():
    text = reel_parallel.concat_list_text([Path("/weird/o'brien/seg0.mp4")])
    # concat-demuxer escaping: ' -> '\''
    assert text.strip() == "file '/weird/o'\\''brien/seg0.mp4'"


def test_concat_list_text_rejects_empty():
    with pytest.raises(ValueError):
        reel_parallel.concat_list_text([])


def test_concat_args_are_lossless_streamcopy():
    args = reel_parallel.concat_args(Path("/t/list.txt"), Path("/t/out.mp4"))
    assert args[:6] == ["-f", "concat", "-safe", "0", "-i", "/t/list.txt"]
    assert "-c" in args and args[args.index("-c") + 1] == "copy"  # no re-encode
    assert "+faststart" in args
    assert args[-1] == "/t/out.mp4"


# ---------------------------------------------------------------------------
# Gating + sizing (env-driven)
# ---------------------------------------------------------------------------


def test_parallel_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_PARALLEL", raising=False)
    assert reel_parallel.parallel_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on", "On"])
def test_parallel_enabled_truthy_values(monkeypatch, val):
    monkeypatch.setenv("MEDIAHUB_REEL_PARALLEL", val)
    assert reel_parallel.parallel_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off", "", "banana"])
def test_parallel_disabled_falsey_values(monkeypatch, val):
    monkeypatch.setenv("MEDIAHUB_REEL_PARALLEL", val)
    assert reel_parallel.parallel_enabled() is False


def test_worker_count_env_override_caps_at_frames(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_REEL_PARALLEL_WORKERS", "8")
    assert reel_parallel.worker_count(450) == 8
    assert reel_parallel.worker_count(3) == 3  # never more workers than frames


def test_worker_count_default_caps_at_max(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_PARALLEL_WORKERS", raising=False)
    monkeypatch.setattr(reel_parallel, "_cpu_count", lambda: 32)
    assert reel_parallel.worker_count(450) == reel_parallel.DEFAULT_MAX_WORKERS


def test_worker_count_ignores_garbage_env(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_REEL_PARALLEL_WORKERS", "not-a-number")
    monkeypatch.setattr(reel_parallel, "_cpu_count", lambda: 2)
    assert reel_parallel.worker_count(450) == 2


def test_per_segment_concurrency_shares_cores(monkeypatch):
    monkeypatch.setattr(reel_parallel, "_cpu_count", lambda: 8)
    assert reel_parallel.per_segment_concurrency(4) == 2
    assert reel_parallel.per_segment_concurrency(8) == 1
    assert reel_parallel.per_segment_concurrency(16) == 1  # never below one tab


# ---------------------------------------------------------------------------
# Availability — honest gating
# ---------------------------------------------------------------------------


def test_available_requires_all_three(monkeypatch):
    monkeypatch.setattr(reel_parallel, "node_available", lambda: True)
    monkeypatch.setattr(reel_parallel, "remotion_segments_installed", lambda: True)
    monkeypatch.setattr(reel_parallel, "ffmpeg_exe", lambda: "/usr/bin/ffmpeg")
    assert reel_parallel.available() is True

    monkeypatch.setattr(reel_parallel, "ffmpeg_exe", lambda: None)
    assert reel_parallel.available() is False  # no compositor

    monkeypatch.setattr(reel_parallel, "ffmpeg_exe", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(reel_parallel, "node_available", lambda: False)
    assert reel_parallel.available() is False  # no node


def test_render_segments_script_is_shipped():
    assert reel_parallel.RENDER_SEGMENTS_SCRIPT.exists()
    assert reel_parallel.RENDER_SEGMENTS_SCRIPT.name == "render_segments.js"


# ---------------------------------------------------------------------------
# try_render_reel_parallel — honest fallback (returns None ⇒ caller goes serial)
# ---------------------------------------------------------------------------


def _common(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))


def test_try_returns_none_when_disabled(monkeypatch, tmp_path):
    _common(monkeypatch, tmp_path)
    monkeypatch.delenv("MEDIAHUB_REEL_PARALLEL", raising=False)
    # Even if it were available, disabled short-circuits before any work.
    monkeypatch.setattr(reel_parallel, "available", lambda: True)
    called = {"render": False}
    monkeypatch.setattr(
        reel_parallel, "render_reel_parallel",
        lambda **k: called.__setitem__("render", True),
    )
    out = reel_parallel.try_render_reel_parallel(
        composition_id="MeetReel", props={"cards": []}, out_path=tmp_path / "r.mp4",
        duration_sec=15.0, size=(1080, 1920),
    )
    assert out is None
    assert called["render"] is False  # never even attempted


def test_try_returns_none_when_unavailable(monkeypatch, tmp_path):
    _common(monkeypatch, tmp_path)
    monkeypatch.setenv("MEDIAHUB_REEL_PARALLEL", "1")
    monkeypatch.setattr(reel_parallel, "available", lambda: False)
    out = reel_parallel.try_render_reel_parallel(
        composition_id="MeetReel", props={"cards": []}, out_path=tmp_path / "r.mp4",
        duration_sec=15.0, size=(1080, 1920),
    )
    assert out is None


def test_try_returns_none_on_unavailable_split(monkeypatch, tmp_path):
    """A sub-threshold reel raises ReelParallelUnavailable internally and
    degrades to serial (None) rather than erroring."""
    _common(monkeypatch, tmp_path)
    monkeypatch.setenv("MEDIAHUB_REEL_PARALLEL", "1")
    monkeypatch.setattr(reel_parallel, "available", lambda: True)
    # 1s @ 30fps = 30 frames, below MIN_FRAMES_TO_SPLIT (60).
    out = reel_parallel.try_render_reel_parallel(
        composition_id="MeetReel", props={"cards": []}, out_path=tmp_path / "r.mp4",
        duration_sec=1.0, size=(1080, 1920),
    )
    assert out is None


def test_try_returns_none_on_render_failure(monkeypatch, tmp_path):
    _common(monkeypatch, tmp_path)
    monkeypatch.setenv("MEDIAHUB_REEL_PARALLEL", "1")
    monkeypatch.setattr(reel_parallel, "available", lambda: True)

    def boom(**kwargs):
        raise RuntimeError("node exploded mid-render")

    monkeypatch.setattr(reel_parallel, "render_reel_parallel", boom)
    out = reel_parallel.try_render_reel_parallel(
        composition_id="MeetReel", props={"cards": []}, out_path=tmp_path / "r.mp4",
        duration_sec=15.0, size=(1080, 1920),
    )
    assert out is None  # any failure ⇒ serial, never a hard error


# ---------------------------------------------------------------------------
# render_reel_parallel orchestration (subprocess seams mocked)
# ---------------------------------------------------------------------------


def _mock_pipeline(monkeypatch):
    """Mock the node + ffmpeg subprocess seams with file-producing fakes that
    exercise the real manifest/plan/concat/move orchestration. Returns a dict
    capturing what the node seam received."""
    captured: dict = {}

    def fake_node(*, composition_id, props_path, manifest_path, duration_sec,
                  size, concurrency, timeout, fps=reel_parallel.REEL_FPS):
        manifest = json.loads(Path(manifest_path).read_text())
        captured["manifest"] = manifest
        captured["composition_id"] = composition_id
        captured["size"] = size
        captured["concurrency"] = concurrency
        captured["fps"] = fps
        captured["props"] = json.loads(Path(props_path).read_text())
        for seg in manifest["segments"]:
            Path(seg["output"]).write_bytes(_FAKE_MP4)

    def fake_concat(list_file, out_path, *, timeout):
        captured["concat_list"] = Path(list_file).read_text()
        Path(out_path).write_bytes(_FAKE_MP4)

    monkeypatch.setattr(reel_parallel, "_run_node_segments", fake_node)
    monkeypatch.setattr(reel_parallel, "_run_ffmpeg_concat", fake_concat)
    monkeypatch.setattr(reel_parallel, "ffmpeg_exe", lambda: "/usr/bin/ffmpeg")
    # Duration probe returns the expected value so the correctness gate passes.
    monkeypatch.setattr(reel_parallel, "media_duration_seconds", lambda p: 15.0)
    return captured


def test_render_reel_parallel_builds_manifest_and_composites(monkeypatch, tmp_path):
    _common(monkeypatch, tmp_path)
    monkeypatch.setattr(reel_parallel, "_cpu_count", lambda: 4)
    monkeypatch.delenv("MEDIAHUB_REEL_PARALLEL_WORKERS", raising=False)
    captured = _mock_pipeline(monkeypatch)

    out = tmp_path / "out.mp4"
    result = reel_parallel.render_reel_parallel(
        composition_id="MeetReel",
        props={"cards": [_props()], "brand": _brand_dict(), "meetName": "Test Meet"},
        out_path=out,
        duration_sec=15.0,
        size=(1080, 1920),
    )
    assert Path(result) == out and out.exists() and out.stat().st_size > 1024

    # Node got a contiguous manifest tiling all 450 frames (15s @ 30fps).
    segs = captured["manifest"]["segments"]
    assert len(segs) == 4  # 4 cpus
    assert segs[0]["start"] == 0
    assert segs[-1]["end"] == 449
    for a, b in zip(segs, segs[1:]):
        assert b["start"] == a["end"] + 1  # no gap, no overlap
    assert captured["composition_id"] == "MeetReel"
    assert captured["size"] == (1080, 1920)
    assert captured["fps"] == reel_parallel.REEL_FPS  # default rate threaded through
    # Concat list references every segment, in order.
    assert captured["concat_list"].count("file '") == 4


def test_render_reel_parallel_plans_at_selected_fps(monkeypatch, tmp_path):
    """A non-default fps re-plans the split at that rate (double the frames at
    60fps) and threads the selected fps down to the node segment renderer."""
    _common(monkeypatch, tmp_path)
    monkeypatch.setattr(reel_parallel, "_cpu_count", lambda: 4)
    monkeypatch.delenv("MEDIAHUB_REEL_PARALLEL_WORKERS", raising=False)
    captured = _mock_pipeline(monkeypatch)

    out = tmp_path / "out60.mp4"
    reel_parallel.render_reel_parallel(
        composition_id="MeetReel",
        props={"cards": [_props()], "brand": _brand_dict(), "meetName": "Test Meet"},
        out_path=out,
        duration_sec=15.0,
        size=(1080, 1920),
        fps=60,
    )
    segs = captured["manifest"]["segments"]
    # 15s @ 60fps ⇒ 900 frames tiled contiguously (vs 450 at 30fps).
    assert segs[0]["start"] == 0
    assert segs[-1]["end"] == 899
    assert captured["fps"] == 60


def test_run_node_segments_appends_fps_only_when_non_default(monkeypatch, tmp_path):
    captured: dict = {}

    class _Proc:
        returncode = 0
        stderr = ""

    def fake_run_capture(cmd, *, cwd=None, timeout=None):
        captured["cmd"] = list(cmd)
        return _Proc()

    monkeypatch.setattr("mediahub.visual.proc.run_capture", fake_run_capture)

    common = dict(
        composition_id="MeetReel",
        props_path=tmp_path / "p.json",
        manifest_path=tmp_path / "m.json",
        duration_sec=15.0,
        size=(1080, 1920),
        concurrency=1,
        timeout=600,
    )
    reel_parallel._run_node_segments(**common, fps=50)
    assert "--fps" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--fps") + 1] == "50"

    captured.clear()
    reel_parallel._run_node_segments(**common, fps=30)
    assert "--fps" not in captured["cmd"]  # default command byte-identical


def test_render_reel_parallel_rejects_subthreshold(monkeypatch, tmp_path):
    _common(monkeypatch, tmp_path)
    with pytest.raises(reel_parallel.ReelParallelUnavailable):
        reel_parallel.render_reel_parallel(
            composition_id="MeetReel", props={"cards": []}, out_path=tmp_path / "r.mp4",
            duration_sec=1.0, size=(1080, 1920),  # 30 frames < 60
        )


def test_render_reel_parallel_discards_wrong_duration(monkeypatch, tmp_path):
    """If the composited reel probes to the wrong length, the parallel result
    is discarded (raises) so the caller renders serially — no silent ship."""
    _common(monkeypatch, tmp_path)
    _mock_pipeline(monkeypatch)
    # Probe reports a wildly wrong duration ⇒ correctness gate must reject.
    monkeypatch.setattr(reel_parallel, "media_duration_seconds", lambda p: 3.0)
    with pytest.raises(RuntimeError, match="expected"):
        reel_parallel.render_reel_parallel(
            composition_id="MeetReel",
            props={"cards": [_props()], "brand": _brand_dict(), "meetName": "M"},
            out_path=tmp_path / "out.mp4", duration_sec=15.0, size=(1080, 1920),
        )


def test_render_reel_parallel_raises_when_segment_missing(monkeypatch, tmp_path):
    _common(monkeypatch, tmp_path)
    # Node seam writes nothing ⇒ missing-segment guard fires.
    monkeypatch.setattr(reel_parallel, "_run_node_segments", lambda **k: None)
    monkeypatch.setattr(reel_parallel, "ffmpeg_exe", lambda: "/usr/bin/ffmpeg")
    with pytest.raises(RuntimeError, match="missing"):
        reel_parallel.render_reel_parallel(
            composition_id="MeetReel",
            props={"cards": [_props()], "brand": _brand_dict(), "meetName": "M"},
            out_path=tmp_path / "out.mp4", duration_sec=15.0, size=(1080, 1920),
        )


# ---------------------------------------------------------------------------
# motion.py seam — parallel result is used; serial is the default + fallback
# ---------------------------------------------------------------------------


def test_motion_helper_returns_none_when_disabled(monkeypatch, tmp_path):
    _common(monkeypatch, tmp_path)
    monkeypatch.delenv("MEDIAHUB_REEL_PARALLEL", raising=False)
    out = motion._render_reel_parallel_or_none(
        props={"cards": []}, cached=tmp_path / "c.mp4", duration_sec=15.0, size=(1080, 1920)
    )
    assert out is None


def test_render_meet_reel_uses_serial_when_parallel_off(monkeypatch, tmp_path):
    """Default behaviour is unchanged: parallel off ⇒ the serial _run_remotion
    renders into the same cache path, and the manifest records 'serial'."""
    _common(monkeypatch, tmp_path)
    monkeypatch.delenv("MEDIAHUB_REEL_PARALLEL", raising=False)

    calls: list[dict] = []

    def fake_remotion(**kwargs):
        Path(kwargs["out_path"]).write_bytes(_FAKE_MP4)
        calls.append(kwargs)
        return Path(kwargs["out_path"])

    monkeypatch.setattr(motion, "_run_remotion", fake_remotion)

    out = tmp_path / "reel.mp4"
    result = motion.render_meet_reel(
        _reel_cards(), _brand_kit(), out, meet_name="Test Meet"
    )
    assert Path(result).exists()
    assert len(calls) == 1  # serial render ran exactly once
    cached = calls[0]["out_path"]
    assert Path(cached).parent.name == "motion_cache"
    manifest = json.loads(Path(cached).with_suffix(".json").read_text())
    assert manifest["render_strategy"] == "serial"
    assert manifest["kind"] == "reel"


def test_render_meet_reel_uses_parallel_result_when_available(monkeypatch, tmp_path):
    """When the parallel helper produces the cache MP4, the serial render is
    skipped entirely and the manifest records 'parallel-segments'."""
    _common(monkeypatch, tmp_path)

    def fake_parallel(*, props, cached, duration_sec, size):
        Path(cached).write_bytes(_FAKE_MP4)
        return Path(cached)

    monkeypatch.setattr(motion, "_render_reel_parallel_or_none", fake_parallel)

    def forbidden(**kwargs):
        raise AssertionError("serial _run_remotion must not run when parallel succeeds")

    monkeypatch.setattr(motion, "_run_remotion", forbidden)

    out = tmp_path / "reel.mp4"
    result = motion.render_meet_reel(
        _reel_cards(), _brand_kit(), out, meet_name="Test Meet"
    )
    assert Path(result).exists()
    # Find the cache sidecar and confirm the strategy was recorded.
    cache_dir = tmp_path / "motion_cache"
    manifests = list(cache_dir.glob("*.json"))
    assert manifests, "expected a render manifest sidecar"
    manifest = json.loads(manifests[0].read_text())
    assert manifest["render_strategy"] == "parallel-segments"


def test_parallel_render_is_cache_key_invariant(monkeypatch, tmp_path):
    """The parallel path is invisible to the content cache: a reel rendered in
    parallel lands at the exact cache key a serial render would, so a later
    request (parallel off) is a clean cache hit with no re-render."""
    _common(monkeypatch, tmp_path)

    # First request: parallel produces the cache file.
    def fake_parallel(*, props, cached, duration_sec, size):
        Path(cached).write_bytes(_FAKE_MP4)
        return Path(cached)

    monkeypatch.setattr(motion, "_render_reel_parallel_or_none", fake_parallel)
    monkeypatch.setattr(
        motion, "_run_remotion",
        lambda **k: (_ for _ in ()).throw(AssertionError("should not serial-render")),
    )
    out1 = tmp_path / "reel1.mp4"
    motion.render_meet_reel(_reel_cards(), _brand_kit(), out1, meet_name="Test Meet")
    cache_files = list((tmp_path / "motion_cache").glob("*.mp4"))
    assert len(cache_files) == 1
    key = cache_files[0].stem

    # Second request, identical inputs, parallel now "off": must be a cache hit
    # (no parallel attempt, no serial render) at the SAME key.
    monkeypatch.setattr(
        motion, "_render_reel_parallel_or_none",
        lambda **k: (_ for _ in ()).throw(AssertionError("should not attempt parallel on hit")),
    )
    out2 = tmp_path / "reel2.mp4"
    motion.render_meet_reel(_reel_cards(), _brand_kit(), out2, meet_name="Test Meet")
    cache_files2 = list((tmp_path / "motion_cache").glob("*.mp4"))
    assert [p.stem for p in cache_files2] == [key]  # same single cache entry
    assert out2.exists()


# ---------------------------------------------------------------------------
# Opt-in real end-to-end render — Node + Remotion + FFmpeg required.
# Proves the actual pipeline produces a valid reel of the right length and
# that the parallel cut matches the serial cut's duration. Gated AND opt-in
# (heavy: two full reel renders) so the default suite stays fast.
# ---------------------------------------------------------------------------

_CAN_E2E = reel_parallel.available()
_RUN_E2E = os.environ.get("MEDIAHUB_RUN_REEL_PARALLEL_E2E", "").lower() in ("1", "true", "yes")


@pytest.mark.skipif(not _CAN_E2E, reason="needs node + remotion + ffmpeg")
@pytest.mark.skipif(not _RUN_E2E, reason="opt-in via MEDIAHUB_RUN_REEL_PARALLEL_E2E=1")
def test_e2e_parallel_reel_matches_serial_duration(tmp_path, monkeypatch):
    from mediahub.visual.reel_ffmpeg import media_duration_seconds

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cards = _reel_cards()
    duration = motion.reel_duration_for(len(cards))

    # Serial reel.
    monkeypatch.delenv("MEDIAHUB_REEL_PARALLEL", raising=False)
    serial_out = tmp_path / "serial.mp4"
    motion.render_meet_reel(cards, _brand_kit(), serial_out, meet_name="E2E Meet")
    assert serial_out.exists() and serial_out.stat().st_size > 4096
    serial_dur = media_duration_seconds(serial_out)

    # Parallel reel — fresh DATA_DIR so it's a cold render, not a cache hit.
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "par"))
    monkeypatch.setenv("MEDIAHUB_REEL_PARALLEL", "1")
    par_out = tmp_path / "parallel.mp4"
    motion.render_meet_reel(cards, _brand_kit(), par_out, meet_name="E2E Meet")
    assert par_out.exists() and par_out.stat().st_size > 4096
    par_dur = media_duration_seconds(par_out)

    # Both land on the advertised duration (frame-pure ⇒ same content length).
    assert serial_dur == pytest.approx(duration, abs=0.3)
    assert par_dur == pytest.approx(duration, abs=0.3)
    assert par_dur == pytest.approx(serial_dur, abs=0.2)
