"""G1.9 — variable-font axis support for the still graphic renderer.

Three layers, each guarding a different way the feature could silently regress:

A. **Shipped fonts** — the three text/data ``layouts/fonts/*.woff2`` really
   carry the variable axes that ``_shared.css`` and ``autofit._FONT_AXES``
   declare (read via Pillow's FreeType backend, a hard dependency, so this runs
   in CI); the three display faces stay static instances.
B. **autofit.optimise_axes** — the deterministic, font-file-free per-slot axis
   optimiser: optical-size tracking, weight clamp + trade-for-fit, and width
   condensation for any width-axis face.
C. **Render wiring** — every v2 result slot binds the axes var, and the renderer
   emits an override ONLY when a slot cannot fit at its requested weight (so a
   slot that already fits renders byte-identically to before).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mediahub.graphic_renderer import autofit as af

_ROOT = Path(__file__).resolve().parents[1]
_LAYOUTS = _ROOT / "src" / "mediahub" / "graphic_renderer" / "layouts"
_FONTS = _LAYOUTS / "fonts"
_SHARED_CSS = _LAYOUTS / "_shared.css"
_V2 = _LAYOUTS / "v2"

# The contract the woff2 files, _shared.css, and autofit._FONT_AXES must agree
# on. Keep in lock-step with all three.
_VARIABLE = {
    "inter": {"wght": (100, 900), "opsz": (14, 32)},
    "space-grotesk": {"wght": (300, 700)},
    "jetbrains-mono": {"wght": (100, 800)},
    # D5 — the serif display register joined as a genuine variable face.
    "playfair-display": {"wght": (400, 900)},
}
_STATIC = ("anton", "bebas-neue", "bowlby-one")

# _shared.css family name + its declared weight range (the @font-face range).
_CSS_FAMILIES = {
    "Inter": (100, 900),
    "Space Grotesk": (300, 700),
    "JetBrains Mono": (100, 800),
    "Playfair Display": (400, 900),
}

# Pillow variation-axis display name -> CSS axis tag.
_AXIS_TAG = {"Weight": "wght", "Optical size": "opsz", "Width": "wdth"}


def _pil_axes(slug: str):
    """``{tag: (min, max)}`` for a shipped woff2 via Pillow, or ``None`` if static."""
    from PIL import ImageFont

    font = ImageFont.truetype(str(_FONTS / f"{slug}.woff2"), 100)
    try:
        raw = font.get_variation_axes()
    except OSError:
        return None
    out: dict[str, tuple[float, float]] = {}
    for axis in raw:
        name = axis.get("name")
        name = name.decode() if isinstance(name, (bytes, bytearray)) else name
        tag = _AXIS_TAG.get(name)
        if tag:
            out[tag] = (axis["minimum"], axis["maximum"])
    return out


# --------------------------------------------------------------------------- #
# A. Shipped fonts carry exactly the declared axes
# --------------------------------------------------------------------------- #
class TestShippedFontsAreVariable:
    @pytest.mark.parametrize("slug", list(_VARIABLE))
    def test_variable_file_present(self, slug):
        assert (_FONTS / f"{slug}.woff2").is_file()

    @pytest.mark.parametrize("slug,expected", list(_VARIABLE.items()))
    def test_woff2_carries_expected_axes(self, slug, expected):
        pytest.importorskip("PIL")
        axes = _pil_axes(slug)
        assert axes is not None, f"{slug}.woff2 is not a variable font"
        for tag, (lo, hi) in expected.items():
            assert tag in axes, f"{slug}.woff2 is missing the {tag!r} axis"
            got_lo, got_hi = axes[tag]
            assert (round(got_lo), round(got_hi)) == (
                lo,
                hi,
            ), f"{slug}.woff2 {tag} range {got_lo}..{got_hi} != declared {lo}..{hi}"

    @pytest.mark.parametrize("slug", _STATIC)
    def test_display_faces_stay_static(self, slug):
        pytest.importorskip("PIL")
        assert _pil_axes(slug) is None, (
            f"{slug}.woff2 is unexpectedly variable — the display faces have no "
            f"variable cut on Google Fonts and must stay static instances"
        )


# --------------------------------------------------------------------------- #
# A'. _shared.css declares matching ranges, and the autofit registry agrees
# --------------------------------------------------------------------------- #
class TestSharedCssDeclaresRanges:
    @pytest.mark.parametrize("family,rng", list(_CSS_FAMILIES.items()))
    def test_single_variable_face_with_range(self, family, rng):
        css = _SHARED_CSS.read_text(encoding="utf-8")
        # Exactly one PRIMARY variable face per family (the per-weight faces are
        # collapsed into the variable woff2). 1.24 adds non-Latin fallback faces
        # under the same family names pointing at a noto-*.woff2 (per-glyph
        # unicode-range fallback so translated text renders) — those are NOT the
        # variable face and are excluded here.
        blocks = re.findall(r"@font-face\s*\{[^}]*\}", css, re.S)
        own = [
            b
            for b in blocks
            if re.search(rf"font-family:\s*'{re.escape(family)}'", b) and "noto-" not in b
        ]
        assert len(own) == 1, f"expected exactly one primary {family} face, got {len(own)}"
        lo, hi = rng
        assert re.search(rf"font-weight:\s*{lo} {hi}\b", own[0]), (
            f"{family} not declared as a font-weight: {lo} {hi} range face"
        )

    def test_optical_sizing_enabled(self):
        assert "font-optical-sizing: auto" in _SHARED_CSS.read_text(encoding="utf-8")

    def test_no_cdn_creep(self):
        css = _SHARED_CSS.read_text(encoding="utf-8")
        assert "gstatic" not in css and "googleapis" not in css


class TestRegistryMatchesCss:
    @pytest.mark.parametrize("family,rng", list(_CSS_FAMILIES.items()))
    def test_registry_weight_matches_css(self, family, rng):
        axes = af.font_axes_for(family)
        assert axes is not None and axes.wght == rng

    def test_registry_opsz_only_on_inter(self):
        assert af.font_axes_for("Inter").opsz == (14.0, 32.0)
        assert af.font_axes_for("Space Grotesk").opsz is None
        assert af.font_axes_for("JetBrains Mono").opsz is None

    def test_static_faces_absent_from_registry(self):
        for family in ("Anton", "Bebas Neue", "Bowlby One"):
            assert af.font_axes_for(family) is None

    def test_no_self_hosted_face_claims_a_width_axis(self):
        # Honest: no shipped family exposes wdth today, so the width capability
        # is tested via a synthetic face below, never faked on a real one.
        for family in _CSS_FAMILIES:
            assert af.font_axes_for(family).wdth is None


# --------------------------------------------------------------------------- #
# B. optimise_axes — the deterministic per-slot optimiser
# --------------------------------------------------------------------------- #
class TestOptimiseAxes:
    def test_static_or_unknown_family_returns_empty_plan(self):
        for family in ("Anton", "Bebas Neue", "Bowlby One", "Comic Sans"):
            plan = af.optimise_axes("HUGHES", 800, font_family=family, weight=400, fitted_px=120)
            assert plan == af.AxisPlan()
            assert plan.css == ""

    def test_opsz_tracks_fitted_px_and_clamps_to_range(self):
        big = af.optimise_axes("X", 9999, font_family="Inter", weight=400, fitted_px=300)
        small = af.optimise_axes("X", 9999, font_family="Inter", weight=400, fitted_px=8)
        mid = af.optimise_axes("X", 9999, font_family="Inter", weight=400, fitted_px=22)
        assert (big.opsz, small.opsz, mid.opsz) == (32, 14, 22)

    def test_no_opsz_axis_means_no_opsz(self):
        plan = af.optimise_axes("1:58", 600, font_family="JetBrains Mono", weight=700, fitted_px=90)
        assert plan.opsz is None

    def test_weight_clamped_to_face_range(self):
        # Space Grotesk caps at 700; JetBrains Mono floors at 100.
        assert (
            af.optimise_axes("X", 9999, font_family="Space Grotesk", weight=900, fitted_px=40).wght
            == 700
        )
        assert (
            af.optimise_axes(
                "X", 9999, font_family="JetBrains Mono", weight="thin", fitted_px=40
            ).wght
            == 100
        )

    def test_fitting_slot_emits_no_css(self):
        plan = af.optimise_axes(
            "1:58.2", 600, font_family="JetBrains Mono", weight=700, fitted_px=90
        )
        assert plan.css == "" and plan.wght == 700

    def test_overflowing_slot_trades_weight_down(self):
        plan = af.optimise_axes(
            "1:45.23 / 50.12 SC", 200, font_family="JetBrains Mono", weight=700, fitted_px=90
        )
        assert plan.css.startswith("'wght' ")
        assert plan.wght is not None and plan.wght < 700

    def test_weight_trade_never_below_floor(self):
        plan = af.optimise_axes(
            "X" * 80, 50, font_family="JetBrains Mono", weight=700, fitted_px=120
        )
        assert plan.wght >= af._WEIGHT_FIT_FLOOR

    def test_width_axis_condenses_when_the_face_has_one(self):
        # No shipped face exposes wdth, so register a synthetic width-capable
        # face to exercise the (real, ready) width-recovery path; restore after.
        af._FONT_AXES["__wtest__"] = af.FontAxes(wght=(100, 900), wdth=(70.0, 100.0))
        try:
            plan = af.optimise_axes(
                "WIDELOAD NAME HERE", 150, font_family="__wtest__", weight=400, fitted_px=80
            )
            assert plan.wdth is not None and 70.0 <= plan.wdth <= 100.0
            assert "'wdth'" in plan.css
        finally:
            del af._FONT_AXES["__wtest__"]

    def test_empty_text_no_deviation_but_reports_opsz(self):
        plan = af.optimise_axes("", 100, font_family="Inter", weight=400, fitted_px=40)
        assert plan.css == "" and plan.opsz == 32

    def test_deterministic(self):
        kw = dict(font_family="JetBrains Mono", weight=700, fitted_px=90)
        a = af.optimise_axes("1:45.23 / 50.12 SC", 200, **kw)
        b = af.optimise_axes("1:45.23 / 50.12 SC", 200, **kw)
        assert a == b

    def test_font_axes_for_normalises_stacks(self):
        assert af.font_axes_for("Inter, system-ui, sans-serif").opsz == (14.0, 32.0)
        assert af.font_axes_for("'JetBrains Mono', monospace").wght == (100, 800)
        assert af.font_axes_for("Anton") is None


class TestAxisCss:
    def test_canonical_order(self):
        assert af.axis_css(wght=612.0, wdth=85.0, opsz=30.0) == "'wght' 612, 'wdth' 85, 'opsz' 30"

    def test_fractional_to_one_dp(self):
        assert af.axis_css(wdth=87.5) == "'wdth' 87.5"

    def test_integers_drop_decimal(self):
        assert af.axis_css(wght=400.0) == "'wght' 400"

    def test_empty(self):
        assert af.axis_css() == ""


# --------------------------------------------------------------------------- #
# C. Render wiring — the v2 result slots consume the optimiser output
# --------------------------------------------------------------------------- #
class TestV2LayoutsConsumeAxesVar:
    def test_every_result_slot_is_wired(self):
        for html in sorted(_V2.glob("*.html")):
            text = html.read_text(encoding="utf-8")
            if "--mh-fit-result-px" in text or "--mh-fit-mega-result-px" in text:
                assert "font-variation-settings: var(--mh-axes" in text, (
                    f"{html.name}: result slot is not wired to an axes var"
                )

    def test_mega_archetypes_use_the_mega_var(self):
        for name in ("big_number_dominant", "cornerstone_numeral"):
            text = (_V2 / f"{name}.html").read_text(encoding="utf-8")
            assert "var(--mh-axes-mega-result, normal)" in text

    def test_wiring_defaults_to_normal(self):
        # the fallback keeps a non-deviating slot byte-identical to before
        for html in _V2.glob("*.html"):
            text = html.read_text(encoding="utf-8")
            for m in re.findall(
                r"font-variation-settings: var\((--mh-axes-[a-z-]+)(, normal)?\)", text
            ):
                assert m[1] == ", normal", f"{html.name}: axes var must default to normal"


class _FakeBrand:
    primary_colour = "#0A2540"
    secondary_colour = "#101820"
    accent_colour = "#FFD24A"


def _v2_fake_brief(result_value: str):
    class _B:
        palette = {"primary": "#0A2540", "secondary": "#101820", "accent": "#FFD24A"}
        text_layers = {
            "athlete_surname": "Hughes",
            "result_value": result_value,
            "event_name": "200m Freestyle",
            "achievement_label": "NEW PB",
        }

    return _B()


class TestRenderEmitsAxesVar:
    def _base_css_for(self, result_value: str) -> str:
        from mediahub.graphic_renderer.render import _fill_v2_archetype

        repl = _fill_v2_archetype(
            _v2_fake_brief(result_value), 1080, 1350, {"BASE_CSS": ""}, brand_kit=_FakeBrand()
        )
        return repl["BASE_CSS"]

    def test_short_result_emits_no_axes_var(self):
        css = self._base_css_for("1:58")
        assert "--mh-axes-result" not in css
        assert "--mh-axes-mega-result" not in css

    def test_long_result_emits_weight_traded_axis(self):
        css = self._base_css_for("1:45.23 / 50.12 / 24.55 / 11.98 SC RELAY")
        assert "--mh-axes-result" in css or "--mh-axes-mega-result" in css
        assert "'wght'" in css
