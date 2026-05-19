"""Logo chip-vs-bare decision for the Adaptive Theming Engine.

Phase 1.6 Stage F's core algorithm: given an uploaded logo's
dominant colour and the current surface colour, decide whether
the logo should sit on a neutral chip (safe-by-default) or
render bare (when it's already visually distinct from the
surface).

Two gates both must pass for "bare":

  1. ΔE2000(dominant, surface) >= 15
     The logo's dominant colour is perceptually distinct from
     the surface in CIELAB-space. Below 15 the logo blurs into
     the surface even with strong luminance contrast.

  2. |APCA Lc(dominant, surface)| >= 45
     The logo has enough perceptual contrast to read on the
     surface, regardless of polarity. Below 45 the edges blur.
     The absolute value handles both polarities: dark logos on
     light surfaces (positive Lc) and light logos on dark
     surfaces (negative Lc) — hence "dual-polarity".

Either gate failing → chip. Both gates passing → bare.

No I/O; pure data. The decision is deterministic and inexpensive
(~0.1ms per call), so it runs synchronously at request time
inside the page-render helper.

References:
  - Stage B's contrast.py for APCA Lc.
  - coloraide for CIEDE2000.
  - Sharma, Wu & Dalal (2005) — CIEDE2000 spec.
  - Andrew Somers — SAPC-APCA reference (apca-w3 v0.1.9).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from coloraide import Color

from .contrast import apca


__all__ = [
    "LogoChipDecision",
    "decide_logo_chip",
    "DE_MIN",
    "APCA_MIN",
    "DEFAULT_CHIP_COLOR",
]


# Gate thresholds. Keep these as module constants so tests can pin
# them and Stage J's polish phase can tune without surgery.
DE_MIN: float = 15.0
APCA_MIN: float = 45.0
DEFAULT_CHIP_COLOR: str = "#FFFFFF"


_HEX_RE = re.compile(r"#[0-9A-Fa-f]{3,8}\b")


@dataclass
class LogoChipDecision:
    """The output of decide_logo_chip(). Carries enough detail for
    the audit panel and the Stage H 'why?' explainer."""
    mode: Literal["chip", "bare"]
    chip_color: str            # background hex (only used when mode == "chip")
    dominant_hex: str          # canonicalised input
    surface_hex: str           # canonicalised input
    delta_e_2000: float        # gate 1 metric
    apca_lc: float             # signed APCA Lc, dominant on surface
    apca_abs: float            # |Lc|
    gate_de_passed: bool
    gate_apca_passed: bool
    reasoning: str             # human-readable, one sentence


def _normalise(hex_str: str) -> str:
    """Return a 6-digit upper-case hex, expanding 3-digit shorthand.

    Returns the input unchanged if not parseable — caller decides
    what to do (decide_logo_chip falls back to chip mode on bad
    inputs)."""
    if not isinstance(hex_str, str):
        return ""
    s = hex_str.strip()
    if not _HEX_RE.fullmatch(s):
        return ""
    body = s.lstrip("#")
    if len(body) == 3:
        body = "".join(ch + ch for ch in body)
    elif len(body) == 8:
        body = body[:6]  # drop alpha
    return "#" + body.upper()


def decide_logo_chip(
    dominant_hex: str,
    surface_hex: str,
    *,
    de_min: float = DE_MIN,
    apca_min: float = APCA_MIN,
    chip_color: str = DEFAULT_CHIP_COLOR,
) -> LogoChipDecision:
    """Decide whether a logo with the given dominant colour should
    render on a chip (safe-by-default) or bare against the surface.

    Parameters
    ----------
    dominant_hex : str
        The logo's dominant non-neutral colour (typically from the
        logo's AI vision pass at upload time).
    surface_hex : str
        The colour the logo is being rendered against — typically the
        resolved value of ``--mh-surface`` for the active theme.
    de_min : float, default 15.0
        ΔE2000 floor for the perceptual-distinctness gate.
    apca_min : float, default 45.0
        |APCA Lc| floor for the contrast gate.
    chip_color : str, default ``#FFFFFF``
        Background hex for the chip (only matters when ``mode='chip'``).

    Returns
    -------
    LogoChipDecision
        The decision with full metrics + a reasoning string.
    """
    dominant = _normalise(dominant_hex)
    surface = _normalise(surface_hex)

    # Bad inputs → safe-by-default: chip. The reasoning explains why.
    if not dominant or not surface:
        return LogoChipDecision(
            mode="chip",
            chip_color=chip_color,
            dominant_hex=dominant or "",
            surface_hex=surface or "",
            delta_e_2000=0.0,
            apca_lc=0.0,
            apca_abs=0.0,
            gate_de_passed=False,
            gate_apca_passed=False,
            reasoning="chip (default): could not parse one of the inputs",
        )

    delta_e = round(
        Color(dominant).delta_e(Color(surface), method="2000"),
        2,
    )
    lc = apca(dominant, surface)
    lc_abs = abs(lc)

    de_ok = delta_e >= de_min
    apca_ok = lc_abs >= apca_min

    if de_ok and apca_ok:
        mode = "bare"
        reasoning = (
            f"bare: dominant {dominant} clears both gates against "
            f"surface {surface} (ΔE2000={delta_e:.1f} ≥ {de_min}, "
            f"|Lc|={lc_abs:.1f} ≥ {apca_min})"
        )
    else:
        mode = "chip"
        which = []
        if not de_ok:
            which.append(f"ΔE2000={delta_e:.1f} < {de_min}")
        if not apca_ok:
            which.append(f"|Lc|={lc_abs:.1f} < {apca_min}")
        reasoning = (
            f"chip: dominant {dominant} too close to surface {surface} "
            f"({', '.join(which)})"
        )

    return LogoChipDecision(
        mode=mode,
        chip_color=chip_color,
        dominant_hex=dominant,
        surface_hex=surface,
        delta_e_2000=delta_e,
        apca_lc=lc,
        apca_abs=round(lc_abs, 1),
        gate_de_passed=de_ok,
        gate_apca_passed=apca_ok,
        reasoning=reasoning,
    )
