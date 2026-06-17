"""Tests for graphic_renderer.saliency — deterministic saliency-aware crops.

Strategy: build synthetic images with a single high-energy "subject" block on
a flat background, in different corners, and assert that the proposed crop
(a) stays within the image bounds, (b) actually contains the subject, and
(c) moves in the same direction as the subject does.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from mediahub.graphic_renderer.saliency import (
    FORMAT_RATIOS,
    best_crop,
    crops_for,
    focus_position,
    focus_position_for_format,
    ratio_for_format,
)

Box = tuple[int, int, int, int]  # (x0, y0, x1, y1)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _textured_block(size: tuple[int, int], seed: int = 0) -> Image.Image:
    """A noise block — dense gradient energy throughout, not just at edges."""
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 256, size=(size[1], size[0], 3), dtype=np.uint8)
    return Image.fromarray(noise, "RGB")


def _image_with_subject(size: tuple[int, int], box: Box, *, seed: int = 0) -> Image.Image:
    """Flat dark canvas with a textured subject block pasted at ``box``."""
    img = Image.new("RGB", size, (8, 8, 8))
    x0, y0, x1, y1 = box
    block = _textured_block((x1 - x0, y1 - y0), seed=seed)
    img.paste(block, (x0, y0))
    return img


def _cutout_with_subject(size: tuple[int, int], box: Box) -> Image.Image:
    """Transparent canvas with one fully-opaque subject block (a cutout)."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    subj = Image.new("RGBA", (x1 - x0, y1 - y0), (220, 30, 30, 255))
    img.paste(subj, (x0, y0))
    return img


def _save(img: Image.Image, tmp_path, name: str) -> str:
    p = tmp_path / name
    img.save(p)
    return str(p)


def _within_bounds(crop, size: tuple[int, int]) -> bool:
    x, y, w, h = crop
    W, H = size
    return x >= 0 and y >= 0 and w > 0 and h > 0 and x + w <= W and y + h <= H


def _contains(crop, box: Box) -> bool:
    x, y, w, h = crop
    bx0, by0, bx1, by1 = box
    return x <= bx0 and y <= by0 and (x + w) >= bx1 and (y + h) >= by1


# --------------------------------------------------------------------------- #
# Subject tracking — horizontal
# --------------------------------------------------------------------------- #


def test_crop_tracks_subject_left_vs_right(tmp_path):
    size = (300, 100)
    left_box = (20, 30, 60, 70)
    right_box = (240, 30, 280, 70)
    left = _save(_image_with_subject(size, left_box, seed=1), tmp_path, "left.png")
    right = _save(_image_with_subject(size, right_box, seed=2), tmp_path, "right.png")

    cl = best_crop(left, "1:1")
    cr = best_crop(right, "1:1")

    # 1:1 on a 300x100 image -> 100x100, sliding horizontally.
    assert cl[2:] == (100, 100)
    assert cr[2:] == (100, 100)
    assert _within_bounds(cl, size)
    assert _within_bounds(cr, size)
    assert _contains(cl, left_box)
    assert _contains(cr, right_box)
    # Crop moves rightward as the subject moves rightward.
    assert cl[0] < cr[0]


# --------------------------------------------------------------------------- #
# Subject tracking — vertical
# --------------------------------------------------------------------------- #


def test_crop_tracks_subject_top_vs_bottom(tmp_path):
    size = (100, 300)
    top_box = (30, 20, 70, 60)
    bottom_box = (30, 240, 70, 280)
    top = _save(_image_with_subject(size, top_box, seed=3), tmp_path, "top.png")
    bottom = _save(_image_with_subject(size, bottom_box, seed=4), tmp_path, "bottom.png")

    ct = best_crop(top, "1:1")
    cb = best_crop(bottom, "1:1")

    # 1:1 on a 100x300 image -> 100x100, sliding vertically.
    assert ct[2:] == (100, 100)
    assert cb[2:] == (100, 100)
    assert _within_bounds(ct, size)
    assert _within_bounds(cb, size)
    assert _contains(ct, top_box)
    assert _contains(cb, bottom_box)
    # Crop moves downward as the subject moves downward.
    assert ct[1] < cb[1]


# --------------------------------------------------------------------------- #
# Multiple ratios at once
# --------------------------------------------------------------------------- #


def test_crops_for_multiple_ratios(tmp_path):
    size = (400, 400)
    box = (300, 300, 360, 360)  # subject bottom-right
    path = _save(_image_with_subject(size, box, seed=5), tmp_path, "corner.png")

    ratios = ["9:16", "1:1", "4:5"]
    out = crops_for(path, ratios)

    # Keyed by the exact specs supplied.
    assert set(out.keys()) == set(ratios)

    expected = {"9:16": 9 / 16, "1:1": 1.0, "4:5": 4 / 5}
    for spec, crop in out.items():
        assert _within_bounds(crop, size)
        # Each crop holds the requested aspect ratio (within a pixel of rounding).
        x, y, w, h = crop
        assert abs((w / h) - expected[spec]) < 0.02
        # The large crops all still contain the corner subject.
        assert _contains(crop, box)


# --------------------------------------------------------------------------- #
# Cutout alpha path
# --------------------------------------------------------------------------- #


def test_crop_uses_cutout_alpha_to_find_subject(tmp_path):
    size = (300, 100)
    right_box = (240, 30, 280, 70)
    left_box = (20, 30, 60, 70)
    right = _save(_cutout_with_subject(size, right_box), tmp_path, "cut_right.png")
    left = _save(_cutout_with_subject(size, left_box), tmp_path, "cut_left.png")

    cr = best_crop(right, "1:1")
    cl = best_crop(left, "1:1")

    assert _within_bounds(cr, size)
    assert _within_bounds(cl, size)
    assert _contains(cr, right_box)
    assert _contains(cl, left_box)
    # Tracks the opaque subject region the same way the gradient path does.
    assert cl[0] < cr[0]


# --------------------------------------------------------------------------- #
# Featureless image -> centred crop
# --------------------------------------------------------------------------- #


def test_uniform_image_centres_crop(tmp_path):
    size = (300, 100)
    path = _save(Image.new("RGB", size, (120, 120, 120)), tmp_path, "flat.png")

    crop = best_crop(path, "1:1")
    x, y, w, h = crop
    assert _within_bounds(crop, size)
    assert (w, h) == (100, 100)
    # With no salient signal the 100-wide window sits centred in the 300 width.
    assert x == 100


# --------------------------------------------------------------------------- #
# Ratio spec forms + validation
# --------------------------------------------------------------------------- #


def test_ratio_spec_forms_are_equivalent(tmp_path):
    path = _save(_image_with_subject((300, 100), (240, 30, 280, 70), seed=6), tmp_path, "r.png")
    as_str = best_crop(path, "9:16")
    as_tuple = best_crop(path, (9, 16))
    as_float = best_crop(path, 9 / 16)
    assert as_str == as_tuple == as_float


def test_string_ratio_separators(tmp_path):
    path = _save(_image_with_subject((300, 100), (240, 30, 280, 70), seed=7), tmp_path, "s.png")
    assert best_crop(path, "9:16") == best_crop(path, "9/16") == best_crop(path, "9x16")


@pytest.mark.parametrize("bad", ["0:1", "1:0", "abc", "-2", 0, -1.5, (1, 0), (1, 2, 3)])
def test_invalid_ratio_raises(tmp_path, bad):
    path = _save(_image_with_subject((100, 100), (10, 10, 40, 40), seed=8), tmp_path, "b.png")
    with pytest.raises(ValueError):
        best_crop(path, bad)


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_repeated_calls_are_deterministic(tmp_path):
    path = _save(_image_with_subject((320, 180), (40, 40, 110, 140), seed=9), tmp_path, "d.png")
    first = crops_for(path, ["9:16", "1:1", "4:5"])
    second = crops_for(path, ["9:16", "1:1", "4:5"])
    assert first == second


# --------------------------------------------------------------------------- #
# Format-aware focus (R1.7)
# --------------------------------------------------------------------------- #


def _pct(pos: str) -> tuple[float, float]:
    """Parse a ``"<x>% <y>%"`` object-position into floats."""
    x, y = pos.split()
    return float(x.rstrip("%")), float(y.rstrip("%"))


def test_format_ratios_cover_the_four_motion_cuts():
    # The exact cuts R1.7 names, each mapped to its real aspect ratio.
    assert FORMAT_RATIOS == {
        "story": "9:16",
        "portrait": "4:5",
        "square": "1:1",
        "landscape": "16:9",
    }


def test_ratio_for_format_resolves_known_cuts():
    assert ratio_for_format("story") == "9:16"
    assert ratio_for_format("portrait") == "4:5"
    assert ratio_for_format("square") == "1:1"
    assert ratio_for_format("landscape") == "16:9"


def test_ratio_for_format_is_case_insensitive_and_trims():
    assert ratio_for_format("LANDSCAPE") == "16:9"
    assert ratio_for_format("  Portrait  ") == "4:5"


@pytest.mark.parametrize("bad", ["", "feed_square", "nonsense", None])
def test_ratio_for_format_falls_back_to_story(bad):
    # Unknown/empty names resolve to the 9:16 story default, never raise.
    assert ratio_for_format(bad) == "9:16"  # type: ignore[arg-type]


def test_focus_position_for_format_matches_explicit_ratio(tmp_path):
    # The per-format wrapper is exactly focus_position at the resolved ratio.
    path = _save(_image_with_subject((1000, 1000), (60, 60, 300, 300), seed=11), tmp_path, "s.png")
    assert focus_position_for_format(path, "story") == focus_position(path, "9:16")
    assert focus_position_for_format(path, "portrait") == focus_position(path, "4:5")
    assert focus_position_for_format(path, "square") == focus_position(path, "1:1")
    assert focus_position_for_format(path, "landscape") == focus_position(path, "16:9")


def test_focus_position_for_format_steers_per_axis(tmp_path):
    """A square source with a top-left subject: the 9:16 story crop slides
    horizontally (tracks X, Y pinned mid) while the 16:9 landscape crop slides
    vertically (tracks Y, X pinned mid). The whole point of R1.7 — each cut
    keeps the subject in frame for *its* aspect, so the strings differ."""
    path = _save(_image_with_subject((1000, 1000), (60, 60, 300, 300), seed=12), tmp_path, "c.png")

    story = focus_position_for_format(path, "story")
    landscape = focus_position_for_format(path, "landscape")
    square = focus_position_for_format(path, "square")

    sx, sy = _pct(story)
    lx, ly = _pct(landscape)
    # Story: subject pulls X left of centre, Y stays mid (full height used).
    assert sx < 50 and abs(sy - 50) < 1
    # Landscape: subject pulls Y above centre, X stays mid (full width used).
    assert abs(lx - 50) < 1 and ly < 50
    # A 1:1 crop of a 1:1 source is the whole image — dead centre.
    assert square == "50% 50%"
    # Distinct focal points across cuts is the deliverable.
    assert story != landscape


def test_focus_position_for_format_unknown_matches_story(tmp_path):
    path = _save(_image_with_subject((1000, 1000), (60, 60, 300, 300), seed=13), tmp_path, "u.png")
    # Unknown cut falls back to the 9:16 story ratio.
    assert focus_position_for_format(path, "feed_square") == focus_position_for_format(
        path, "story"
    )


def test_focus_position_for_format_safe_default_on_bad_path():
    # Same never-raise contract as focus_position.
    assert focus_position_for_format("", "landscape") == "center 28%"
    assert focus_position_for_format("/nonexistent/photo.jpg", "square") == "center 28%"


def test_focus_position_for_format_is_deterministic(tmp_path):
    path = _save(_image_with_subject((900, 1600), (80, 80, 260, 320), seed=14), tmp_path, "det.png")
    for fmt in ("story", "portrait", "square", "landscape"):
        assert focus_position_for_format(path, fmt) == focus_position_for_format(path, fmt)
