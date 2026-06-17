"""Format-variant orchestrator.

Calls ``render_brief`` for each declared format size and returns a list of
``RenderResult`` records. Default formats produce a feed-square, feed-portrait,
and a story PNG — the minimum required by the V8 spec.

G1.3 adds landscape & extended aspect ratios (16:9, 3:2, 4:3). These are
**opt-in** — requested explicitly via a ``formats=`` argument, a ``?format=``
request param, or a ``brief.format_priority`` entry — so the default render
still emits only the square/portrait/story trio (no extra cost/time per card).
The matching *per-format composition rules* live in ``render.py``
(``_format_aspect`` / ``_scale_for_format`` / ``_v2_fit_boxes`` /
``_format_composition_css``): a wide canvas is composed as a deliberate
landscape design, not a portrait layout stretched sideways.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .render import render_brief, RenderResult


FORMAT_SIZES: dict[str, tuple[int, int]] = {
    "feed_square": (1080, 1080),
    "feed_portrait": (1080, 1350),
    "story": (1080, 1920),
    "reel_cover": (1080, 1920),
    "carousel_slide": (1080, 1080),
    # G1.3 — landscape & extended aspect ratios. Height is held at 1080 so the
    # long edge grows with the ratio (clean, consistent landscape outputs).
    # "landscape" deliberately matches the motion renderer's 1920×1080 name.
    "landscape": (1920, 1080),  # 16:9 — web / YouTube / X header
    "landscape_3_2": (1620, 1080),  # 3:2 — classic photo landscape
    "landscape_4_3": (1440, 1080),  # 4:3 — presentation / legacy
}


def render_all_formats(
    brief,
    *,
    output_dir: str | Path,
    formats: Optional[list[str]] = None,
    athlete_path: Optional[str | Path] = None,
    venue_path: Optional[str | Path] = None,
    logo_path: Optional[str | Path] = None,
    bg_photo_path: Optional[str | Path] = None,
    brand_kit=None,
    sponsor_name: str = "",
    sponsor_logo_path: Optional[str | Path] = None,
    venue_attribution: str = "",
    skip_cutout: bool = False,
    watermark_text: str = "",
    photo_pos_override: str = "",
) -> list[RenderResult]:
    """Render the visual at multiple format sizes. Returns one ``RenderResult`` per format.

    ``photo_pos_override`` (UI 1.18): an explicit CSS ``object-position`` from
    the inspector crop control, applied to every format. Empty keeps the
    deterministic saliency focus.
    """
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

    # Filter to known formats once, preserving order.
    pending = [(fmt, FORMAT_SIZES[fmt]) for fmt in formats if fmt in FORMAT_SIZES]

    def _one(fmt: str, size: tuple[int, int]):
        return render_brief(
            brief,
            output_dir=output_dir,
            size=size,
            format_name=fmt,
            athlete_path=athlete_path,
            venue_path=venue_path,
            logo_path=logo_path,
            bg_photo_path=bg_photo_path,
            brand_kit=brand_kit,
            sponsor_name=sponsor_name,
            sponsor_logo_path=sponsor_logo_path,
            venue_attribution=venue_attribution,
            skip_cutout=skip_cutout,
            watermark_text=watermark_text,
            photo_pos_override=photo_pos_override,
        )

    out: list[RenderResult] = []
    # Parallel render — each format spins up its own Chromium tab. Cap at 4
    # workers so we don't thrash the host on the free Render tier.
    # Disable via MEDIAHUB_RENDER_PARALLEL=0 for debugging.
    import os as _os

    # Default to 3 concurrent format renders (square/portrait/story all at
    # once). Each Chromium uses ~150MB so 3 fits in Render's free tier RAM.
    # Disable via MEDIAHUB_RENDER_PARALLEL=0; cap via MEDIAHUB_RENDER_WORKERS=N.
    parallel = _os.environ.get("MEDIAHUB_RENDER_PARALLEL", "1") != "0" and len(pending) > 1
    max_workers = int(_os.environ.get("MEDIAHUB_RENDER_WORKERS", "3"))
    if parallel:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Preserve declared order by keying futures back to their index.
        results: list[Optional[RenderResult]] = [None] * len(pending)
        with ThreadPoolExecutor(max_workers=min(max_workers, len(pending))) as pool:
            future_to_idx = {
                pool.submit(_one, fmt, size): i for i, (fmt, size) in enumerate(pending)
            }
            for fut in as_completed(future_to_idx):
                idx = future_to_idx[fut]
                fmt_name = pending[idx][0]
                try:
                    results[idx] = fut.result()
                except Exception as e:
                    import sys as _sys

                    print(f"[graphic_renderer] format {fmt_name} failed: {e}", file=_sys.stderr)
        out = [r for r in results if r is not None]
    else:
        for fmt, size in pending:
            try:
                out.append(_one(fmt, size))
            except Exception as e:
                import sys as _sys

                print(f"[graphic_renderer] format {fmt} failed: {e}", file=_sys.stderr)
    return out


__all__ = ["FORMAT_SIZES", "render_all_formats"]
