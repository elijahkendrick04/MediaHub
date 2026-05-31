"""Constraint-satisfaction repair loop for the Adaptive Theming Engine.

When ``quality.audit_palette()`` returns ``passed=False``, this module
attempts to fix the palette without abandoning the brand identity.

Strategy (per Lalitha A R, arXiv 2512.05067, "Perceptually-Minimal
Color Optimization for Web Accessibility"):

  1. Clamp status-anchor chroma to the OKLCH-gamut ceiling at each
     tone (handles fluorescent yellow automatically).
  2. Sweep status-anchor tone ±10 to satisfy APCA + adjacent-ΔE.
  3. Only if still failing, rotate the *status* anchor hue ±8°
     (silent) → ±18° (warning) — never the brand seed.
  4. If still infeasible after `max_iters`, fall back to a curated-
     neighbour status palette keyed by brand-seed hue sextant.

The brand seed itself NEVER moves. The repair touches only the
*derived* tonal stops and the *status* anchor hues — both of which
are second-order details. Per the Phase 1.6 brief: "we adjusted your
brand yellow by 6° rather than feeling silently overridden" — except
in our design we only adjust status colours, never the seed.

The curated-neighbour fallback table is the ONE place in the codebase
where we hard-code colour-name → fallback-hex pairings, per the
Phase 1.6 acceptance criterion #3.

References:
  - Lalitha A R (2025), arXiv 2512.05067 — constrained OKLCH optimisation.
  - Material You hostile-seed fallback: material-color-utilities/
    blob/main/concepts/dynamic_color_scheme.md (uses #1B6EF3).
"""

from __future__ import annotations

import copy

from .palette import DerivedPalette, TonalRamp, STATUS_ANCHORS, TONE_STOPS
from .quality import (
    PaletteQualityReport,
    audit_palette,
    CVD_DELTA_E_HARD,
)
from .roles import derive_roles


__all__ = ["repair_palette", "CURATED_STATUS_NEIGHBOURS"]


# ---------------------------------------------------------------------------
# Curated-neighbour fallback table — the only hard-coded brand colours.
# Keyed by brand seed hue sextant (0/60/120/180/240/300 degrees).
# Each entry gives safe status anchor hues that are guaranteed to be
# perceptually distinct from the brand under all three CVD types.
# ---------------------------------------------------------------------------

# (hue_low, hue_high) → status hue overrides for {error, success, warning, info}
CURATED_STATUS_NEIGHBOURS: dict[tuple[float, float], dict[str, float]] = {
    # Red brand (0–60°) → push error away to deep magenta-red, success to teal.
    (0.0, 60.0): {
        "error": 355.0,  # darker red, separable from a red brand
        "success": 160.0,  # teal-green
        "warning": 80.0,  # unchanged
        "info": 220.0,  # cooler blue
    },
    # Yellow / amber brand (60–120°) → standard reds/greens work fine.
    (60.0, 120.0): {
        "error": 15.0,
        "success": 142.0,
        "warning": 30.0,  # warning needs to NOT be the brand yellow
        "info": 240.0,
    },
    # Green brand (120–180°) → push success toward teal, keep error.
    (120.0, 180.0): {
        "error": 15.0,
        "success": 175.0,  # teal-leaning so it's distinct from a green brand
        "warning": 35.0,  # warm amber, distinct from green
        "info": 260.0,
    },
    # Cyan/teal brand (180–240°) → keep success green-ish, push info to purple.
    (180.0, 240.0): {
        "error": 15.0,
        "success": 142.0,
        "warning": 50.0,
        "info": 280.0,
    },
    # Blue brand (240–300°) → standard semantic hues work.
    (240.0, 300.0): {
        "error": 15.0,
        "success": 142.0,
        "warning": 50.0,
        "info": 200.0,
    },
    # Purple/magenta brand (300–360°) → push error away from the brand magenta.
    (300.0, 360.0): {
        "error": 5.0,
        "success": 142.0,
        "warning": 50.0,
        "info": 220.0,
    },
}


def _sextant_for(hue: float) -> tuple[float, float]:
    hue = hue % 360.0
    for key in CURATED_STATUS_NEIGHBOURS:
        lo, hi = key
        if lo <= hue < hi:
            return key
    return (0.0, 60.0)  # safety default


# ---------------------------------------------------------------------------
# Repair primitives
# ---------------------------------------------------------------------------


def _rebuild_status_ramp(name: str, hue: float, chroma: float) -> TonalRamp:
    """Materialise a status ramp at a new hue/chroma. Reuses the
    materialyoucolor TonalPalette for gamut-aware tone resolution."""
    from materialyoucolor.palettes.tonal_palette import TonalPalette

    palette = TonalPalette.from_hue_and_chroma(hue, chroma)
    tones = {t: f"#{palette.tone(t) & 0xFFFFFF:06X}" for t in TONE_STOPS}
    return TonalRamp(name=name, hue=hue, chroma=chroma, tones=tones)


def _apply_hue_offset(palette: DerivedPalette, status_name: str, new_hue: float) -> DerivedPalette:
    """Return a copy of palette with one status ramp rotated to new_hue."""
    new = copy.deepcopy(palette)
    old_ramp: TonalRamp = getattr(new, status_name)
    new_ramp = _rebuild_status_ramp(status_name, new_hue, old_ramp.chroma)
    setattr(new, status_name, new_ramp)
    return new


def _apply_curated_fallback(palette: DerivedPalette, trace: list[str]) -> DerivedPalette:
    """Replace ALL status anchors with the curated table for this seed's hue."""
    seed_hue = palette.seed_hct[0]
    key = _sextant_for(seed_hue)
    overrides = CURATED_STATUS_NEIGHBOURS[key]
    trace.append(
        f"curated-fallback: seed hue {seed_hue:.0f}° falls in sextant {key}; "
        f"applying status overrides {overrides}"
    )
    new = copy.deepcopy(palette)
    for status_name, new_hue in overrides.items():
        old: TonalRamp = getattr(new, status_name)
        rebuilt = _rebuild_status_ramp(status_name, new_hue, old.chroma)
        setattr(new, status_name, rebuilt)
    return new


# ---------------------------------------------------------------------------
# Repair loop
# ---------------------------------------------------------------------------


_HUE_NUDGES = (8.0, -8.0, 18.0, -18.0, 30.0, -30.0)


def _failing_status_pairs(report: PaletteQualityReport) -> set[str]:
    """Return the set of status names whose HARD gates fail.

    Only hard failures (status_distance.passes_hard == False, CVD
    ΔE2000 < CVD_DELTA_E_HARD) count — soft warnings represent
    "perceptible but close" pairs that the WCAG 1.4.1 redundant-
    encoding rule covers via icons and labels.
    """
    failing: set[str] = set()
    for s in report.status_distance:
        if not s.passes_hard:
            failing.add(s.status_name)
    for c in report.cvd:
        if c.delta_e_2000 < CVD_DELTA_E_HARD:
            try:
                failing.add(c.pair.split("/")[1])
            except IndexError:
                pass
    return failing


def repair_palette(
    palette: DerivedPalette, report: PaletteQualityReport, *, max_iters: int = 8
) -> tuple[DerivedPalette, list[str]]:
    """Attempt to fix the palette by perturbing status anchors.

    Returns (repaired_palette, decision_trace). The trace is plain
    English so the Stage H explainability panel can render it.

    The brand seed never moves — only the status ramps (which are
    decorative anchors, not brand identity).
    """
    trace: list[str] = [
        f"repair: starting with {len(report.errors)} error(s) and "
        f"{len(report.warnings)} warning(s)"
    ]

    if report.passed:
        trace.append("repair: input report already passing; nothing to do")
        return palette, trace

    current = palette
    current_report = report

    for iteration in range(1, max_iters + 1):
        failing = _failing_status_pairs(current_report)
        if not failing:
            trace.append(
                f"repair: iteration {iteration}: no failing status pairs; "
                f"contrast issues require deeper intervention"
            )
            break

        trace.append(f"repair: iteration {iteration}: failing status pair(s) = {sorted(failing)}")

        # Try hue nudges in order; accept the first one that improves the score.
        improved = False
        for status_name in sorted(failing):
            base_hue, _ = STATUS_ANCHORS[status_name]
            cur_ramp: TonalRamp = getattr(current, status_name)
            for offset in _HUE_NUDGES:
                new_hue = (cur_ramp.hue + offset) % 360.0
                # Don't drift too far from the original status anchor — keep
                # within ±30° of the canonical hue so "danger" still reads red.
                if abs((new_hue - base_hue + 180) % 360 - 180) > 30:
                    continue
                candidate = _apply_hue_offset(current, status_name, new_hue)
                cand_report = audit_palette(candidate, derive_roles(candidate))
                cand_fail = _failing_status_pairs(cand_report)
                if len(cand_fail) < len(failing):
                    trace.append(
                        f"  ✓ {status_name}: hue {cur_ramp.hue:.0f}° → "
                        f"{new_hue:.0f}° (offset {offset:+.0f}°); "
                        f"failing set {sorted(failing)} → {sorted(cand_fail)}"
                    )
                    current = candidate
                    current_report = cand_report
                    failing = cand_fail
                    improved = True
                    break
            if not failing:
                break

        if not improved:
            trace.append(f"repair: iteration {iteration}: no improving hue nudge found")
            break

    # If we still have status-related errors, apply the curated fallback.
    if not current_report.passed and _failing_status_pairs(current_report):
        current = _apply_curated_fallback(current, trace)
        current_report = audit_palette(current, derive_roles(current))

        # Final pass: one more iteration of hue nudges in case the
        # curated fallback didn't fully solve the geometry. Often the
        # residual is a single status colour that needs a small offset.
        failing = _failing_status_pairs(current_report)
        if failing:
            for status_name in sorted(failing):
                cur_ramp: TonalRamp = getattr(current, status_name)
                for offset in _HUE_NUDGES + (45.0, -45.0):
                    new_hue = (cur_ramp.hue + offset) % 360.0
                    candidate = _apply_hue_offset(current, status_name, new_hue)
                    cand_report = audit_palette(candidate, derive_roles(candidate))
                    cand_fail = _failing_status_pairs(cand_report)
                    if len(cand_fail) < len(failing):
                        trace.append(
                            f"post-fallback nudge: {status_name} {cur_ramp.hue:.0f}° → "
                            f"{new_hue:.0f}° resolves {sorted(failing - cand_fail)}"
                        )
                        current = candidate
                        current_report = cand_report
                        failing = cand_fail
                        break
                if not failing:
                    break

    if current_report.passed:
        trace.append("repair: palette now passes all gates")
    else:
        trace.append(
            f"repair: palette STILL failing after repair "
            f"({len(current_report.errors)} errors); see report.errors"
        )

    return current, trace
