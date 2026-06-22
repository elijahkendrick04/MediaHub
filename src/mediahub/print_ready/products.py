"""The print & merch product registry (roadmap 1.20).

A :class:`FormatSpec` (in ``club_platform.format_catalog``) is a *canvas* — pixels,
bleed, a target dpi. A **product** is the physical thing that canvas is printed on:
an A3 poster on 170 gsm silk, a cotton tee printed front *and* back, a sublimated
mug. This module is the pure-data registry that ties the two together and carries
the production facts the rest of the pipeline needs:

* which canvas(es) a product prints — its **placements** (front / back / wrap);
* the **substrate**, **print method** and recommended **target dpi** for legible
  output on that method (litho resolves fine type; DTG on cotton does not);
* the **ink limit** (Total Area Coverage %) the substrate can carry before it
  won't dry / offsets — fed to the preflight proofer;
* the **mockup** scene that previews it, and a provider-agnostic **fulfilment
  SKU** hint for the (optional, later) fulfilment slot.

Design rules, same as the format catalogue: **pure data, no AI, no I/O.** Building
the registry touches no network and no provider. The judgement-free physical facts
live here; the deterministic *proofing* of a specific design against a product
lives in :mod:`mediahub.print_ready.proof`, and the export in
:mod:`mediahub.print_ready.engine`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from mediahub.club_platform.format_catalog import FormatSpec, format_for
from mediahub.club_platform.post_types import canonical_slug

# Product families, in the order the UI groups them.
FAMILIES: tuple[str, ...] = ("paper", "signage", "apparel", "drinkware", "accessory")

# Print methods we model — each implies a sensible legibility floor.
PRINT_METHODS: tuple[str, ...] = (
    "litho",  # offset litho — sharpest, fine type fine
    "digital",  # digital toner / inkjet — sharp, short runs
    "large_format",  # banners / signage — viewed at distance, coarse dpi
    "dtg",  # direct-to-garment — cotton wicks, no fine type
    "sublimation",  # dye-sub onto coated mugs / poly — sharp on its substrate
    "vinyl",  # cut/print vinyl — stickers, decals
)


@dataclass(frozen=True)
class Placement:
    """One printable region on a product (a tee *front*, a mug *wrap*).

    ``format_slug`` is the :class:`FormatSpec` canvas the artwork is designed on;
    ``area_w_mm`` / ``area_h_mm`` are the physical print area on the product, which
    the proofer uses to compute the *effective* dpi the artwork lands at.
    """

    slug: str
    label: str
    format_slug: str
    area_w_mm: float
    area_h_mm: float

    @property
    def format(self) -> Optional[FormatSpec]:
        return format_for(self.format_slug)

    def to_dict(self) -> dict:
        spec = self.format
        return {
            "slug": self.slug,
            "label": self.label,
            "format_slug": self.format_slug,
            "area_w_mm": self.area_w_mm,
            "area_h_mm": self.area_h_mm,
            "canvas_px": list(spec.size) if spec else None,
        }


@dataclass(frozen=True)
class PrintProduct:
    """A physical print/merch product — the production profile around a canvas."""

    slug: str
    title: str
    family: str
    description: str
    placements: tuple[Placement, ...]
    substrate: str
    print_method: str
    target_dpi: int
    min_text_pt: float
    max_ink_coverage: int  # Total Area Coverage ceiling, % (sum of C+M+Y+K)
    mockup_template: str
    fulfilment_sku: str
    eco: str = ""  # honest sustainability note (a provider attribute, when known)

    def __post_init__(self) -> None:
        if self.family not in FAMILIES:
            raise ValueError(f"unknown product family: {self.family!r}")
        if self.print_method not in PRINT_METHODS:
            raise ValueError(f"unknown print method: {self.print_method!r}")
        if not self.placements:
            raise ValueError(f"product {self.slug!r} has no placements")
        if self.target_dpi <= 0:
            raise ValueError(f"product {self.slug!r} target_dpi must be positive")
        if not (100 <= self.max_ink_coverage <= 400):
            raise ValueError(f"product {self.slug!r} max_ink_coverage out of range")

    @property
    def double_sided(self) -> bool:
        return len(self.placements) > 1

    @property
    def primary_placement(self) -> Placement:
        return self.placements[0]

    def placement(self, slug: object) -> Optional[Placement]:
        want = canonical_slug(slug)
        return next((p for p in self.placements if p.slug == want), None)

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "title": self.title,
            "family": self.family,
            "description": self.description,
            "placements": [p.to_dict() for p in self.placements],
            "double_sided": self.double_sided,
            "substrate": self.substrate,
            "print_method": self.print_method,
            "target_dpi": self.target_dpi,
            "min_text_pt": self.min_text_pt,
            "max_ink_coverage": self.max_ink_coverage,
            "mockup_template": self.mockup_template,
            "fulfilment_sku": self.fulfilment_sku,
            "eco": self.eco,
        }


# ---------------------------------------------------------------------------
# The registry. Ink-limit (TAC) figures are standard pressroom values: coated
# litho 300%, uncoated 280%, large-format 280%, DTG on cotton ~270% (the fibre
# wicks), dye-sub on a coated mug ~320%. Min legible text is the method floor at
# the *printed* size — posters are read at distance so their floor is larger.
# ---------------------------------------------------------------------------

_PRODUCTS: tuple[PrintProduct, ...] = (
    # --- Paper ------------------------------------------------------------
    PrintProduct(
        slug="business_card",
        title="Business card",
        family="paper",
        description="Double-sided 85 × 55 mm contact card for coaches & committee.",
        placements=(
            Placement("front", "Front", "business_card", 85.0, 55.0),
            Placement("back", "Back", "business_card", 85.0, 55.0),
        ),
        substrate="350 gsm silk, matt-laminated",
        print_method="litho",
        target_dpi=300,
        min_text_pt=6.0,
        max_ink_coverage=300,
        mockup_template="flatlay",
        fulfilment_sku="paper-bizcard-85x55-350silk",
    ),
    PrintProduct(
        slug="postcard",
        title="Postcard",
        family="paper",
        description="A6 save-the-date / thank-you / match-day postcard.",
        placements=(Placement("front", "Front", "postcard_a6", 105.0, 148.0),),
        substrate="350 gsm uncoated board",
        print_method="digital",
        target_dpi=300,
        min_text_pt=7.0,
        max_ink_coverage=280,
        mockup_template="flatlay",
        fulfilment_sku="paper-postcard-a6-350uncoated",
    ),
    PrintProduct(
        slug="flyer",
        title="Flyer",
        family="paper",
        description="A5 handout flyer — open days, learn-to-swim, fundraisers.",
        placements=(Placement("front", "Front", "print_flyer_a5", 148.0, 210.0),),
        substrate="170 gsm silk",
        print_method="digital",
        target_dpi=300,
        min_text_pt=7.0,
        max_ink_coverage=300,
        mockup_template="poster_wall",
        fulfilment_sku="paper-flyer-a5-170silk",
    ),
    PrintProduct(
        slug="poster_a3",
        title="Poster (A3)",
        family="paper",
        description="A3 noticeboard poster for the leisure-centre wall.",
        placements=(Placement("front", "Front", "print_poster_a3", 297.0, 420.0),),
        substrate="170 gsm silk",
        print_method="litho",
        target_dpi=150,
        min_text_pt=12.0,
        max_ink_coverage=300,
        mockup_template="poster_wall",
        fulfilment_sku="paper-poster-a3-170silk",
        eco="Recycled-stock option available from the fulfilment partner.",
    ),
    PrintProduct(
        slug="poster_a2",
        title="Poster (A2)",
        family="paper",
        description="A2 gala / open-day headline poster.",
        placements=(Placement("front", "Front", "print_poster_a2", 420.0, 594.0),),
        substrate="200 gsm silk",
        print_method="litho",
        target_dpi=150,
        min_text_pt=14.0,
        max_ink_coverage=300,
        mockup_template="poster_wall",
        fulfilment_sku="paper-poster-a2-200silk",
        eco="Recycled-stock option available from the fulfilment partner.",
    ),
    PrintProduct(
        slug="sticker",
        title="Sticker",
        family="paper",
        description="75 mm die-cut square sticker / kit-bag badge.",
        placements=(Placement("face", "Face", "sticker_square", 75.0, 75.0),),
        substrate="White vinyl, gloss-laminated, kiss-cut",
        print_method="vinyl",
        target_dpi=300,
        min_text_pt=6.0,
        max_ink_coverage=300,
        mockup_template="flatlay",
        fulfilment_sku="vinyl-sticker-75sq-gloss",
    ),
    # --- Signage ----------------------------------------------------------
    PrintProduct(
        slug="roll_up_banner",
        title="Roll-up banner",
        family="signage",
        description="850 × 2000 mm pull-up banner for galas & recruitment stands.",
        placements=(Placement("face", "Face", "roll_up_banner", 850.0, 2000.0),),
        substrate="440 gsm anti-curl PVC + cassette",
        print_method="large_format",
        target_dpi=100,
        min_text_pt=24.0,
        max_ink_coverage=280,
        mockup_template="poster_wall",
        fulfilment_sku="signage-rollup-850x2000-pvc",
    ),
    # --- Apparel ----------------------------------------------------------
    PrintProduct(
        slug="club_tee",
        title="Club t-shirt",
        family="apparel",
        description="Front + back DTG-printed cotton tee for the fundraising kit.",
        placements=(
            Placement("front", "Front", "tee_front", 280.0, 350.0),
            Placement("back", "Back", "tee_back", 280.0, 350.0),
        ),
        substrate="180 gsm ring-spun cotton",
        print_method="dtg",
        target_dpi=200,
        min_text_pt=14.0,
        max_ink_coverage=270,
        mockup_template="tee",
        fulfilment_sku="apparel-tee-dtg-cotton",
        eco="Organic-cotton blank option available from the fulfilment partner.",
    ),
    # --- Drinkware --------------------------------------------------------
    PrintProduct(
        slug="club_mug",
        title="Club mug",
        family="drinkware",
        description="Sublimated 11 oz ceramic mug — wrap-around artwork.",
        placements=(Placement("wrap", "Wrap", "mug_wrap", 200.0, 85.0),),
        substrate="11 oz coated white ceramic",
        print_method="sublimation",
        target_dpi=300,
        min_text_pt=8.0,
        max_ink_coverage=320,
        mockup_template="mug",
        fulfilment_sku="drinkware-mug-11oz-sublimation",
    ),
    # --- Accessory --------------------------------------------------------
    PrintProduct(
        slug="tote_bag",
        title="Tote bag",
        family="accessory",
        description="Cotton tote with a single large front print.",
        placements=(Placement("face", "Face", "tote_bag", 350.0, 400.0),),
        substrate="140 gsm cotton canvas",
        print_method="dtg",
        target_dpi=200,
        min_text_pt=14.0,
        max_ink_coverage=270,
        mockup_template="tote",
        fulfilment_sku="accessory-tote-dtg-cotton",
        eco="Organic-cotton blank option available from the fulfilment partner.",
    ),
)


# Fast lookup, validated for slug-uniqueness + placement integrity at import.
_BY_SLUG: dict[str, PrintProduct] = {}
for _product in _PRODUCTS:
    if _product.slug in _BY_SLUG:  # pragma: no cover - guards a developer typo
        raise ValueError(f"duplicate PrintProduct slug: {_product.slug}")
    for _pl in _product.placements:
        if _pl.format is None:  # pragma: no cover - guards a developer typo
            raise ValueError(
                f"product {_product.slug!r} placement {_pl.slug!r} references "
                f"unknown format {_pl.format_slug!r}"
            )
    _BY_SLUG[_product.slug] = _product


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def all_products() -> tuple[PrintProduct, ...]:
    """Every registered product, in registry (family) order."""
    return _PRODUCTS


def product_for(slug: object) -> Optional[PrintProduct]:
    """The :class:`PrintProduct` for ``slug`` (canonicalised), or ``None``."""
    return _BY_SLUG.get(canonical_slug(slug))


def is_known(slug: object) -> bool:
    return canonical_slug(slug) in _BY_SLUG


def products_in_family(family: str) -> list[PrintProduct]:
    """Products in one family, in registry order."""
    return [p for p in _PRODUCTS if p.family == family]


def families() -> tuple[str, ...]:
    """Families that actually carry at least one product, in order."""
    present = {p.family for p in _PRODUCTS}
    return tuple(f for f in FAMILIES if f in present)


def grouped() -> list[dict]:
    """The catalogue grouped by family — the shape the product picker renders."""
    out: list[dict] = []
    for fam in families():
        out.append(
            {
                "family": fam,
                "label": fam.replace("_", " ").title(),
                "products": [p.to_dict() for p in products_in_family(fam)],
            }
        )
    return out


__all__ = [
    "FAMILIES",
    "PRINT_METHODS",
    "Placement",
    "PrintProduct",
    "all_products",
    "product_for",
    "is_known",
    "products_in_family",
    "families",
    "grouped",
]
