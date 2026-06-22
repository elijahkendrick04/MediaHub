"""Roadmap 1.20 Build B — the deterministic print auto-proofer (print_ready/proof.py).

Each check is pinned with a designed-to-fail and a designed-to-pass case, plus the
honest-info path when a fact is missing. Pure maths — no rendering, fully
deterministic.
"""

from __future__ import annotations

import io

import pytest

from PIL import Image

from mediahub.print_ready import products as P
from mediahub.print_ready import proof as PR
from mediahub.print_ready.proof import ArtworkProfile, Violation


def _png(width: int, height: int, colour=(255, 255, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buf, format="PNG")
    return buf.getvalue()


def _codes(report) -> set[str]:
    return {v.code for v in report.violations}


# ---------------------------------------------------------------------------
# Report model
# ---------------------------------------------------------------------------


def test_clean_report_is_ready_for_the_printer():
    poster = P.product_for("poster_a3")
    spec = poster.primary_placement.format
    art = ArtworkProfile(
        width_px=spec.width,
        height_px=spec.height,
        ink_colours=("#0A2540",),
        paper_colour="#FFFFFF",
        min_text_px=80,
        content_inset_px=spec.width // 4,
        full_bleed=True,
    )
    rep = PR.run_preflight(art, poster)
    assert rep.ok and rep.passed
    assert rep.violations == ()
    assert "Ready for the printer" in rep.summary()
    d = rep.to_dict()
    assert d["ok"] and d["counts"]["error"] == 0


def test_report_orders_errors_before_warnings():
    card = P.product_for("business_card")
    spec = card.primary_placement.format
    # tiny artwork (resolution error) + no bleed (warning)
    art = ArtworkProfile(width_px=120, height_px=78, full_bleed=False)
    rep = PR.run_preflight(art, card)
    severities = [v.severity for v in rep.violations]
    assert severities == sorted(severities, key=lambda s: {"error": 0, "warning": 1, "info": 2}[s])
    assert rep.violations[0].severity == "error"


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_resolution_blocks_when_far_too_low():
    a2 = P.product_for("poster_a2")
    art = ArtworkProfile(width_px=600, height_px=850)  # ~36 dpi on A2
    rep = PR.run_preflight(art, a2)
    res = [v for v in rep.violations if v.code == "resolution_low"]
    assert res and res[0].severity == "error"
    assert not rep.ok  # an error blocks export
    assert "dpi" in res[0].detail


def test_resolution_warns_when_a_bit_low_and_passes_at_target():
    poster = P.product_for("poster_a3")
    spec = poster.primary_placement.format  # 150 dpi target
    # ~110 dpi (between 0.5× and 1× target) → warning, not error
    low = ArtworkProfile(width_px=int(spec.width * 0.73), height_px=int(spec.height * 0.73))
    rep = PR.run_preflight(low, poster)
    res = [v for v in rep.violations if v.code == "resolution_low"]
    assert res and res[0].severity == "warning"
    # exactly the canvas size → at target → no resolution violation
    full = ArtworkProfile(width_px=spec.width, height_px=spec.height)
    assert "resolution_low" not in _codes(PR.run_preflight(full, poster))


# ---------------------------------------------------------------------------
# Text legibility
# ---------------------------------------------------------------------------


def test_text_too_small_warns_with_printed_point_size():
    banner = P.product_for("roll_up_banner")  # needs ≥24 pt
    spec = banner.primary_placement.format
    art = ArtworkProfile(width_px=spec.width, height_px=spec.height, min_text_px=20)
    rep = PR.run_preflight(art, banner)
    t = [v for v in rep.violations if v.code == "text_too_small"]
    assert t and t[0].severity == "warning" and "pt" in t[0].detail


def test_text_size_unknown_is_an_honest_info():
    rep = PR.run_preflight(
        ArtworkProfile(width_px=2480, height_px=3508), P.product_for("poster_a2")
    )
    info = [v for v in rep.violations if v.code == "text_size_unknown"]
    assert info and info[0].severity == "info"


def test_large_text_passes_text_check():
    poster = P.product_for("poster_a3")
    spec = poster.primary_placement.format
    art = ArtworkProfile(width_px=spec.width, height_px=spec.height, min_text_px=200)
    assert "text_too_small" not in _codes(PR.run_preflight(art, poster))


# ---------------------------------------------------------------------------
# Bleed + safe margin
# ---------------------------------------------------------------------------


def test_no_bleed_warns_for_trimmed_product():
    flyer = P.product_for("flyer")
    spec = flyer.primary_placement.format
    art = ArtworkProfile(width_px=spec.width, height_px=spec.height, full_bleed=False)
    rep = PR.run_preflight(art, flyer)
    b = [v for v in rep.violations if v.code == "no_bleed"]
    assert b and b[0].severity == "warning"


def test_bleed_unverified_when_unknown():
    flyer = P.product_for("flyer")
    spec = flyer.primary_placement.format
    art = ArtworkProfile(width_px=spec.width, height_px=spec.height)  # full_bleed=None
    assert "bleed_unverified" in _codes(PR.run_preflight(art, flyer))


def test_apparel_has_no_bleed_requirement():
    tee = P.product_for("club_tee")
    spec = tee.primary_placement.format  # bleed_mm == 0
    art = ArtworkProfile(width_px=spec.width, height_px=spec.height, full_bleed=False)
    codes = _codes(PR.run_preflight(art, tee, tee.placement("front")))
    assert "no_bleed" not in codes and "bleed_unverified" not in codes


def test_content_in_margin_warns_when_too_close():
    card = P.product_for("business_card")
    spec = card.primary_placement.format
    # content only ~1mm from the edge (card is 85mm wide → 1mm ≈ width_px/85)
    inset = int(spec.width / 85.0 * 1.0)
    art = ArtworkProfile(
        width_px=spec.width, height_px=spec.height, full_bleed=True, content_inset_px=inset
    )
    rep = PR.run_preflight(art, card)
    assert "content_in_margin" in _codes(rep)


# ---------------------------------------------------------------------------
# Contrast / gamut / ink coverage (colour science)
# ---------------------------------------------------------------------------


def test_low_contrast_on_paper_warns():
    poster = P.product_for("poster_a3")
    spec = poster.primary_placement.format
    art = ArtworkProfile(
        width_px=spec.width,
        height_px=spec.height,
        ink_colours=("#EDEDED",),  # pale grey ink
        paper_colour="#FFFFFF",  # on white
        full_bleed=True,
        min_text_px=120,
    )
    assert "low_contrast_on_paper" in _codes(PR.run_preflight(art, poster))


def test_strong_contrast_passes():
    poster = P.product_for("poster_a3")
    spec = poster.primary_placement.format
    art = ArtworkProfile(
        width_px=spec.width,
        height_px=spec.height,
        ink_colours=("#111111",),
        paper_colour="#FFFFFF",
        full_bleed=True,
        min_text_px=120,
    )
    assert "low_contrast_on_paper" not in _codes(PR.run_preflight(art, poster))


def test_vivid_colour_flags_gamut_shift():
    poster = P.product_for("poster_a3")
    spec = poster.primary_placement.format
    art = ArtworkProfile(
        width_px=spec.width,
        height_px=spec.height,
        ink_colours=("#00E5FF",),  # vivid cyan-ish, far out of CMYK gamut
        paper_colour="#FFFFFF",
        full_bleed=True,
        min_text_px=120,
    )
    assert "out_of_cmyk_gamut" in _codes(PR.run_preflight(art, poster))


def test_in_gamut_colour_does_not_flag():
    # ordinary / muted / dark colours are not flagged as out-of-gamut
    assert not PR._vivid_out_of_gamut("#808080")
    assert not PR._vivid_out_of_gamut("#000000")
    assert not PR._vivid_out_of_gamut("#0A2540")  # club navy
    # a neon does flag
    assert PR._vivid_out_of_gamut("#00E5FF")


def test_heavy_ink_coverage_warns_against_substrate_limit():
    banner = P.product_for("roll_up_banner")  # 280% TAC limit
    spec = banner.primary_placement.format
    # a very dark saturated red builds a high total area coverage (~290%)
    art = ArtworkProfile(
        width_px=spec.width,
        height_px=spec.height,
        ink_colours=("#1A0000",),
        paper_colour="#1A0000",  # flooded dark background
        full_bleed=True,
        min_text_px=400,
    )
    rep = PR.run_preflight(art, banner)
    cov = [v for v in rep.violations if v.code == "ink_coverage_high"]
    assert cov and cov[0].severity == "warning"
    assert "%" in cov[0].detail


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def test_aspect_mismatch_warns():
    mug = P.product_for("club_mug")  # wide wrap
    art = ArtworkProfile(width_px=1080, height_px=1920)  # tall artwork
    assert "aspect_mismatch" in _codes(PR.run_preflight(art, mug))


def test_matching_aspect_passes_geometry():
    poster = P.product_for("poster_a3")
    spec = poster.primary_placement.format
    art = ArtworkProfile(width_px=spec.width, height_px=spec.height)
    assert "aspect_mismatch" not in _codes(PR.run_preflight(art, poster))


# ---------------------------------------------------------------------------
# Multi-placement (double-sided) products
# ---------------------------------------------------------------------------


def test_preflight_product_proofs_each_supplied_placement():
    tee = P.product_for("club_tee")
    fspec = tee.placement("front").format
    arts = {
        "front": ArtworkProfile(width_px=fspec.width, height_px=fspec.height, min_text_px=300),
        "back": ArtworkProfile(width_px=300, height_px=375),  # low-res back
    }
    reports = PR.run_preflight_product(arts, tee)
    assert {r.placement_slug for r in reports} == {"front", "back"}
    back = next(r for r in reports if r.placement_slug == "back")
    assert "resolution_low" in _codes(back)


def test_preflight_product_skips_unsupplied_placements():
    tee = P.product_for("club_tee")
    fspec = tee.placement("front").format
    reports = PR.run_preflight_product(
        {"front": ArtworkProfile(width_px=fspec.width, height_px=fspec.height)}, tee
    )
    assert [r.placement_slug for r in reports] == ["front"]


# ---------------------------------------------------------------------------
# Profile builders
# ---------------------------------------------------------------------------


def test_profile_from_image_reads_size_and_paper():
    art = PR.profile_from_image(_png(800, 600, (250, 250, 248)))
    assert art.width_px == 800 and art.height_px == 600
    assert PR._hex_rgb(art.paper_colour) == (250, 250, 248)


def test_profile_from_image_is_deterministic():
    data = _png(400, 400, (12, 37, 64))
    a, b = PR.profile_from_image(data), PR.profile_from_image(data)
    assert a == b


def test_profile_from_image_detects_full_bleed_vs_margin():
    # A flooded photo-like image (varied edges) reads as full bleed.
    buf = io.BytesIO()
    img = Image.new("RGB", (200, 200), (10, 40, 80))
    for x in range(200):
        for y in range(0, 200, 2):
            img.putpixel((x, y), (200, 60, 30))
    img.save(buf, format="PNG")
    assert PR.profile_from_image(buf.getvalue()).full_bleed is True
    # A clean white border reads as a margin (no bleed).
    art = PR.profile_from_image(_png(300, 300, (255, 255, 255)))
    assert art.full_bleed is False


def test_profile_from_design_maps_palette_to_inks_and_paper():
    art = PR.profile_from_design(
        {"background": "#FFFFFF", "primary": "#0A2540", "accent": "#C8102E"},
        width_px=1754,
        height_px=2480,
        min_text_px=60,
    )
    assert art.paper_colour == "#FFFFFF"
    assert "#0A2540" in art.ink_colours and "#C8102E" in art.ink_colours
    assert art.min_text_px == 60


def test_artwork_profile_rejects_bad_dimensions():
    with pytest.raises(ValueError):
        ArtworkProfile(width_px=0, height_px=100)


def test_violation_serialises():
    v = Violation("c", "warning", "T", "d", fix="f", where="front")
    assert v.to_dict() == {
        "code": "c", "severity": "warning", "title": "T",
        "detail": "d", "fix": "f", "where": "front",
    }
