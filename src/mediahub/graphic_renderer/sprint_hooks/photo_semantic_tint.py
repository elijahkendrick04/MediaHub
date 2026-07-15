"""Photo-derived semantic tints (Canva gap analysis C4).

A post-render hook that classifies the card's hero photo into Android-Palette
semantic roles (``photo_palette.classify_swatches`` — deterministic PIL k-means +
verbatim AOSP scoring) and emits a small set of **non-brand-locked** paint tokens
the photo layouts can consume:

* ``--mh-photo-scrim`` — the ``dark_muted`` swatch blended toward black; a scrim
  that shares the photo's own shadow hue instead of a neutral rgba-black, so the
  darkened band reads as part of the same art-directed piece. APCA-gated: it is
  only emitted when the card's on-ground ink still clears the headline bar on it.
* ``--mh-photo-wash`` — the ``muted`` swatch; a quiet colour cast for the
  desaturated photo washes (replacing pure grayscale), applied at the layout's
  existing wash opacity so legibility maths are untouched.
* ``--mh-photo-glow`` — the ``dark_vibrant`` hue; the cutout glow / contact-shadow
  colour, a decorative accent behind the subject.

Hard rules (mirrors ``photo_tint``): brand hexes are NEVER touched — these are
brand-*independent* photo tints painted only through the new ``--mh-photo-*``
vars, which every layout consumes with a neutral ``var(..., <fallback>)`` so an
absent hook (no photo, disabled, or a photo with no usable swatch) renders
byte-identical. Deterministic (same HTML in → same HTML out). Every scrim
substitution is APCA-gated; the chosen swatches are recorded as an HTML comment
for the explainability sidecar.

Default ON: runs unless ``MEDIAHUB_PHOTO_SEMANTIC_TINT`` is explicitly falsy.
"""

from __future__ import annotations

import os
import re

from . import RenderHookCtx
from .photo_tint import _hero_photo_bytes, _is_hex

ORDER = 45  # after photo_tint (40) so it reads the resolved roles, before mono (90)

# The card's headline ink, matched as a *declaration* (``--mh-on-primary:#hex``)
# anywhere in the HTML. Taking the FIRST match lands on render.py's main role
# block, so an earlier hook's partial injected ``:root{}`` (e.g. photo_tint's
# surface tint) can't hide the ink the way a "last :root block" scan would.
_ON_PRIMARY_RE = re.compile(r"(?<![\w-])--mh-on-primary\s*:\s*(#[0-9A-Fa-f]{3,6})\b")

_FALSE = {"0", "false", "no", "off"}

# Scrim: blend the photo's own shadow swatch this far toward black. 0.70 keeps a
# hint of the photo's cast while staying dark enough to protect text.
_SCRIM_TO_BLACK = 0.70


def _enabled() -> bool:
    return os.environ.get("MEDIAHUB_PHOTO_SEMANTIC_TINT", "").strip().lower() not in _FALSE


def _swatch_hex(role_map, *roles):
    """First present swatch hex among ``roles`` (fallback chain), or ``None``."""
    for role in roles:
        s = role_map.get(role)
        if s is not None:
            return s.hex
    return None


def apply(html: str, ctx: RenderHookCtx) -> str:
    """Inject deterministic, photo-derived semantic tint vars (C4). No-op unless
    enabled, the card is v2, and it carries a photo with usable swatches."""
    if not _enabled() or not getattr(ctx, "is_v2", False):
        return html

    photo = _hero_photo_bytes(html)
    if photo is None:
        return html

    ink_match = _ON_PRIMARY_RE.search(html)
    ink = ink_match.group(1) if ink_match else ""
    if not _is_hex(ink):
        return html

    from mediahub.graphic_renderer.photo_palette import (
        classify_swatches,
        extract_palette,
        tint_toward,
    )
    from mediahub.quality.compliance import LC_LARGE
    from mediahub.theming.contrast import apca

    swatches = classify_swatches(extract_palette(photo))
    if all(v is None for v in swatches.values()):
        return html

    decls: dict[str, str] = {}
    notes: list[str] = []

    # Scrim — dark_muted (else dark_vibrant) pulled toward black, APCA-gated so a
    # bright-photo scrim can never end up too light to protect the ink.
    scrim_seed = _swatch_hex(swatches, "dark_muted", "dark_vibrant")
    if scrim_seed:
        scrim = tint_toward(scrim_seed, "#000000", _SCRIM_TO_BLACK)
        if abs(apca(ink, scrim)) >= LC_LARGE:
            decls["--mh-photo-scrim"] = scrim
            notes.append(f"scrim<-{scrim_seed}")

    # Wash — the muted swatch (else the vibrant one) as a quiet colour cast for
    # the desaturated photo washes; a decorative tint, not a text ground.
    wash_seed = _swatch_hex(swatches, "muted", "light_muted", "vibrant")
    if wash_seed:
        decls["--mh-photo-wash"] = wash_seed
        notes.append(f"wash<-{wash_seed}")

    # Glow — the dark_vibrant hue for the cutout glow / contact shadow.
    glow_seed = _swatch_hex(swatches, "dark_vibrant", "vibrant")
    if glow_seed:
        decls["--mh-photo-glow"] = glow_seed
        notes.append(f"glow<-{glow_seed}")

    if not decls:
        return html

    block = (
        f"<!-- mh-photo-roles: {' '.join(notes)} -->"
        "<style>:root{" + "".join(f"{k}:{v};" for k, v in decls.items()) + "}</style>"
    )
    if "</body>" in html:
        return html.replace("</body>", block + "</body>", 1)
    return html + block


__all__ = ["ORDER", "apply"]
