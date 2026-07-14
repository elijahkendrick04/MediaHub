"""Elevation & shadow-colour system (Canva gap analysis B1/B2).

Canva-grade output owes much of its "physical" feel to two quiet rules this
module encodes:

* **Layered shadows, one light source.** A single Gaussian ``box-shadow`` reads
  as a sticker with a smudge; real penumbrae fall off in layers. Every
  elevation level here emits a tight *contact* layer plus a doubling key-light
  ramp — same x:y direction (light from straight above) at every level, so all
  the furniture on a card sits in one physical space. The v2 layouts previously
  carried ~9 mutually inconsistent single-layer shadows; they now consume the
  ``--mh-elev-N`` tokens.
* **Hue-tinted darks, never pure black.** ``rgba(0,0,0,…)`` over a coloured
  ground overlays grey and washes the card out. :func:`shadow_rgb` derives one
  shadow colour per card from the resolved ground role — keep its hue, drop the
  saturation, floor the lightness — and every elevation token paints in it.

Deterministic by construction: pure float maths on the resolved role hexes, no
randomness, no AI, no network. Same brief → same tokens → same PNG.
"""

from __future__ import annotations

import colorsys

__all__ = ["shadow_rgb", "elevation_shadow", "elevation_drop_filter", "elevation_vars", "LEVELS"]

# The five elevation levels the layouts may address. 1 = resting chip,
# 3 = floating panel / disc, 5 = hero object lifted off a photo.
LEVELS: tuple[int, ...] = (1, 2, 3, 4, 5)

# Alpha budget per level: the *summed* opacity of all layers stays roughly
# constant per level so deeper stacks read softer, not darker. Dark-first
# feeds need slightly stronger shadows than a white-canvas design tool.
_CONTACT_ALPHA = {1: 0.22, 2: 0.24, 3: 0.26, 4: 0.28, 5: 0.30}
_RAMP_ALPHA = {1: 0.18, 2: 0.17, 3: 0.16, 4: 0.15, 5: 0.14}


def _hex_to_rgb(hex_colour: str) -> tuple[int, int, int]:
    h = (hex_colour or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"not a hex colour: {hex_colour!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def shadow_rgb(ground_hex: str) -> str:
    """The card's shadow colour as an ``"r,g,b"`` CSS triple.

    Keeps the resolved ground's hue, drops saturation to 40% of its value
    (capped at 0.45) and floors lightness into the 0.06–0.14 band — a deep
    ambient dark that carries the brand's cast instead of greying it. Falls
    back to a neutral ink-dark when the ground hex is unparseable, so a render
    can never break on a bad palette.
    """
    try:
        r, g, b = _hex_to_rgb(ground_hex)
    except Exception:
        return "10,12,16"
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    s2 = min(0.45, s * 0.4 + 0.12)
    l2 = max(0.06, min(0.14, l * 0.25))
    r2, g2, b2 = colorsys.hls_to_rgb(h, l2, s2)
    return f"{int(round(r2 * 255))},{int(round(g2 * 255))},{int(round(b2 * 255))}"


def _clamp_level(level: int) -> int:
    return 1 if level < 1 else 5 if level > 5 else int(level)


def elevation_shadow(level: int, *, scale: float = 1.0) -> str:
    """The ``box-shadow`` value for one elevation level.

    One tight contact layer plus ``level`` key-light layers whose y-offset and
    blur double per step (2/4/8/16/32px at ``scale`` 1.0), all straight-down
    (x = 0) so every element implies the same light. Colour rides the
    per-card ``--mh-shadow-rgb`` token with a neutral fallback, so the same
    token string works on any card and tints automatically.
    """
    lv = _clamp_level(level)
    k = max(0.25, float(scale))
    rgb = "var(--mh-shadow-rgb,10,12,16)"
    layers = [f"0 1px 2px rgba({rgb},{_CONTACT_ALPHA[lv]:.2f})"]
    ramp_alpha = _RAMP_ALPHA[lv]
    for step in range(1, lv + 1):
        off = int(round(2**step * k))
        blur = int(round(2 ** (step + 1) * k))
        layers.append(f"0 {off}px {blur}px rgba({rgb},{ramp_alpha:.2f})")
    return ", ".join(layers)


def elevation_drop_filter(level: int, *, scale: float = 1.0) -> str:
    """The ``filter: drop-shadow(...)`` twin for silhouette elements (cutouts).

    Two layers only (contact + one key) — stacked drop-shadows re-blur the
    whole silhouette each pass, so a full five-layer ramp would smear. The
    key layer lands at the same offset/blur as the box twin's deepest layer,
    keeping cutouts and panels in the same implied light.
    """
    lv = _clamp_level(level)
    k = max(0.25, float(scale))
    rgb = "var(--mh-shadow-rgb,10,12,16)"
    off = int(round(2**lv * k))
    blur = int(round(2 ** (lv + 1) * k))
    return (
        f"drop-shadow(0 2px 4px rgba({rgb},{_CONTACT_ALPHA[lv]:.2f})) "
        f"drop-shadow(0 {off}px {blur}px rgba({rgb},{_RAMP_ALPHA[lv] + 0.10:.2f}))"
    )


def elevation_vars(ground_hex: str, *, scale: float = 1.0) -> dict[str, str]:
    """All elevation tokens for one card, ready for the ``:root{--mh-*}`` block.

    ``scale`` lets a caller grow the whole system with the canvas (the render
    passes ``min(w, h) / 1080`` so a story cut and a landscape cut sit in the
    same relative light).
    """
    out = {"--mh-shadow-rgb": shadow_rgb(ground_hex)}
    for lv in LEVELS:
        out[f"--mh-elev-{lv}"] = elevation_shadow(lv, scale=scale)
    for lv in (1, 2, 3):
        out[f"--mh-elev-drop-{lv}"] = elevation_drop_filter(lv, scale=scale)
    return out
