"""Renderer localisation (1.24 Build 3) — RTL direction, non-Latin self-hosted
fonts, and autofit absorbing translated-text expansion.

The HTML-capture tests stub ``render_html_to_png`` so they assert the composed
CSS/HTML the renderer feeds Chromium WITHOUT needing a browser — fast and
deterministic. The font-asset and autofit tests are pure.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

from mediahub.graphic_renderer import render as R

_LAYOUTS = Path(R.__file__).resolve().parent / "layouts"
_FONTS = _LAYOUTS / "fonts"


# --- RTL direction helper (unit) -------------------------------------------
class TestLocalizedOverridesCss:
    def test_rtl_languages_flip_direction(self):
        assert "direction: rtl" in R._localized_overrides_css("ar")
        assert "direction: rtl" in R._localized_overrides_css("ur")
        assert "direction: rtl" in R._localized_overrides_css("ar-EG")

    def test_ltr_and_empty_inject_nothing(self):
        for code in ("cy", "en", "fr", "ru", "zh", "", None):
            assert R._localized_overrides_css(code) == ""


# --- Non-Latin self-hosted fonts -------------------------------------------
class TestScriptFontsShipped:
    def test_woff2_files_present(self):
        names = {p.name for p in _FONTS.glob("*.woff2")}
        for slug in (
            "noto-sans-cyrillic",
            "noto-sans-arabic",
            "noto-sans-devanagari",
            "noto-sans-bengali",
        ):
            assert f"{slug}.woff2" in names, f"missing script font {slug}.woff2"

    def test_shared_css_wires_them_first_party(self):
        css = (_LAYOUTS / "_shared.css").read_text()
        assert "gstatic" not in css and "googleapis" not in css
        # The four standalone script families are declared.
        for fam in ("Noto Sans Arabic", "Noto Sans Devanagari", "Noto Sans Bengali"):
            assert f"'{fam}'" in css
        # Each script woff2 is referenced and on disk.
        for slug in ("noto-sans-arabic", "noto-sans-devanagari", "noto-sans-bengali"):
            assert f"url(fonts/{slug}.woff2)" in css
            assert (_FONTS / f"{slug}.woff2").is_file()

    def test_files_are_under_the_hygiene_size_gate(self):
        # check-added-large-files caps at 1500 KB; keep the script fonts small.
        for p in _FONTS.glob("noto-sans-*.woff2"):
            assert p.stat().st_size < 1_500_000, f"{p.name} too large for the repo gate"


# --- HTML composition (browser-free capture) -------------------------------
def _capture_render_html(monkeypatch, language: str) -> str:
    """Compose a card's render HTML, stubbing Chromium, for one language."""
    from mediahub.web import design_editor as DE

    params = DE.coerce_params(
        {
            "archetype": "",
            "format": "feed_portrait",
            "full": False,
            "text": dict(DE.DEFAULT_TEXT),
        }
    )
    brief = DE.build_brief_from_params(params)
    kit = DE.brand_kit_for_params(params)
    cap: dict = {}

    def _fake_png(html, output_path, size, **kwargs):
        cap["html"] = html
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    with tempfile.TemporaryDirectory() as d:
        R.render_brief(
            brief,
            output_dir=d,
            size=params.size,
            format_name=params.format_id,
            brand_kit=kit,
            quality=params.render_quality,
            language=language,
        )
    return cap["html"]


class TestRenderHtmlLocalisation:
    def test_arabic_render_injects_rtl_and_self_hosted_noto(self, monkeypatch):
        html = _capture_render_html(monkeypatch, "ar")
        assert "direction: rtl" in html
        # The Noto faces from _shared.css ride in, rewritten to file:// (never CDN).
        assert "noto-sans-arabic.woff2" in html
        assert "gstatic" not in html and "googleapis" not in html

    def test_welsh_render_has_no_rtl(self, monkeypatch):
        html = _capture_render_html(monkeypatch, "cy")
        assert "direction: rtl" not in html

    def test_default_render_unchanged_no_rtl(self, monkeypatch):
        html = _capture_render_html(monkeypatch, "")
        assert "direction: rtl" not in html


# --- Autofit absorbs translated-text expansion (deterministic, no browser) --
class TestAutofitAbsorbsExpansion:
    def test_longer_text_gets_a_smaller_font_but_still_fits(self):
        from mediahub.graphic_renderer.autofit import fit_font_px

        short = fit_font_px("Win", 400, 120, max_px=200)
        long = fit_font_px(
            "Pencampwriaethau Haf Cymru — record personol newydd", 400, 120, max_px=200
        )
        assert short > long, "a longer translation must autofit to a smaller size"
        assert long >= 8, "but it must still resolve to a usable size, not vanish"


# --- Label re-render bridge (mocked provider) ------------------------------
class TestTranslateCardLabels:
    def test_translates_labels_keeps_names_and_results(self):
        from mediahub.localize import translate as T
        from mediahub.web.translate_card import translate_card_labels

        layers = {
            "athlete_full_name": "Hannah Cox",
            "athlete_surname": "COX",
            "event_name": "100m Freestyle",
            "achievement_label": "NEW PB",
            "result_value": "56.24",
        }
        ret = {"event_name": "100m Dull Rhydd", "achievement_label": "RECORD PERSONOL NEWYDD"}
        with (
            mock.patch.object(T, "generate_json", return_value=ret),
            mock.patch.object(T, "active_provider", return_value="gemini-api"),
        ):
            out = translate_card_labels(layers, "cy")
        assert out["event_name"] == "100m Dull Rhydd"
        assert out["achievement_label"] == "RECORD PERSONOL NEWYDD"
        # Names and result digits are preserved verbatim.
        assert out["athlete_full_name"] == "Hannah Cox"
        assert out["athlete_surname"] == "COX"
        assert out["result_value"] == "56.24"

    def test_no_translatable_labels_is_a_no_op(self):
        from mediahub.localize import translate as T
        from mediahub.web.translate_card import translate_card_labels

        gj = mock.MagicMock()
        with mock.patch.object(T, "generate_json", gj):
            out = translate_card_labels({"athlete_full_name": "Hannah Cox"}, "cy")
        gj.assert_not_called()
        assert out == {"athlete_full_name": "Hannah Cox"}
