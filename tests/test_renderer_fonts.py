"""Regression pins for the two renderer-wide typography defects (2026-06-09).

1. **Self-hosted fonts must actually load in renders.** ``render_html_to_png``
   used Playwright ``set_content()``, which leaves the document on an
   ``about:blank`` origin — Chromium refuses ``file://`` subresource fetches
   from there, so every self-hosted ``@font-face`` silently failed and all
   production graphics shipped in fallback sans. The runner now writes the
   page beside the output and ``goto()``-navigates it as a real ``file://``
   document. The pin renders the same text through the public runner twice —
   once in 'Anton', once forced to generic sans — and asserts the two PNGs
   differ structurally. If the regression returns, Anton falls back to that
   same sans and the distance collapses to ~0 (measured: 0.40 healthy vs
   0.0000 broken).

2. **The autofit estimate must err wide for Anton.** The generic condensed
   table scale under-measured real Anton caps (~10–25%), so fitted hero lines
   overflowed their ``nowrap`` slots (long surnames clipped off-canvas). The
   pin cross-checks ``autofit.em_width``'s estimate against the *shipped*
   ``anton.woff2`` metrics for a corpus of realistic all-caps strings: the
   estimate must never be narrower than the real advance width (the
   never-overflow contract) and must stay within a sane margin of it (so
   hero text isn't shrunk absurdly).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mediahub.graphic_renderer.render import LAYOUTS_DIR

_FONTS_DIR = LAYOUTS_DIR / "fonts"


def _have_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            try:
                b = p.chromium.launch()
                b.close()
                return True
            except Exception:
                return False
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# 1. Fonts load through the public runner
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not _have_playwright(), reason="Playwright/Chromium not available")
def test_self_hosted_fonts_load_in_renders(tmp_path):
    from mediahub.graphic_renderer.render import render_html_to_png
    from mediahub.quality.variant_metrics import perceptual_spread

    shared = (LAYOUTS_DIR / "_shared.css").read_text(encoding="utf-8")
    # the same file:// rewrite render_brief applies to BASE_CSS
    shared = shared.replace("url(fonts/", f"url({_FONTS_DIR.as_uri()}/")

    def page(family: str) -> str:
        return (
            f"<!DOCTYPE html><html><head><style>{shared}\n"
            "body { margin:0; width:800px; height:400px; background:#fff; }\n"
            f".t {{ font-family:{family}; font-size:150px; color:#000; }}\n"
            "</style></head><body>"
            '<div class="t">HUGHES 2:08.41</div>'
            "</body></html>"
        )

    anton_a = tmp_path / "anton_a.png"
    anton_b = tmp_path / "anton_b.png"
    fallback = tmp_path / "fallback.png"
    render_html_to_png(page("'Anton', sans-serif"), anton_a, (800, 400))
    render_html_to_png(page("'Anton', sans-serif"), anton_b, (800, 400))
    render_html_to_png(page("sans-serif"), fallback, (800, 400))

    # control: the runner is deterministic for identical input
    control = perceptual_spread([str(anton_a), str(anton_b)])
    assert control <= 0.02, f"identical renders should match (got {control:.3f})"

    # the pin: Anton must render as Anton, not as the generic fallback.
    # Healthy renderer measures ~0.40 here; the set_content regression (fonts
    # silently blocked) collapses it to ~0.0 because both pages then paint
    # the same fallback sans.
    distance = perceptual_spread([str(anton_a), str(fallback)])
    assert distance >= 0.10, (
        f"Anton render is indistinguishable from the generic-sans render "
        f"(distance {distance:.3f}) — self-hosted @font-face files are not "
        f"loading; did render_html_to_png regress to set_content()?"
    )


# --------------------------------------------------------------------------- #
# 2. Autofit's Anton estimate errs wide vs the shipped font file
# --------------------------------------------------------------------------- #

_CAPS_CORPUS = [
    "HUGHES",
    "CONSTANTINOPOLOUS",
    "VAN DER BERG-WILLIAMS",
    "O'SULLIVAN",
    "LLEWELYN-SMYTHE",
    "WOLFESCHLEGELSTEINHAUSEN",
    "PAPADOPOULOS",
    "JOHNSON-JONES",
    "DE LA CRUZ",
    "SZCZEPANSKI",
    "WHITTINGHAM",
    "100M FREESTYLE",
    "4X100M MEDLEY RELAY",
    "PERSONAL BEST",
    "CLUB RECORD",
]


def _real_anton_em(text: str) -> float:
    from PIL import ImageFont

    font = ImageFont.truetype(str(_FONTS_DIR / "anton.woff2"), 1000)
    return font.getlength(text) / 1000.0


def test_anton_estimate_errs_wide_not_narrow():
    pytest.importorskip("PIL")
    try:
        _real_anton_em("X")
    except Exception:
        pytest.skip("Pillow/FreeType cannot load the shipped anton.woff2")

    from mediahub.graphic_renderer.autofit import em_width

    for text in _CAPS_CORPUS:
        real = _real_anton_em(text)
        estimate = em_width(text, font_family="Anton", weight=400)
        # never narrower than reality — a fitted line must not overflow…
        assert estimate >= real, (
            f"autofit under-measures Anton for {text!r}: estimate "
            f"{estimate:.3f}em < real {real:.3f}em — fitted hero lines will "
            f"overflow their boxes again (the clipped-surname regression)"
        )
        # …and not absurdly wide, or hero text shrinks for no reason.
        assert estimate <= real * 1.35, (
            f"autofit over-measures Anton for {text!r}: estimate "
            f"{estimate:.3f}em vs real {real:.3f}em"
        )
