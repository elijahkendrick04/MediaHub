"""Analyse a user-uploaded exemplar/reference post via Claude vision.

Returns structured style features that can feed back into the creative_brief.
Falls back to neutral defaults when no vision API is available.
"""
from __future__ import annotations

from typing import Any

from mediahub.media_ai import generate_vision, generate_json


_DEFAULT = {
    "composition": "balanced two-thirds layout with athlete left, headline right",
    "headline_font_style": "condensed sans-serif, heavy weight",
    "body_font_style": "geometric sans-serif",
    "colour_palette": [],
    "image_treatment": "cutout with subtle shadow",
    "text_density": "medium",
    "stat_treatment": "single oversized result chip",
    "logo_placement": "top-left or bottom-right",
    "tone": "professional",
    "use_for_post_angles": [],
}


def analyse_exemplar(image_path: str) -> dict:
    """Analyse one reference image and return style features.

    Output keys:
      composition, headline_font_style, body_font_style, colour_palette,
      image_treatment, text_density, stat_treatment, logo_placement,
      tone, use_for_post_angles.
    """
    sys = (
        "You are a sports-graphics art director. Look at the supplied reference "
        "image and extract the LAYOUT/STYLE patterns we can borrow without copying. "
        "Never describe specific people. Output JSON with these keys: "
        "composition, headline_font_style, body_font_style, colour_palette (list of hex codes), "
        "image_treatment, text_density (low|medium|high), stat_treatment, logo_placement, "
        "tone, use_for_post_angles (list of strings like 'medal_gold','pb_improvement')."
    )
    prompt = (
        "Describe the layout shape, typography pairing, colour palette and treatment. "
        "Do NOT identify any individuals. Return ONLY the JSON object."
    )
    raw = generate_vision([image_path], prompt, system=sys, max_tokens=800)
    parsed = _try_extract_json(raw)
    if not parsed:
        return dict(_DEFAULT)
    out = dict(_DEFAULT)
    out.update({k: v for k, v in parsed.items() if k in _DEFAULT})
    return out


def _try_extract_json(text: str) -> dict | None:
    if not text:
        return None
    import json as _json
    import re as _re
    s = text.strip()
    fence = _re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", s, _re.DOTALL)
    if fence:
        s = fence.group(1).strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return _json.loads(s[start:end + 1])
    except Exception:
        return None


__all__ = ["analyse_exemplar"]
