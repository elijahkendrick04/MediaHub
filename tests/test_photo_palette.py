"""Tests for graphic_renderer.photo_palette — deterministic photo k-means.

Strategy mirrors test_saliency.py: build synthetic images with known colour
makeup (flat blocks, cutouts with transparency, gradients) and assert the
extracted palette is (a) deterministic, (b) faithful to the colours actually
present, (c) honest about each colour's share of the frame, and (d) safe on
junk/empty input. Plus the ``tint_toward`` mixing primitive.
"""
from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from mediahub.graphic_renderer.photo_palette import (
    PhotoPalette,
    Swatch,
    extract_palette,
    tint_toward,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _two_colour(left: tuple, right: tuple, size=(80, 80)) -> Image.Image:
    """Vertical split: ``left`` colour | ``right`` colour, fully opaque."""
    w, h = size
    img = Image.new("RGB", size, left)
    img.paste(Image.new("RGB", (w // 2, h), right), (w // 2, 0))
    return img


def _cutout(subject: tuple, size=(80, 80), box=(20, 10, 60, 70)) -> Image.Image:
    """Transparent canvas with one opaque ``subject`` block (a rembg cutout)."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    img.paste(Image.new("RGBA", (x1 - x0, y1 - y0), subject + (255,)), (x0, y0))
    return img


def _rgb_of(hex_value: str) -> tuple[int, int, int]:
    h = hex_value.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _close(a: tuple, b: tuple, tol: int = 14) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# --------------------------------------------------------------------------- #
# Determinism — the whole reason this is maths, not an LLM
# --------------------------------------------------------------------------- #


def test_palette_is_deterministic():
    raw = _png_bytes(_two_colour((200, 30, 30), (30, 30, 200)))
    p1 = extract_palette(raw)
    p2 = extract_palette(raw)
    assert p1.to_list() == p2.to_list()
    assert not p1.is_empty


def test_resolution_independent_dominant():
    """A small and a large copy of the same scene yield the same dominant
    colour — the downscale makes prominence resolution-independent."""
    small = extract_palette(_png_bytes(_two_colour((210, 40, 40), (20, 60, 160), (60, 60))))
    large = extract_palette(_png_bytes(_two_colour((210, 40, 40), (20, 60, 160), (400, 400))))
    assert _close(small.dominant.rgb, large.dominant.rgb)


# --------------------------------------------------------------------------- #
# Faithfulness — the colours and their shares
# --------------------------------------------------------------------------- #


def test_two_equal_colours_split_evenly():
    p = extract_palette(_png_bytes(_two_colour((200, 30, 30), (30, 30, 200))))
    by_hex = {s.hex: s for s in p.swatches}
    assert len(p.swatches) == 2
    # Each half of the frame ≈ 50%.
    for s in p.swatches:
        assert s.weight == pytest.approx(0.5, abs=0.05)
    # Both colours recovered (red-ish and blue-ish).
    reds = [s for s in p.swatches if s.rgb[0] > s.rgb[2]]
    blues = [s for s in p.swatches if s.rgb[2] > s.rgb[0]]
    assert reds and blues


def test_weights_sum_to_one():
    p = extract_palette(_png_bytes(_two_colour((10, 200, 90), (240, 200, 10))))
    assert sum(s.weight for s in p.swatches) == pytest.approx(1.0, abs=1e-6)


def test_dominant_is_the_largest_share():
    # 3/4 green, 1/4 orange.
    img = Image.new("RGB", (80, 80), (20, 170, 80))
    img.paste(Image.new("RGB", (80, 20), (230, 120, 30)), (0, 0))
    p = extract_palette(_png_bytes(img))
    assert p.dominant is not None
    assert p.dominant.rgb[1] > p.dominant.rgb[0]  # green channel leads → the green ground
    assert p.dominant.weight >= 0.5


# --------------------------------------------------------------------------- #
# Cutout alpha — the transparent void must not pollute the palette
# --------------------------------------------------------------------------- #


def test_cutout_alpha_excludes_transparent_background():
    """A red subject on a transparent canvas → a red palette, not a black/empty
    one. Only the opaque subject pixels are clustered."""
    p = extract_palette(_png_bytes(_cutout((205, 45, 45))))
    assert not p.is_empty
    assert _close(p.dominant.rgb, (205, 45, 45), tol=20)


def test_fully_transparent_is_empty():
    clear = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
    assert extract_palette(_png_bytes(clear)).is_empty


# --------------------------------------------------------------------------- #
# Vibrant / dominant / tint_target selection
# --------------------------------------------------------------------------- #


def test_vibrant_prefers_chromatic_over_neutral():
    # Mostly grey with a vivid magenta stripe.
    img = Image.new("RGB", (80, 80), (128, 128, 128))
    img.paste(Image.new("RGB", (80, 24), (220, 20, 200)), (0, 0))
    p = extract_palette(_png_bytes(img))
    vib = p.vibrant()
    assert vib is not None
    assert vib.chroma >= 28
    # The grey ground is the dominant by share, but the magenta is the tint target.
    assert p.dominant.chroma < vib.chroma
    assert p.tint_target() == vib.hex


def test_neutral_photo_has_no_vibrant_but_tint_falls_back_to_dominant():
    grey = extract_palette(_png_bytes(Image.new("RGB", (60, 60), (120, 120, 120))))
    assert grey.vibrant() is None
    assert grey.tint_target() == grey.dominant.hex  # graceful fallback


def test_empty_palette_tint_target_is_none():
    assert PhotoPalette(()).tint_target() is None
    assert PhotoPalette(()).dominant is None
    assert PhotoPalette(()).average_hex is None


# --------------------------------------------------------------------------- #
# Source types + k cap
# --------------------------------------------------------------------------- #


def test_accepts_path_bytes_and_image(tmp_path):
    img = _two_colour((200, 30, 30), (30, 30, 200))
    raw = _png_bytes(img)
    p = tmp_path / "x.png"
    p.write_bytes(raw)
    from_path = extract_palette(str(p))
    from_bytes = extract_palette(raw)
    from_image = extract_palette(img)
    assert from_path.to_list() == from_bytes.to_list() == from_image.to_list()


def test_k_caps_swatch_count():
    # A four-colour image clustered to k=2 → at most 2 swatches.
    img = Image.new("RGB", (80, 80))
    img.paste(Image.new("RGB", (40, 40), (200, 0, 0)), (0, 0))
    img.paste(Image.new("RGB", (40, 40), (0, 200, 0)), (40, 0))
    img.paste(Image.new("RGB", (40, 40), (0, 0, 200)), (0, 40))
    img.paste(Image.new("RGB", (40, 40), (200, 200, 0)), (40, 40))
    assert len(extract_palette(_png_bytes(img), k=2).swatches) <= 2


# --------------------------------------------------------------------------- #
# Robustness — never raise on bad input
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", [b"", b"not-an-image", b"\x89PNG\r\n\x1a\nbroken"])
def test_junk_bytes_yield_empty_palette(bad):
    assert extract_palette(bad).is_empty


def test_missing_path_yields_empty_palette():
    assert extract_palette("/no/such/file.png").is_empty


# --------------------------------------------------------------------------- #
# Swatch maths
# --------------------------------------------------------------------------- #


def test_swatch_chroma_and_luminance():
    vivid = Swatch(hex="#FF0000", weight=1.0, rgb=(255, 0, 0))
    grey = Swatch(hex="#808080", weight=1.0, rgb=(128, 128, 128))
    assert vivid.chroma == 255
    assert grey.chroma == 0
    assert 0.0 <= grey.luminance <= 1.0
    assert vivid.luminance < Swatch("#FFFFFF", 1.0, (255, 255, 255)).luminance


# --------------------------------------------------------------------------- #
# tint_toward — the bounded mix primitive
# --------------------------------------------------------------------------- #


def test_tint_toward_endpoints_and_midpoint():
    assert tint_toward("#000000", "#FFFFFF", 0.0) == "#000000"
    assert tint_toward("#000000", "#FFFFFF", 1.0) == "#FFFFFF"
    assert tint_toward("#000000", "#FFFFFF", 0.5) == "#808080"


def test_tint_toward_clamps_out_of_range():
    assert tint_toward("#102030", "#A0B0C0", -1.0) == "#102030"  # clamped to 0
    assert tint_toward("#102030", "#A0B0C0", 5.0) == "#A0B0C0"  # clamped to 1


def test_tint_toward_small_amount_stays_near_base():
    out = tint_toward("#0A2540", "#E67828", 0.12)
    assert _close(_rgb_of(out), _rgb_of("#0A2540"), tol=40)  # a nudge, not a swap
    assert out != "#0A2540"
