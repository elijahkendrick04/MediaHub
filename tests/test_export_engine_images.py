"""Tests for export_engine.images — deterministic raster conversion (1.19).

Pillow is a hard dependency, so these run everywhere. AVIF/WebP encoders vary by
build; tests that need them skip when the running Pillow can't encode them.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from mediahub.export_engine import images
from mediahub.export_engine.images import (
    ImageConvertError,
    can_encode,
    convert_image,
    convert_image_bytes,
)
from mediahub.export_engine.options import ExportOptions


def _png_bytes(size=(200, 120), rgba=(220, 30, 30, 255)) -> bytes:
    im = Image.new("RGBA", size, rgba)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _open(data: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    im.load()
    return im


class TestConvertBytes:
    def test_png_to_jpeg_flattens_alpha(self):
        out = convert_image_bytes(_png_bytes(), fmt="jpg")
        im = _open(out)
        assert im.format == "JPEG"
        assert im.mode == "RGB"  # no alpha in a JPEG

    def test_png_keeps_alpha_when_transparent(self):
        out = convert_image_bytes(_png_bytes(), fmt="png", options=ExportOptions(transparent=True))
        assert _open(out).mode == "RGBA"

    def test_png_flattened_when_not_transparent(self):
        out = convert_image_bytes(_png_bytes(), fmt="png", options=ExportOptions(transparent=False))
        assert _open(out).mode == "RGB"

    def test_scale_changes_dimensions(self):
        out = convert_image_bytes(_png_bytes((200, 100)), fmt="png", options=ExportOptions(scale=0.5))
        assert _open(out).size == (100, 50)

    def test_flatten_background_colour_applied(self):
        # Fully transparent source, flattened onto green → corner pixel is green.
        src = _png_bytes((20, 20), rgba=(0, 0, 0, 0))
        out = convert_image_bytes(src, fmt="jpg", options=ExportOptions(background="#00ff00"))
        px = _open(out).getpixel((0, 0))
        assert px[1] > 200 and px[0] < 60 and px[2] < 60

    def test_jpeg_quality_changes_size(self):
        # A photo-ish gradient so quality actually bites.
        im = Image.new("RGB", (256, 256))
        im.putdata([(x, (x * y) % 256, y) for y in range(256) for x in range(256)])
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        raw = buf.getvalue()
        small = convert_image_bytes(raw, fmt="jpg", options=ExportOptions(quality=20))
        big = convert_image_bytes(raw, fmt="jpg", options=ExportOptions(quality=95))
        assert len(small) < len(big)

    def test_deterministic(self):
        a = convert_image_bytes(_png_bytes(), fmt="jpg", options=ExportOptions(quality=70))
        b = convert_image_bytes(_png_bytes(), fmt="jpg", options=ExportOptions(quality=70))
        assert a == b

    def test_unknown_format_raises(self):
        with pytest.raises(ImageConvertError):
            convert_image_bytes(_png_bytes(), fmt="pdf")  # not a raster image format

    def test_bad_source_raises(self):
        with pytest.raises(ImageConvertError):
            convert_image_bytes(b"not an image", fmt="png")

    @pytest.mark.skipif(not can_encode("webp"), reason="no WebP encoder in this Pillow")
    def test_webp_round_trip(self):
        out = convert_image_bytes(_png_bytes(), fmt="webp", options=ExportOptions(quality=80))
        assert _open(out).format == "WEBP"

    @pytest.mark.skipif(not can_encode("avif"), reason="no AVIF encoder in this Pillow")
    def test_avif_round_trip(self):
        out = convert_image_bytes(_png_bytes(), fmt="avif", options=ExportOptions(quality=60))
        assert _open(out).format == "AVIF"


class TestConvertFile:
    def test_writes_output_file(self, tmp_path: Path):
        src = tmp_path / "card.png"
        src.write_bytes(_png_bytes())
        out = convert_image(src, tmp_path / "card.jpg", fmt="jpg")
        assert out.is_file()
        assert _open(out.read_bytes()).format == "JPEG"

    def test_creates_parent_dirs(self, tmp_path: Path):
        src = tmp_path / "card.png"
        src.write_bytes(_png_bytes())
        out = convert_image(src, tmp_path / "nested" / "deep" / "card.jpg", fmt="jpg")
        assert out.is_file()

    def test_missing_source_raises(self, tmp_path: Path):
        with pytest.raises(ImageConvertError):
            convert_image(tmp_path / "ghost.png", tmp_path / "o.jpg", fmt="jpg")


class TestCanEncode:
    def test_png_jpeg_always(self):
        assert can_encode("png")
        assert can_encode("jpg")
        assert can_encode("jpeg")

    def test_non_raster_is_false(self):
        assert not can_encode("pdf")
        assert not can_encode("mp4")
