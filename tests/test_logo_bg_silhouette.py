"""tests/test_logo_bg_silhouette.py — versatile signed-in logo-wall silhouettes.

The signed-in app paints a soft, brand-tinted wall of the org's logos behind
every page. Each mark is the logo's *silhouette*, recoloured via a CSS mask —
which only looks good if every uploaded logo, of any colour and any background,
becomes a clean transparent silhouette (never a solid tinted rectangle).

These tests pin that guarantee for the matrix of real-world uploads: transparent
PNGs, opaque white-background JPEGs, opaque coloured-background PNGs, RGBA images
that are fully opaque, SVG vectors, and a sweep of foreground/background colour
combinations.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.brand.logos import (  # noqa: E402
    logo_bg_silhouette_path,
    logos_dir,
)

PID = "silhouette-test-club"


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def _draw_mark(im: Image.Image, fg: tuple) -> None:
    """A logo-ish mark: an outlined badge + a bar, so trimming has something to
    bound and there are interior + edge details (not a flat fill)."""
    d = ImageDraw.Draw(im)
    w, h = im.size
    d.ellipse([w * 0.30, h * 0.18, w * 0.70, h * 0.82], outline=fg, width=max(3, w // 60))
    d.rectangle([w * 0.42, h * 0.40, w * 0.58, h * 0.60], fill=fg)
    d.rectangle([w * 0.20, h * 0.86, w * 0.80, h * 0.92], fill=fg)


def _place(pid: str, logo_id: str, im: Image.Image, ext: str, **save_kw) -> None:
    path = logos_dir(pid) / f"{logo_id}.{ext}"
    im.save(path, **save_kw)


def _silhouette(pid: str, logo_id: str) -> Image.Image:
    p = logo_bg_silhouette_path(pid, logo_id)
    assert p is not None and p.exists(), f"no silhouette produced for {logo_id}"
    return Image.open(p).convert("RGBA")


def _assert_clean_silhouette(sil: Image.Image) -> None:
    """The core guarantee: real opaque artwork remains, and a substantial share
    of the mark is see-through — i.e. it is a silhouette, NOT a solid tinted
    rectangle (the failure mode for opaque-background uploads)."""
    alpha = np.asarray(sil.getchannel("A"))
    # Has real, opaque artwork.
    assert int(alpha.max()) > 200, f"artwork lost — max alpha {alpha.max()}"
    # A solid block is ~0% transparent; a real silhouette has plenty of
    # negative space keyed/left out.
    transparent_frac = float((alpha < 40).mean())
    assert (
        transparent_frac > 0.12
    ), f"looks like a solid block — only {transparent_frac:.0%} transparent"


# --------------------------------------------------------------------------- #
# Per-format / per-background cases
# --------------------------------------------------------------------------- #


def test_transparent_png_keeps_its_alpha():
    im = Image.new("RGBA", (480, 220), (0, 0, 0, 0))
    _draw_mark(im, (18, 18, 18, 255))  # near-black mark on transparent
    _place(PID, "transp_png", im, "png")
    _assert_clean_silhouette(_silhouette(PID, "transp_png"))


def test_opaque_white_jpeg_is_keyed_not_a_block():
    im = Image.new("RGB", (480, 220), (255, 255, 255))
    _draw_mark(im, (18, 18, 18))  # black mark on opaque white
    _place(PID, "white_jpg", im, "jpg", quality=92)
    _assert_clean_silhouette(_silhouette(PID, "white_jpg"))


def test_opaque_coloured_background_png_is_keyed():
    # A logo shipped on a solid brand-coloured tile (not white) + light artwork.
    im = Image.new("RGB", (480, 220), (10, 32, 72))  # navy tile
    _draw_mark(im, (245, 245, 235))  # near-white mark
    _place(PID, "navy_png", im, "png")
    _assert_clean_silhouette(_silhouette(PID, "navy_png"))


def test_fully_opaque_rgba_is_keyed():
    # RGBA but every pixel opaque (alpha==255) — the "exported with a white
    # background but kept RGBA" case. Must be keyed, not trusted as alpha.
    im = Image.new("RGBA", (480, 220), (255, 255, 255, 255))
    _draw_mark(im, (12, 90, 80, 255))  # teal mark
    _place(PID, "rgba_opaque", im, "png")
    _assert_clean_silhouette(_silhouette(PID, "rgba_opaque"))


def test_svg_passes_through_untouched():
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
        "<circle cx='50' cy='50' r='40' fill='#0a2540'/></svg>"
    )
    (logos_dir(PID) / "vector01.svg").write_text(svg)
    p = logo_bg_silhouette_path(PID, "vector01")
    assert p is not None and p.suffix.lower() == ".svg" and p.exists()


def test_missing_logo_returns_none():
    assert logo_bg_silhouette_path(PID, "does-not-exist") is None


def test_result_is_cached():
    im = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    _draw_mark(im, (200, 30, 40, 255))
    _place(PID, "cache01", im, "png")
    first = logo_bg_silhouette_path(PID, "cache01")
    assert first and first.exists()
    mtime = first.stat().st_mtime_ns
    second = logo_bg_silhouette_path(PID, "cache01")
    assert second == first
    assert second.stat().st_mtime_ns == mtime, "silhouette was recomputed, not cached"


# --------------------------------------------------------------------------- #
# "All colours" sweep — every fg/bg combination must yield a clean silhouette
# --------------------------------------------------------------------------- #

_COLOURS = {
    "black": (17, 17, 17),
    "white": (245, 245, 238),
    "navy": (10, 32, 72),
    "teal": (15, 142, 134),
    "green": (52, 179, 107),
    "red": (200, 16, 46),
    "gold": (244, 196, 96),
}


@pytest.mark.parametrize("bg_name", list(_COLOURS))
def test_all_colour_combinations_make_a_clean_silhouette(bg_name):
    bg = _COLOURS[bg_name]
    # Pick a clearly-different foreground so the keyer has real contrast (a logo
    # whose artwork equals its background is invisible by construction).
    fg = _COLOURS["white"] if sum(bg) < 360 else _COLOURS["black"]
    im = Image.new("RGB", (360, 200), bg)
    _draw_mark(im, fg)
    lid = f"combo_{bg_name}"
    _place(PID, lid, im, "png")
    _assert_clean_silhouette(_silhouette(PID, lid))
