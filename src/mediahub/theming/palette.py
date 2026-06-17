"""Tonal-palette derivation for the Adaptive Theming Engine.

Given a seed hex, build:

  * 5 brand-derived tonal ramps via the Material 3 TonalSpot scheme:
      primary         — seed hue, chroma capped at MD3 default (~36)
      secondary       — same hue, chroma 16 (muted)
      tertiary        — hue + 60°, chroma 24 (analogous accent)
      neutral         — same hue, chroma 4 (page background family)
      neutral_variant — same hue, chroma 8 (borders / dividers)

  * 4 status anchor ramps at fixed hues:
      error           — hue 25° (MD3 default; warm red)
      success         — hue 142° (emerald-green, safe across CVD)
      warning         — hue 80° (amber)
      info            — hue 240° (blue, complementary to most brands)

Status palettes are NOT derived from the brand seed — that would let a
red-branded swimming club's "danger" red be visually identical to
their brand, which defeats WCAG 1.4.1 and the cross-cultural status
semantics established by Aslam (2006) and Elliot & Maier (2007).

Each ramp materialises the 13 standard MD3 tones {0, 10, 20, 30, 40,
50, 60, 70, 80, 90, 95, 99, 100} via materialyoucolor's TonalPalette
implementation, which respects HCT-gamut chroma capping at each tone
— a fluorescent-yellow seed automatically desaturates at light tones
without us doing anything explicit.

References:
  - Material Design 3 — Color Roles: m3.material.io/styles/color/roles
  - material-color-utilities/concepts/dynamic_color_scheme.md
  - HCT vs CAM16 vs OKLCH: facelessuser.github.io/coloraide/colors/hct/
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from materialyoucolor.hct import Hct
from materialyoucolor.scheme.scheme_tonal_spot import SchemeTonalSpot
from materialyoucolor.palettes.tonal_palette import TonalPalette


__all__ = [
    "TonalRamp",
    "DerivedPalette",
    "derive_palette",
    "derive_palette_multi",
    "TONE_STOPS",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Material 3's canonical 13 tone stops. Tone 0 = black, 100 = white.
TONE_STOPS: tuple[int, ...] = (0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 99, 100)

# Fixed hue / chroma anchors for the four status families. These DO NOT
# move with the brand seed — they're locked by hue family per
# cross-cultural-semantics research (Aslam 2006, WCAG 1.4.1).
STATUS_ANCHORS: dict[str, tuple[float, float]] = {
    "error": (25.0, 84.0),  # MD3 default — warm signal red
    "success": (142.0, 50.0),  # emerald, safe across CVD
    "warning": (80.0, 70.0),  # amber, cross-culturally stable per Aslam
    "info": (240.0, 45.0),  # blue, complementary to most brand hues
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TonalRamp:
    """A single tonal palette — fixed hue/chroma, 13 lightness stops."""

    name: str
    hue: float
    chroma: float
    tones: dict[int, str]  # tone (0..100) → CSS hex

    def tone(self, t: int) -> str:
        """Return the hex for a specific tone, or the closest available."""
        if t in self.tones:
            return self.tones[t]
        # closest from TONE_STOPS
        closest = min(TONE_STOPS, key=lambda k: abs(k - t))
        return self.tones[closest]


@dataclass
class DerivedPalette:
    """Nine tonal ramps + the seed metadata."""

    seed_hex: str
    seed_hct: tuple[float, float, float]
    primary: TonalRamp
    secondary: TonalRamp
    tertiary: TonalRamp
    neutral: TonalRamp
    neutral_variant: TonalRamp
    error: TonalRamp
    success: TonalRamp
    warning: TonalRamp
    info: TonalRamp
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    decision_trace: list[str] = field(default_factory=list)

    def all_ramps(self) -> list[TonalRamp]:
        return [
            self.primary,
            self.secondary,
            self.tertiary,
            self.neutral,
            self.neutral_variant,
            self.error,
            self.success,
            self.warning,
            self.info,
        ]

    def ramp_by_name(self, name: str) -> TonalRamp:
        for r in self.all_ramps():
            if r.name == name:
                return r
        raise KeyError(name)


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


def _hex_to_argb(h: str) -> int:
    return 0xFF000000 | int(h.lstrip("#")[:6], 16)


def _argb_to_hex(argb: int) -> str:
    return f"#{argb & 0xFFFFFF:06X}"


def _materialise(palette: TonalPalette, name: str) -> TonalRamp:
    tones = {t: _argb_to_hex(palette.tone(t)) for t in TONE_STOPS}
    return TonalRamp(name=name, hue=palette.hue, chroma=palette.chroma, tones=tones)


def _status_ramp(name: str) -> TonalRamp:
    hue, chroma = STATUS_ANCHORS[name]
    palette = TonalPalette.from_hue_and_chroma(hue, chroma)
    return _materialise(palette, name)


def derive_palette(seed_hex: str) -> DerivedPalette:
    """Build a DerivedPalette from a seed hex.

    Implementation: instantiate ``SchemeTonalSpot(seed_hct, False, 0.0)``
    and extract its underlying tonal palettes. SchemeTonalSpot is the
    MD3-standard scheme with the canonical hue offsets:
       primary   — source hue
       secondary — same hue (chroma 16)
       tertiary  — source hue + 60° (chroma 24)
       neutral   — same hue (chroma 4)
       neutral_v — same hue (chroma 8)
    The chroma caps come from the SchemeTonalSpot constructor, which
    matches the MD3 defaults exactly.
    """
    trace: list[str] = []
    seed_argb = _hex_to_argb(seed_hex)
    seed_hct_obj = Hct.from_int(seed_argb)
    seed_hct = (seed_hct_obj.hue, seed_hct_obj.chroma, seed_hct_obj.tone)
    trace.append(
        f"seed: {seed_hex} → HCT(H={seed_hct[0]:.1f}, C={seed_hct[1]:.1f}, T={seed_hct[2]:.1f})"
    )

    scheme = SchemeTonalSpot(seed_hct_obj, False, 0.0)
    trace.append("scheme: SchemeTonalSpot (MD3 default) instantiated for light scheme")

    primary = _materialise(scheme.primary_palette, "primary")
    secondary = _materialise(scheme.secondary_palette, "secondary")
    tertiary = _materialise(scheme.tertiary_palette, "tertiary")
    neutral = _materialise(scheme.neutral_palette, "neutral")
    neutral_variant = _materialise(scheme.neutral_variant_palette, "neutral_variant")
    trace.append(
        f"brand ramps: primary(H={primary.hue:.0f} C={primary.chroma:.0f}), "
        f"secondary(H={secondary.hue:.0f} C={secondary.chroma:.0f}), "
        f"tertiary(H={tertiary.hue:.0f} C={tertiary.chroma:.0f}), "
        f"neutral(H={neutral.hue:.0f} C={neutral.chroma:.0f}), "
        f"neutral_variant(H={neutral_variant.hue:.0f} C={neutral_variant.chroma:.0f})"
    )

    error = _status_ramp("error")
    success = _status_ramp("success")
    warning = _status_ramp("warning")
    info = _status_ramp("info")
    trace.append(
        f"status ramps: fixed anchors error(H={STATUS_ANCHORS['error'][0]:.0f}), "
        f"success(H={STATUS_ANCHORS['success'][0]:.0f}), "
        f"warning(H={STATUS_ANCHORS['warning'][0]:.0f}), "
        f"info(H={STATUS_ANCHORS['info'][0]:.0f})"
    )

    return DerivedPalette(
        seed_hex=seed_hex.upper(),
        seed_hct=seed_hct,
        primary=primary,
        secondary=secondary,
        tertiary=tertiary,
        neutral=neutral,
        neutral_variant=neutral_variant,
        error=error,
        success=success,
        warning=warning,
        info=info,
        decision_trace=trace,
    )


# ---------------------------------------------------------------------------
# G1.20 — Brand-palette expansion to N custom club colours
# ---------------------------------------------------------------------------
# The single-seed engine derives `secondary` (muted, same hue) and `tertiary`
# (hue + 60°) from the one seed. When a club supplies their *own* secondary /
# accent colours, `derive_palette_multi` keeps the MD3-derived primary, neutral,
# neutral_variant and the four locked status ramps, but replaces the secondary
# and tertiary ramps with tonal ramps built from the club's real colours. The
# APCA-gated mapping of colour → slot lives in `roles.assign_brand_roles`.
#
# Back-compatibility is exact: with one (or zero) brandable colour the function
# returns `derive_palette(primary)` unchanged — same ramps, same trace — so a
# single-seed kit is byte-identical to the pre-G1.20 engine.


def _custom_ramp(name: str, seed_hex: str) -> TonalRamp:
    """Materialise a 13-tone ramp from a club colour's own HCT.

    Uses the colour's actual hue *and* chroma (gamut-mapped per tone by
    materialyoucolor), so the club's vivid gold stays vivid — unlike the
    MD3 scheme's deliberately-muted derived secondary. Mirrors the
    ``_status_ramp`` construction so the tone geometry is identical.
    """
    argb = _hex_to_argb(seed_hex)
    hct = Hct.from_int(argb)
    palette = TonalPalette.from_hue_and_chroma(hct.hue, hct.chroma)
    return _materialise(palette, name)


def derive_palette_multi(seeds: list[str]) -> DerivedPalette:
    """Build a DerivedPalette from N custom club colours.

    The first brandable colour (APCA-gated) anchors the palette exactly as a
    single seed would — primary / neutral / neutral_variant / status ramps are
    all derived from it via :func:`derive_palette`. Any additional distinct
    brandable colours replace the ``secondary`` / ``tertiary`` ramps with the
    club's real colours.

    With ≤ 1 brandable colour this returns :func:`derive_palette` output
    unchanged (byte-identical single-seed behaviour). Never raises.
    """
    # Local import: `roles` imports from `palette`, so importing it at module
    # load time would create a cycle. Deferring to call time keeps `palette` a
    # leaf module (the established BrandKit pattern).
    from .roles import assign_brand_roles

    assignment = assign_brand_roles(seeds)
    # ``primary`` is only None when no parseable hex was supplied at all; fall
    # back to the generic-default navy (matches seed_extract's fallback) so
    # this never feeds garbage into derive_palette.
    primary_hex = assignment.primary or "#0E2A47"

    base = derive_palette(primary_hex)

    # ≤ 1 brandable colour → nothing to expand; identical to single-seed.
    if not assignment.secondary and not assignment.tertiary:
        return base

    if assignment.secondary:
        base.secondary = _custom_ramp("secondary", assignment.secondary)
    if assignment.tertiary:
        base.tertiary = _custom_ramp("tertiary", assignment.tertiary)

    base.decision_trace.append(
        "multi-colour expansion: "
        + ", ".join(f"{role}={hexv}" for role, hexv in assignment.slots().items())
    )
    base.decision_trace.extend(assignment.trace)
    return base
