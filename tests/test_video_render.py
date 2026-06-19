"""Tests for video.render — the pure arg builder, cache key, honest-error (1.6).

A real render needs FFmpeg (absent in CI sandboxes), so live renders aren't
exercised here; the deterministic arg/cache logic and the honest-error path are.
"""

from __future__ import annotations

import pytest

from mediahub.video.edl import EDL, Clip, CompiledGraph, compile_filtergraph
from mediahub.video.render import (
    VideoEngineUnavailable,
    build_ffmpeg_args,
    cache_key,
    render_edl,
)


def _edl(src="a.mp4", out_ms=3000, **kw):
    return EDL(clips=[Clip(source=src, in_ms=0, out_ms=out_ms, **kw)])


def test_build_ffmpeg_args_maps_video_and_audio():
    g = compile_filtergraph(_edl())
    args = build_ffmpeg_args(g, fps=30, out_path="out.mp4")
    assert args[:2] == ["-i", "a.mp4"]
    assert "-filter_complex" in args
    assert "-map" in args and "[v0]" in args
    assert "[a0]" in args
    assert "libx264" in args and "yuv420p" in args
    assert args[-1] == "out.mp4"


def test_build_ffmpeg_args_appends_caption_burn():
    g = compile_filtergraph(_edl())
    args = build_ffmpeg_args(g, fps=30, out_path="out.mp4", ass_paths=["/tmp/c.ass"])
    fc = args[args.index("-filter_complex") + 1]
    assert "ass=" in fc
    assert "[vcap0]" in fc
    # The mapped video label is now the captioned one.
    assert "[vcap0]" in args


def test_build_ffmpeg_args_chains_caption_and_title_burns():
    g = compile_filtergraph(_edl())
    args = build_ffmpeg_args(
        g, fps=30, out_path="out.mp4", ass_paths=["/tmp/cap.ass", "/tmp/title.ass"]
    )
    fc = args[args.index("-filter_complex") + 1]
    assert fc.count("ass=") == 2
    assert "[vcap1]" in args  # the final (titles) label is mapped


def test_build_ffmpeg_args_clamps_duration():
    g = compile_filtergraph(_edl())
    args = build_ffmpeg_args(g, fps=30, out_path="out.mp4", duration_ms=5000)
    assert "-t" in args
    assert "5.000" in args


def test_cache_key_is_stable_and_sensitive(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    e1 = _edl()
    k1 = cache_key(e1)
    assert k1 == cache_key(_edl())  # same EDL → same key
    e2 = _edl(out_ms=4000)
    assert cache_key(e2) != k1  # different cut → different key
    assert len(k1) == 24


def test_render_edl_honest_error_without_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr("mediahub.video.render.available", lambda: False)
    with pytest.raises(VideoEngineUnavailable):
        render_edl(_edl(), tmp_path / "out.mp4")


def test_render_edl_cache_hit_publishes_without_ffmpeg(monkeypatch, tmp_path):
    """A pre-existing cached MP4 is published with no FFmpeg call."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr("mediahub.video.render.available", lambda: True)
    e = _edl()
    from mediahub.video import render as _render

    cached = _render.cache_dir() / f"{cache_key(e)}.mp4"
    cached.write_bytes(b"\x00" * 2048)  # > 1024 → treated as a real cached render
    cached.with_suffix(".json").write_text("{}")

    out = tmp_path / "published.mp4"
    result = render_edl(e, out)
    assert result == out
    assert out.exists() and out.stat().st_size == 2048
    assert out.with_suffix(".json").exists()  # manifest travelled with it


# --- live integration (gated; runs where FFmpeg + the renderer exist) -----

from mediahub.video.render import available as _render_available  # noqa: E402


def _make_clip(exe, path, *, size, freq, dur=2):
    import subprocess

    subprocess.run(
        [
            exe,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={size}:rate=30:duration={dur}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:duration={dur}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )


@pytest.mark.skipif(not _render_available(), reason="FFmpeg + renderer not available")
def test_live_render_reframe_transition_and_captions(tmp_path, monkeypatch):
    """End-to-end: two real clips → reframe + fade + burned captions → MP4."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.visual.reel_ffmpeg import ffmpeg_exe

    from mediahub.video.edl import EDL, Clip, Transition
    from mediahub.video.probe import probe_clip

    exe = ffmpeg_exe()
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    _make_clip(exe, a, size="640x480", freq=440)
    _make_clip(exe, b, size="1280x720", freq=880)

    c2 = Clip(source=str(b), in_ms=0, out_ms=1500, crop=(280, 0, 720, 720))
    c2.transition_in = Transition("fade", 400)
    edl = EDL(
        width=1080,
        height=1920,
        fps=30,
        clips=[Clip(source=str(a), in_ms=0, out_ms=1500), c2],
        captions={
            "color": "#FFF",
            "scrim": "#0A2540",
            "cues": [{"from": 0, "dur": 30, "text": "PB"}],
        },
    )
    out = render_edl(edl, tmp_path / "out.mp4")
    assert out.exists() and out.stat().st_size > 4096
    probed = probe_clip(out)
    assert probed.display_size == (1080, 1920)  # reframed to story
    assert probed.has_audio
    # 1500 + 1500 - 400ms fade overlap ≈ 2.6s.
    assert 2300 <= probed.duration_ms <= 2900
