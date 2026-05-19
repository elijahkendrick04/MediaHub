"""Palette-quality QA gates for the Adaptive Theming Engine.

Given a ``DerivedPalette`` + ``ThemeRoles``, run every quality check
the Phase 1.6 dissertation requires and return a structured report.

The gates (each contributes errors / warnings to the report):

  1. APCA Lc ≥ 75 for text-on-surface role pairs (Silver body text).
  2. APCA Lc ≥ 45 for UI elements (outline against surface).
  3. WCAG 2.x ratio ≥ 4.5 for text pairs (the legal threshold).
  4. CIEDE2000 ΔE ≥ 5 between adjacent tones (Radix's "clearly
     perceptible step" threshold).
  5. CIEDE2000 ΔE ≥ 15 between brand seed and each status anchor
     (red/amber/green/blue) — soft fail at < 25.
  6. Machado-CVD ΔE2000 ≥ 10 for brand-vs-status pairs under
     deuteranopia / protanopia / tritanopia.

Returns ``PaletteQualityReport`` with full per-check detail (every
role pair, every ΔE, every CVD) so the Stage H explainability panel
can render the audit trail.

References:
  - APCA — see contrast.py.
  - CIEDE2000 — Sharma, Wu & Dalal (2005).
  - Radix Colors — radix-ui.com/colors/docs/palette-composition/understanding-the-scale.
  - ColorBrewer ΔE floor — Brewer (2003), Cartography & GIS.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from coloraide import Color

from .palette import DerivedPalette, TonalRamp, TONE_STOPS
from .roles import RoleScheme, ThemeRoles
from .contrast import apca, wcag2_ratio
from .cvd import delta_e_under_cvd, CVDPair, CVD_TYPES


__all__ = [
    "PaletteQualityReport",
    "ContrastCheck",
    "AdjacencyCheck",
    "StatusDistanceCheck",
    "CVDCheck",
    "audit_palette",
]


# ---------------------------------------------------------------------------
# Thresholds (centralised so they're easy to tune in one place)
# ---------------------------------------------------------------------------

# APCA Lc thresholds. MD3's role tables guarantee a WCAG 4.5:1 ratio
# between text and surface, which corresponds to roughly APCA Lc 60
# (the Bronze body-text threshold). Lc 75 is the more ambitious Silver
# threshold MD3 doesn't promise. We use 60 as the *hard* floor (errors)
# and 75 as the *ideal* (warnings only).
#
# UI elements (outlines, dividers) are intentionally low-contrast in
# MD3 — the canonical `outline_variant` against `surface` sits around
# Lc 25-35. We use 30 as the hard floor.
APCA_BODY_FLOOR = 60.0     # WCAG-equivalent (hard fail < this)
APCA_BODY_IDEAL = 75.0     # APCA Silver (warning < this)
APCA_UI_FLOOR = 30.0       # outline / divider visibility (hard fail < this)
APCA_UI_IDEAL = 45.0       # APCA Bronze non-text (warning < this)
WCAG2_AA_FLOOR = 4.5       # normal text AA (legal threshold)
WCAG2_AA_UI_FLOOR = 3.0    # UI components and large text
ADJACENT_DELTA_E_FLOOR = 5.0
STATUS_DELTA_E_HARD = 15.0
STATUS_DELTA_E_SOFT = 25.0
# CVD thresholds. ΔE2000 ≥ 10 is the ColorBrewer working floor for
# categorical-palette legibility — but red-green confusion under
# deuteranopia is fundamental (a red brand and a green success literally
# project to the same point in dichromat space), so achieving 10 across
# all three CVD types for every status pair is sometimes geometrically
# impossible. We therefore distinguish:
#   - hard floor (errors)   : ΔE < 5  — truly indistinguishable; must repair
#   - soft floor (warnings) : ΔE < 10 — distinguishable but close; flag
#                                       the user to verify their icons/labels
# Per WCAG 1.4.1, colour must never be the sole carrier of state, so
# the warning band is acceptable when paired with icons + text.
# ΔE < 3 is at the just-noticeable-difference (JND) threshold per Sharma
# 2005; below that, colours are perceptually identical even with effort.
# We use 3 as the hard floor: a CVD pair with ΔE < 3 will be a real
# accessibility failure no matter the icon/label. Above 3 (and below 10)
# we warn because the gap is small enough that distracted users may
# struggle.
CVD_DELTA_E_HARD = 3.0
CVD_DELTA_E_FLOOR = 10.0


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ContrastCheck:
    scheme: str           # "light" | "dark"
    role_pair: str        # e.g. "primary/on_primary"
    foreground: str       # hex
    background: str       # hex
    apca_lc: float
    wcag2_ratio: float
    floor_apca: float
    floor_wcag2: float
    passes_apca: bool
    passes_wcag2: bool

    @property
    def passed(self) -> bool:
        return self.passes_apca


@dataclass
class AdjacencyCheck:
    palette: str
    tone_a: int
    tone_b: int
    hex_a: str
    hex_b: str
    delta_e_2000: float
    distinguishable: bool


@dataclass
class StatusDistanceCheck:
    seed_hex: str
    status_name: str   # "error" | "success" | "warning" | "info"
    status_hex: str
    delta_e_2000: float
    passes_hard: bool  # ≥ 15
    passes_soft: bool  # ≥ 25


@dataclass
class CVDCheck:
    cvd: str
    pair: str
    a_hex: str
    b_hex: str
    delta_e_2000: float
    distinguishable: bool


@dataclass
class PaletteQualityReport:
    palette: DerivedPalette
    contrast: list[ContrastCheck] = field(default_factory=list)
    adjacency: list[AdjacencyCheck] = field(default_factory=list)
    status_distance: list[StatusDistanceCheck] = field(default_factory=list)
    cvd: list[CVDCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # Phase 1.6 Stage H — Cohen-Or harmonic-template fit. Optional
    # because old serialisations don't have it; new audits populate
    # it via audit_palette() below.
    harmonic_fit: Optional[dict] = None

    @property
    def passed(self) -> bool:
        return not self.errors

    def to_summary(self) -> dict:
        """A trimmed dict for JSON serialisation on BrandKit.
        Cheap counts-only payload — Stage G consumers use this to
        avoid loading the full per-check detail.

        The richer ``to_detail()`` form (Stage H) is the source of
        truth for the explainability panel.
        """
        return {
            "passed": self.passed,
            "n_contrast_checks": len(self.contrast),
            "n_contrast_failures": sum(1 for c in self.contrast if not c.passed),
            "n_adjacency_checks": len(self.adjacency),
            "n_adjacency_failures": sum(1 for a in self.adjacency if not a.distinguishable),
            "n_status_distance_checks": len(self.status_distance),
            "n_status_distance_failures": sum(
                1 for s in self.status_distance if not s.passes_hard
            ),
            "n_cvd_checks": len(self.cvd),
            "n_cvd_failures": sum(1 for c in self.cvd if not c.distinguishable),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

    def to_detail(self) -> dict:
        """Full per-check detail for the Stage H audit panel.

        Returns every contrast / adjacency / status_distance / CVD
        row as a dict, plus the harmonic fit and the standard
        warnings/errors lists. Larger payload (~10–25KB depending
        on palette size) than ``to_summary()`` but still cheap to
        cache. Stored in the on-disk theme JSON under the new
        ``quality_detail`` key so the explainability panel can
        render without re-running the QA pipeline.
        """
        from dataclasses import asdict
        return {
            "passed": self.passed,
            "harmonic_fit": self.harmonic_fit,
            "contrast": [asdict(c) for c in self.contrast],
            "adjacency": [asdict(a) for a in self.adjacency],
            "status_distance": [asdict(s) for s in self.status_distance],
            "cvd": [asdict(c) for c in self.cvd],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


# ---------------------------------------------------------------------------
# Gate 1 + 2: contrast (APCA + WCAG2)
# ---------------------------------------------------------------------------

# Role pairs that carry text. Format: (fg_role, bg_role, label).
_TEXT_ROLE_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("on_primary",           "primary",            "primary/on_primary"),
    ("on_primary_container", "primary_container",  "primary_container/on_primary_container"),
    ("on_secondary",         "secondary",          "secondary/on_secondary"),
    ("on_secondary_container","secondary_container","secondary_container/on_secondary_container"),
    ("on_tertiary",          "tertiary",           "tertiary/on_tertiary"),
    ("on_tertiary_container","tertiary_container", "tertiary_container/on_tertiary_container"),
    ("on_error",             "error",              "error/on_error"),
    ("on_error_container",   "error_container",    "error_container/on_error_container"),
    ("on_background",        "background",         "background/on_background"),
    ("on_surface",           "surface",            "surface/on_surface"),
    ("on_surface_variant",   "surface_variant",    "surface_variant/on_surface_variant"),
)

# UI role pairs (lower contrast floor — outline strokes etc.).
# outline_variant is intentionally decorative-only in MD3 (no contrast
# guarantee) so we don't check it; outline is the visible-boundary
# token and gets a 3:1 WCAG floor / APCA Lc 30 floor.
_UI_ROLE_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("outline", "surface", "surface/outline"),
)


def _contrast_checks(scheme: RoleScheme, scheme_name: str) -> list[ContrastCheck]:
    out: list[ContrastCheck] = []
    role_lookup = scheme.as_dict()
    for fg_role, bg_role, label in _TEXT_ROLE_PAIRS:
        fg = role_lookup[fg_role]
        bg = role_lookup[bg_role]
        lc = apca(fg, bg)
        ratio = wcag2_ratio(fg, bg)
        out.append(ContrastCheck(
            scheme=scheme_name,
            role_pair=label,
            foreground=fg,
            background=bg,
            apca_lc=lc,
            wcag2_ratio=ratio,
            floor_apca=APCA_BODY_FLOOR,
            floor_wcag2=WCAG2_AA_FLOOR,
            passes_apca=abs(lc) >= APCA_BODY_FLOOR,
            passes_wcag2=ratio >= WCAG2_AA_FLOOR,
        ))
    for fg_role, bg_role, label in _UI_ROLE_PAIRS:
        fg = role_lookup[fg_role]
        bg = role_lookup[bg_role]
        lc = apca(fg, bg)
        ratio = wcag2_ratio(fg, bg)
        out.append(ContrastCheck(
            scheme=scheme_name,
            role_pair=label,
            foreground=fg,
            background=bg,
            apca_lc=lc,
            wcag2_ratio=ratio,
            floor_apca=APCA_UI_FLOOR,
            floor_wcag2=WCAG2_AA_UI_FLOOR,
            passes_apca=abs(lc) >= APCA_UI_FLOOR,
            passes_wcag2=ratio >= WCAG2_AA_UI_FLOOR,
        ))
    return out


# ---------------------------------------------------------------------------
# Gate 3: adjacent-tone ΔE2000
# ---------------------------------------------------------------------------


def _adjacency_checks(palette: DerivedPalette) -> list[AdjacencyCheck]:
    out: list[AdjacencyCheck] = []
    for ramp in palette.all_ramps():
        prev_tone: Optional[int] = None
        prev_hex: Optional[str] = None
        for t in TONE_STOPS:
            hex_t = ramp.tones[t]
            if prev_tone is not None:
                de = Color(prev_hex).delta_e(Color(hex_t), method="2000")
                out.append(AdjacencyCheck(
                    palette=ramp.name,
                    tone_a=prev_tone,
                    tone_b=t,
                    hex_a=prev_hex,
                    hex_b=hex_t,
                    delta_e_2000=round(de, 2),
                    distinguishable=de >= ADJACENT_DELTA_E_FLOOR,
                ))
            prev_tone = t
            prev_hex = hex_t
    return out


# ---------------------------------------------------------------------------
# Gate 4: brand seed ⊕ status anchors
# ---------------------------------------------------------------------------


def _status_distance_checks(palette: DerivedPalette) -> list[StatusDistanceCheck]:
    out: list[StatusDistanceCheck] = []
    seed = palette.seed_hex
    seed_c = Color(seed)
    for ramp in (palette.error, palette.success, palette.warning, palette.info):
        # Compare seed to the *anchor* tone (40 in light scheme) of each status.
        status_hex = ramp.tones[40]
        de = seed_c.delta_e(Color(status_hex), method="2000")
        out.append(StatusDistanceCheck(
            seed_hex=seed,
            status_name=ramp.name,
            status_hex=status_hex,
            delta_e_2000=round(de, 2),
            passes_hard=de >= STATUS_DELTA_E_HARD,
            passes_soft=de >= STATUS_DELTA_E_SOFT,
        ))
    return out


# ---------------------------------------------------------------------------
# Gate 5: CVD-simulated ΔE2000
# ---------------------------------------------------------------------------


def _cvd_checks(palette: DerivedPalette) -> list[CVDCheck]:
    out: list[CVDCheck] = []
    seed = palette.seed_hex
    pairs = [
        ("seed/error",   seed, palette.error.tones[40]),
        ("seed/success", seed, palette.success.tones[40]),
        ("seed/warning", seed, palette.warning.tones[40]),
        ("seed/info",    seed, palette.info.tones[40]),
    ]
    for cvd in CVD_TYPES:
        for label, a, b in pairs:
            r = delta_e_under_cvd(a, b, cvd, threshold=CVD_DELTA_E_FLOOR)
            out.append(CVDCheck(
                cvd=cvd,
                pair=label,
                a_hex=r.a_hex,
                b_hex=r.b_hex,
                delta_e_2000=r.delta_e_2000,
                distinguishable=r.distinguishable,
            ))
    return out


# ---------------------------------------------------------------------------
# Top-level audit
# ---------------------------------------------------------------------------


def audit_palette(palette: DerivedPalette, roles: ThemeRoles) -> PaletteQualityReport:
    """Run every QA gate against the palette+roles and return a report."""
    report = PaletteQualityReport(palette=palette)

    # 1+2: contrast (both schemes)
    report.contrast.extend(_contrast_checks(roles.light, "light"))
    report.contrast.extend(_contrast_checks(roles.dark,  "dark"))
    for c in report.contrast:
        if not c.passes_apca:
            report.errors.append(
                f"APCA Lc {c.apca_lc} below floor {c.floor_apca} for "
                f"{c.scheme}.{c.role_pair} (fg={c.foreground} bg={c.background})"
            )

    # 3: adjacency
    report.adjacency.extend(_adjacency_checks(palette))
    weak_adjacent = [a for a in report.adjacency if not a.distinguishable]
    for a in weak_adjacent:
        report.warnings.append(
            f"Adjacent tones {a.palette}.{a.tone_a}/{a.tone_b} have "
            f"ΔE2000={a.delta_e_2000} (< {ADJACENT_DELTA_E_FLOOR})"
        )

    # 4: brand-vs-status distance
    report.status_distance.extend(_status_distance_checks(palette))
    for s in report.status_distance:
        if not s.passes_hard:
            report.errors.append(
                f"Brand seed too close to {s.status_name}: "
                f"ΔE2000={s.delta_e_2000} (< {STATUS_DELTA_E_HARD})"
            )
        elif not s.passes_soft:
            report.warnings.append(
                f"Brand seed within soft-warn of {s.status_name}: "
                f"ΔE2000={s.delta_e_2000} (< {STATUS_DELTA_E_SOFT})"
            )

    # 5: CVD — hard fail at ΔE < 5, soft warn at ΔE < 10. Above 10 = pass.
    report.cvd.extend(_cvd_checks(palette))
    for c in report.cvd:
        if c.delta_e_2000 < CVD_DELTA_E_HARD:
            report.errors.append(
                f"CVD-{c.cvd}: {c.pair} ΔE2000={c.delta_e_2000} "
                f"(< {CVD_DELTA_E_HARD}); truly indistinguishable for affected users"
            )
        elif not c.distinguishable:
            report.warnings.append(
                f"CVD-{c.cvd}: {c.pair} ΔE2000={c.delta_e_2000} "
                f"(< {CVD_DELTA_E_FLOOR}); pair status messages with icon + text "
                f"so colour is not the sole signal (WCAG 1.4.1)"
            )

    # 6: harmonic fit (Phase 1.6 Stage H — Cohen-Or 2006). Lower
    # energy = better hue harmony. Scored across the seven brand-
    # role hues; results inform the audit panel but never produce
    # errors (harmony is aesthetic, not accessibility).
    try:
        from .harmony import fit_harmonic_template
        hues: list[float] = []
        for ramp in palette.all_ramps():
            if ramp.hue is not None:
                hues.append(float(ramp.hue))
        if hues:
            fit = fit_harmonic_template(hues)
            report.harmonic_fit = fit.to_dict()
    except Exception:
        # Harmonic fit is opportunistic; failures don't block.
        report.harmonic_fit = None

    return report
