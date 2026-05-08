"""Tests for graphic_renderer.render — Playwright HTML→PNG renderer.

These tests run real Playwright renders. They are skipped if Playwright/Chromium
isn't installed in the environment.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate as gen_brief
from mediahub.graphic_renderer.render import (
    GeneratedVisual,
    RenderResult,
    darken,
    lighten,
    render_brief,
)
from mediahub.graphic_renderer.variants import FORMAT_SIZES, render_all_formats
from mediahub.media_requirements.evaluator import EvaluationResult


def _have_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa
        # Probe browser launch
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
                browser.close()
                return True
            except Exception:
                return False
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _have_playwright(), reason="Playwright/Chromium not available")


def _brand():
    return BrandKit(
        profile_id="test",
        display_name="Test Swim Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="TSC",
    )


def _eval(layout="individual_hero"):
    return EvaluationResult(
        content_item_id="ci-1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout=layout,
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label="NEW PB",
        explain="ok",
    )


def _brief(layout="individual_hero"):
    item = {
        "id": "ci-1",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
        },
    }
    return gen_brief(item, _eval(layout=layout), _brand(),
                     profile_id="test", meet_name="Manchester Open",
                     venue_name="Manchester Aquatics Centre")


def test_color_helpers():
    assert darken("#FFFFFF", 0.5) != "#FFFFFF"
    assert lighten("#000000", 0.5) != "#000000"
    # Bounds-safe
    out = darken("#0E5BFF", 0.30)
    assert out.startswith("#") and len(out) == 7


def test_render_brief_individual_hero(tmp_path: Path):
    brief = _brief("individual_hero")
    res = render_brief(brief, output_dir=tmp_path, size=(1080, 1350),
                       format_name="feed_portrait", brand_kit=_brand())
    assert isinstance(res, RenderResult)
    assert isinstance(res.visual, GeneratedVisual)
    assert res.visual.format_name == "feed_portrait"
    assert res.visual.width == 1080 and res.visual.height == 1350
    out = Path(res.visual.file_path)
    assert out.exists()
    # Real PNG, not a placeholder; expect substantial size
    assert out.stat().st_size > 50_000, f"PNG too small: {out.stat().st_size}"
    # PNG magic bytes
    with open(out, "rb") as fh:
        assert fh.read(8) == b"\x89PNG\r\n\x1a\n"


def test_render_brief_medal_card(tmp_path: Path):
    brief = _brief("medal_card")
    # Medal needs a place in the achievement
    brief.text_layers["place"] = "1"
    res = render_brief(brief, output_dir=tmp_path, size=(1080, 1080),
                       format_name="feed_square", brand_kit=_brand())
    out = Path(res.visual.file_path)
    assert out.exists()
    assert out.stat().st_size > 50_000


def test_render_all_formats_produces_trio(tmp_path: Path):
    brief = _brief("individual_hero")
    results = render_all_formats(brief, output_dir=tmp_path, brand_kit=_brand())
    # Should produce at least the default trio
    assert len(results) >= 3
    formats = {r.visual.format_name for r in results}
    assert {"feed_square", "feed_portrait", "story"}.issubset(formats)
    for r in results:
        out = Path(r.visual.file_path)
        assert out.exists()
        assert out.stat().st_size > 30_000


def test_format_sizes_constant_has_required_formats():
    for f in ("feed_square", "feed_portrait", "story"):
        assert f in FORMAT_SIZES
    assert FORMAT_SIZES["feed_square"] == (1080, 1080)
    assert FORMAT_SIZES["feed_portrait"] == (1080, 1350)
    assert FORMAT_SIZES["story"] == (1080, 1920)
