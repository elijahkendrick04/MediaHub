"""Colour-vision-deficiency simulation for the Adaptive Theming Engine.

Implements Machado, Oliveira & Fernandes (2009), "A Physiologically-
based Model for Simulation of Color Vision Deficiency". The Machado
matrices are what Chromium/Blink ships natively for the
`vision_deficiency.cc` simulator that Chrome DevTools exposes.

Per CVD type at severity 1.0 (full dichromacy):

  * Deuteranopia (deutan)  — absence of M-cones (green). Most common
                             (~6% of males). Confuses red-green along
                             a similar axis to protanopia but preserves
                             luminance perception.
  * Protanopia  (protan)   — absence of L-cones (red). Reds appear
                             dark / lose luminance.
  * Tritanopia  (tritan)   — absence of S-cones (blue). Confuses
                             blue-yellow. Rare (< 0.01%).

The matrices below come from the UFRGS publication
(www.inf.ufrgs.br/~oliveira/pubs_files/CVD_Simulation/CVD_Simulation.html)
and are independently confirmed by the Chromium source
(chromium/third_party/blink/renderer/core/css/vision_deficiency.cc).

For each pair we care about (brand vs error, brand vs success, …) the
collision check is:

  1. Apply the Machado matrix at severity 1.0 to both sRGB colours
     (linearise → multiply → re-encode).
  2. Convert both simulated colours to CIELAB.
  3. Compute ΔE2000.
  4. Distinguishable iff ΔE2000 ≥ 10 (ColorBrewer's working floor for
     categorical-palette legibility).

References:
  - Machado, Oliveira & Fernandes (2009), IEEE TVCG vol 15.
  - Chromium vision_deficiency.cc — chromium.googlesource.com.
  - DaltonLens review of CVD libraries — daltonlens.org/opensource-cvd-simulation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from coloraide import Color


__all__ = [
    "simulate",
    "delta_e_under_cvd",
    "CVDPair",
    "CVD",
    "CVD_TYPES",
    "DEUTAN_MATRIX",
    "PROTAN_MATRIX",
    "TRITAN_MATRIX",
]


CVD = Literal["deutan", "protan", "tritan"]
CVD_TYPES: tuple[CVD, ...] = ("deutan", "protan", "tritan")


# ---------------------------------------------------------------------------
# Machado matrices at severity 1.0 (full dichromacy)
# ---------------------------------------------------------------------------
# Source: Machado et al. 2009 (Table 1) and Chromium vision_deficiency.cc.
# These operate on LINEAR-LIGHT sRGB (not gamma-corrected).

DEUTAN_MATRIX = np.array([
    [0.367,  0.861, -0.228],
    [0.280,  0.673,  0.047],
    [-0.012, 0.043,  0.969],
])

PROTAN_MATRIX = np.array([
    [0.152, 1.053, -0.205],
    [0.115, 0.786,  0.099],
    [-0.004,-0.048, 1.052],
])

TRITAN_MATRIX = np.array([
    [1.256, -0.077, -0.179],
    [-0.078, 0.931,  0.148],
    [0.005,  0.691,  0.304],
])

_MATRICES: dict[str, np.ndarray] = {
    "deutan": DEUTAN_MATRIX,
    "protan": PROTAN_MATRIX,
    "tritan": TRITAN_MATRIX,
}


# ---------------------------------------------------------------------------
# sRGB ↔ linear-light helpers
# ---------------------------------------------------------------------------


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def _hex_to_linear(hex_str: str) -> np.ndarray:
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(ch + ch for ch in h)
    r, g, b = (int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))
    return np.array([_srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)])


def _linear_to_hex(lin: np.ndarray) -> str:
    rgb = [round(_linear_to_srgb(float(c)) * 255) for c in lin]
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, v)) for v in rgb))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def simulate(hex_color: str, cvd: CVD) -> str:
    """Return the hex value a viewer with `cvd` perceives for `hex_color`.

    `cvd` must be one of `deutan`, `protan`, `tritan`.
    """
    if cvd not in _MATRICES:
        raise ValueError(f"unknown CVD type {cvd!r}; expected one of {CVD_TYPES}")
    matrix = _MATRICES[cvd]
    linear = _hex_to_linear(hex_color)
    simulated_linear = matrix @ linear
    return _linear_to_hex(simulated_linear)


@dataclass
class CVDPair:
    cvd: CVD
    a_hex: str
    b_hex: str
    a_simulated: str
    b_simulated: str
    delta_e_2000: float
    distinguishable: bool   # ΔE2000 ≥ 10


def delta_e_under_cvd(a_hex: str, b_hex: str, cvd: CVD,
                      *, threshold: float = 10.0) -> CVDPair:
    """Return the CIEDE2000 ΔE between two colours after both are
    Machado-simulated for the given CVD. Distinguishable iff
    ΔE2000 ≥ `threshold` (default 10, the ColorBrewer floor)."""
    a_sim = simulate(a_hex, cvd)
    b_sim = simulate(b_hex, cvd)
    delta = Color(a_sim).delta_e(Color(b_sim), method="2000")
    return CVDPair(
        cvd=cvd,
        a_hex=a_hex.upper(),
        b_hex=b_hex.upper(),
        a_simulated=a_sim,
        b_simulated=b_sim,
        delta_e_2000=round(delta, 2),
        distinguishable=delta >= threshold,
    )
