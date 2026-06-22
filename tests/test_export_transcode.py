"""Tests for export_engine.transcode — FFmpeg video/GIF transcodes (1.19).

The pure argument builders run everywhere (no binary needed); the runners that
actually shell out to FFmpeg skip when no binary is available — the same
convention as tests/test_audio_ops.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mediahub.export_engine import transcode
from mediahub.export_engine.transcode import (
    TranscodeError,
    crf_for_quality,
    gif_args,
    gif_to_video_args,
    mp4_args,
    webm_args,
)
from mediahub.visual.reel_ffmpeg import ffmpeg_exe

_NO_FFMPEG = ffmpeg_exe() is None


class TestCrfMapping:
    def test_endpoints(self):
        assert crf_for_quality(100, best=18, worst=28) == 18
        assert crf_for_quality(10, best=18, worst=28) == 28

    def test_midpoint_between(self):
        crf = crf_for_quality(55, best=18, worst=28)
        assert 18 < crf < 28

    def test_clamped(self):
        assert crf_for_quality(9999, best=15, worst=50) == 15
        assert crf_for_quality(-10, best=15, worst=50) == 50

    def test_lower_quality_is_higher_crf(self):
        # CRF is inverted: worse quality → bigger number.
        assert crf_for_quality(30, best=18, worst=28) > crf_for_quality(80, best=18, worst=28)


class TestGifArgs:
    def test_uses_two_stage_palette(self):
        args = gif_args(Path("in.mp4"), Path("out.gif"), fps=12, width=480)
        joined = " ".join(args)
        assert "palettegen" in joined
        assert "paletteuse" in joined
        assert "split" in joined

    def test_width_scales_explicitly(self):
        args = " ".join(gif_args(Path("a.mp4"), Path("o.gif"), width=320))
        assert "scale=320:-1" in args

    def test_scale_factor_when_no_width(self):
        args = " ".join(gif_args(Path("a.mp4"), Path("o.gif"), width=0, scale=0.5))
        assert "scale=trunc(iw*0.5000)" in args

    def test_no_scaling_when_native(self):
        # The scaling *filter* is always comma-prefixed; bayer_scale= is not it.
        args = " ".join(gif_args(Path("a.mp4"), Path("o.gif"), width=0, scale=1.0))
        assert ",scale=" not in args

    def test_loop_field_passed(self):
        args = gif_args(Path("a.mp4"), Path("o.gif"), loop=-1)
        assert "-loop" in args and args[args.index("-loop") + 1] == "-1"

    def test_fps_clamped(self):
        args = " ".join(gif_args(Path("a.mp4"), Path("o.gif"), fps=9999))
        assert "fps=50" in args

    def test_dither_falls_back_to_bayer(self):
        args = " ".join(gif_args(Path("a.mp4"), Path("o.gif"), dither="weird"))
        assert "dither=bayer" in args


class TestWebmArgs:
    def test_vp9_constant_quality(self):
        args = " ".join(webm_args(Path("a.mp4"), Path("o.webm"), crf=32))
        assert "libvpx-vp9" in args
        assert "-crf 32" in args
        assert "-b:v 0" in args  # CRF mode

    def test_transparent_uses_alpha_pixfmt(self):
        args = " ".join(webm_args(Path("a.mp4"), Path("o.webm"), transparent=True))
        assert "yuva420p" in args
        assert "-auto-alt-ref 0" in args

    def test_opaque_is_yuv420p(self):
        args = " ".join(webm_args(Path("a.mp4"), Path("o.webm"), transparent=False))
        assert "yuv420p" in args and "yuva420p" not in args

    def test_scale_factor_applied(self):
        args = " ".join(webm_args(Path("a.mp4"), Path("o.webm"), scale=2.0))
        assert "scale=trunc(iw*2.0000/2)*2" in args


class TestMp4AndGifToVideoArgs:
    def test_mp4_is_web_friendly(self):
        args = " ".join(mp4_args(Path("a.mov"), Path("o.mp4"), crf=23))
        assert "libx264" in args
        assert "yuv420p" in args
        assert "faststart" in args

    def test_gif_to_mp4_pads_even(self):
        args = " ".join(gif_to_video_args(Path("a.gif"), Path("o.mp4")))
        assert "trunc(iw/2)*2" in args
        assert "libx264" in args

    def test_gif_to_webm(self):
        args = " ".join(gif_to_video_args(Path("a.gif"), Path("o.webm"), fmt="webm"))
        assert "libvpx-vp9" in args

    def test_gif_to_webm_has_no_mp4_only_movflags(self):
        # -movflags is an MP4/MOV muxer option; it must not ride the WebM path.
        args = " ".join(gif_to_video_args(Path("a.gif"), Path("o.webm"), fmt="webm"))
        assert "movflags" not in args
        # ...but the MP4 path still gets faststart.
        assert "movflags" in " ".join(gif_to_video_args(Path("a.gif"), Path("o.mp4")))

    def test_webm_args_snaps_even_at_native_scale(self):
        # Odd-sized sources must still get an even-dimension filter (VP9/yuv420p).
        args = " ".join(webm_args(Path("a.mp4"), Path("o.webm"), scale=1.0))
        assert "trunc(iw/2)*2" in args


@pytest.mark.skipif(_NO_FFMPEG, reason="no FFmpeg binary available")
class TestRunnersLive:
    """Exercised only where FFmpeg is installed."""

    def _make_clip(self, path: Path, *, secs: float = 1.0, size: str = "160x120") -> Path:
        import subprocess

        subprocess.run(
            [
                ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", f"testsrc=size={size}:rate=15:duration={secs}",
                str(path),
            ],
            check=True,
        )
        return path

    def test_video_to_gif_and_back(self, tmp_path):
        clip = self._make_clip(tmp_path / "clip.mp4")
        gif = transcode.video_to_gif(clip, tmp_path / "out.gif", fps=10, width=120)
        assert gif.is_file() and gif.stat().st_size > 0
        mp4 = transcode.gif_to_video(gif, tmp_path / "back.mp4")
        assert mp4.is_file() and mp4.stat().st_size > 0

    def test_to_webm(self, tmp_path):
        clip = self._make_clip(tmp_path / "clip.mp4")
        webm = transcode.to_webm(clip, tmp_path / "out.webm", quality=60)
        assert webm.is_file() and webm.stat().st_size > 0

    def test_to_webm_odd_dimensions(self, tmp_path):
        # Regression: an odd-sized source must still encode to WebM at scale 1.0.
        clip = self._make_clip(tmp_path / "odd.mp4", size="161x121")
        webm = transcode.to_webm(clip, tmp_path / "odd.webm", quality=50)
        assert webm.is_file() and webm.stat().st_size > 0

    def test_gif_to_webm_runs(self, tmp_path):
        # Regression: GIF→WebM must not carry the MP4-only -movflags and fail.
        clip = self._make_clip(tmp_path / "clip.mp4")
        gif = transcode.video_to_gif(clip, tmp_path / "g.gif", fps=8, width=100)
        webm = transcode.gif_to_video(gif, tmp_path / "g.webm", fmt="webm")
        assert webm.is_file() and webm.stat().st_size > 0


@pytest.mark.skipif(not _NO_FFMPEG, reason="FFmpeg present — honest-error path needs it absent")
def test_runner_honest_errors_without_ffmpeg(tmp_path):
    with pytest.raises(TranscodeError):
        transcode.video_to_gif(tmp_path / "nope.mp4", tmp_path / "o.gif")
