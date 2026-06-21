"""charts.export — rasterise a chart to a ready-to-post PNG (roadmap 1.11).

A chart you can't post is half a product: Instagram and Facebook don't accept
SVG. This module turns the deterministic chart SVG into a PNG at real social
dimensions, reusing the still renderer's warm Chromium pool
(``graphic_renderer.render.render_html_to_png``) — the same engine, fonts and
colour pipeline the cards use, so a chart and a card from the same run match.

Deterministic + cached: the SVG is content-addressed (same spec + brand + size →
same file under ``DATA_DIR/charts_cache``), so a re-export is a cache hit and the
bytes are stable for a given Chromium. PNG rendering needs Playwright; when it's
unavailable the caller gets an honest error rather than a broken download (the
SVG path always works without it).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path
from typing import Optional

from .models import ChartSpec
from .render import render_chart_svg

# Real social dimensions (w, h). One source of truth for the export sizes.
EXPORT_FORMATS: dict[str, tuple[int, int]] = {
    "square": (1080, 1080),  # IG feed
    "portrait": (1080, 1350),  # IG portrait
    "story": (1080, 1920),  # IG/FB story, full-bleed
    "landscape": (1920, 1080),  # X / web / slide
    "wide": (1200, 675),  # link preview / OG image
}


def _cache_dir() -> Path:
    data_dir = Path(os.environ.get("DATA_DIR", ".")).resolve()
    d = data_dir / "charts_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _wrap_html(svg: str) -> str:
    """Full-bleed HTML page holding the SVG at the viewport size (the screenshot box)."""
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>html,body{margin:0;padding:0;background:transparent}"
        "svg{display:block}</style></head><body>" + svg + "</body></html>"
    )


def chart_png_path(
    spec: ChartSpec,
    *,
    fmt: str = "square",
    role_vars: Optional[dict[str, str]] = None,
    palette: Optional[dict] = None,
    brand_kit=None,
    quality=None,
) -> Path:
    """Render ``spec`` to a PNG at the named social ``fmt`` and return its path.

    Cached by content (SVG + size). Raises whatever the renderer raises when
    Playwright/Chromium is unavailable (an honest infra error, not a fake PNG).
    """
    w, h = EXPORT_FORMATS.get(fmt, EXPORT_FORMATS["square"])
    sized = replace(spec, width=w, height=h)
    # Self-contained SVG (fonts inlined) so Chromium needs no external font wiring.
    svg = render_chart_svg(sized, role_vars, palette=palette, brand_kit=brand_kit, embed_fonts=True)
    key = hashlib.blake2b(f"{w}x{h}|".encode() + svg.encode("utf-8"), digest_size=16).hexdigest()
    out = _cache_dir() / f"{key}.png"
    if out.exists() and out.stat().st_size > 0:
        return out  # content-addressed cache hit

    from mediahub.graphic_renderer.render import render_html_to_png

    render_html_to_png(_wrap_html(svg), out, (w, h), image_format="png", quality=quality)
    return out


def chart_png_bytes(spec: ChartSpec, *, fmt: str = "square", **kw) -> bytes:
    """Convenience: the PNG as bytes."""
    return chart_png_path(spec, fmt=fmt, **kw).read_bytes()


__all__ = ["EXPORT_FORMATS", "chart_png_path", "chart_png_bytes"]
