"""charts.fonts — self-hosted typefaces for standalone chart SVG.

A chart SVG is served and embedded on its own (a browser ``<img>``, a microsite,
a download), so it must carry its own fonts — and, like every other MediaHub
surface, **never from the Google Fonts CDN** (reliability + the Munich GDPR
ruling; see CLAUDE.md "Fonts are self-hosted on every surface"). This module
inlines the *same* first-party woff2 files the still renderer ships
(``graphic_renderer/layouts/fonts/*.woff2``) as base64 ``data:`` URIs inside an
``@font-face`` ``<style>`` block, so the SVG is fully self-contained and
CDN-free on every surface.

Deterministic and cheap: the encoded font is read once and cached, so the same
chart renders byte-identically every time.
"""

from __future__ import annotations

import base64
import functools
from pathlib import Path

# The two registers a chart uses: a condensed display face for the headline +
# big numerals, and Inter for axis/data/table text. Both are already self-hosted
# for the card renderer; we reuse those exact files (no new font assets).
_FONT_DIR = Path(__file__).resolve().parent.parent / "graphic_renderer" / "layouts" / "fonts"

DISPLAY_FAMILY = "Anton"
BODY_FAMILY = "Inter"
MONO_FAMILY = "JetBrains Mono"

_FILES: dict[str, str] = {
    DISPLAY_FAMILY: "anton.woff2",
    BODY_FAMILY: "inter.woff2",
    MONO_FAMILY: "jetbrains-mono.woff2",
}


@functools.lru_cache(maxsize=8)
def _data_uri(family: str) -> str:
    """base64 ``data:`` URI for a family's woff2, or "" if the file is missing."""
    fname = _FILES.get(family)
    if not fname:
        return ""
    path = _FONT_DIR / fname
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:font/woff2;base64,{b64}"


@functools.lru_cache(maxsize=2)
def font_face_css(embed: bool = True) -> str:
    """The ``@font-face`` block for a chart SVG's ``<style>``.

    When ``embed`` is True (default) the woff2 is inlined as a ``data:`` URI so
    the SVG is self-contained. When False, the families are still declared (so
    the renderer's own ``file://`` fonts apply when the SVG is rasterised through
    the HTML→PNG path) but nothing is inlined — lighter, used by tests.
    """
    blocks: list[str] = []
    faces = [
        (DISPLAY_FAMILY, "400"),
        (BODY_FAMILY, "100 900"),
        (MONO_FAMILY, "100 800"),
    ]
    for family, weight in faces:
        if embed:
            uri = _data_uri(family)
            if not uri:
                continue
            src = f"url({uri}) format('woff2')"
        else:
            fname = _FILES.get(family, "")
            src = f"url(fonts/{fname}) format('woff2')"
        blocks.append(
            "@font-face{"
            f"font-family:'{family}';"
            f"src:{src};"
            f"font-weight:{weight};font-style:normal;font-display:swap;"
            "}"
        )
    return "".join(blocks)


def display_stack() -> str:
    """CSS font stack for headline / numerals (condensed display + safe fallback)."""
    return f"'{DISPLAY_FAMILY}','Arial Narrow',system-ui,sans-serif"


def body_stack() -> str:
    """CSS font stack for axis labels, data labels, table text."""
    return f"'{BODY_FAMILY}',system-ui,-apple-system,Segoe UI,Roboto,sans-serif"


def mono_stack() -> str:
    """CSS font stack for tabular numerals (times in tables / ladders)."""
    return f"'{MONO_FAMILY}',ui-monospace,SFMono-Regular,Menlo,monospace"


__all__ = [
    "font_face_css",
    "display_stack",
    "body_stack",
    "mono_stack",
    "DISPLAY_FAMILY",
    "BODY_FAMILY",
    "MONO_FAMILY",
]
