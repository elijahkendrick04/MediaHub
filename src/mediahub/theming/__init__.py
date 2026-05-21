"""Adaptive Theming Engine — colour-science package (Phase 1.6 Stage B).

Public entry points:

    from mediahub.theming import derive_theme, extract_seed

    seed = extract_seed(logo_svg_or_png_bytes_or_hex)
    theme = derive_theme(seed)

    # theme.palette         — DerivedPalette (9 tonal ramps × 13 tones)
    # theme.roles.light     — RoleScheme for light mode
    # theme.roles.dark      — RoleScheme for dark mode
    # theme.quality_report  — PaletteQualityReport with APCA + CVD + ΔE checks
    # theme.was_repaired    — bool: did the constraint loop fire?
    # theme.decision_trace  — list[str] for the audit panel

The whole pipeline is deterministic — same seed produces bytewise
identical output every time. Computation happens once at brand-kit
save time (see BrandKit.ensure_derived_palette); nothing in this
package reads at request time.

See docs/THEMING.md for the architecture and
academic citations. The seven internal modules:

  seed_extract — SVG fast-path → raster fallback → QuantizeCelebi + Score
  palette      — HCT seed → 5 × 13 tonal palettes + 4 status anchors
  roles        — DerivedPalette → Material 3 role-token map (light + dark)
  contrast     — APCA Lc + WCAG2 ratio + ink-on-surface picker
  cvd          — Machado 2009 deuteranopia / protanopia / tritanopia
  quality      — every QA gate → PaletteQualityReport
  repair       — constraint-satisfaction loop with curated fallbacks
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, TypedDict

from .palette import DerivedPalette, derive_palette
from .roles import RoleScheme, ThemeRoles, derive_roles
from .quality import PaletteQualityReport, audit_palette
from .repair import repair_palette
from .seed_extract import SeedResult, extract_seed


__all__ = [
    "DerivedTheme",
    "derive_theme",
    "extract_seed",
    "DerivedPalette",
    "RoleScheme",
    "ThemeRoles",
    "PaletteQualityReport",
    "SeedResult",
    "ThemeJSON",
]


# ---------------------------------------------------------------------------
# DTCG-format JSON shape — documented as a TypedDict so consumers can
# introspect the cached palette without importing the dataclasses.
# ---------------------------------------------------------------------------


class ThemeJSON(TypedDict, total=False):
    """The shape of ClubProfile.brand_kit.derived_palette.

    Stable serialised form — the source of truth that Stage D (CSS),
    Stage G (Remotion / email / static graphic) all consume.
    """
    schema_version: str          # "1" — bump if breaking changes ever needed
    seed_hex: str                # the canonical brand-seed hex
    seed_hct: list[float]        # [hue, chroma, tone] in HCT space
    seed_source: str             # "hex" | "svg" | "raster" | "fallback"
    seed_candidates: list[dict]  # top-N quantizer candidates for audit panel
    palettes: dict[str, dict]    # palette name → {"hue": h, "chroma": c, "tones": {"0": "#...", ...}}
    roles: dict[str, dict]       # "light" / "dark" → {role_name: "#hex", ...}
    quality: dict                # PaletteQualityReport as dict
    decision_trace: list[str]    # human-readable audit log
    was_repaired: bool
    generated_at: str            # ISO-8601 UTC


# ---------------------------------------------------------------------------
# DerivedTheme — the top-level dataclass returned by derive_theme()
# ---------------------------------------------------------------------------


@dataclass
class DerivedTheme:
    palette: DerivedPalette
    roles: ThemeRoles
    quality_report: PaletteQualityReport
    seed_result: SeedResult
    was_repaired: bool
    decision_trace: list[str]
    generated_at: str

    def to_json(self) -> ThemeJSON:
        """Serialise to the DTCG-format dict cached on BrandKit.

        Stage H additions (additive — schema_version unchanged):
          - ``quality_detail`` carries the full per-check rows for
            the explainability panel.
          - ``harmonic_fit`` carries the Cohen-Or template-fit
            result (also nested inside ``quality_detail``).
        Existing ``quality`` (summary counts) remains for Stage G
        consumers that only need the counts.
        """
        return {
            "schema_version": "1",
            "seed_hex": self.palette.seed_hex,
            "seed_hct": list(self.palette.seed_hct),
            "seed_source": self.seed_result.source_kind,
            "seed_candidates": [
                {"hex": c.hex, "hct": list(c.hct), "score": c.score}
                for c in self.seed_result.candidates
            ],
            "palettes": {
                ramp.name: {
                    "hue": ramp.hue,
                    "chroma": ramp.chroma,
                    "tones": {str(k): v for k, v in ramp.tones.items()},
                }
                for ramp in self.palette.all_ramps()
            },
            "roles": {
                "light": asdict(self.roles.light),
                "dark": asdict(self.roles.dark),
            },
            "quality": self.quality_report.to_summary(),
            # Phase 1.6 Stage H — full per-check audit detail + harmony.
            "quality_detail": self.quality_report.to_detail(),
            "harmonic_fit": self.quality_report.harmonic_fit,
            "decision_trace": self.decision_trace,
            "was_repaired": self.was_repaired,
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# derive_theme — the single entry point
# ---------------------------------------------------------------------------


def derive_theme(
    seed_or_source: str | bytes,
    *,
    force_repair: bool = False,
    repair_max_iters: int = 8,
) -> DerivedTheme:
    """Produce a full DerivedTheme from a seed hex, SVG markup, or raster
    bytes.

    Parameters
    ----------
    seed_or_source : str | bytes
        One of:
          - A CSS hex colour ``#RRGGBB`` (passed through unchanged).
          - SVG markup as a string (parsed via lxml fast-path).
          - Raster bytes (PNG / JPEG) — rasterised + quantized.
    force_repair : bool, default False
        If True, always run the repair loop even when the QA gates
        pass. Useful for tests asserting the loop is idempotent on a
        good palette.
    repair_max_iters : int, default 8
        Safety bound on the constraint-satisfaction iterations.

    Returns
    -------
    DerivedTheme
        The full output (palette + roles + quality report + trace).
        Always non-None: a fallback default fires for empty/invalid
        inputs so the engine never crashes the brand-kit save path.
    """
    seed_result = extract_seed(seed_or_source)
    palette = derive_palette(seed_result.hex)
    roles = derive_roles(palette)
    report = audit_palette(palette, roles)

    decision_trace = list(seed_result.trace) + list(palette.decision_trace)
    was_repaired = False

    if force_repair or not report.passed:
        palette, repair_trace = repair_palette(
            palette, report, max_iters=repair_max_iters
        )
        roles = derive_roles(palette)
        report = audit_palette(palette, roles)
        decision_trace.extend(repair_trace)
        was_repaired = True

    return DerivedTheme(
        palette=palette,
        roles=roles,
        quality_report=report,
        seed_result=seed_result,
        was_repaired=was_repaired,
        decision_trace=decision_trace,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
