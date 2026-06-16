"""G1.3 — landscape & extended aspect-ratio support (16:9, 3:2, 4:3).

Two layers:
  * Pure-logic tests for the per-format composition helpers — no Playwright,
    so they always run. They lock the ``FORMAT_SIZES`` contract, the aspect
    classifier, the v1/v2 composition rules, and (critically) the
    *byte-identical* guarantee: the standard square/portrait/story formats must
    pick up none of the new behaviour.
  * Real Playwright renders proving the new formats produce correct-dimension
    PNGs and carry the composition retune — skipped if Chromium is absent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mediahub.graphic_renderer.variants import FORMAT_SIZES, render_all_formats
from mediahub.graphic_renderer.render import (
    render_brief,
    _format_aspect,
    _scale_for_format,
    _v2_fit_boxes,
    _format_composition_css,
    _LANDSCAPE_ASPECTS,
)


# --------------------------------------------------------------------------
# Pure logic — no browser required
# --------------------------------------------------------------------------

# the three families G1.3 adds, with their canonical sizes + nominal ratios
_NEW_FORMATS = {
    "landscape": ((1920, 1080), 16 / 9),
    "landscape_3_2": ((1620, 1080), 3 / 2),
    "landscape_4_3": ((1440, 1080), 4 / 3),
}

# the dicts the pre-G1.3 _scale_for_format returned for the standard formats
_LEGACY_SCALE = {
    (1080, 1080): {"surname": 0.32, "first": 0.075, "event": 0.026, "result": 0.055, "ribbon": 0.034},
    (1080, 1350): {"surname": 0.34, "first": 0.07, "event": 0.024, "result": 0.052, "ribbon": 0.032},
    (1080, 1920): {"surname": 0.28, "first": 0.06, "event": 0.022, "result": 0.045, "ribbon": 0.028},
}


def test_new_landscape_formats_present_with_correct_ratios():
    for name, (size, ratio) in _NEW_FORMATS.items():
        assert name in FORMAT_SIZES, f"{name} missing from FORMAT_SIZES"
        assert FORMAT_SIZES[name] == size
        w, h = size
        assert w > h, f"{name} must be landscape (w > h)"
        assert abs(w / h - ratio) < 0.01, f"{name} ratio {w / h:.3f} != {ratio:.3f}"


def test_existing_formats_untouched():
    # G1.3 is additive — it must not disturb the pre-existing five formats.
    assert FORMAT_SIZES["feed_square"] == (1080, 1080)
    assert FORMAT_SIZES["feed_portrait"] == (1080, 1350)
    assert FORMAT_SIZES["story"] == (1080, 1920)
    assert FORMAT_SIZES["reel_cover"] == (1080, 1920)
    assert FORMAT_SIZES["carousel_slide"] == (1080, 1080)


def test_format_aspect_classification():
    assert _format_aspect(1080, 1080) == "square"
    assert _format_aspect(1080, 1350) == "portrait"
    assert _format_aspect(1080, 1920) == "story"
    assert _format_aspect(1920, 1080) == "landscape_169"
    assert _format_aspect(1620, 1080) == "landscape_32"
    assert _format_aspect(1440, 1080) == "landscape_43"
    # every FORMAT_SIZES entry classifies into a known family without error
    for _name, (w, h) in FORMAT_SIZES.items():
        assert _format_aspect(w, h)


def test_format_aspect_snaps_off_nominal_widths():
    assert _format_aspect(2560, 1080) == "landscape_169"  # 21:9 ultra-wide
    assert _format_aspect(1700, 1080) == "landscape_32"  # ~1.57, between 3:2 and 16:9
    assert _format_aspect(1400, 1080) == "landscape_43"  # ~1.30, near 4:3


def test_scale_for_format_legacy_values_unchanged():
    # The standard formats must return EXACTLY the pre-G1.3 multipliers, so
    # their renders stay byte-identical.
    for size, expected in _LEGACY_SCALE.items():
        assert _scale_for_format(*size) == expected


def test_scale_for_format_landscape_distinct_and_keyed():
    s169 = _scale_for_format(1920, 1080)
    s32 = _scale_for_format(1620, 1080)
    s43 = _scale_for_format(1440, 1080)
    # the three landscape families are distinct from one another …
    assert s169 != s32 and s32 != s43 and s169 != s43
    # … and from the portrait baseline
    assert s169 != _scale_for_format(1080, 1350)
    # wider canvas -> larger height-share multipliers (16:9 > 3:2 > 4:3)
    assert s169["surname"] > s32["surname"] > s43["surname"]
    assert s169["result"] > s32["result"] > s43["result"]
    # no slot dropped or added relative to the legacy contract
    assert set(s169) == {"surname", "first", "event", "result", "ribbon"}


def test_v2_fit_boxes_legacy_unchanged():
    for size in [(1080, 1080), (1080, 1350), (1080, 1920)]:
        boxes = _v2_fit_boxes(*size)
        assert boxes["surname"] == (0.86, 0.18, 44, 132)
        assert boxes["result"] == (0.52, 0.12, 40, 104)
        assert boxes["mega_result"] == (0.92, 0.34, 72, 300)
        assert boxes["mega_name"] == (0.92, 0.22, 64, 220)


def test_v2_fit_boxes_landscape_uses_more_height_share():
    port = _v2_fit_boxes(1080, 1350)["surname"]
    land = _v2_fit_boxes(1920, 1080)["surname"]
    # landscape claims more of the short (height) edge, less of the wide width
    assert land[1] > port[1], "landscape should use more height share"
    assert land[0] < port[0], "landscape should use less width share"
    # min px climbs so type stays substantial on the bigger canvas
    assert land[2] >= port[2]
    # all four hero slots are defined (4-tuples) for every landscape family
    for w, h in [(1920, 1080), (1620, 1080), (1440, 1080)]:
        boxes = _v2_fit_boxes(w, h)
        assert set(boxes) == {"surname", "result", "mega_result", "mega_name"}
        for frac in boxes.values():
            assert len(frac) == 4


def test_format_composition_css_noop_for_standard_formats():
    # the byte-identical guarantee: standard formats get NO extra CSS appended.
    for size in [(1080, 1080), (1080, 1350), (1080, 1920)]:
        assert _format_composition_css(*size) == ""


def _edge_pad(w: int, h: int) -> int:
    line = next(
        ln for ln in _format_composition_css(w, h).splitlines() if "--mh-edge-pad" in ln
    )
    return int(line.split("--mh-edge-pad:")[1].split("px")[0])


def test_format_composition_css_landscape_retune():
    css = _format_composition_css(1920, 1080)
    assert "G1.3 per-format composition" in css
    assert '--mh-format:"landscape_169"' in css
    assert "--mh-edge-pad" in css
    # 16:9 gets a 4-column stat grid; the narrower ratios get 3
    assert "repeat(4,1fr)" in css
    assert "repeat(3,1fr)" in _format_composition_css(1620, 1080)
    assert "repeat(3,1fr)" in _format_composition_css(1440, 1080)
    # the safe edge inset widens with the ratio, never below the 56px baseline
    assert _edge_pad(1920, 1080) > _edge_pad(1620, 1080) > _edge_pad(1440, 1080) >= 56


def test_landscape_aspects_constant_matches_helpers():
    assert set(_LANDSCAPE_ASPECTS) == {"landscape_169", "landscape_32", "landscape_43"}
    for w, h in [(1920, 1080), (1620, 1080), (1440, 1080)]:
        assert _format_aspect(w, h) in _LANDSCAPE_ASPECTS
        assert _format_composition_css(w, h) != ""


# --------------------------------------------------------------------------
# Real renders — require Playwright/Chromium
# --------------------------------------------------------------------------


def _have_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            browser.close()
            return True
    except Exception:
        return False


_render = pytest.mark.skipif(not _have_playwright(), reason="Playwright/Chromium not available")


def _brand():
    from mediahub.brand.kit import BrandKit

    return BrandKit(
        profile_id="test",
        display_name="Test Swim Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="TSC",
    )


def _brief(layout: str = "big_number_dominant"):
    from mediahub.creative_brief.generator import generate as gen_brief
    from mediahub.media_requirements.evaluator import EvaluationResult

    ev = EvaluationResult(
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
    item = {
        "id": "ci-1",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
        },
    }
    return gen_brief(
        item,
        ev,
        _brand(),
        profile_id="test",
        meet_name="Manchester Open",
        venue_name="Manchester Aquatics Centre",
    )


def _png_size(path) -> tuple[int, int]:
    import struct

    with open(path, "rb") as fh:
        head = fh.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return struct.unpack(">II", head[16:24])


@_render
@pytest.mark.parametrize("fmt", ["landscape", "landscape_3_2", "landscape_4_3"])
def test_render_brief_landscape_dimensions(tmp_path: Path, fmt: str):
    size = FORMAT_SIZES[fmt]
    res = render_brief(
        _brief(), output_dir=tmp_path, size=size, format_name=fmt, brand_kit=_brand()
    )
    assert res.visual.format_name == fmt
    assert (res.visual.width, res.visual.height) == size
    out = Path(res.visual.file_path)
    assert out.exists()
    assert _png_size(out) == size  # the PNG really is at the landscape size
    assert out.stat().st_size > 30_000  # a real render, not a stub
    assert "G1.3 per-format composition" in res.html


@_render
def test_landscape_render_carries_composition_portrait_does_not(tmp_path: Path):
    # Same brief, two formats: the portrait HTML must be free of the G1.3 block
    # (byte-identical guarantee), the landscape HTML must carry it.
    port = render_brief(
        _brief(),
        output_dir=tmp_path / "p",
        size=FORMAT_SIZES["feed_portrait"],
        format_name="feed_portrait",
        brand_kit=_brand(),
    )
    land = render_brief(
        _brief(),
        output_dir=tmp_path / "l",
        size=FORMAT_SIZES["landscape"],
        format_name="landscape",
        brand_kit=_brand(),
    )
    assert "G1.3 per-format composition" not in port.html
    assert "G1.3 per-format composition" in land.html


@_render
def test_render_all_formats_landscape_is_opt_in(tmp_path: Path):
    # landscape is opt-in: absent from the default trio, present when requested.
    default = render_all_formats(_brief(), output_dir=tmp_path / "d", brand_kit=_brand())
    default_fmts = {r.visual.format_name for r in default}
    assert {"feed_square", "feed_portrait", "story"}.issubset(default_fmts)
    assert default_fmts.isdisjoint({"landscape", "landscape_3_2", "landscape_4_3"})

    chosen = render_all_formats(
        _brief(),
        output_dir=tmp_path / "c",
        formats=["landscape", "landscape_3_2", "landscape_4_3"],
        brand_kit=_brand(),
    )
    assert {r.visual.format_name for r in chosen} == {
        "landscape",
        "landscape_3_2",
        "landscape_4_3",
    }
    for r in chosen:
        assert _png_size(r.visual.file_path) == FORMAT_SIZES[r.visual.format_name]
