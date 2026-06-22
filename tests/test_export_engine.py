"""Tests for export_engine.engine + cache — the orchestrator (roadmap 1.19)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from mediahub.export_engine import (
    CONVERSIONS,
    ExportError,
    ExportOptions,
    can_convert,
    convert_file,
    engine_status,
    source_category,
    target_formats_for,
)
from mediahub.export_engine import cache as ec


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    """Point DATA_DIR at a temp dir so the export cache is per-test."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    yield


def _png(tmp_path: Path, name="card.png", size=(120, 80)) -> Path:
    p = tmp_path / name
    Image.new("RGBA", size, (10, 80, 200, 255)).save(p)
    return p


class TestSourceCategory:
    @pytest.mark.parametrize(
        "name,cat",
        [
            ("a.png", "image"),
            ("a.JPG", "image"),
            ("a.webp", "image"),
            ("clip.mp4", "video"),
            ("clip.MOV", "video"),
            ("loop.gif", "gif"),
            ("track.wav", "audio"),
            ("track.mp3", "audio"),
            ("weird.xyz", "unknown"),
        ],
    )
    def test_category_from_suffix(self, name, cat):
        assert source_category(name) == cat


class TestCapabilityMap:
    def test_target_formats_for_image(self):
        keys = {f.key for f in target_formats_for("image")}
        assert keys == {"png", "jpg", "webp", "avif"}

    def test_target_formats_for_path(self):
        keys = {f.key for f in target_formats_for("clip.mp4")}
        assert "gif" in keys and "webm" in keys and "wav" in keys

    def test_can_convert(self):
        assert can_convert("image", "jpg")
        assert can_convert("clip.mp4", "gif")
        assert not can_convert("image", "mp4")
        assert not can_convert("track.wav", "png")

    def test_gif_only_to_video(self):
        assert CONVERSIONS["gif"] == frozenset({"mp4", "webm"})

    def test_unknown_source_has_no_targets(self):
        assert target_formats_for("weird.xyz") == []


class TestConvertFile:
    def test_image_conversion_writes_to_cache(self, tmp_path):
        src = _png(tmp_path)
        res = convert_file(src, "jpg", options=ExportOptions(quality=80))
        assert res.path.is_file()
        assert res.fmt == "jpg"
        assert res.mime == "image/jpeg"
        assert res.size_bytes > 0
        assert res.from_cache is False
        # The cache file lives under DATA_DIR/export_cache.
        assert ec.cache_dir() in res.path.parents

    def test_second_call_is_cache_hit(self, tmp_path):
        src = _png(tmp_path)
        first = convert_file(src, "jpg")
        second = convert_file(src, "jpg")
        assert first.path == second.path
        assert second.from_cache is True

    def test_different_options_are_different_cache_entries(self, tmp_path):
        src = _png(tmp_path)
        a = convert_file(src, "jpg", options=ExportOptions(quality=40))
        b = convert_file(src, "jpg", options=ExportOptions(quality=90))
        assert a.path != b.path

    def test_explicit_out_path_used(self, tmp_path):
        src = _png(tmp_path)
        out = tmp_path / "explicit" / "card.png"
        res = convert_file(src, "png", out=out)
        assert res.path == out
        assert out.is_file()

    def test_changed_source_busts_cache(self, tmp_path):
        src = _png(tmp_path, size=(120, 80))
        a = convert_file(src, "png")
        # Rewrite the source with different content (new size → new fingerprint).
        Image.new("RGBA", (200, 200), (1, 2, 3, 255)).save(src)
        b = convert_file(src, "png")
        assert a.path != b.path

    def test_unknown_format_raises(self, tmp_path):
        src = _png(tmp_path)
        with pytest.raises(Exception):  # UnknownFormatError (ValueError subclass)
            convert_file(src, "ico")

    def test_impossible_conversion_raises(self, tmp_path):
        src = _png(tmp_path)
        with pytest.raises(ExportError):
            convert_file(src, "mp4")  # can't make a video from a still here

    def test_missing_source_raises(self, tmp_path):
        with pytest.raises(ExportError):
            convert_file(tmp_path / "ghost.png", "jpg")


class TestVideoToGifScaleLive:
    """Regression: convert_file video→GIF must honour the scale option, not
    fall back to the toolbox's default 480px width."""

    def _ffmpeg(self):
        from mediahub.visual.reel_ffmpeg import ffmpeg_exe

        return ffmpeg_exe()

    def _clip(self, path: Path) -> Path:
        import subprocess

        subprocess.run(
            [
                self._ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=1",
                str(path),
            ],
            check=True,
        )
        return path

    def test_scale_changes_gif_width(self, tmp_path):
        if not self._ffmpeg():
            pytest.skip("no FFmpeg binary available")
        from PIL import Image

        clip = self._clip(tmp_path / "clip.mp4")
        full = convert_file(clip, "gif", options=ExportOptions(scale=1.0), out=tmp_path / "full.gif")
        half = convert_file(clip, "gif", options=ExportOptions(scale=0.5), out=tmp_path / "half.gif")
        w_full = Image.open(full.path).width
        w_half = Image.open(half.path).width
        assert w_full == 320  # native, not the 480px default
        assert w_half < w_full  # the scale option actually took effect


class TestStatus:
    def test_engine_status_shape(self):
        st = engine_status()
        assert "ffmpeg" in st
        assert "conversions" in st
        assert set(st["conversions"]) == set(CONVERSIONS)


class TestCacheModule:
    def test_content_key_stable(self):
        assert ec.content_key("a", 1, b"x") == ec.content_key("a", 1, b"x")
        assert ec.content_key("a") != ec.content_key("b")

    def test_file_fingerprint_changes_with_content(self, tmp_path):
        p = tmp_path / "f.bin"
        p.write_bytes(b"aaaa")
        fp1 = ec.file_fingerprint(p)
        p.write_bytes(b"bbbbbbbb")  # different size
        assert ec.file_fingerprint(p) != fp1

    def test_missing_file_fingerprint(self, tmp_path):
        assert ec.file_fingerprint(tmp_path / "nope.bin").startswith("missing:")

    def test_cached_path_suffix(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        p = ec.cached_path("gif", "x", "y")
        assert p.suffix == ".gif"
        assert p.parent == ec.cache_dir()
