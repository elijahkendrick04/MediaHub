"""Tests for video.ops — single-clip FFmpeg video edits (roadmap 1.6 / 1.19).

Pure argument builders run everywhere; the runners that shell out to FFmpeg skip
when no binary is available — same convention as tests/test_audio_ops.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mediahub.video import ops
from mediahub.video.ops import (
    VideoOpError,
    crop_args,
    mute_args,
    resize_args,
    reverse_args,
    speed_args,
    trim_args,
)
from mediahub.visual.reel_ffmpeg import ffmpeg_exe

_NO_FFMPEG = ffmpeg_exe() is None


class TestArgBuilders:
    def test_trim(self):
        args = " ".join(trim_args(Path("a.mp4"), Path("o.mp4"), start=1.5, end=4.0))
        assert "-ss 1.500" in args
        assert "-t 2.500" in args  # end - start
        assert "libx264" in args

    def test_trim_no_end(self):
        args = trim_args(Path("a.mp4"), Path("o.mp4"), start=2.0)
        assert "-t" not in args  # runs to the end

    def test_crop_snaps_even(self):
        args = " ".join(crop_args(Path("a.mp4"), Path("o.mp4"), x=10, y=20, width=101, height=51))
        assert "crop=100:50:10:20" in args  # widths snapped to even

    def test_resize_keep_aspect_uses_auto_dimension(self):
        args = " ".join(resize_args(Path("a.mp4"), Path("o.mp4"), width=480))
        assert "scale=480:-2" in args

    def test_resize_exact_snaps_even(self):
        args = " ".join(resize_args(Path("a.mp4"), Path("o.mp4"), width=481, height=271, keep_aspect=False))
        assert "scale=480:270" in args

    def test_resize_requires_a_dimension(self):
        with pytest.raises(VideoOpError):
            resize_args(Path("a.mp4"), Path("o.mp4"))

    def test_speed_changes_video_and_audio(self):
        args = " ".join(speed_args(Path("a.mp4"), Path("o.mp4"), factor=2.0))
        assert "setpts=0.500000*PTS" in args
        assert "atempo=2.000000" in args

    def test_speed_unity_keeps_audio_copy(self):
        args = " ".join(speed_args(Path("a.mp4"), Path("o.mp4"), factor=1.0))
        assert "-c:a copy" in args
        assert "atempo" not in args

    def test_speed_mute_drops_audio(self):
        args = " ".join(speed_args(Path("a.mp4"), Path("o.mp4"), factor=2.0, mute=True))
        assert "-an" in args
        assert "atempo" not in args

    def test_speed_clamped(self):
        fast = " ".join(speed_args(Path("a.mp4"), Path("o.mp4"), factor=99))
        # 4.0 is the clamp ceiling: setpts = 1/4 = 0.25
        assert "setpts=0.250000*PTS" in fast

    def test_mute_streamcopies_video(self):
        args = " ".join(mute_args(Path("a.mp4"), Path("o.mp4")))
        assert "-c:v copy" in args
        assert "-an" in args

    def test_reverse_both_streams(self):
        args = " ".join(reverse_args(Path("a.mp4"), Path("o.mp4")))
        assert "-vf reverse" in args
        assert "areverse" in args

    def test_reverse_mute(self):
        args = " ".join(reverse_args(Path("a.mp4"), Path("o.mp4"), mute=True))
        assert "reverse" in args
        assert "-an" in args
        assert "areverse" not in args


@pytest.mark.skipif(_NO_FFMPEG, reason="no FFmpeg binary available")
class TestRunnersLive:
    def _make_clip(self, path: Path, *, secs: float = 1.0) -> Path:
        import subprocess

        subprocess.run(
            [
                ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=15:duration={secs}",
                "-f", "lavfi", "-i", f"sine=frequency=440:duration={secs}",
                "-shortest", str(path),
            ],
            check=True,
        )
        return path

    def test_trim_crop_resize(self, tmp_path):
        clip = self._make_clip(tmp_path / "clip.mp4", secs=2.0)
        assert ops.trim(clip, tmp_path / "t.mp4", start=0.2, end=1.0).is_file()
        assert ops.crop(clip, tmp_path / "c.mp4", x=0, y=0, width=80, height=60).is_file()
        assert ops.resize(clip, tmp_path / "r.mp4", width=80).is_file()

    def test_speed_mute_reverse(self, tmp_path):
        clip = self._make_clip(tmp_path / "clip.mp4")
        assert ops.change_speed(clip, tmp_path / "s.mp4", factor=2.0).is_file()
        assert ops.mute(clip, tmp_path / "m.mp4").is_file()
        assert ops.reverse(clip, tmp_path / "rev.mp4").is_file()

    def test_concat(self, tmp_path):
        a = self._make_clip(tmp_path / "a.mp4")
        b = self._make_clip(tmp_path / "b.mp4")
        out = ops.concat([a, b], tmp_path / "joined.mp4")
        assert out.is_file() and out.stat().st_size > 0


@pytest.mark.skipif(not _NO_FFMPEG, reason="FFmpeg present — honest-error path needs it absent")
def test_runner_honest_errors_without_ffmpeg(tmp_path):
    with pytest.raises(VideoOpError):
        ops.reverse(tmp_path / "nope.mp4", tmp_path / "o.mp4")
