"""Wheel-arithmetic companion accent for thin brand palettes (Canva gap C10).

A one- or two-colour club still deserves a lively card. Where the renderer's
existing accent repair only ever tints the *same* hue toward white/black
(strictly monochrome), Canva/Coolors/Adobe complete a thin palette with a
**hue-arithmetic companion** — a complementary (or split-complementary) accent
re-matched to the brand colour's lightness/chroma band. A geometric hue
relationship reads as intentional, so the card gets a real second colour instead
of a darker shade of the first.

This module proposes those companions deterministically:

  * only when the kit has fewer than two distinct brandable colours (reusing
    ``roles.assign_brand_roles`` — the same brandability + CIEDE2000 distinctness
    gates the palette engine already trusts);
  * candidates are the complementary (+180°) and split-complementary (+150° /
    +210°) hues at the primary's own HCT chroma, tone-stepped only as far as the
    **APCA ink gate** demands (legibility beats art, exactly like every other
    accent path);
  * scored by the Cohen-Or harmonic fit (``harmony.fit_harmonic_template``);
  * emitted with a plain-English provenance for the decision trace.

This is brand-*derived* arithmetic — the same class of maths ``darken()`` already
is — not colour invention. But because it introduces a hue the club didn't
upload, the caller MUST gate it behind an explicit operator opt-in (the BrandKit
``allow_derived_accent`` flag or the ``MEDIAHUB_DERIVED_ACCENT`` env switch),
default OFF. See :func:`mediahub.graphic_renderer.render._derived_accent_enabled`.

Deterministic and pure: same seed → same companion. No LLM, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from materialyoucolor.hct import Hct

from .harmony import fit_harmonic_template
from .roles import BRANDABLE_CHROMA_MIN

__all__ = ["CompanionAccent", "derive_companion_accent"]

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

# The wheel-arithmetic candidates, in preference order. Complementary first (the
# "complementary pop" recipe designers rely on); the two split-complementary
# neighbours are the fallbacks when the direct complement can't be made legible.
_OFFSETS: tuple[tuple[float, str], ...] = (
    (180.0, "complementary"),
    (150.0, "split-complementary (+150°)"),
    (210.0, "split-complementary (+210°)"),
)


@dataclass(frozen=True)
class CompanionAccent:
    """A derived accent hue for a thin palette, with provenance."""

    hex: str
    provenance: str  # e.g. "derived complementary of #0E2A47"
    template: str  # winning Cohen-Or harmonic template
    energy: float  # harmonic-fit energy (lower = more harmonic)
    offset: float  # the hue rotation applied, in degrees


def _is_hex(value) -> bool:
    return isinstance(value, str) and bool(_HEX_RE.match(value.strip()))


def _to_hct(hex_str: str) -> Hct:
    return Hct.from_int(0xFF000000 | int(hex_str.lstrip("#"), 16))


def _hct_hex(hue: float, chroma: float, tone: float) -> str:
    c = Hct.from_hct(hue % 360.0, max(0.0, chroma), max(0.0, min(100.0, tone)))
    return f"#{c.to_int() & 0xFFFFFF:06X}"


def _legible_candidate(hue: float, chroma: float, ground_hex: str) -> Optional[str]:
    """A hex at ``hue``/``chroma`` that reads BOTH ways on ``ground_hex``, or None.

    Starts at the ground's own tone (the brand's lightness band) and steps toward
    the legible pole (lighter for a dark ground, darker for a light one) only as
    far as the APCA gate demands — so the companion stays as close to the brand's
    lightness band as legibility allows.
    """
    from mediahub.quality.compliance import is_legible

    g_tone = _to_hct(ground_hex).tone
    tones = [g_tone] + (
        [60.0, 70.0, 78.0, 85.0, 92.0] if g_tone < 50 else [42.0, 32.0, 24.0, 16.0, 10.0]
    )
    for tone in tones:
        cand = _hct_hex(hue, chroma, tone)
        if is_legible(cand, ground_hex) and is_legible(ground_hex, cand):
            return cand
    return None


def derive_companion_accent(
    primary_hex: str, extra_colours: Optional[list[str]] = None
) -> Optional[CompanionAccent]:
    """Propose a hue-arithmetic companion accent for a thin brand palette (C10).

    Returns ``None`` (no companion) when the kit already has two or more distinct
    brandable colours, when the primary isn't a parseable hex, or when the
    primary is a near-grey with no meaningful hue to complement. Otherwise builds
    the complementary + split-complementary candidates at the primary's chroma,
    keeps only those the APCA gate can make legible on the primary ground, scores
    the survivors by Cohen-Or harmonic fit, and returns the lowest-energy winner
    with its provenance. Fully deterministic.
    """
    if not _is_hex(primary_hex):
        return None
    # Thinness gate: reuse the palette engine's brandability + distinctness maths.
    from .roles import assign_brand_roles

    seeds = [primary_hex] + [c for c in (extra_colours or []) if _is_hex(c)]
    assignment = assign_brand_roles(seeds)
    if assignment.secondary or assignment.tertiary:
        return None  # ≥ 2 distinct brandable colours — not a thin palette

    p = _to_hct(primary_hex)
    if p.chroma < BRANDABLE_CHROMA_MIN:
        return None  # a near-grey primary has no hue worth complementing

    best: Optional[tuple[tuple[float, int, str], CompanionAccent]] = None
    for pref, (offset, label) in enumerate(_OFFSETS):
        cand = _legible_candidate((p.hue + offset) % 360.0, p.chroma, primary_hex)
        if cand is None:
            continue
        fit = fit_harmonic_template([p.hue, _to_hct(cand).hue])
        companion = CompanionAccent(
            hex=cand,
            provenance=f"derived {label} of {primary_hex.upper()}",
            template=fit.template,
            energy=fit.energy,
            offset=offset,
        )
        # Rank by harmonic energy (lower = better), then the offset-table
        # preference order (complementary first — the "complementary pop" recipe
        # designers rely on; the Cohen-Or fit rarely separates a 2-hue set), then
        # the hex. A total, deterministic ordering.
        key = (fit.energy, pref, cand)
        if best is None or key < best[0]:
            best = (key, companion)
    return best[1] if best is not None else None
