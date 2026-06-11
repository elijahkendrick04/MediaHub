"""Cohen-Or harmonic-template fit — Phase 1.6 Stage H.

Implements the seven hue templates from Cohen-Or, Sorkine, Gal,
Leyvand & Xu, "Color Harmonization" (SIGGRAPH 2006). Given a set
of hues from a palette, search all 7 templates × 72 rotation
steps for the template + rotation that minimises out-of-band
hue distance. The winning template's energy quantifies how
"harmonic" the palette is.

Templates from the paper, §3:
    i — one narrow band (18° wide)
    V — one wide band (94° wide)
    L — narrow + wide, 90° apart
    I — two narrow bands, 180° apart
    T — half-wheel (180° wide)
    Y — narrow + wide, 180° apart
    X — two wide bands, 180° apart

For each template and rotation θ, energy = Σ d(h_i, T) where
d(h_i, T) is the shortest angular distance from hue h_i to the
nearest edge of any band in the rotated template (0 if inside a
band).

Computational cost: 7 templates × 72 rotation steps × N hues ≈
500 distance computations for typical 7-hue palettes. Sub-
millisecond on any modern hardware; runs once at palette
derivation, never per-request.

References:
    - Cohen-Or et al. (SIGGRAPH 2006) — original paper
    - github.com/tasoshi/colorharmonization — reference Python port
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import List, Tuple


__all__ = [
    "HARMONIC_TEMPLATES",
    "HarmonicFit",
    "fit_harmonic_template",
    "template_band_edges",
]


# (centre_offset_deg, width_deg) — see Cohen-Or 2006, Figure 4.
HARMONIC_TEMPLATES: dict[str, list[Tuple[float, float]]] = {
    "i": [(0.0, 18.0)],
    "V": [(0.0, 94.0)],
    "L": [(0.0, 18.0), (90.0, 78.0)],
    "I": [(0.0, 18.0), (180.0, 18.0)],
    "T": [(0.0, 180.0)],
    "Y": [(0.0, 18.0), (180.0, 94.0)],
    "X": [(0.0, 94.0), (180.0, 94.0)],
}


@dataclass
class HarmonicFit:
    """The best-fit harmonic template for a set of hues."""

    template: str  # one of i / V / L / I / T / Y / X
    rotation: float  # best rotation in degrees [0, 360)
    energy: float  # total out-of-band distance (lower = better)
    hue_count: int  # how many hues were scored
    template_bands: list[Tuple[float, float]] = field(default_factory=list)

    def to_dict(self) -> dict:
        # template_bands is list[tuple] in memory; JSON round-trip
        # converts tuples to lists, so normalise to list[list] here so
        # in-memory and on-disk representations compare equal.
        d = asdict(self)
        d["template_bands"] = [list(b) for b in self.template_bands]
        return d


def _angular_min(h: float, low: float, high: float) -> float:
    """Shortest angular distance from hue h to the band [low, high].

    All angles in degrees. The band is interpreted on a circle so
    crossing 0°/360° is handled correctly. Inside the band → 0.
    """
    h = h % 360.0
    low = low % 360.0
    high = high % 360.0
    # Two cases: band doesn't wrap (low <= high), or does (low > high).
    if low <= high:
        if low <= h <= high:
            return 0.0
        # Distance to either edge.
        d_low = min(abs(h - low), 360.0 - abs(h - low))
        d_high = min(abs(h - high), 360.0 - abs(h - high))
        return min(d_low, d_high)
    # Wrapped band: [low, 360) ∪ [0, high]
    if h >= low or h <= high:
        return 0.0
    # Distance to the two edges
    d_low = min(abs(h - low), 360.0 - abs(h - low))
    d_high = min(abs(h - high), 360.0 - abs(h - high))
    return min(d_low, d_high)


def template_band_edges(
    bands: List[Tuple[float, float]],
    rotation: float,
) -> List[Tuple[float, float]]:
    """Return each band as (low_deg, high_deg) after rotating by
    ``rotation`` degrees. All values in [0, 360)."""
    out: list[Tuple[float, float]] = []
    for centre, width in bands:
        c = (centre + rotation) % 360.0
        half = width / 2.0
        low = (c - half) % 360.0
        high = (c + half) % 360.0
        out.append((low, high))
    return out


def _template_energy(
    hues: List[float],
    bands: List[Tuple[float, float]],
    rotation: float,
) -> float:
    """Sum of out-of-band distances for all hues vs the rotated template."""
    edges = template_band_edges(bands, rotation)
    total = 0.0
    for h in hues:
        # Each hue's distance is the MIN over the template's bands
        # (i.e. the hue snaps to the nearest band).
        per_band = [_angular_min(h, low, high) for low, high in edges]
        total += min(per_band) if per_band else 0.0
    return total


def fit_harmonic_template(
    hues: List[float],
    *,
    rotation_step: float = 5.0,
) -> HarmonicFit:
    """Find the harmonic template + rotation that minimises out-of-
    band distance for the given hue list.

    Empty input returns the ``i`` template at rotation 0 with
    energy 0 (a trivial fit). Single-hue input is also a trivial
    fit; the more interesting cases are 3+ hues where templates
    actually compete.

    The rotation grid resolution is controlled by ``rotation_step``
    (default 5°, giving 72 rotations per template).
    """
    if not hues:
        return HarmonicFit(
            template="i",
            rotation=0.0,
            energy=0.0,
            hue_count=0,
            template_bands=list(HARMONIC_TEMPLATES["i"]),
        )

    normalised = [h % 360.0 for h in hues]
    best_template = "i"
    best_rotation = 0.0
    best_energy = float("inf")

    # Generate rotation candidates: 0, step, 2*step, …, 360-step.
    step = max(rotation_step, 1.0)
    rotations: list[float] = []
    r = 0.0
    while r < 360.0:
        rotations.append(r)
        r += step

    for tname, bands in HARMONIC_TEMPLATES.items():
        for rot in rotations:
            energy = _template_energy(normalised, bands, rot)
            if energy < best_energy:
                best_energy = energy
                best_template = tname
                best_rotation = rot

    return HarmonicFit(
        template=best_template,
        rotation=round(best_rotation, 1),
        energy=round(best_energy, 2),
        hue_count=len(hues),
        template_bands=list(HARMONIC_TEMPLATES[best_template]),
    )
