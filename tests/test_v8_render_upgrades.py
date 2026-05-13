"""V8.1 Issue 7 §1-3 — render upgrade tests.

Verifies that the three render-stack upgrades are wired into the renderer:

1. Premium @font-face declarations make it into the page <style>.
2. DPR feature flag is honoured (different DPR -> different PNG bytes).
3. Grain overlay on/off changes the PNG (measurable diff).

The actual Playwright render is wrapped in a skip guard so this file
runs in any environment.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mediahub.graphic_renderer import render as render_mod
from mediahub.graphic_renderer.render import (
    _GRAIN_SVG_BLOCK,
    _common_replacements,
    _dpr_render,
    _grain_enabled,
    _premium_fonts_enabled,
)


# ---------------------------------------------------------------------------
# Feature-flag plumbing (no Playwright needed)
# ---------------------------------------------------------------------------

def test_premium_fonts_flag_default_on(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_RENDER_PREMIUM_FONTS", raising=False)
    assert _premium_fonts_enabled() is True


def test_premium_fonts_flag_off(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_PREMIUM_FONTS", "0")
    assert _premium_fonts_enabled() is False


def test_grain_flag_default_on(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_RENDER_GRAIN", raising=False)
    assert _grain_enabled() is True


def test_grain_flag_off(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_GRAIN", "off")
    assert _grain_enabled() is False


def test_dpr_default_is_2(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_RENDER_DPR", raising=False)
    assert _dpr_render() == 2


def test_dpr_clamped_to_4(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_DPR", "9")
    assert _dpr_render() == 4


def test_dpr_clamped_min_1(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_DPR", "0")
    assert _dpr_render() == 1


def test_dpr_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_DPR", "abc")
    assert _dpr_render() == 2


# ---------------------------------------------------------------------------
# _shared.css is on disk and contains the premium @font-face declarations
# ---------------------------------------------------------------------------

def test_shared_css_exists_and_declares_premium_fonts():
    p = Path(__file__).resolve().parent.parent / "src" / "mediahub" / "graphic_renderer" / "layouts" / "_shared.css"
    assert p.exists(), "V8.1 §1: _shared.css must exist"
    css = p.read_text("utf-8")
    # @font-face declarations
    assert "@font-face" in css
    # Premium families called out by the spec
    for family in ("Bebas Neue", "Anton", "Bowlby One", "Inter", "Space Grotesk"):
        assert family in css, f"missing @font-face for {family}"
    # WOFF2 sources from gstatic (so renders are deterministic)
    assert "fonts.gstatic.com" in css
    assert ".woff2" in css


def test_grain_svg_block_uses_turbulence_filter():
    # The overlay relies on feTurbulence + feColorMatrix to produce noise.
    assert "feTurbulence" in _GRAIN_SVG_BLOCK
    assert "feColorMatrix" in _GRAIN_SVG_BLOCK
    assert 'id="grain"' in _GRAIN_SVG_BLOCK


# ---------------------------------------------------------------------------
# _common_replacements injects shared CSS when the flag is on
# ---------------------------------------------------------------------------

class _FakeBrief:
    """Minimal stand-in so we can drive _common_replacements without a real brief."""
    def __init__(self):
        self.palette = {"primary": "#0E5BFF", "secondary": "#101820", "accent": "#FFFFFF"}
        self.text_layers = {
            "athlete_full_name": "Eira Hughes",
            "athlete_first_name": "Eira",
            "athlete_surname": "Hughes",
            "achievement_label": "NEW PB",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
            "meet_name": "Manchester Open",
        }
        self.confidence_label = "NEW PB"
        self.club_short = "TSC"
        self.club_full = "Test Swim Club"


class _FakeBrand:
    profile_id = "test"
    display_name = "Test Swim Club"
    short_name = "TSC"
    primary_colour = "#0E5BFF"
    secondary_colour = "#101820"
    accent_colour = "#FFFFFF"


def test_common_replacements_inlines_shared_css_when_flag_on(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_PREMIUM_FONTS", "1")
    repl = _common_replacements(
        _FakeBrief(), 1080, 1350, _FakeBrand(),
        athlete_data_uri=None, logo_block="", result_chip="", sponsor_block="",
    )
    assert "BASE_CSS" in repl
    css = repl["BASE_CSS"]
    # The shared.css content is concatenated in
    assert "@font-face" in css
    assert "Bebas Neue" in css
    # Belt-and-braces @import is still present as a fallback
    assert "fonts.googleapis.com/css2" in css


def test_common_replacements_omits_shared_css_when_flag_off(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_PREMIUM_FONTS", "0")
    repl = _common_replacements(
        _FakeBrief(), 1080, 1350, _FakeBrand(),
        athlete_data_uri=None, logo_block="", result_chip="", sponsor_block="",
    )
    css = repl["BASE_CSS"]
    # @import line still there, but no @font-face block from _shared.css
    assert "fonts.googleapis.com/css2" in css
    assert "@font-face" not in css


# ---------------------------------------------------------------------------
# Real render: end-to-end PNG diff for grain on/off and DPR=1 vs DPR=2
# ---------------------------------------------------------------------------

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


_PLAYWRIGHT = _have_playwright()


def _render_brief_for_test():
    from mediahub.brand.kit import BrandKit
    from mediahub.creative_brief.generator import generate as gen_brief
    from mediahub.media_requirements.evaluator import EvaluationResult

    bk = BrandKit(
        profile_id="test",
        display_name="Test Swim Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="TSC",
    )
    ev = EvaluationResult(
        content_item_id="ci-1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout="individual_hero",
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
    return gen_brief(item, ev, bk, profile_id="test", meet_name="Manchester Open"), bk


@pytest.mark.skipif(not _PLAYWRIGHT, reason="Playwright/Chromium not available")
def test_grain_on_vs_off_changes_png_bytes(tmp_path, monkeypatch):
    from mediahub.graphic_renderer.render import render_brief
    brief, bk = _render_brief_for_test()

    monkeypatch.setenv("MEDIAHUB_RENDER_GRAIN", "1")
    on = render_brief(brief, output_dir=tmp_path / "on", size=(1080, 1350),
                      format_name="feed_portrait", brand_kit=bk)

    monkeypatch.setenv("MEDIAHUB_RENDER_GRAIN", "0")
    off = render_brief(brief, output_dir=tmp_path / "off", size=(1080, 1350),
                      format_name="feed_portrait", brand_kit=bk)

    # HTML differs (grain class swapped out)
    assert on.html != off.html
    # Grain HTML carries the marker; off HTML does not.
    assert "texture-grain" in on.html
    assert 'class="texture-grain"' not in off.html
    # PNG bytes differ
    h_on = hashlib.sha256(Path(on.visual.file_path).read_bytes()).hexdigest()
    h_off = hashlib.sha256(Path(off.visual.file_path).read_bytes()).hexdigest()
    assert h_on != h_off, "grain on/off must produce different PNGs"


@pytest.mark.skipif(not _PLAYWRIGHT, reason="Playwright/Chromium not available")
def test_dpr_2_vs_dpr_1_changes_png_bytes(tmp_path, monkeypatch):
    from mediahub.graphic_renderer.render import render_brief
    brief, bk = _render_brief_for_test()

    monkeypatch.setenv("MEDIAHUB_RENDER_DPR", "1")
    monkeypatch.setenv("MEDIAHUB_RENDER_GRAIN", "0")  # take grain out of the equation
    r1 = render_brief(brief, output_dir=tmp_path / "d1", size=(1080, 1350),
                      format_name="feed_portrait", brand_kit=bk)

    monkeypatch.setenv("MEDIAHUB_RENDER_DPR", "2")
    r2 = render_brief(brief, output_dir=tmp_path / "d2", size=(1080, 1350),
                      format_name="feed_portrait", brand_kit=bk)

    # Final size must still be exactly 1080x1350 (resampled by PIL)
    from PIL import Image
    assert Image.open(r1.visual.file_path).size == (1080, 1350)
    assert Image.open(r2.visual.file_path).size == (1080, 1350)

    h1 = hashlib.sha256(Path(r1.visual.file_path).read_bytes()).hexdigest()
    h2 = hashlib.sha256(Path(r2.visual.file_path).read_bytes()).hexdigest()
    assert h1 != h2, "DPR=1 and DPR=2 must yield different PNG bytes (anti-shortcut)"


@pytest.mark.skipif(not _PLAYWRIGHT, reason="Playwright/Chromium not available")
def test_premium_fonts_appear_in_rendered_html(tmp_path, monkeypatch):
    from mediahub.graphic_renderer.render import render_brief
    brief, bk = _render_brief_for_test()

    monkeypatch.setenv("MEDIAHUB_RENDER_PREMIUM_FONTS", "1")
    res = render_brief(brief, output_dir=tmp_path, size=(1080, 1350),
                       format_name="feed_portrait", brand_kit=bk)

    # _shared.css declarations must be inlined into the page <style>
    assert "@font-face" in res.html
    assert "Bebas Neue" in res.html
    assert "fonts.gstatic.com" in res.html
