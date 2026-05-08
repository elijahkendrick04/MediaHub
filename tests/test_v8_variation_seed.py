"""V8.1 issue 4 — variation_seed produces visibly different briefs and PNGs.

Asserts:
  - Three different seeds produce three different briefs (palette / family /
    image_treatment / hook differ pairwise).
  - Re-rendering the same brief data with seeds 1 and 2 produces PNGs whose
    bytes are not identical.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate as gen_brief
from mediahub.graphic_renderer.render import render_brief
from mediahub.media_requirements.evaluator import EvaluationResult


def _have_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
                browser.close()
                return True
            except Exception:
                return False
    except Exception:
        return False


def _brand():
    return BrandKit(
        profile_id="test",
        display_name="Test Swim Club",
        primary_colour="#A30D2D",
        secondary_colour="#000000",
        accent_colour="#FFD86E",
        short_name="TSC",
    )


def _eval():
    return EvaluationResult(
        content_item_id="ci-1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout=None,
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label="NEW PB",
        explain="ok",
    )


def _item():
    return {
        "id": "ci-1",
        "post_angle": "confirmed_official_pb",
        "achievement": {
            "swim_id": "ci-1",
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
            "post_angle": "confirmed_official_pb",
        },
    }


def test_seed_changes_layout_palette_and_hook():
    """Briefs at seeds 1, 2, 3 must differ from each other and from seed 0."""
    item, ev, brand = _item(), _eval(), _brand()
    briefs = [
        gen_brief(item, ev, brand, profile_id="test", variation_seed=s)
        for s in (0, 1, 2, 3)
    ]
    # Pairwise — at least one of (palette, layout_template, primary_hook,
    # image_treatment) must differ between every pair.
    for i in range(len(briefs)):
        for j in range(i + 1, len(briefs)):
            a, b = briefs[i], briefs[j]
            differs = (
                a.palette != b.palette
                or a.layout_template != b.layout_template
                or a.primary_hook != b.primary_hook
                or a.image_treatment != b.image_treatment
            )
            assert differs, f"Briefs {i} and {j} are identical: {a.to_dict()}"

    # Specific contracts:
    # seed 1 -> same family but inverted colour roles (primary <-> secondary)
    assert briefs[1].layout_template == briefs[0].layout_template
    assert briefs[1].palette["primary"] == briefs[0].palette["secondary"]
    assert briefs[1].palette["secondary"] == briefs[0].palette["primary"]

    # seed 2 -> different layout family
    assert briefs[2].layout_template != briefs[0].layout_template

    # seed 3 -> text-led / no photo
    assert "no photo" in briefs[3].image_treatment.lower() or "text-led" in briefs[3].image_treatment.lower()


def test_same_seed_is_deterministic_for_brief_shape():
    """Two calls with the same seed yield identical brief shape (modulo id)."""
    item, ev, brand = _item(), _eval(), _brand()
    a = gen_brief(item, ev, brand, profile_id="test", variation_seed=2)
    b = gen_brief(item, ev, brand, profile_id="test", variation_seed=2)
    # Compare everything except the random id and timestamp.
    ad, bd = a.to_dict(), b.to_dict()
    for drop in ("id", "created_at", "why_this_design"):
        ad.pop(drop, None)
        bd.pop(drop, None)
    assert ad == bd


@pytest.mark.skipif(not _have_playwright(), reason="Playwright/Chromium not available")
def test_seed_1_and_seed_2_pngs_differ_bytewise(tmp_path: Path):
    """The PNG produced for seed=1 must NOT be byte-identical to seed=2."""
    item, ev, brand = _item(), _eval(), _brand()
    out1 = tmp_path / "s1"
    out2 = tmp_path / "s2"
    out1.mkdir()
    out2.mkdir()

    brief1 = gen_brief(item, ev, brand, profile_id="test", variation_seed=1)
    brief2 = gen_brief(item, ev, brand, profile_id="test", variation_seed=2)

    r1 = render_brief(brief1, output_dir=out1, size=(1080, 1350),
                      format_name="feed_portrait", brand_kit=brand)
    r2 = render_brief(brief2, output_dir=out2, size=(1080, 1350),
                      format_name="feed_portrait", brand_kit=brand)

    p1 = Path(r1.visual.file_path).read_bytes()
    p2 = Path(r2.visual.file_path).read_bytes()
    assert p1[:8] == b"\x89PNG\r\n\x1a\n" and p2[:8] == b"\x89PNG\r\n\x1a\n"
    assert p1 != p2, "Seed-1 and seed-2 PNGs were byte-identical (variation seed broken)"
