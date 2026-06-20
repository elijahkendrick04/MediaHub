"""Deterministic, APCA-policed text effects (roadmap 1.9).

Covers the effect engine (deterministic CSS/SVG, the legibility downgrade), the
DesignSpec token (validation + schema + hashable round-trip), the brief field,
and the renderer wiring (the span rides the value; empty effects are a no-op).
"""
from __future__ import annotations

from mediahub.creative_brief import design_spec as ds
from mediahub.graphic_renderer import render as rnd
from mediahub.graphic_renderer import text_effects as fx


_COLOURS = dict(ground="#0A1A3F", ink="#FFFFFF", accent="#F5C518", on_accent="#0A1A3F")


# --------------------------------------------------------------------------- #
# Effect engine
# --------------------------------------------------------------------------- #
class TestEngine:
    def test_vocabulary_matches_design_spec(self):
        # The renderer is the authority; the spec must never offer an effect the
        # renderer cannot run.
        assert fx.TEXT_EFFECTS == ds.TEXT_EFFECTS

    def test_every_active_effect_resolves(self):
        for name in fx.TEXT_EFFECTS:
            res = fx.effect_css(name, **_COLOURS)
            assert isinstance(res, fx.EffectResult)
            assert res.applied in fx.TEXT_EFFECTS

    def test_none_is_noop(self):
        res = fx.effect_css("none", **_COLOURS)
        assert res.is_noop and res.style == "" and not res.svg

    def test_deterministic(self):
        a = fx.effect_css("extrude", **_COLOURS)
        b = fx.effect_css("extrude", **_COLOURS)
        assert a == b and a.style == b.style

    def test_fill_preserving_effects_are_legible(self):
        for name in ("shadow", "lift", "echo", "glitch", "neon", "extrude", "outline"):
            res = fx.effect_css(name, **_COLOURS)
            assert res.style and res.legible and not res.downgraded

    def test_unknown_effect_falls_back_to_none(self):
        assert fx.effect_css("sparkle-unicorn", **_COLOURS).applied == "none"

    def test_neon_glows_in_brand_accent(self):
        assert "var(--mh-accent)" in fx.effect_css("neon", **_COLOURS).style

    def test_warp_is_self_contained_svg_filter(self):
        style = fx.effect_css("warp", **_COLOURS).style
        # data-URI SVG filter referenced by a literal #w fragment (no page defs).
        assert "filter:url('data:image/svg+xml," in style and style.rstrip(";").endswith("#w')")

    def test_background_uses_legible_ink_on_accent(self):
        res = fx.effect_css("background", **_COLOURS)
        assert _COLOURS["on_accent"] in res.style and "var(--mh-accent)" in res.style

    def test_gradient_legible_applies(self):
        res = fx.effect_css("gradient", **_COLOURS)
        assert res.applied == "gradient" and not res.downgraded
        assert "background-clip:text" in res.style

    def test_fill_altering_downgrades_when_illegible(self):
        # ink == ground ⇒ hollow/splice/gradient would be invisible → outline.
        bad = dict(ground="#FFFFFF", ink="#FFFFFF", accent="#FFFFFF", on_accent="#000000")
        for name in ("hollow", "splice", "gradient"):
            res = fx.effect_css(name, **bad)
            assert res.applied == "outline" and res.downgraded and res.legible
            assert res.reason and "APCA" in res.reason

    def test_no_cdn_anywhere(self):
        for name in fx.TEXT_EFFECTS:
            s = fx.effect_css(name, **_COLOURS).style
            assert "googleapis" not in s and "gstatic" not in s


# --------------------------------------------------------------------------- #
# Span wrapping + curve SVG
# --------------------------------------------------------------------------- #
class TestApplication:
    def test_apply_wraps_value(self):
        res = fx.effect_css("shadow", **_COLOURS)
        out = fx.apply_to_value("SMITH", res)
        assert out.startswith('<span class="mh-fx"') and "SMITH" in out

    def test_apply_noop_returns_value_untouched(self):
        res = fx.effect_css("none", **_COLOURS)
        assert fx.apply_to_value("SMITH", res) == "SMITH"

    def test_apply_empty_value_untouched(self):
        res = fx.effect_css("neon", **_COLOURS)
        assert fx.apply_to_value("", res) == ""

    def test_apply_svg_effect_does_not_span_wrap(self):
        res = fx.effect_css("curve", **_COLOURS)
        # curve is handled by the caller (curve_text_svg), not a span.
        assert fx.apply_to_value("GOLD", res) == "GOLD"

    def test_curve_svg_is_valid_and_contains_text(self):
        svg = fx.curve_text_svg("GOLD MEDAL", curvature=0.4)
        assert svg.startswith("<svg") and svg.count("<textPath") == 1
        assert "GOLD MEDAL" in svg and "viewBox" in svg

    def test_curve_svg_deterministic_and_distinct_ids(self):
        assert fx.curve_text_svg("A") == fx.curve_text_svg("A")
        # different text ⇒ different path id (no fragment collision on a page)
        import re

        id_a = re.search(r'id="([^"]+)"', fx.curve_text_svg("ALPHA")).group(1)
        id_b = re.search(r'id="([^"]+)"', fx.curve_text_svg("BETA")).group(1)
        assert id_a != id_b

    def test_curve_svg_escapes_text(self):
        assert "&lt;script&gt;" in fx.curve_text_svg("<script>")


# --------------------------------------------------------------------------- #
# DesignSpec token
# --------------------------------------------------------------------------- #
class TestDesignSpecToken:
    def _spec(self, raw_effects):
        return ds.normalise(
            {"archetype": "a", "text_effects": raw_effects},
            archetypes=["a", "b"],
            token_roles=["primary", "accent"],
        )

    def test_valid_effects_survive(self):
        spec = self._spec({"headline": "neon", "result": "gradient"})
        assert spec.text_effects_map() == {"headline": "neon", "result": "gradient"}

    def test_unknown_slot_and_effect_dropped(self):
        spec = self._spec({"toenail": "neon", "headline": "explode", "result": "shadow"})
        assert spec.text_effects_map() == {"result": "shadow"}

    def test_none_effect_dropped(self):
        spec = self._spec({"headline": "none", "result": "lift"})
        assert spec.text_effects_map() == {"result": "lift"}

    def test_default_is_empty(self):
        spec = ds.normalise({"archetype": "a"}, archetypes=["a"], token_roles=["primary"])
        assert spec.text_effects == () and spec.text_effects_map() == {}

    def test_spec_is_hashable(self):
        spec = self._spec({"headline": "neon"})
        assert isinstance(hash(spec), int)  # tuple field keeps it frozen-hashable

    def test_to_dict_round_trips(self):
        spec = self._spec({"headline": "neon"})
        assert spec.to_dict()["text_effects"] == {"headline": "neon"}

    def test_schema_advertises_effects(self):
        schema = ds.design_spec_json_schema(archetypes=["a"], token_roles=["primary"])
        te = schema["properties"]["text_effects"]
        assert set(te["properties"]) == set(ds.TEXT_EFFECT_SLOTS)
        assert te["properties"]["headline"]["enum"] == list(ds.TEXT_EFFECTS)
        # required like every other spec field (normalise fills the {} default).
        assert "text_effects" in schema["required"]


# --------------------------------------------------------------------------- #
# Brief field + apply_design_spec + renderer wiring
# --------------------------------------------------------------------------- #
class TestBriefAndRenderWiring:
    def test_apply_design_spec_carries_effects(self):
        from mediahub.creative_brief.generator import CreativeBrief, apply_design_spec

        brief = CreativeBrief(
            id="c", content_item_id="ci", profile_id="p", achievement_summary="",
            objective="", primary_hook="", confidence_label="", tone="", layout_template="x",
            inspiration_pattern_id="", image_treatment="", text_hierarchy=[],
            brand_instructions="", sponsor_instructions=None, sourced_asset_ids=[],
            safety_notes=[], why_this_design="", text_layers={}, palette={}, format_priority=[],
        )
        spec = ds.normalise(
            {"archetype": "x", "text_effects": {"headline": "neon"}},
            archetypes=["x"], token_roles=["primary"],
        )
        apply_design_spec(brief, spec)
        assert brief.text_effects == {"headline": "neon"}

    def test_wiring_wraps_slot_value(self):
        repl = {"ATHLETE_SURNAME_DISPLAY": "SMITH", "RESULT_VALUE": "1:42.10"}
        root_vars = {"--mh-primary": "#0A1A3F", "--mh-on-primary": "#FFFFFF", "--mh-accent": "#F5C518"}
        rnd._apply_text_effects_to_repl(repl, {"headline": "neon", "result": "shadow"}, root_vars)
        assert 'class="mh-fx"' in repl["ATHLETE_SURNAME_DISPLAY"] and "SMITH" in repl["ATHLETE_SURNAME_DISPLAY"]
        assert 'class="mh-fx"' in repl["RESULT_VALUE"]

    def test_wiring_curve_swaps_in_svg(self):
        repl = {"ATHLETE_SURNAME_DISPLAY": "SMITH"}
        root_vars = {"--mh-primary": "#0A1A3F", "--mh-on-primary": "#FFFFFF", "--mh-accent": "#F5C518"}
        rnd._apply_text_effects_to_repl(repl, {"headline": "curve"}, root_vars)
        assert "<svg" in repl["ATHLETE_SURNAME_DISPLAY"] and "<textPath" in repl["ATHLETE_SURNAME_DISPLAY"]

    def test_wiring_unknown_slot_is_noop(self):
        repl = {"ATHLETE_SURNAME_DISPLAY": "SMITH"}
        before = dict(repl)
        rnd._apply_text_effects_to_repl(repl, {"nope": "neon"}, {"--mh-primary": "#000"})
        assert repl == before

    def test_wiring_missing_value_skipped(self):
        repl = {"RESULT_VALUE": ""}
        rnd._apply_text_effects_to_repl(repl, {"result": "neon"}, {"--mh-primary": "#000"})
        assert repl["RESULT_VALUE"] == ""
