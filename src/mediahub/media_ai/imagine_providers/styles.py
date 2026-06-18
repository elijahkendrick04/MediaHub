"""Curated, provider-agnostic style vocabulary for the ``imagine`` seam.

The sport-editorial look presets are a *product* decision, not a provider one:
the same "editorial" or "poster" brief should read the same whether it is drawn
by the cloud backend (Gemini/Imagen) or the in-house local diffusion model. So
the vocabulary lives here, shared by every provider, instead of being owned by
one of them.

``compose_prompt`` folds a chosen preset into the text prompt — the one place a
style name becomes guidance words — so curated looks apply consistently across
backends that only take a prompt (Imagen) and ours that could also take a
structured field.
"""

from __future__ import annotations

from typing import Optional

# Curated sport-editorial looks (no "3D clay" gimmicks by default).
STYLE_PRESETS = {
    "editorial": (
        "premium sports-magazine editorial photography, cinematic lighting, "
        "high contrast, shallow depth of field, atmospheric"
    ),
    "abstract": (
        "abstract editorial sports background, dynamic geometric forms, "
        "gradient lighting, subtle motion blur, clean negative space"
    ),
    "poster": (
        "bold modern sports poster art, strong graphic shapes, flat colour "
        "blocking, screen-print texture"
    ),
    "duotone": ("high-contrast duotone treatment, two-colour gradient, editorial poster feel"),
    "line_art": (
        "clean black-and-white line art, printable colouring-page style, bold "
        "outlines, no shading, white background"
    ),
}

DEFAULT_STYLE = "editorial"


def compose_prompt(prompt: str, style: Optional[str]) -> str:
    """Fold a style preset into the text prompt.

    An unknown style name is passed through untouched (a smart backend may still
    understand it); a recognised preset appends its curated guidance words.
    """
    base = (prompt or "").strip()
    key = (style or "").strip().lower() or DEFAULT_STYLE
    suffix = STYLE_PRESETS.get(key)
    if not suffix:
        return base
    return f"{base}. Style: {suffix}." if base else suffix


__all__ = ["STYLE_PRESETS", "DEFAULT_STYLE", "compose_prompt"]
