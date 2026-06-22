"""Deterministic print auto-proofing (roadmap 1.20's intelligence core).

Before a club sends a design to a printer, MediaHub checks it the way a good
print shop's pre-press operator would — and, true to the explainability rule,
says in plain words *what* is wrong and *how to fix it*. The checks are pure,
reproducible maths (a ruler and a calculator, never a model), so the same design
against the same product always proofs the same way. This is the print side of
the deterministic-engine boundary.

What it checks
--------------
* **Resolution** — the artwork's *effective* dpi once stretched to the product's
  physical print area. A 1000 px image on an A2 poster edge is ~60 dpi, however
  large the canvas spec; print wants the product's target dpi. Pairs with the
  1.2 upscale tools.
* **Text legibility** — the smallest text's *printed* point size against the
  method's floor (litho resolves 6 pt; a roll-up read across a hall needs 24).
* **Bleed** — trimmed products need the background to run past the cut line or a
  white sliver shows; flags a design that stops at the trim.
* **Safe margin** — critical content kept clear of the trim edge's quiet zone.
* **Contrast on paper** — ink-on-paper APCA, so pale ink on pale stock is caught.
* **CMYK gamut** — vivid RGB colours that will shift duller in process ink.
* **Total ink coverage (TAC)** — a too-heavy build that won't dry / will offset
  on the chosen stock.

Each finding is a :class:`Violation` with a severity. *Errors* block export
(unless the caller forces it); *warnings* inform; *infos* mark a check that could
not run because a fact (text size, the inks used) was not supplied. A clean
report — no errors, no warnings — means "ready for the printer".
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from mediahub.club_platform.format_catalog import FormatSpec
from mediahub.graphic_renderer.print_export import cmyk_percent
from mediahub.print_ready.products import Placement, PrintProduct
from mediahub.theming.contrast import apca

_MM_PER_IN = 25.4
_PT_PER_IN = 72.0

# Severities, most-to-least serious.
ERROR = "error"
WARNING = "warning"
INFO = "info"
_SEVERITY_RANK = {ERROR: 0, WARNING: 1, INFO: 2}


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    """One pre-press finding — what's wrong, and how to fix it."""

    code: str
    severity: str
    title: str
    detail: str
    fix: str = ""
    where: str = ""

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "fix": self.fix,
            "where": self.where,
        }


@dataclass(frozen=True)
class ArtworkProfile:
    """The facts the proofer needs about one piece of artwork.

    ``width_px`` / ``height_px`` are mandatory (everything physical derives from
    them). The rest are optional: supply what's known and the dependent checks
    run; omit them and those checks emit an honest *info* ("couldn't verify")
    rather than a false pass. ``ink_colours`` / ``paper_colour`` are ``#hex``;
    ``min_text_px`` is the smallest rendered text height in canvas pixels;
    ``content_inset_px`` is the smallest distance from any critical element to
    the artwork edge; ``full_bleed`` is whether the design runs to all edges
    (``None`` = unknown).
    """

    width_px: int
    height_px: int
    ink_colours: tuple[str, ...] = ()
    paper_colour: str = ""
    min_text_px: int = 0
    content_inset_px: int = -1  # -1 = unknown
    full_bleed: Optional[bool] = None

    def __post_init__(self) -> None:
        if self.width_px <= 0 or self.height_px <= 0:
            raise ValueError("artwork dimensions must be positive")


@dataclass(frozen=True)
class PreflightReport:
    """The outcome of proofing one artwork against one product placement."""

    product_slug: str
    placement_slug: str
    violations: tuple[Violation, ...] = field(default_factory=tuple)

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == ERROR]

    @property
    def warnings(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == WARNING]

    @property
    def infos(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == INFO]

    @property
    def ok(self) -> bool:
        """True when nothing *blocks* export (no errors). Warnings still allowed."""
        return not self.errors

    @property
    def passed(self) -> bool:
        """True when the artwork is clean — no errors *and* no warnings."""
        return not self.errors and not self.warnings

    def summary(self) -> str:
        if self.passed:
            return "Ready for the printer — no issues found."
        bits = []
        if self.errors:
            bits.append(f"{len(self.errors)} blocking issue" + ("s" if len(self.errors) != 1 else ""))
        if self.warnings:
            bits.append(f"{len(self.warnings)} warning" + ("s" if len(self.warnings) != 1 else ""))
        if not bits and self.infos:
            return "No problems found; some checks could not be verified."
        return ", ".join(bits) + "."

    def to_dict(self) -> dict:
        return {
            "product": self.product_slug,
            "placement": self.placement_slug,
            "ok": self.ok,
            "passed": self.passed,
            "summary": self.summary(),
            "counts": {
                "error": len(self.errors),
                "warning": len(self.warnings),
                "info": len(self.infos),
            },
            "violations": [v.to_dict() for v in self.violations],
        }


# ---------------------------------------------------------------------------
# Colour helpers (small + local; the heavy science is reused from print_export)
# ---------------------------------------------------------------------------


def _hex_rgb(value: str) -> Optional[tuple[int, int, int]]:
    s = str(value or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6 or any(c not in "0123456789abcdefABCDEF" for c in s):
        return None
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def _vivid_out_of_gamut(hex_colour: str) -> bool:
    """Heuristic: is this a very vivid colour CMYK ink will struggle to match?

    The deterministic device RGB↔CMYK transform is a pure inverse — it round-trips
    every colour exactly, so it cannot *measure* gamut (claiming otherwise would be
    the fake the honest-error rule forbids). The honest signal is the long-known
    pre-press rule of thumb: highly-saturated, bright sRGB colours (neon cyans,
    greens, oranges) sit outside typical process-CMYK gamut and print more muted.
    We flag only the genuinely-vivid corner so ordinary brand colours don't nag.
    """
    rgb = _hex_rgb(hex_colour)
    if rgb is None:
        return False
    r, g, b = (v / 255.0 for v in rgb)
    mx, mn = max(r, g, b), min(r, g, b)
    sat = 0.0 if mx <= 0 else (mx - mn) / mx
    return sat >= _GAMUT_SAT and mx >= _GAMUT_VAL


# Thresholds — defensible pressroom / accessibility figures, named so a reader
# can see exactly what "too low" means.
_RES_OK_RATIO = 0.98  # within 2% of target dpi counts as met (canvas px round)
_RES_ERROR_RATIO = 0.5  # below half target dpi → blocking
_MIN_PAPER_Lc = 45.0  # APCA headline floor for ink on paper
_GAMUT_SAT = 0.9  # saturation above which a bright colour is "vivid"
_GAMUT_VAL = 0.85  # brightness above which a saturated colour likely shifts
_ASPECT_TOL = 0.06  # |artwork-aspect − canvas-aspect| this fraction is fine


# ---------------------------------------------------------------------------
# Individual checks — each a pure (artwork, product, placement, spec) → list
# ---------------------------------------------------------------------------


def check_resolution(
    art: ArtworkProfile, product: PrintProduct, placement: Placement, spec: FormatSpec
) -> list[Violation]:
    w_in = placement.area_w_mm / _MM_PER_IN
    h_in = placement.area_h_mm / _MM_PER_IN
    if w_in <= 0 or h_in <= 0:  # pragma: no cover - registry guarantees positive
        return []
    eff = min(art.width_px / w_in, art.height_px / h_in)
    target = product.target_dpi
    ratio = eff / target if target else 1.0
    if ratio >= _RES_OK_RATIO:  # within rounding of target → met
        return []
    sev = ERROR if ratio < _RES_ERROR_RATIO else WARNING
    return [
        Violation(
            code="resolution_low",
            severity=sev,
            title="Image resolution too low for print",
            detail=(
                f"Your artwork is {art.width_px}×{art.height_px}px. Printed at "
                f"{placement.area_w_mm:g}×{placement.area_h_mm:g}mm that is only "
                f"~{eff:.0f} dpi, but {product.title.lower()} needs ≥{target} dpi "
                f"for a sharp result."
            ),
            fix=(
                "Upscale the image with the photo tools (1.2), start from a "
                "higher-resolution source, or print it smaller."
            ),
            where=placement.slug,
        )
    ]


def check_text_size(
    art: ArtworkProfile, product: PrintProduct, placement: Placement, spec: FormatSpec
) -> list[Violation]:
    if art.min_text_px <= 0:
        return [
            Violation(
                code="text_size_unknown",
                severity=INFO,
                title="Text size not measured",
                detail=(
                    f"Couldn't read the smallest text size, so legibility wasn't "
                    f"checked. {product.title} prints text best at ≥"
                    f"{product.min_text_pt:g} pt."
                ),
                where=placement.slug,
            )
        ]
    printed_in = art.min_text_px / art.height_px * (placement.area_h_mm / _MM_PER_IN)
    printed_pt = printed_in * _PT_PER_IN
    if printed_pt >= product.min_text_pt:
        return []
    return [
        Violation(
            code="text_too_small",
            severity=WARNING,
            title="Smallest text may be hard to read in print",
            detail=(
                f"Your smallest text prints at about {printed_pt:.1f} pt; "
                f"{product.title.lower()} (printed by {product.print_method}) "
                f"stays legible at ≥{product.min_text_pt:g} pt."
            ),
            fix="Increase the smallest text, or trim the fine print.",
            where=placement.slug,
        )
    ]


def check_bleed(
    art: ArtworkProfile, product: PrintProduct, placement: Placement, spec: FormatSpec
) -> list[Violation]:
    if spec.bleed_mm <= 0:
        return []  # this product isn't trimmed to the artwork edge
    if art.full_bleed is True:
        return []
    if art.full_bleed is None:
        return [
            Violation(
                code="bleed_unverified",
                severity=INFO,
                title="Check the artwork reaches every edge",
                detail=(
                    f"{product.title} is trimmed after printing. Make sure the "
                    f"background runs {spec.bleed_mm:g}mm past the cut on all four "
                    f"sides, or a thin white edge can show."
                ),
                where=placement.slug,
            )
        ]
    return [
        Violation(
            code="no_bleed",
            severity=WARNING,
            title="Artwork has no bleed",
            detail=(
                f"The design stops at the trim line, but {product.title.lower()} "
                f"is cut by hand and needs {spec.bleed_mm:g}mm of bleed or a white "
                f"sliver may show along an edge."
            ),
            fix=(
                f"Extend the background {spec.bleed_mm:g}mm past every edge — the "
                f"print export adds the bleed box and crop marks automatically."
            ),
            where=placement.slug,
        )
    ]


def check_safe_margin(
    art: ArtworkProfile, product: PrintProduct, placement: Placement, spec: FormatSpec
) -> list[Violation]:
    if spec.bleed_mm <= 0 or art.content_inset_px < 0:
        return []  # not trimmed, or no element-position info to judge
    quiet_mm = max(spec.bleed_mm + 1.0, 3.0)
    inset_mm = art.content_inset_px / art.width_px * placement.area_w_mm
    if inset_mm >= quiet_mm:
        return []
    return [
        Violation(
            code="content_in_margin",
            severity=WARNING,
            title="Content sits too close to the cut edge",
            detail=(
                f"Some content is only ~{inset_mm:.1f}mm from the trim; the guillotine "
                f"can drift, so keep important text and logos ≥{quiet_mm:g}mm inside."
            ),
            fix="Nudge edge-hugging text and logos toward the centre.",
            where=placement.slug,
        )
    ]


def check_contrast(
    art: ArtworkProfile, product: PrintProduct, placement: Placement, spec: FormatSpec
) -> list[Violation]:
    if not art.ink_colours or not art.paper_colour:
        return []
    best = max((abs(apca(ink, art.paper_colour)) for ink in art.ink_colours), default=0.0)
    if best >= _MIN_PAPER_Lc:
        return []
    return [
        Violation(
            code="low_contrast_on_paper",
            severity=WARNING,
            title="Low contrast on the paper",
            detail=(
                f"The strongest ink-on-paper contrast is APCA {best:.0f}, below the "
                f"~{_MIN_PAPER_Lc:.0f} a printed headline needs — pale ink on pale "
                f"stock is hard to read."
            ),
            fix="Darken the ink or lighten the background for more contrast.",
            where=placement.slug,
        )
    ]


def check_gamut(
    art: ArtworkProfile, product: PrintProduct, placement: Placement, spec: FormatSpec
) -> list[Violation]:
    out: list[Violation] = []
    for ink in art.ink_colours:
        if _vivid_out_of_gamut(ink):
            out.append(
                Violation(
                    code="out_of_cmyk_gamut",
                    severity=WARNING,
                    title="Vivid colour may look duller in print",
                    detail=(
                        f"{ink.upper()} is a very vivid colour; process CMYK ink "
                        f"often can't reach it, so it can print more muted than it "
                        f"looks on screen."
                    ),
                    fix="Pick a slightly less saturated shade, or accept the shift.",
                    where=placement.slug,
                )
            )
        if len(out) >= 3:  # don't drown the report in gamut notes
            break
    return out


def check_ink_coverage(
    art: ArtworkProfile, product: PrintProduct, placement: Placement, spec: FormatSpec
) -> list[Violation]:
    limit = product.max_ink_coverage
    worst_hex = ""
    worst_tac = 0
    for colour in (*art.ink_colours, art.paper_colour):
        if not colour:
            continue
        if _hex_rgb(colour) is None:
            continue
        tac = sum(cmyk_percent(colour))
        if tac > worst_tac:
            worst_tac, worst_hex = tac, colour
    if not worst_hex or worst_tac <= limit:
        return []
    return [
        Violation(
            code="ink_coverage_high",
            severity=WARNING,
            title="Too much ink for this stock",
            detail=(
                f"{worst_hex.upper()} builds to {worst_tac}% total ink, above the "
                f"{limit}% {product.substrate} can carry — heavy areas may not dry "
                f"and can offset onto the next sheet."
            ),
            fix="Lighten the heaviest colour, or choose a stock that takes more ink.",
            where=placement.slug,
        )
    ]


def check_geometry(
    art: ArtworkProfile, product: PrintProduct, placement: Placement, spec: FormatSpec
) -> list[Violation]:
    if not spec.is_print:  # pragma: no cover - registry guarantees print canvases
        return [
            Violation(
                code="not_print_format",
                severity=ERROR,
                title="This canvas has no print size",
                detail="The placement's format carries no dpi, so it can't be printed.",
                where=placement.slug,
            )
        ]
    art_aspect = art.width_px / art.height_px
    canvas_aspect = spec.width / spec.height
    if abs(art_aspect - canvas_aspect) <= _ASPECT_TOL * canvas_aspect:
        return []
    return [
        Violation(
            code="aspect_mismatch",
            severity=WARNING,
            title="Artwork shape doesn't match the product",
            detail=(
                f"Your artwork is {art.width_px}×{art.height_px} but "
                f"{product.title.lower()} is {spec.width}×{spec.height} — it will be "
                f"cropped or letterboxed to fit."
            ),
            fix="Re-render the design at this product's size (magic resize) first.",
            where=placement.slug,
        )
    ]


_CHECKS = (
    check_resolution,
    check_text_size,
    check_bleed,
    check_safe_margin,
    check_contrast,
    check_gamut,
    check_ink_coverage,
    check_geometry,
)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_preflight(
    artwork: ArtworkProfile,
    product: PrintProduct,
    placement: Optional[Placement] = None,
) -> PreflightReport:
    """Proof one artwork against one product placement → a sorted report.

    ``placement`` defaults to the product's primary placement. Violations are
    ordered most-serious-first so the UI leads with what blocks the print.
    """
    pl = placement or product.primary_placement
    spec = pl.format
    if spec is None:  # pragma: no cover - registry guarantees a real format
        raise ValueError(f"placement {pl.slug!r} has no format")
    found: list[Violation] = []
    for check in _CHECKS:
        found.extend(check(artwork, product, pl, spec))
    found.sort(key=lambda v: _SEVERITY_RANK.get(v.severity, 9))
    return PreflightReport(product.slug, pl.slug, tuple(found))


def run_preflight_product(
    artwork_by_placement: dict[str, ArtworkProfile],
    product: PrintProduct,
) -> list[PreflightReport]:
    """Proof every placement of a (possibly double-sided) product.

    ``artwork_by_placement`` maps a placement slug to its artwork; a placement
    with no supplied artwork is skipped (a club may only be printing the front).
    """
    reports: list[PreflightReport] = []
    for pl in product.placements:
        art = artwork_by_placement.get(pl.slug)
        if art is not None:
            reports.append(run_preflight(art, product, pl))
    return reports


# ---------------------------------------------------------------------------
# Building an ArtworkProfile from a real image / a design manifest
# ---------------------------------------------------------------------------


def profile_from_image(source: Union[bytes, str, Path]) -> ArtworkProfile:
    """Read pixel size + a deterministic colour sample from a PNG/JPEG.

    The paper colour is sampled from the corners (the substrate-facing area);
    the inks are the most-used distinctly-different colours. Text size and bleed
    are *not* inferable from a flat raster, so they stay unknown — enrich with
    :func:`profile_from_design` when the design's metadata is to hand.
    """
    from PIL import Image  # local import keeps the module import light

    if isinstance(source, (str, Path)):
        img = Image.open(source)
    else:
        img = Image.open(io.BytesIO(source))
    img = img.convert("RGB")
    w, h = img.size
    paper = _sample_paper(img)
    inks = _sample_inks(img, paper)
    full_bleed = _detect_full_bleed(img, paper)
    return ArtworkProfile(
        width_px=w,
        height_px=h,
        ink_colours=inks,
        paper_colour=paper,
        full_bleed=full_bleed,
    )


def profile_from_design(
    design: dict,
    *,
    width_px: int,
    height_px: int,
    min_text_px: int = 0,
    content_inset_px: int = -1,
    full_bleed: Optional[bool] = None,
) -> ArtworkProfile:
    """Build a profile from a render brief / design-spec mapping.

    Reads the palette (background → paper, primary/secondary/accent → inks) from
    a BrandKit/brief-shaped ``design`` mapping; the caller supplies the pixel
    size and any known text/inset/bleed facts the renderer recorded.
    """
    paper = _first_hex(design, ("background", "paper", "ground", "surface", "bg"))
    inks = tuple(
        c
        for c in (
            _first_hex(design, ("primary", "primary_colour", "ink", "headline")),
            _first_hex(design, ("secondary", "secondary_colour")),
            _first_hex(design, ("accent", "accent_colour")),
        )
        if c
    )
    return ArtworkProfile(
        width_px=width_px,
        height_px=height_px,
        ink_colours=inks,
        paper_colour=paper,
        min_text_px=max(0, min_text_px),
        content_inset_px=content_inset_px,
        full_bleed=full_bleed,
    )


def _first_hex(design: dict, keys: tuple[str, ...]) -> str:
    for k in keys:
        v = (design or {}).get(k)
        if isinstance(v, str) and _hex_rgb(v) is not None:
            return "#" + v.strip().lstrip("#")
    return ""


def _to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _sample_paper(img) -> str:
    """The substrate-facing colour: the most common of the four corner pixels."""
    w, h = img.size
    pts = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    px = img.load()
    counts: dict[tuple[int, int, int], int] = {}
    for x, y in pts:
        c = px[x, y]
        counts[c] = counts.get(c, 0) + 1
    best = max(counts.items(), key=lambda kv: kv[1])[0]
    return _to_hex(best)


def _sample_inks(img, paper_hex: str, *, max_inks: int = 3) -> tuple[str, ...]:
    """The dominant colours that differ clearly from the paper.

    Quantises a downscaled copy to a small palette (deterministic) and keeps the
    most-used colours that are far enough from the paper to count as ink.
    """
    small = img.resize((64, 64))
    quant = small.quantize(colors=8, method=2)  # method=2 == MEDIANCUT, deterministic
    palette = quant.getpalette() or []
    counts = quant.getcolors() or []
    paper_rgb = _hex_rgb(paper_hex) or (255, 255, 255)
    ranked = sorted(counts, key=lambda kv: kv[0], reverse=True)
    inks: list[str] = []
    for _count, idx in ranked:
        rgb = (palette[idx * 3], palette[idx * 3 + 1], palette[idx * 3 + 2])
        dist = sum((rgb[i] - paper_rgb[i]) ** 2 for i in range(3)) ** 0.5
        if dist < 40:  # too close to the paper to be ink
            continue
        inks.append(_to_hex(rgb))
        if len(inks) >= max_inks:
            break
    return tuple(inks)


def _detect_full_bleed(img, paper_hex: str) -> Optional[bool]:
    """Heuristic: does the design run to the edges, or sit on a paper margin?

    Samples the outer 1-px ring. If it's essentially all the paper colour the
    artwork has a margin (*not* full bleed → bleed risk); if the ring carries
    other colour the design reaches the edge (full bleed). Conservative: returns
    ``None`` when it can't tell, so the bleed check stays an honest info.
    """
    w, h = img.size
    if w < 8 or h < 8:
        return None
    paper_rgb = _hex_rgb(paper_hex) or (255, 255, 255)
    px = img.load()
    step = max(1, min(w, h) // 32)
    edge_pts = (
        [(x, 0) for x in range(0, w, step)]
        + [(x, h - 1) for x in range(0, w, step)]
        + [(0, y) for y in range(0, h, step)]
        + [(w - 1, y) for y in range(0, h, step)]
    )
    non_paper = 0
    for x, y in edge_pts:
        rgb = px[x, y]
        if sum((rgb[i] - paper_rgb[i]) ** 2 for i in range(3)) ** 0.5 > 40:
            non_paper += 1
    frac = non_paper / max(1, len(edge_pts))
    if frac >= 0.25:
        return True  # the design clearly reaches the edges
    if frac == 0:
        return False  # a clean paper border — there's a margin, no bleed
    return None  # ambiguous — stay honest


__all__ = [
    "ERROR",
    "WARNING",
    "INFO",
    "Violation",
    "ArtworkProfile",
    "PreflightReport",
    "run_preflight",
    "run_preflight_product",
    "profile_from_image",
    "profile_from_design",
    "check_resolution",
    "check_text_size",
    "check_bleed",
    "check_safe_margin",
    "check_contrast",
    "check_gamut",
    "check_ink_coverage",
    "check_geometry",
]
