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

from mediahub.graphic_renderer.saliency import best_crop, crops_for

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
