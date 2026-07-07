"""Tests for `mediahub.media_library.tagger` — the ingest measurement spine.

PHOTOS-1/4: EXIF-aware measurement (dimensions, orientation, dominant
colours), EXIF-orientation baking, and the deterministic technical-quality
metrics (Laplacian sharpness, clipping fractions, luma entropy, 64-bit dHash).
All pure Pillow/numpy — same file in, same numbers out.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageFilter

from mediahub.media_library import tagger
from mediahub.media_library.models import MediaAsset
from mediahub.media_library.tagger import (
    bake_exif_orientation,
    dhash_hamming,
    measure_asset,
    measure_image,
)

_ORIENTATION_TAG = 0x0112


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _noise_image(size=(640, 480), seed=0) -> Image.Image:
    rng = np.random.default_rng(seed)
    return Image.fromarray(
        rng.integers(0, 256, size=(size[1], size[0], 3), dtype=np.uint8), "RGB"
    )


def _save(img: Image.Image, tmp_path, name: str, **kwargs) -> str:
    p = tmp_path / name
    img.save(p, **kwargs)
    return str(p)


def _save_with_orientation(img: Image.Image, tmp_path, name: str, orientation: int) -> str:
    exif = Image.Exif()
    exif[_ORIENTATION_TAG] = orientation
    p = tmp_path / name
    img.save(p, format="JPEG", exif=exif.tobytes())
    return str(p)


# ---------------------------------------------------------------------------
# measure_image — shape + basics
# ---------------------------------------------------------------------------


class TestMeasureImage:
    def test_returns_dimensions_and_orientation(self, tmp_path) -> None:
        path = _save(_noise_image((640, 480)), tmp_path, "land.png")
        m = measure_image(path)
        assert m["width"] == 640
        assert m["height"] == 480
        assert m["orientation"] == "landscape"

    def test_portrait_and_square(self, tmp_path) -> None:
        assert (
            measure_image(_save(_noise_image((300, 500)), tmp_path, "p.png"))["orientation"]
            == "portrait"
        )
        assert (
            measure_image(_save(_noise_image((400, 400)), tmp_path, "s.png"))["orientation"]
            == "square"
        )

    def test_dominant_colours_are_hex(self, tmp_path) -> None:
        img = Image.new("RGB", (200, 200), (0, 51, 102))
        path = _save(img, tmp_path, "navy.png")
        m = measure_image(path)
        assert m["dominant_colours"]
        for c in m["dominant_colours"]:
            assert c.startswith("#") and len(c) == 7

    def test_quality_dict_shape(self, tmp_path) -> None:
        path = _save(_noise_image(), tmp_path, "q.png")
        q = measure_image(path)["quality"]
        assert set(q.keys()) == {
            "sharpness",
            "clip_highlights",
            "clip_shadows",
            "entropy",
            "dhash",
        }
        assert q["sharpness"] > 0
        assert 0.0 <= q["clip_highlights"] <= 1.0
        assert 0.0 <= q["clip_shadows"] <= 1.0
        assert 0.0 <= q["entropy"] <= 8.0
        # 64-bit dHash as 16 lowercase hex chars.
        assert len(q["dhash"]) == 16
        int(q["dhash"], 16)

    def test_unreadable_file_returns_empty_measurement(self, tmp_path) -> None:
        p = tmp_path / "junk.jpg"
        p.write_bytes(b"not an image at all")
        m = measure_image(str(p))
        assert m["width"] == 0 and m["height"] == 0
        assert m["orientation"] == "unknown"
        assert m["dominant_colours"] == []
        assert m["quality"] is None

    def test_deterministic(self, tmp_path) -> None:
        path = _save(_noise_image(seed=7), tmp_path, "det.png")
        assert measure_image(path) == measure_image(path)


# ---------------------------------------------------------------------------
# EXIF awareness
# ---------------------------------------------------------------------------


class TestExif:
    def test_measure_is_exif_aware_for_legacy_files(self, tmp_path) -> None:
        # A 600x400 landscape JPEG tagged orientation 6 DISPLAYS as 400x600
        # portrait; legacy (un-baked) files must measure at display shape.
        path = _save_with_orientation(_noise_image((600, 400), seed=1), tmp_path, "o6.jpg", 6)
        m = measure_image(path)
        assert (m["width"], m["height"]) == (400, 600)
        assert m["orientation"] == "portrait"

    def test_bake_rewrites_upright_and_strips_tag(self, tmp_path) -> None:
        path = _save_with_orientation(_noise_image((600, 400), seed=2), tmp_path, "bake.jpg", 6)
        assert bake_exif_orientation(path) is True
        with Image.open(path) as im:
            assert im.size == (400, 600)
            assert im.getexif().get(_ORIENTATION_TAG) in (None, 1)
        # Second bake is a no-op (nothing left to transpose).
        assert bake_exif_orientation(path) is False

    def test_bake_leaves_untagged_files_untouched(self, tmp_path) -> None:
        path = _save(_noise_image((300, 200), seed=3), tmp_path, "plain.jpg", format="JPEG")
        before = open(path, "rb").read()
        assert bake_exif_orientation(path) is False
        assert open(path, "rb").read() == before

    def test_bake_never_raises_on_junk(self, tmp_path) -> None:
        p = tmp_path / "junk.jpg"
        p.write_bytes(b"\xff\xd8\xff\xe0garbage")
        assert bake_exif_orientation(str(p)) is False


# ---------------------------------------------------------------------------
# Quality metrics — orderings that matter
# ---------------------------------------------------------------------------


class TestQualityMetrics:
    def test_sharp_beats_blurred(self, tmp_path) -> None:
        sharp = _noise_image((400, 300), seed=4)
        blurred = sharp.filter(ImageFilter.GaussianBlur(radius=6))
        qs = measure_image(_save(sharp, tmp_path, "sharp.png"))["quality"]
        qb = measure_image(_save(blurred, tmp_path, "blur.png"))["quality"]
        assert qs["sharpness"] > qb["sharpness"] * 5

    def test_clipping_fractions(self, tmp_path) -> None:
        white = Image.new("RGB", (100, 100), (255, 255, 255))
        black = Image.new("RGB", (100, 100), (0, 0, 0))
        qw = measure_image(_save(white, tmp_path, "w.png"))["quality"]
        qb = measure_image(_save(black, tmp_path, "b.png"))["quality"]
        assert qw["clip_highlights"] == pytest.approx(1.0)
        assert qw["clip_shadows"] == pytest.approx(0.0)
        assert qb["clip_shadows"] == pytest.approx(1.0)
        assert qb["clip_highlights"] == pytest.approx(0.0)

    def test_flat_frame_has_near_zero_entropy(self, tmp_path) -> None:
        flat = Image.new("RGB", (100, 100), (120, 120, 120))
        q = measure_image(_save(flat, tmp_path, "flat.png"))["quality"]
        assert q["entropy"] < 0.5
        busy = measure_image(_save(_noise_image((100, 100), seed=5), tmp_path, "busy.png"))[
            "quality"
        ]
        assert busy["entropy"] > q["entropy"]

    def test_dhash_close_for_near_frames_far_for_different(self, tmp_path) -> None:
        base = _noise_image((400, 300), seed=6)
        # A near-frame: same shot, tiny brightness shift (burst sibling).
        arr = np.asarray(base, dtype=np.int16)
        near = Image.fromarray(np.clip(arr + 3, 0, 255).astype(np.uint8), "RGB")
        other = _noise_image((400, 300), seed=99)
        h_base = measure_image(_save(base, tmp_path, "h1.png"))["quality"]["dhash"]
        h_near = measure_image(_save(near, tmp_path, "h2.png"))["quality"]["dhash"]
        h_other = measure_image(_save(other, tmp_path, "h3.png"))["quality"]["dhash"]
        assert dhash_hamming(h_base, h_near) <= 6
        assert dhash_hamming(h_base, h_other) > 6

    def test_dhash_hamming_defensive(self) -> None:
        assert dhash_hamming("", "abc") == 64
        assert dhash_hamming("zz", "00") == 64
        assert dhash_hamming("00", "00") == 0


# ---------------------------------------------------------------------------
# measure_asset
# ---------------------------------------------------------------------------


class TestMeasureAsset:
    def test_populates_fields_and_quality(self, tmp_path) -> None:
        path = _save(_noise_image((640, 480), seed=8), tmp_path, "a.png")
        a = MediaAsset(id="x", filename="a.png", path=path)
        assert measure_asset(a) is True
        assert (a.width, a.height) == (640, 480)
        assert a.orientation == "landscape"
        assert isinstance(a.media_meta.get("quality"), dict)
        assert a.media_meta["quality"]["dhash"]

    def test_never_sets_has_face(self, tmp_path) -> None:
        # M4: the fake aspect-ratio face hint is gone; has_face stays None
        # until a REAL signal exists.
        path = _save(_noise_image((300, 400), seed=9), tmp_path, "b.png")
        a = MediaAsset(id="x", filename="b.png", path=path)
        measure_asset(a)
        assert a.has_face is None
        assert not hasattr(tagger, "_face_hint")

    def test_unreadable_leaves_asset_untouched(self, tmp_path) -> None:
        a = MediaAsset(
            id="x",
            filename="gone.jpg",
            path=str(tmp_path / "gone.jpg"),
            width=1200,
            height=800,
            orientation="landscape",
        )
        assert measure_asset(a) is False
        # A failed measurement never zeroes out data already stored.
        assert (a.width, a.height) == (1200, 800)
        assert "quality" not in a.media_meta
