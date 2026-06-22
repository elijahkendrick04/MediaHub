"""Roadmap 1.20 Build A — print profiles & the print/merch product registry.

Pins two things:
- the physical-dimension helpers added to ``FormatSpec`` (mm / in / effective dpi);
- the ``print_ready.products`` registry's integrity and public API.

Pure data, no rendering — fast and deterministic.
"""

from __future__ import annotations

import pytest

from mediahub.club_platform import format_catalog as fc
from mediahub.print_ready import products as P


# ---------------------------------------------------------------------------
# FormatSpec physical-dimension helpers (the "print profile on FormatSpec")
# ---------------------------------------------------------------------------


def test_screen_native_format_has_no_physical_size():
    ig = fc.format_for("ig_post")
    assert ig.dpi == 0 and not ig.is_print
    assert ig.width_mm == 0.0 and ig.height_mm == 0.0
    assert ig.width_in == 0.0 and ig.height_in == 0.0
    assert ig.physical_label == ""
    assert ig.effective_dpi(1000) == 0.0


def test_print_format_physical_size_matches_dpi_maths():
    a3 = fc.format_for("print_poster_a3")
    assert a3.is_print and a3.dpi == 150
    # 1754 px / 150 dpi * 25.4 ≈ 297 mm (A3 short edge), 2480 → ~420 mm.
    assert round(a3.width_mm) == 297
    assert round(a3.height_mm) == 420
    assert round(a3.width_in, 1) == 11.7
    assert "mm" in a3.physical_label


def test_effective_dpi_catches_the_low_resolution_trap():
    a2 = fc.format_for("print_poster_a2")
    # A small social image stretched onto an A2 poster is nowhere near print res.
    assert a2.effective_dpi(1000, axis="width") < 100
    # Artwork rendered at the canvas size lands exactly on the target dpi.
    assert a2.effective_dpi(a2.width, axis="width") == pytest.approx(150.0, abs=0.5)
    assert a2.effective_dpi(a2.height, axis="height") == pytest.approx(150.0, abs=0.5)


def test_to_dict_carries_physical_fields():
    d = fc.format_for("business_card").to_dict()
    for key in ("width_mm", "height_mm", "physical_label", "bleed_mm", "dpi", "is_print"):
        assert key in d
    assert d["is_print"] is True
    assert d["physical_label"]


# ---------------------------------------------------------------------------
# New print/merch catalogue entries
# ---------------------------------------------------------------------------

_NEW_PRINT = ("business_card", "postcard_a6", "print_flyer_a5", "print_poster_a3",
              "print_poster_a2", "sticker_square", "roll_up_banner")
_NEW_MERCH = ("tee_front", "tee_back", "mug_wrap", "tote_bag")


@pytest.mark.parametrize("slug", _NEW_PRINT + _NEW_MERCH)
def test_new_formats_are_print_aware(slug):
    spec = fc.format_for(slug)
    assert spec is not None, slug
    assert spec.is_print, f"{slug} should carry print intent (dpi/bleed)"
    assert spec.dpi > 0
    assert spec.physical_label  # has an honest physical size


def test_new_categories_present_and_grouped():
    cats = fc.categories()
    assert "print" in cats and "merch" in cats
    assert {f.slug for f in fc.formats_in_category("print")} >= set(_NEW_PRINT)
    assert {f.slug for f in fc.formats_in_category("merch")} >= set(_NEW_MERCH)


def test_print_and_merch_formats_are_universal():
    # A club can print any design — these must not be gated behind post types.
    for slug in _NEW_PRINT + _NEW_MERCH:
        assert fc.format_for(slug).requires_post_types == ()
    universal = {f.slug for f in fc.formats_for_sport(None)}
    assert set(_NEW_PRINT) <= universal and set(_NEW_MERCH) <= universal


def test_catalogue_slugs_still_unique_after_additions():
    seen: set[str] = set()
    for f in fc.all_formats():
        assert f.slug not in seen, f"duplicate slug {f.slug}"
        seen.add(f.slug)


# ---------------------------------------------------------------------------
# Product registry integrity
# ---------------------------------------------------------------------------


def test_registry_non_empty_and_covers_families():
    prods = P.all_products()
    assert len(prods) >= 8
    fams = {p.family for p in prods}
    assert {"paper", "apparel", "drinkware", "accessory"} <= fams


def test_every_product_is_structurally_sound():
    for p in P.all_products():
        assert p.family in P.FAMILIES, p.slug
        assert p.print_method in P.PRINT_METHODS, p.slug
        assert p.placements, p.slug
        assert p.target_dpi > 0, p.slug
        assert p.min_text_pt > 0, p.slug
        assert 100 <= p.max_ink_coverage <= 400, p.slug
        assert p.fulfilment_sku, p.slug
        # every placement points at a real, print-aware canvas
        for pl in p.placements:
            spec = pl.format
            assert spec is not None, (p.slug, pl.slug)
            assert spec.is_print, (p.slug, pl.slug)
            assert pl.area_w_mm > 0 and pl.area_h_mm > 0


def test_product_slugs_are_unique():
    seen: set[str] = set()
    for p in P.all_products():
        assert p.slug not in seen, f"duplicate product {p.slug}"
        seen.add(p.slug)


def test_double_sided_detection():
    tee = P.product_for("club_tee")
    assert tee.double_sided and len(tee.placements) == 2
    assert {pl.slug for pl in tee.placements} == {"front", "back"}
    card = P.product_for("business_card")
    assert card.double_sided  # front + back
    poster = P.product_for("poster_a3")
    assert not poster.double_sided
    assert poster.primary_placement.slug == "front"


def test_placement_lookup():
    tee = P.product_for("club_tee")
    back = tee.placement("back")
    assert back is not None and back.format_slug == "tee_back"
    assert tee.placement("sleeve") is None


def test_lookup_helpers():
    assert P.product_for("club_mug").family == "drinkware"
    assert P.product_for("nope") is None
    assert P.is_known("tote_bag") and not P.is_known("nope")
    paper = P.products_in_family("paper")
    assert {p.slug for p in paper} >= {"business_card", "flyer", "poster_a3"}
    assert "paper" in P.families()


def test_grouped_shape_matches_picker_contract():
    groups = P.grouped()
    assert groups and all({"family", "label", "products"} <= set(g) for g in groups)
    # families appear in the declared order
    order = [g["family"] for g in groups]
    assert order == [f for f in P.FAMILIES if f in order]
    # a product dict carries everything the UI + proofer need
    one = groups[0]["products"][0]
    for key in ("slug", "title", "family", "placements", "target_dpi",
                "max_ink_coverage", "min_text_pt", "mockup_template", "double_sided"):
        assert key in one


def test_invalid_product_construction_is_rejected():
    good = P.product_for("flyer").primary_placement
    with pytest.raises(ValueError):
        P.PrintProduct(
            slug="bad", title="Bad", family="not_a_family", description="",
            placements=(good,), substrate="", print_method="litho",
            target_dpi=300, min_text_pt=6.0, max_ink_coverage=300,
            mockup_template="", fulfilment_sku="x",
        )
    with pytest.raises(ValueError):
        P.PrintProduct(
            slug="bad", title="Bad", family="paper", description="",
            placements=(), substrate="", print_method="litho",
            target_dpi=300, min_text_pt=6.0, max_ink_coverage=300,
            mockup_template="", fulfilment_sku="x",
        )
