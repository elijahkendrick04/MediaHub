"""Per-card colour-accessibility audit + colourblind simulation (G1.18).

Every generated card paints a fixed set of brand **colour roles** (the
``--mh-*`` tokens the renderer resolves in
``graphic_renderer.render.resolved_role_vars_for_brief``): a ground, a surface
panel, an accent, and the inks that sit on them. Before a card ships we already
gate *legibility* deterministically (``quality.compliance`` — APCA only). This
module is the richer, human-facing **accessibility report** layered over the
same role set:

  1. **APCA + WCAG 2.x, side by side**, for every text/background pair the card
     actually paints — the modern perceptual model *and* the figure an auditor
     will quote — each classified into its standard band (APCA Lc bands /
     WCAG AA·AAA).
  2. **Colourblind simulation** (deuteranopia / protanopia / tritanopia) via the
     Machado matrices in ``theming.cvd``. For each deficiency we re-derive the
     palette a colourblind viewer perceives ("the preview"), re-score every text
     pair on the *simulated* colours (contrast shifts — protan reds darken), and
     check that distinct roles stay tellable apart (CIEDE2000 ΔE under the same
     simulation).

It is deliberately **deterministic** — pure colour-science maths, no LLM, no
network, no rendering — consistent with the standing rule that parsers,
detectors, the ranker and the colour-science modules are never AI-substituted.
It reads a card's resolved colours and reports; it never invents a colour or
makes a creative judgement.

The headline contrast pairs and APCA thresholds are kept byte-identical to the
``quality.compliance`` gate (pinned by a behavioural-equivalence test) so the
audit can never tell a club a card is fine when the ship gate would reject it,
or vice versa. The audit is a superset: it adds WCAG numbers, band labels, and
the full colourblind story on top of that same legibility verdict.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from coloraide import Color

from mediahub.quality.compliance import LC_LARGE
from mediahub.theming import cvd as _cvd
from mediahub.theming.contrast import apca, pick_ink, wcag2_ratio

__all__ = [
    "PairSpec",
    "PairContrast",
    "CVDPairContrast",
    "CVDCollision",
    "CVDPreview",
    "ColourAudit",
    "CONTRAST_PAIRS",
    "CVD_TYPES",
    "CVD_LABELS",
    "DE_THRESHOLD",
    "apca_band",
    "wcag_band",
    "simulate_roles",
    "audit_roles",
    "audit_brief",
    "swatches_svg",
]

# Re-export the canonical CVD set so callers need only one import.
CVD_TYPES = _cvd.CVD_TYPES  # ("deutan", "protan", "tritan")

# Human labels for the three dichromacies — used in the report and the preview.
CVD_LABELS: dict[str, str] = {
    "deutan": "Deuteranopia — red-green (≈6% of males, the common one)",
    "protan": "Protanopia — red-green (reds lose luminance, go dark)",
    "tritan": "Tritanopia — blue-yellow (rare, <0.01%)",
}

# CIEDE2000 distinguishability floor: two role colours are "tellable apart" when
# their ΔE2000 (after CVD simulation) clears this. 10 is ColorBrewer's working
# floor for categorical-palette legibility — the same default ``theming.cvd``
# uses, so the audit and the theming engine judge "distinct" by one measure.
DE_THRESHOLD = 10.0


# --------------------------------------------------------------------------- #
# Canonical card pairs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PairSpec:
    """One text-on-background pair a v2 card paints, with its APCA floor.

    Mirrors ``quality.compliance._ROLE_PAIRS`` (legibility gate) and adds a
    human ``description`` for the report. The behavioural-equivalence test
    pins ``audit_roles(...).passes`` to ``compliance.check_roles(...).passes``,
    so this list can never silently drift from the ship gate.
    """

    name: str
    description: str
    fg_role: str
    bg_role: str
    min_apca: float


# The text→background pairs every v2 archetype renders, keyed to the ``--mh-*``
# roles. Identical set + thresholds to the compliance gate; descriptions added.
CONTRAST_PAIRS: tuple[PairSpec, ...] = (
    PairSpec(
        "name_on_ground",
        "Athlete name / hero text on the card ground",
        "--mh-on-primary",
        "--mh-primary",
        LC_LARGE,
    ),
    PairSpec(
        "text_on_surface",
        "Body & meta text on the surface panel",
        "--mh-on-surface",
        "--mh-surface",
        LC_LARGE,
    ),
    PairSpec(
        "accent_on_ground",
        "Accent kicker / label on the ground",
        "--mh-accent",
        "--mh-primary",
        LC_LARGE,
    ),
    PairSpec(
        "chip_text_on_accent",
        "Result numeral on the accent chip",
        "--mh-primary",
        "--mh-accent",
        LC_LARGE,
    ),
)

# Role pairs that must stay *visually distinct* (not text contrast — separation)
# for a card to read structurally. These are distinguishability checks (ΔE2000),
# the colour-blindness failure mode contrast alone misses: an accent that pops
# off the ground for full-colour vision but merges into it for a deutan viewer.
_ADJACENCY_PAIRS: tuple[tuple[str, str], ...] = (
    ("--mh-accent", "--mh-primary"),
    ("--mh-accent", "--mh-surface"),
    ("--mh-primary", "--mh-surface"),
    ("--mh-secondary", "--mh-primary"),
)

# Roles drawn in the colourblind preview swatch strip, in reading order.
_SWATCH_ROLES: tuple[tuple[str, str], ...] = (
    ("--mh-primary", "ground"),
    ("--mh-surface", "surface"),
    ("--mh-accent", "accent"),
    ("--mh-secondary", "secondary"),
    ("--mh-on-primary", "ink"),
)


def _is_hex(v) -> bool:
    """True for a ``#rgb`` or ``#rrggbb`` string (matches the renderer's test)."""
    return isinstance(v, str) and v.strip().startswith("#") and len(v.strip()) in (4, 7)


# --------------------------------------------------------------------------- #
# Band classifiers
# --------------------------------------------------------------------------- #


def apca_band(lc: float) -> str:
    """Name the APCA use-case band for a signed Lc value (by magnitude).

    Bands follow the published APCA lookup minimums (Lc 90/75/60/45/30): the
    bar a contrast clears, not what the card needs. ``"fail"`` means below the
    Lc 30 non-text floor — invisible.
    """
    mag = abs(lc)
    if mag >= 90:
        return "preferred"  # Lc90 — preferred body text
    if mag >= 75:
        return "silver"  # Lc75 — minimum body text (WCAG-AA-equivalent)
    if mag >= 60:
        return "fluent"  # Lc60 — fluent / larger body
    if mag >= 45:
        return "bronze"  # Lc45 — large/headline & non-text floor
    if mag >= 30:
        return "ui"  # Lc30 — UI / non-text minimum
    return "fail"


def wcag_band(ratio: float) -> str:
    """Name the best WCAG 2.x conformance band a contrast ratio reaches.

    Large display type (these cards) clears AA at 3:1 and AAA at 4.5:1; normal
    text needs 4.5 (AA) / 7 (AAA). We report the *highest* band reached and
    annotate "(large)" where it only holds for large text.
    """
    if ratio >= 7.0:
        return "AAA"
    if ratio >= 4.5:
        return "AA"
    if ratio >= 3.0:
        return "AA (large)"
    return "fail"


# --------------------------------------------------------------------------- #
# Report dataclasses
# --------------------------------------------------------------------------- #


@dataclass
class PairContrast:
    """One text/background pair scored under full-colour vision, both models."""

    name: str
    description: str
    fg_role: str
    bg_role: str
    fg_hex: str
    bg_hex: str
    apca_lc: float  # signed: + dark-on-light, − light-on-dark
    apca_band: str
    wcag2_ratio: float
    wcag_band: str
    min_apca: float  # the APCA floor this pair is held to
    passes: bool  # abs(apca_lc) >= min_apca — the compliance verdict


@dataclass
class CVDPairContrast:
    """A text/background pair re-scored after Machado-simulating both colours."""

    name: str
    fg_sim: str
    bg_sim: str
    apca_lc: float
    wcag2_ratio: float
    min_apca: float
    passes: bool
    apca_shift: float  # abs(sim Lc) − abs(normal Lc); negative = worse for this viewer


@dataclass
class CVDCollision:
    """Whether two distinct roles stay tellable apart under one deficiency.

    ``distinguishable`` is False only when the roles read as different colours
    in full vision (``delta_e_normal`` >= threshold) but collapse under this
    deficiency (``delta_e_2000`` < threshold). Roles that are close by design —
    a tonal ground/surface step separated by lightness + the outline hairline —
    are not a colour-blindness defect, so they never count as a collision.
    """

    role_a: str
    role_b: str
    a_sim: str
    b_sim: str
    delta_e_normal: float  # ΔE2000 in full colour
    delta_e_2000: float  # ΔE2000 after CVD simulation
    distinguishable: bool


@dataclass
class CVDPreview:
    """The full colour-blindness story for one deficiency type."""

    cvd: str  # "deutan" | "protan" | "tritan"
    label: str
    simulated_roles: dict[str, str]  # --mh-* -> perceived hex (the preview palette)
    pairs: list[CVDPairContrast] = field(default_factory=list)
    collisions: list[CVDCollision] = field(default_factory=list)
    legible: bool = True  # every text pair still clears its APCA floor
    distinct: bool = True  # every adjacency pair stays distinguishable
    passes: bool = True  # legible AND distinct


@dataclass
class ColourAudit:
    """The complete per-card colour-accessibility verdict."""

    roles: dict[str, str]  # the resolved --mh-* set this audit scored
    pairs: list[PairContrast] = field(default_factory=list)
    cvd: list[CVDPreview] = field(default_factory=list)
    passes: bool = True  # full-colour-vision legibility (== compliance gate)
    cvd_safe: bool = True  # legible AND distinct under all three deficiencies
    score: float = 1.0  # 0..1, worst pair normalised to its floor (full vision)
    warnings: list[str] = field(default_factory=list)

    @property
    def accessible(self) -> bool:
        """True only when the card reads for full-colour *and* all CVD viewers."""
        return self.passes and self.cvd_safe

    def explain(self) -> str:
        """One-line human summary for the 'why this design' surface."""
        if not self.pairs:
            return "no scorable colour pairs (no resolved roles)"
        worst = min(abs(p.apca_lc) for p in self.pairs)
        if self.accessible:
            return f"colour-accessible — min Lc {worst:.0f}, safe for deutan/protan/tritan"
        if self.passes and not self.cvd_safe:
            unsafe = ", ".join(p.cvd for p in self.cvd if not p.passes)
            return f"reads in full colour (min Lc {worst:.0f}) but risky for: {unsafe}"
        bad = ", ".join(p.name for p in self.pairs if not p.passes)
        return f"low contrast on: {bad}"

    def to_summary(self) -> dict:
        """Counts-only payload for a cheap badge / list view."""
        return {
            "passes": self.passes,
            "cvd_safe": self.cvd_safe,
            "accessible": self.accessible,
            "score": self.score,
            "n_pairs": len(self.pairs),
            "n_pair_failures": sum(1 for p in self.pairs if not p.passes),
            "cvd": {prev.cvd: prev.passes for prev in self.cvd},
            "warnings": list(self.warnings),
        }

    def to_detail(self) -> dict:
        """Full per-pair / per-deficiency detail for the explainability panel."""
        return {
            "passes": self.passes,
            "cvd_safe": self.cvd_safe,
            "accessible": self.accessible,
            "score": self.score,
            "roles": dict(self.roles),
            "pairs": [asdict(p) for p in self.pairs],
            "cvd": [asdict(prev) for prev in self.cvd],
            "warnings": list(self.warnings),
        }


# --------------------------------------------------------------------------- #
# Core API
# --------------------------------------------------------------------------- #


def simulate_roles(role_vars: dict, cvd: str) -> dict[str, str]:
    """Return the ``--mh-*`` palette a viewer with ``cvd`` perceives.

    Every hex role is Machado-simulated; non-hex tokens (the ``--mh-outline``
    rgba hairline) pass through unchanged. This *is* the colourblind "preview"
    palette — hand it to a renderer or paint it as swatches.
    """
    return {
        k: (_cvd.simulate(v, cvd) if _is_hex(v) else v) for k, v in role_vars.items()
    }


def _score_pairs(role_vars: dict) -> list[PairContrast]:
    """Score every canonical card pair present in ``role_vars`` (full vision)."""
    out: list[PairContrast] = []
    for spec in CONTRAST_PAIRS:
        fg, bg = role_vars.get(spec.fg_role), role_vars.get(spec.bg_role)
        if not (_is_hex(fg) and _is_hex(bg)):
            continue
        lc = apca(fg, bg)
        ratio = wcag2_ratio(fg, bg)
        out.append(
            PairContrast(
                name=spec.name,
                description=spec.description,
                fg_role=spec.fg_role,
                bg_role=spec.bg_role,
                fg_hex=fg.upper(),
                bg_hex=bg.upper(),
                apca_lc=lc,
                apca_band=apca_band(lc),
                wcag2_ratio=ratio,
                wcag_band=wcag_band(ratio),
                min_apca=spec.min_apca,
                passes=abs(lc) >= spec.min_apca,
            )
        )
    return out


def _cvd_preview(role_vars: dict, cvd: str, *, de_threshold: float) -> CVDPreview:
    """Build the simulated palette, re-scored pairs, and collision checks."""
    sim_roles = simulate_roles(role_vars, cvd)
    preview = CVDPreview(cvd=cvd, label=CVD_LABELS.get(cvd, cvd), simulated_roles=sim_roles)

    for spec in CONTRAST_PAIRS:
        fg, bg = role_vars.get(spec.fg_role), role_vars.get(spec.bg_role)
        if not (_is_hex(fg) and _is_hex(bg)):
            continue
        fg_sim, bg_sim = sim_roles[spec.fg_role], sim_roles[spec.bg_role]
        lc = apca(fg_sim, bg_sim)
        passes = abs(lc) >= spec.min_apca
        preview.pairs.append(
            CVDPairContrast(
                name=spec.name,
                fg_sim=fg_sim,
                bg_sim=bg_sim,
                apca_lc=lc,
                wcag2_ratio=wcag2_ratio(fg_sim, bg_sim),
                min_apca=spec.min_apca,
                passes=passes,
                apca_shift=round(abs(lc) - abs(apca(fg, bg)), 1),
            )
        )
        preview.legible = preview.legible and passes

    for role_a, role_b in _ADJACENCY_PAIRS:
        a, b = role_vars.get(role_a), role_vars.get(role_b)
        if not (_is_hex(a) and _is_hex(b)):
            continue
        # Skip a pair that is the same colour in full vision — nothing to "lose".
        if a.upper() == b.upper():
            continue
        normal_de = round(Color(a).delta_e(Color(b), method="2000"), 2)
        pair = _cvd.delta_e_under_cvd(a, b, cvd, threshold=de_threshold)
        # A collision is a CVD *failure* only when the roles are meant to read
        # as different colours (clear in full vision) yet collapse under this
        # deficiency. A pair that is already close in full colour is a tonal
        # design step, not a colour-blindness defect.
        collapses = normal_de >= de_threshold and not pair.distinguishable
        preview.collisions.append(
            CVDCollision(
                role_a=role_a,
                role_b=role_b,
                a_sim=pair.a_simulated,
                b_sim=pair.b_simulated,
                delta_e_normal=normal_de,
                delta_e_2000=pair.delta_e_2000,
                distinguishable=not collapses,
            )
        )
        preview.distinct = preview.distinct and not collapses

    preview.passes = preview.legible and preview.distinct
    return preview


def audit_roles(
    role_vars: dict,
    *,
    cvd_types=CVD_TYPES,
    de_threshold: float = DE_THRESHOLD,
) -> ColourAudit:
    """Audit a resolved ``--mh-*`` role set for colour accessibility.

    ``role_vars`` is the dict ``graphic_renderer.render.resolved_role_vars_for_brief``
    returns (or any compatible ``--mh-*`` mapping). Produces the full report:
    APCA+WCAG per text pair under full vision, plus a colourblind preview,
    re-scored pairs and collision checks for each deficiency in ``cvd_types``.

    Pure and deterministic; tolerates a partial role set (pairs whose roles are
    absent or non-hex are simply skipped, never guessed).
    """
    pairs = _score_pairs(role_vars)
    passes = all(p.passes for p in pairs)
    score = round(
        min((min(1.0, abs(p.apca_lc) / p.min_apca) for p in pairs), default=1.0), 3
    )

    warnings: list[str] = []
    for p in pairs:
        if not p.passes:
            warnings.append(
                f"low contrast: {p.name} Lc {abs(p.apca_lc):.0f} < {p.min_apca:.0f} "
                f"(WCAG {p.wcag2_ratio:.1f}:1)"
            )

    previews: list[CVDPreview] = []
    for cvd in cvd_types:
        preview = _cvd_preview(role_vars, cvd, de_threshold=de_threshold)
        previews.append(preview)
        for cp in preview.pairs:
            if not cp.passes:
                warnings.append(
                    f"{cvd}: {cp.name} loses contrast (Lc {abs(cp.apca_lc):.0f} "
                    f"< {cp.min_apca:.0f})"
                )
        for col in preview.collisions:
            if not col.distinguishable:
                warnings.append(
                    f"{cvd}: {col.role_a} and {col.role_b} collapse "
                    f"(ΔE {col.delta_e_normal:.0f}→{col.delta_e_2000:.0f}, "
                    f"floor {de_threshold:.0f})"
                )

    return ColourAudit(
        roles=dict(role_vars),
        pairs=pairs,
        cvd=previews,
        passes=passes,
        cvd_safe=all(p.passes for p in previews),
        score=score,
        warnings=warnings,
    )


def audit_brief(brief, brand_kit=None, **kwargs) -> ColourAudit:
    """Audit the colours a v2 render of ``brief`` would paint.

    Convenience over :func:`audit_roles`: resolves the card's ``--mh-*`` set via
    the renderer's single source of truth (so the audit scores *exactly* what
    ships — Tier A baseline → director's APCA-gated assignment → medal tint),
    then audits it. ``brand_kit`` and any keyword args forward through.
    """
    from mediahub.graphic_renderer.render import resolved_role_vars_for_brief

    return audit_roles(resolved_role_vars_for_brief(brief, brand_kit), **kwargs)


# --------------------------------------------------------------------------- #
# Visual preview — a deterministic SVG swatch strip
# --------------------------------------------------------------------------- #


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def swatches_svg(role_vars: dict, *, cvd_types=CVD_TYPES) -> str:
    """A self-contained SVG comparing the palette across vision types.

    One labelled row per vision mode — full colour, then each deficiency — with
    a swatch per role showing the perceived hex. A purely deterministic, pure
    artifact (no Playwright, no network): the at-a-glance "deut/prot/trit
    preview" the explainability surface can embed or save.

    Safe by construction: only validated hex fills and a fixed label vocabulary
    reach the markup, and every text node is XML-escaped.
    """
    cols = [(role, lbl) for role, lbl in _SWATCH_ROLES if _is_hex(role_vars.get(role))]
    rows = [("normal", "Full colour", role_vars)] + [
        (c, CVD_LABELS.get(c, c), simulate_roles(role_vars, c)) for c in cvd_types
    ]

    pad, label_w, header_h, cell_w, cell_h, gap = 12, 150, 26, 116, 56, 8
    width = pad * 2 + label_w + len(cols) * (cell_w + gap) - (gap if cols else 0)
    height = pad * 2 + header_h + len(rows) * (cell_h + gap) - (gap if rows else 0)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Colour palette across full-colour and colourblind vision">',
        f'<rect width="{width}" height="{height}" fill="#0A0B11"/>',
        '<style>text{font-family:system-ui,-apple-system,Segoe UI,sans-serif;}</style>',
    ]

    # Column headers (role names).
    for ci, (_role, lbl) in enumerate(cols):
        cx = pad + label_w + ci * (cell_w + gap) + cell_w / 2
        parts.append(
            f'<text x="{cx:.0f}" y="{pad + header_h - 8}" fill="#9AA0AE" font-size="12" '
            f'text-anchor="middle">{_xml_escape(lbl)}</text>'
        )

    # One row per vision mode.
    for ri, (_mode, row_label, roles) in enumerate(rows):
        ry = pad + header_h + ri * (cell_h + gap)
        parts.append(
            f'<text x="{pad}" y="{ry + cell_h / 2 + 4:.0f}" fill="#E8E6DF" font-size="12">'
            f"{_xml_escape(row_label)}</text>"
        )
        for ci, (role, _lbl) in enumerate(cols):
            hex_v = roles.get(role, "#000000")
            cx = pad + label_w + ci * (cell_w + gap)
            ink = pick_ink(hex_v)[0]
            parts.append(
                f'<rect x="{cx:.0f}" y="{ry:.0f}" width="{cell_w}" height="{cell_h}" rx="8" '
                f'fill="{hex_v}" stroke="rgba(255,255,255,0.12)"/>'
            )
            parts.append(
                f'<text x="{cx + cell_w / 2:.0f}" y="{ry + cell_h / 2 + 4:.0f}" fill="{ink}" '
                f'font-size="12" text-anchor="middle" font-family="monospace">'
                f"{_xml_escape(hex_v.upper())}</text>"
            )

    parts.append("</svg>")
    return "".join(parts)
