"""Tests for export_engine.quick_actions — the toolbox (roadmap 1.19).

Image + PDF actions use Pillow/pypdf (present everywhere) and run fully; the
video/GIF actions delegate to FFmpeg and only smoke-test their wiring (skipping
the live run when no binary is available).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from mediahub.export_engine import quick_actions as qa
from mediahub.export_engine.options import ExportOptions
from mediahub.visual.reel_ffmpeg import ffmpeg_exe

_NO_FFMPEG = ffmpeg_exe() is None


def _png(p: Path, size=(400, 300), rgb=(120, 60, 200)) -> Path:
    Image.new("RGB", size, rgb).save(p)
    return p


class TestImageActions:
    def test_convert(self, tmp_path):
        src = _png(tmp_path / "p.png")
        out = qa.convert_image(src, tmp_path / "p.jpg", fmt="jpg", options=ExportOptions(quality=80))
        assert Image.open(out).format == "JPEG"

    def test_resize_preserves_aspect(self, tmp_path):
        src = _png(tmp_path / "p.png", size=(400, 300))
        out = qa.resize_image(src, tmp_path / "r.png", width=200)
        assert Image.open(out).size == (200, 150)

    def test_resize_by_scale(self, tmp_path):
        src = _png(tmp_path / "p.png", size=(400, 300))
        out = qa.resize_image(src, tmp_path / "r.png", scale=0.25)
        assert Image.open(out).size == (100, 75)

    def test_resize_requires_a_dimension(self, tmp_path):
        src = _png(tmp_path / "p.png")
        with pytest.raises(ValueError):
            qa.resize_image(src, tmp_path / "r.png")

    def test_crop_fractions(self, tmp_path):
        src = _png(tmp_path / "p.png", size=(400, 300))
        out = qa.crop_image(src, tmp_path / "c.png", x=0.25, y=0.25, w=0.5, h=0.5)
        assert Image.open(out).size == (200, 150)

    def test_images_to_pdf(self, tmp_path):
        a = _png(tmp_path / "a.png")
        b = _png(tmp_path / "b.png", rgb=(20, 200, 60))
        out = qa.images_to_pdf([a, b], tmp_path / "bundle.pdf")
        assert out.is_file() and out.stat().st_size > 0
        assert out.read_bytes()[:4] == b"%PDF"

    def test_images_to_pdf_needs_one(self, tmp_path):
        with pytest.raises(ValueError):
            qa.images_to_pdf([], tmp_path / "x.pdf")


class TestGifActionGuards:
    def test_gif_to_video_rejects_bad_format(self, tmp_path):
        with pytest.raises(ValueError):
            qa.gif_to_video(tmp_path / "a.gif", tmp_path / "o.png", fmt="png")


class TestActionCatalogue:
    def test_groups_present(self):
        assert set(qa.ACTIONS) == {"image", "video", "gif"}

    def test_video_has_core_actions_but_not_merge(self):
        keys = {k for k, _ in qa.ACTIONS["video"]}
        assert {"trim", "crop", "resize", "speed", "mute", "reverse", "to_gif"} <= keys
        # merge needs multiple sources; the single-asset quick-action route
        # can't dispatch it, so advertising it would be a guaranteed 400.
        assert "merge" not in keys

    def test_image_has_core_actions(self):
        keys = {k for k, _ in qa.ACTIONS["image"]}
        assert {"convert", "resize", "crop", "to_pdf"} <= keys


@pytest.mark.skipif(_NO_FFMPEG, reason="no FFmpeg binary available")
class TestVideoActionsLive:
    def _clip(self, path: Path) -> Path:
        import subprocess

        subprocess.run(
            [
                ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=size=160x120:rate=15:duration=1",
                str(path),
            ],
            check=True,
        )
        return path

    def test_trim_and_reverse_and_gif(self, tmp_path):
        clip = self._clip(tmp_path / "c.mp4")
        assert qa.video_trim(clip, tmp_path / "t.mp4", start=0.1, end=0.6).is_file()
        assert qa.video_reverse(clip, tmp_path / "rev.mp4").is_file()
        gif = qa.video_to_gif(clip, tmp_path / "g.gif", fps=8, width=80)
        assert gif.is_file()
        assert qa.gif_to_video(gif, tmp_path / "back.mp4").is_file()


@pytest.mark.skipif(not _NO_FFMPEG, reason="FFmpeg present — honest-error path needs it absent")
def test_video_action_honest_errors_without_ffmpeg(tmp_path):
    from mediahub.video.ops import VideoOpError

    with pytest.raises(VideoOpError):
        qa.video_trim(tmp_path / "nope.mp4", tmp_path / "o.mp4", start=0, end=1)
