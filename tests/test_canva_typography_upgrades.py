"""Canva gap analysis — typography track (D6, D7-curve, D8, D9).

Pure-function / source-contract tests for the four typography upgrades:

* **D6** — the fact-gated ``emphasis_word`` DesignSpec field + per-word emphasis
  treatments (accent ink / accent pill / heavier weight), APCA-gated with a
  downgrade, HTML-escaped, first-whole-word-match only, mono-safe.
* **D7-curve** — ``curve_text_svg`` keeps the shallow quadratic for
  ``|curvature| <= 0.4`` (byte-identical) and switches to a true SVG arc
  (A-command) above it, with tight-curve letter-spacing compensation.
* **D8** — a density/mood-coherent weight register (``--mh-wght-kicker/meta/data``)
  emitted only when spent (byte-identical default), consumed by a handful of
  layouts and mirrored into the Remotion props.
* **D9** — self-hosted Noto Bold/Black display cuts aliased under the display
  families + per-script advance-width scales in autofit.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from mediahub.creative_brief import design_spec as ds
from mediahub.graphic_renderer import autofit
from mediahub.graphic_renderer import render as rnd
from mediahub.graphic_renderer import text_effects as fx

_LAYOUTS = Path(rnd.LAYOUTS_DIR)
_SHARED = _LAYOUTS / "_shared.css"
_FONTS = _LAYOUTS / "fonts"

_COLOURS = dict(ground="#0A1A3F", accent="#F5C518", on_accent="#16140E")


# --------------------------------------------------------------------------- #
# D6 — per-word emphasis
# --------------------------------------------------------------------------- #
class TestD6EmphasisVocabulary:
    def test_vocab_matches_design_spec(self):
        # The renderer is the authority; the spec must never offer a treatment
        # the renderer cannot execute (mirror of the TEXT_EFFECTS drift guard).
        assert fx.EMPHASIS_STYLES == ds.EMPHASIS_STYLES
        assert ds.DEFAULT_EMPHASIS_STYLE in ds.EMPHASIS_STYLES

    def test_normalise_cleans_word_to_single_bounded_token(self):
        spec = ds.normalise(
            {"archetype": "a", "emphasis_word": "  GOLD medal here "},
            archetypes=["a"],
            token_roles=["primary"],
        )
        assert spec.emphasis_word == "GOLD"  # first token only

    def test_normalise_bounds_word_length(self):
        spec = ds.normalise(
            {"archetype": "a", "emphasis_word": "X" * 200},
            archetypes=["a"],
            token_roles=["primary"],
        )
        assert len(spec.emphasis_word) == ds.MAX_EMPHASIS_WORD_LEN

    def test_normalise_style_coerced_and_defaults(self):
        spec = ds.normalise(
            {"archetype": "a", "emphasis_style": "sparkle"},
            archetypes=["a"],
            token_roles=["primary"],
        )
        assert spec.emphasis_style == ds.DEFAULT_EMPHASIS_STYLE

    def test_default_is_empty_and_byte_identical(self):
        spec = ds.normalise({"archetype": "a"}, archetypes=["a"], token_roles=["primary"])
        assert spec.emphasis_word == "" and spec.emphasis_style == ds.DEFAULT_EMPHASIS_STYLE

    def test_schema_advertises_emphasis(self):
        schema = ds.design_spec_json_schema(archetypes=["a"], token_roles=["primary"])
        assert "emphasis_word" in schema["properties"]
        assert schema["properties"]["emphasis_style"]["enum"] == list(ds.EMPHASIS_STYLES)
        assert "emphasis_word" in schema["required"]

    def test_spec_stays_hashable(self):
        spec = ds.normalise(
            {"archetype": "a", "emphasis_word": "GOLD"}, archetypes=["a"], token_roles=["primary"]
        )
        assert isinstance(hash(spec), int)


class TestD6EmphasisEngine:
    def test_accent_ink_applies_when_legible(self):
        res = fx.emphasis_css("accent_ink", **_COLOURS)
        assert res.applied == "accent_ink" and res.style == "color:var(--mh-accent);"
        assert not res.downgraded

    def test_accent_ink_downgrades_to_plain_when_illegible(self):
        res = fx.emphasis_css("accent_ink", ground="#F5C518", accent="#F6C61A", on_accent="#000")
        assert res.applied == "plain" and res.style == "" and res.downgraded
        assert "APCA" in res.reason

    def test_accent_pill_uses_role_var_and_legible_ink(self):
        res = fx.emphasis_css("accent_pill", **_COLOURS)
        assert "background:var(--mh-accent)" in res.style and _COLOURS["on_accent"] in res.style
        assert res.applied == "accent_pill"

    def test_heavy_sets_variable_weight_only(self):
        res = fx.emphasis_css("heavy", **_COLOURS)
        assert "'wght' 800" in res.style and res.legible

    def test_unknown_style_falls_back_to_default(self):
        res = fx.emphasis_css("rainbow", **_COLOURS)
        assert res.applied in ("accent_ink", "plain")

    def test_accent_ink_is_mono_safe(self):
        # No raw brand hex — the accent rides var(--mh-accent), which mono_mode
        # rewrites, so an accent-ink emphasis never leaks a brand colour in mono.
        res = fx.emphasis_css("accent_ink", **_COLOURS)
        assert "#" not in res.style


class TestD6EmphasiseValue:
    def _res(self):
        return fx.emphasis_css("accent_ink", **_COLOURS)

    def test_wraps_first_whole_word_only(self):
        out = fx.emphasise_value("SMITH GOLD GOLD", "gold", self._res())
        assert out.count("mh-em") == 1 and '<span class="mh-em"' in out

    def test_no_match_is_byte_identical(self):
        val = "SMITH HUGHES"
        assert fx.emphasise_value(val, "BRONZE", self._res()) == val

    def test_whole_word_boundary(self):
        # "PB" must not match inside "PBEST".
        val = "PBEST RUN"
        assert fx.emphasise_value(val, "PB", self._res()) == val

    def test_escapes_markup_no_injection(self):
        val = fx._esc("A <b>X</b> B")  # already-escaped slot value
        out = fx.emphasise_value(val, "<b>", self._res())
        assert "<b>" not in out  # the word is escaped before matching

    def test_does_not_match_inside_a_tag(self):
        # A value already carrying a <br> — the word "br" must never wrap the tag.
        val = "line<br>two"
        out = fx.emphasise_value(val, "br", self._res())
        assert "<br>" in out and 'class="mh-em"' not in out

    def test_downgraded_result_leaves_value_untouched(self):
        plain = fx.emphasis_css("accent_ink", ground="#FFF", accent="#FFF", on_accent="#000")
        val = "SMITH GOLD"
        assert fx.emphasise_value(val, "GOLD", plain) == val


class TestD6RenderWiring:
    def _root(self):
        return {"--mh-primary": "#0A1A3F", "--mh-on-primary": "#FFFFFF", "--mh-accent": "#F5C518"}

    def test_emphasis_applies_to_first_matching_slot(self):
        repl = {
            "ATHLETE_SURNAME_DISPLAY": "HUGHES",
            "ACHIEVEMENT_LABEL": "NEW PB",
            "EVENT_NAME": "200m Freestyle",
        }
        rnd._apply_text_effects_to_repl(
            repl, {}, self._root(), emphasis_word="200m", emphasis_style="accent_pill"
        )
        assert "mh-em" in repl["EVENT_NAME"]
        assert "mh-em" not in repl["ATHLETE_SURNAME_DISPLAY"]

    def test_no_emphasis_word_is_noop(self):
        repl = {"ATHLETE_SURNAME_DISPLAY": "HUGHES"}
        before = dict(repl)
        rnd._apply_text_effects_to_repl(repl, {}, self._root(), emphasis_word="", emphasis_style="")
        assert repl == before

    def test_curve_slot_is_skipped_no_span_leak_in_svg(self):
        # curve replaces the slot with an SVG that lays RAW text; the emphasis
        # span must not be injected there (it would render literally).
        repl = {"ACHIEVEMENT_LABEL": "GOLD"}
        rnd._apply_text_effects_to_repl(
            repl,
            {"kicker": "curve"},
            self._root(),
            emphasis_word="GOLD",
            emphasis_style="accent_ink",
        )
        assert "<svg" in repl["ACHIEVEMENT_LABEL"] and "mh-em" not in repl["ACHIEVEMENT_LABEL"]

    def test_apply_design_spec_carries_emphasis(self):
        from mediahub.creative_brief.generator import CreativeBrief, apply_design_spec

        brief = CreativeBrief(
            id="c",
            content_item_id="ci",
            profile_id="p",
            achievement_summary="",
            objective="",
            primary_hook="",
            confidence_label="",
            tone="",
            layout_template="x",
            inspiration_pattern_id="",
            image_treatment="",
            text_hierarchy=[],
            brand_instructions="",
            sponsor_instructions=None,
            sourced_asset_ids=[],
            safety_notes=[],
            why_this_design="",
            text_layers={},
            palette={},
            format_priority=[],
        )
        spec = ds.normalise(
            {"archetype": "x", "emphasis_word": "GOLD", "emphasis_style": "accent_pill"},
            archetypes=["x"],
            token_roles=["primary"],
        )
        apply_design_spec(brief, spec)
        assert brief.emphasis_word == "GOLD" and brief.emphasis_style == "accent_pill"


# --------------------------------------------------------------------------- #
# D7-curve — quadratic below 0.4, true arc above
# --------------------------------------------------------------------------- #
class TestD7Curve:
    def test_quadratic_byte_identical_at_and_below_threshold(self):
        for c in (0.0, 0.2, 0.35, 0.4, -0.4):
            svg = fx.curve_text_svg("GOLD MEDAL", curvature=c)
            assert 'viewBox="0 0 1000 360"' in svg  # the historic quadratic frame
            assert " A " not in svg  # no arc command

    def test_arc_above_threshold_uses_a_command(self):
        for c in (0.5, 0.75, 1.0, -0.75):
            svg = fx.curve_text_svg("WESTON SC", curvature=c)
            d = re.search(r'<path[^>]*\sd="([^"]+)"', svg).group(1)
            assert " A " in d  # a true SVG arc
            assert svg.count("<textPath") == 1 and "WESTON SC" in svg

    def test_arc_letterspacing_grows_with_curvature(self):
        def ls(c):
            m = re.search(r'letter-spacing="([0-9.]+)em"', fx.curve_text_svg("CLUB", curvature=c))
            return float(m.group(1))

        assert ls(0.5) < ls(1.0)  # tighter curve → more splay compensation
        assert 0.02 <= ls(0.5) <= 0.05 and 0.02 <= ls(1.0) <= 0.05

    def test_arc_deterministic_and_distinct_ids(self):
        assert fx.curve_text_svg("A", curvature=0.9) == fx.curve_text_svg("A", curvature=0.9)
        id_a = re.search(r'id="([^"]+)"', fx.curve_text_svg("ALPHA", curvature=0.9)).group(1)
        id_b = re.search(r'id="([^"]+)"', fx.curve_text_svg("BETA", curvature=0.9)).group(1)
        assert id_a != id_b

    def test_arc_escapes_text(self):
        assert "&lt;script&gt;" in fx.curve_text_svg("<script>", curvature=0.9)

    def test_full_wrap_never_degenerates(self):
        # At |c| == 1 the arc is clamped short of a full turn (non-zero A path).
        svg = fx.curve_text_svg("CLUB", curvature=1.0)
        d = re.search(r'<path[^>]*\sd="([^"]+)"', svg).group(1)
        # start and end points must differ (a real arc, not a zero-length A).
        pts = re.findall(r"-?\d+\.\d+", d)
        assert pts[0:2] != pts[-2:]


# --------------------------------------------------------------------------- #
# D8 — density/mood-coherent weight register
# --------------------------------------------------------------------------- #
class TestD8WeightRegister:
    def test_default_case_returns_none(self):
        assert autofit.weight_register_for("standard", "neutral") is None
        assert autofit.weight_register_for("", "") is None
        assert autofit.weight_register_for("standard", "") is None

    def test_bold_density_spends_the_register(self):
        r = autofit.weight_register_for("bold", "neutral")
        assert r == {"kicker": 680, "meta": 760, "data": 760}

    def test_non_neutral_mood_spends_it_on_standard(self):
        loud = autofit.weight_register_for("standard", "explosive")
        quiet = autofit.weight_register_for("standard", "calm")
        assert loud["meta"] > 620 and quiet["meta"] < 620

    def test_clamped_to_face_axis_ranges(self):
        for density in ("standard", "bold"):
            for mood in ds.MOODS:
                r = autofit.weight_register_for(density, mood)
                if r is None:
                    continue
                assert 300 <= r["kicker"] <= 700  # Space Grotesk axis
                assert 100 <= r["meta"] <= 900  # Inter axis
                assert 100 <= r["data"] <= 800  # JetBrains Mono axis

    def test_kicker_clamps_at_space_grotesk_max(self):
        assert autofit.weight_register_for("bold", "triumphant")["kicker"] == 700


class TestD8RenderEmission:
    def _capture_html(self, monkeypatch, *, pack, mood):
        import mediahub.web.design_editor as DE

        monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
        params = DE.coerce_params(
            {
                "archetype": "big_number_dominant",
                "format": "feed_portrait",
                "full": True,
                "text": dict(DE.DEFAULT_TEXT),
            }
        )
        brief = DE.build_brief_from_params(params)
        brief.style_pack = pack
        brief.mood = mood
        kit = DE.brand_kit_for_params(params)
        cap: dict = {}

        def fake(html, output_path, size, **kw):
            cap["html"] = html
            Path(output_path).write_bytes(b"x")
            return 8

        monkeypatch.setattr(rnd, "render_html_to_png", fake)
        with tempfile.TemporaryDirectory() as d:
            rnd.render_brief(
                brief, output_dir=d, size=params.size, format_name=params.format_id, brand_kit=kit
            )
        return cap["html"]

    def test_standard_neutral_emits_no_weight_var(self, monkeypatch):
        # The :root DEFINITION (`--mh-wght-kicker:<n>`) must be absent, so the
        # migrated layouts fall back to their historic weight (byte-identical).
        # The `var(--mh-wght-kicker, 700)` USAGE in the layout CSS always exists.
        html = self._capture_html(monkeypatch, pack="bokeh-none-none-standard", mood="neutral")
        assert "--mh-wght-kicker:" not in html

    def test_bold_emits_weight_vars(self, monkeypatch):
        html = self._capture_html(monkeypatch, pack="bokeh-none-none-bold", mood="explosive")
        assert "--mh-wght-kicker:" in html and "--mh-wght-meta:" in html


class TestD8LayoutAndMotionParity:
    _MIGRATED = (
        "big_number_dominant",
        "vertical_stat_tower",
        "three_card_editorial_grid",
        "ticker_strip",
    )

    def test_layouts_consume_the_weight_vars(self):
        seen = set()
        for name in self._MIGRATED:
            css = (_LAYOUTS / "v2" / f"{name}.html").read_text()
            for reg in ("kicker", "meta", "data"):
                if f"var(--mh-wght-{reg}" in css:
                    seen.add(reg)
        assert seen == {"kicker", "meta", "data"}, seen

    def test_motion_py_forwards_the_register(self):
        src = Path(rnd.__file__).parent.parent.joinpath("visual", "motion.py").read_text()
        assert "weight_register_for" in src
        assert "wghtKicker" in src and "wghtMeta" in src and "wghtData" in src

    def test_storycard_consumes_the_register(self):
        from mediahub.visual import motion

        story = (motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx").read_text()
        kit = (motion.REMOTION_DIR / "src" / "compositions" / "sprint" / "sceneKit.tsx").read_text()
        assert "wghtKicker" in story and "wghtMeta" in story
        assert "wghtData" in (story + kit)

    def test_props_mirror_only_when_spent(self):
        from mediahub.brand.kit import BrandKit
        from mediahub.visual import motion

        brand = BrandKit(
            profile_id="p",
            display_name="P SC",
            primary_colour="#0E2A47",
            secondary_colour="#C9A227",
            accent_colour="#FFFFFF",
            short_name="PSC",
        )
        card = {
            "id": "s1",
            "swim_id": "s1",
            "meet_name": "Open",
            "achievement": {
                "swim_id": "s1",
                "swimmer_name": "Eira Hughes",
                "event_name": "100m Free",
                "result_time": "1:01.00",
            },
        }

        def bd(pack, mood):
            return {
                "style_pack": pack,
                "mood": mood,
                "layout_template": "big_number_dominant",
                "text_layers": {},
            }

        std = motion._card_to_props(
            card, brief=bd("bokeh-none-none-standard", "neutral"), brand_kit=brand
        )
        bold = motion._card_to_props(
            card, brief=bd("bokeh-none-none-bold", "explosive"), brand_kit=brand
        )
        assert "wghtKicker" not in std
        assert bold["wghtKicker"] == 700 and bold["wghtMeta"] == 820

    def test_varfont_animation_does_not_change_the_static_targets(self):
        # varfont-animation animates the register weight in the compositions
        # (a bloom UP to these targets), but must NOT alter the values motion.py
        # emits — the terminal/held weight the still ships is unchanged, so
        # still↔motion parity holds and no register regressed.
        from mediahub.brand.kit import BrandKit
        from mediahub.visual import motion

        brand = BrandKit(
            profile_id="p",
            display_name="P SC",
            primary_colour="#0E2A47",
            secondary_colour="#C9A227",
            accent_colour="#FFFFFF",
            short_name="PSC",
        )
        card = {
            "id": "s1",
            "swim_id": "s1",
            "meet_name": "Open",
            "achievement": {
                "swim_id": "s1",
                "swimmer_name": "Eira Hughes",
                "event_name": "100m Free",
                "result_time": "1:01.00",
            },
        }
        bold = motion._card_to_props(
            card,
            brief={
                "style_pack": "bokeh-none-none-bold",
                "mood": "explosive",
                "layout_template": "big_number_dominant",
                "text_layers": {},
            },
            brand_kit=brand,
        )
        # The emitted register targets are the deterministic engine's, not the
        # bloom's — and no animation-only field ("wghtBloom") leaks into props.
        assert bold["wghtKicker"] == 700 and bold["wghtMeta"] == 820
        assert bold["wghtData"] == 790
        assert "wghtBloom" not in bold


# --------------------------------------------------------------------------- #
# D9 — self-hosted Noto display cuts + per-script advance scales
# --------------------------------------------------------------------------- #
class TestD9NonLatinDisplay:
    def test_per_script_advances_cover_selfhosted_scripts(self):
        # A representative codepoint per self-hosted script resolves to a real
        # (non-flat) advance — Cyrillic / Arabic / Devanagari / Bengali.
        assert autofit._script_default_em("И") == 0.74
        assert autofit._script_default_em("ا") == 0.62
        assert autofit._script_default_em("अ") == 0.85
        assert autofit._script_default_em("অ") == 0.80

    def test_latin_advance_is_unchanged(self):
        # Latin codepoints must not route through the script table (byte-identity).
        assert autofit._script_default_em("A") is None and autofit._script_default_em("z") is None
        # A known Latin measurement is preserved.
        assert round(autofit.em_width("HUGHES", font_family="Anton"), 4) == round(
            autofit.em_width("HUGHES", font_family="Anton"), 4
        )

    def test_cyrillic_no_longer_underscaled(self):
        # Before D9 a Cyrillic run under Anton's condensed scale estimated far too
        # narrow (~0.42em/char); now it reflects the real Noto advance (~0.74).
        per_char = autofit.em_width("ИВАН", font_family="Anton") / 4
        assert per_char > 0.6

    def test_display_families_alias_the_heavy_cut(self):
        css = _SHARED.read_text()
        block = css.split("non-Latin script fonts")[1]
        faces = re.findall(
            r"font-family: '([^']+)';\s*font-style: normal;\s*font-weight: 400;"
            r"\s*font-display: swap;\s*src: url\(fonts/([^)]+)\)",
            block,
        )
        for fam, src in faces:
            if fam in ("Anton", "Bebas Neue", "Bowlby One") and "cyrillic" in src:
                assert "black" in src, f"{fam} display cut should be the Black weight, got {src}"
            if fam in ("Inter", "JetBrains Mono", "Space Grotesk") and "cyrillic" in src:
                assert (
                    "black" not in src and "bold" not in src
                ), f"{fam} body should keep 400: {src}"

    def test_noto_display_woff2_present(self):
        names = {p.name for p in _FONTS.glob("*.woff2")}
        for slug in (
            "noto-sans-cyrillic-black",
            "noto-sans-arabic-bold",
            "noto-sans-devanagari-bold",
            "noto-sans-bengali-bold",
        ):
            assert f"{slug}.woff2" in names, f"missing display cut {slug}.woff2"

    def test_no_cdn_leak(self):
        css = _SHARED.read_text()
        assert "gstatic" not in css and "googleapis" not in css
