"""Image-side tagging: dimensions, orientation, dominant colours, face hint.

Pure-Pillow heuristics so it works in published sandbox. `has_face` is a
best-effort signal; it relies on aspect ratio / luminance variance and is
intended to be overridden by user metadata when present.
"""
from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Optional

from PIL import Image

log = logging.getLogger(__name__)


def measure_image(path: str) -> dict:
    """Return {width, height, orientation, dominant_colours[], has_face_hint}."""
    try:
        img = Image.open(path)
    except Exception as e:
        log.debug("measure_image open failed for %s: %s", path, e)
        return {
            "width": 0, "height": 0, "orientation": "unknown",
            "dominant_colours": [], "has_face_hint": None,
        }
    img = img.convert("RGB")
    w, h = img.size
    orientation = "square"
    if w > h * 1.05:
        orientation = "landscape"
    elif h > w * 1.05:
        orientation = "portrait"
    dominant = _dominant_colours(img, n=4)
    has_face_hint = _face_hint(img)
    return {
        "width": w, "height": h, "orientation": orientation,
        "dominant_colours": dominant, "has_face_hint": has_face_hint,
    }


def _dominant_colours(img: Image.Image, n: int = 4) -> list[str]:
    """Quick palette via downsample + quantise. Returns hex list."""
    try:
        small = img.resize((120, 120))
        # Quantise to a small palette and pick top
        pal = small.quantize(colors=16, method=Image.Quantize.MEDIANCUT)
        pal_rgb = pal.convert("RGB")
        # Count pixels by colour
        pixels = list(pal_rgb.getdata())
        counts = Counter(pixels)
        most = counts.most_common(n * 2)
        out: list[str] = []
        for (r, g, b), _ in most:
            # Skip near-pure-white/black to keep palette useful
            if (r > 245 and g > 245 and b > 245) or (r < 12 and g < 12 and b < 12):
                continue
            out.append(f"#{r:02X}{g:02X}{b:02X}")
            if len(out) >= n:
                break
        return out
    except Exception as e:
        log.debug("dominant_colours failed: %s", e)
        return []


def _face_hint(img: Image.Image) -> Optional[bool]:
    """Very rough heuristic — true if portrait-ish aspect AND mid luminance.

    Real face detection requires opencv or rembg's u2netp_human_seg; we keep
    this dependency-light. The user can override the metadata flag in the UI.
    """
    try:
        w, h = img.size
        if w == 0 or h == 0:
            return None
        ar = w / h
        # Headshot/portrait aspect range
        if 0.5 <= ar <= 1.2:
            # Coarse luminance check on centre
            cx, cy = w // 2, int(h * 0.35)
            r0, c0 = max(0, cx - 30), max(0, cy - 30)
            r1, c1 = min(w, cx + 30), min(h, cy + 30)
            crop = img.crop((r0, c0, r1, c1)).convert("L")
            stat = crop.getextrema()
            spread = stat[1] - stat[0]
            if spread > 60:  # textured (likely face content vs flat sky)
                return True
        return False
    except Exception:
        return None


__all__ = ["measure_image"]
