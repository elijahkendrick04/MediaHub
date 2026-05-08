"""Format-variant orchestrator.

Calls ``render_brief`` for each declared format size and returns a list of
``RenderResult`` records. Default formats produce a feed-square, feed-portrait,
and a story PNG — the minimum required by the V8 spec.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .render import render_brief, RenderResult


FORMAT_SIZES: dict[str, tuple[int, int]] = {
    "feed_square":     (1080, 1080),
    "feed_portrait":   (1080, 1350),
    "story":           (1080, 1920),
    "reel_cover":      (1080, 1920),
    "carousel_slide":  (1080, 1080),
}


def render_all_formats(
    brief,
    *,
    output_dir: str | Path,
    formats: Optional[list[str]] = None,
    athlete_path: Optional[str | Path] = None,
    venue_path: Optional[str | Path] = None,
    logo_path: Optional[str | Path] = None,
    brand_kit=None,
    sponsor_name: str = "",
    venue_attribution: str = "",
    skip_cutout: bool = False,
) -> list[RenderResult]:
    """Render the visual at multiple format sizes. Returns one ``RenderResult`` per format."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if formats is None:
        # Default: respect the pattern's format_priority, else fall back to 3 standard formats
        priority = list(getattr(brief, "format_priority", []) or [])
        # Always render the spec-mandated trio
        wanted = []
        for name in ("feed_square", "feed_portrait", "story"):
            if name not in wanted:
                wanted.append(name)
        # Prepend the brief's preferred first format if it's outside the trio
        for fmt in priority:
            if fmt in FORMAT_SIZES and fmt not in wanted:
                wanted.append(fmt)
        formats = wanted

    out: list[RenderResult] = []
    for fmt in formats:
        size = FORMAT_SIZES.get(fmt)
        if not size:
            continue
        try:
            res = render_brief(
                brief,
                output_dir=output_dir,
                size=size,
                format_name=fmt,
                athlete_path=athlete_path,
                venue_path=venue_path,
                logo_path=logo_path,
                brand_kit=brand_kit,
                sponsor_name=sponsor_name,
                venue_attribution=venue_attribution,
                skip_cutout=skip_cutout,
            )
            out.append(res)
        except Exception as e:
            # Don't lose the whole batch if one variant fails — log and continue
            import sys as _sys
            print(f"[graphic_renderer] format {fmt} failed: {e}", file=_sys.stderr)
    return out


__all__ = ["FORMAT_SIZES", "render_all_formats"]
