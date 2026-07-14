"""Canva gap-analysis upgrade tests (docs/CANVA_GAP_ANALYSIS.md).

Pins the Wave A–E builds:

* A2 — emblem base separates from the card ground (see test_g1_22_icon_overlay
  for the full contract; here only the exported threshold is sanity-pinned).
* A4 — the logo text-mark fallback is a styled SVG monogram, not bare initials.
* A5 — numeric separator kerning: tag-safe wrapping + fitted-size credit.
* B1/B2 — elevation tokens: layered, one light direction, hue-tinted shadow rgb.
* B3 — ground micro-gradient emitted only when the shaded endpoint stays legible.
* B5/C5 — sticker/wash photo treatments (vocabulary + still assets + gating).
* C2 — brand-hue-tinted neutral inks (pure only for neutral grounds / gate fails).
* C3 — --mh-secondary-vis degrades to the accent for one-band palettes.
* C7 — glitch dyad derives from the accent, fixed dyad only as fallback.
* C8 — gradient meshes carry the grain dither layer.
* D1 — measured family width overrides + pair-aware hero fitting.
* D2 — tracking ramps are monotone and register-correct.
* D3 — balanced-wrap capability scan + crush trigger.
* E1 — measured auto-enhance: deficient photos corrected, healthy pass through.

All pure-function (no Playwright) so they run in any environment.
"""

from __future__ import annotations

from PIL import Image

from mediahub.graphic_renderer import elevation
from mediahub.graphic_renderer import photo_adjust as pa
from mediahub.graphic_renderer import render as R
from mediahub.graphic_renderer import text_effects as fx
from mediahub.graphic_renderer.autofit import em_width, tracking_for_px
from mediahub.graphic_renderer.gradient_mesh import build_mesh_svg
from mediahub.graphic_renderer.style_packs import _accent_geometry_html


# --------------------------------------------------------------------------- #
# A4 — monogram fallback
# --------------------------------------------------------------------------- #
class _NoLogoKit:
    short_name = "Riverside Swimming Club"
    display_name = "Riverside Swimming Club"


def test_logo_fallback_is_a_styled_monogram_chip():
    html, mod = R._build_logo_treatment(_NoLogoKit(), None)
    assert html.startswith("<svg")
    assert "currentColor" in html  # inherits the lockup's legible ink
    assert ">R<" in html  # generic words stripped → the R monogram
    assert mod == ""


def test_logo_fallback_multiword_initials():
    class Kit:
        short_name = "City of Leeds"
        display_name = "City of Leeds"

    html, _ = R._build_logo_treatment(Kit(), None)
    assert ">CL<" in html  # "of" stripped, City + Leeds


# --------------------------------------------------------------------------- #
# A5 — numeric separator kerning
# --------------------------------------------------------------------------- #
def test_kern_wraps_intra_numeric_separators_only():
    html, n = R._kern_numeric_seps("1:45.23")
    assert n == 2
    assert html == '1<span class="mh-sep">:</span>45<span class="mh-sep">.</span>23'
    assert R._kern_numeric_seps("DQ") == ("DQ", 0)
    assert R._kern_numeric_seps("1st") == ("1st", 0)


def test_kern_never_touches_markup_attributes():
    effect_wrapped = '<span class="mh-fx" style="text-shadow:0 0.045em 0.14em;">58.34</span>'
    html, n = R._kern_numeric_seps(effect_wrapped)
    assert n == 1
    assert 'style="text-shadow:0 0.045em 0.14em;"' in html  # attribute untouched
    assert '58<span class="mh-sep">.</span>34' in html


def test_kern_skips_curve_svg_slots():
    svg = '<svg class="mh-fx-curve">58.34</svg>'
    assert R._kern_numeric_seps(svg) == (svg, 0)


# --------------------------------------------------------------------------- #
# B1/B2 — elevation system
# --------------------------------------------------------------------------- #
def test_elevation_layers_grow_with_level_in_one_light_direction():
    e1 = elevation.elevation_shadow(1)
    e5 = elevation.elevation_shadow(5)
    assert e1.count("rgba") == 2 and e5.count("rgba") == 6  # contact + N key layers
    # One light source: every offset is straight down (x == 0).
    for token in (e1 + ", " + e5).split(", "):
        assert token.strip().startswith("0 ")
    # Tokens consume the per-card tinted rgb with a neutral fallback.
    assert "var(--mh-shadow-rgb,10,12,16)" in e1


def test_shadow_rgb_keeps_the_ground_hue():
    import colorsys

    navy = elevation.shadow_rgb("#0A2540")
    r, g, b = (int(v) for v in navy.split(","))
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    hn, _, _ = colorsys.rgb_to_hls(0x0A / 255, 0x25 / 255, 0x40 / 255)
    assert abs(h - hn) < 0.06  # hue preserved
    assert l <= 0.15  # deep
    assert elevation.shadow_rgb("not-a-hex") == "10,12,16"


def test_elevation_vars_bundle():
    vars_ = elevation.elevation_vars("#0A2540")
    assert set(f"--mh-elev-{i}" for i in range(1, 6)) <= set(vars_)
    assert "--mh-shadow-rgb" in vars_ and "--mh-elev-drop-2" in vars_


# --------------------------------------------------------------------------- #
# C2 — tinted neutral inks
# --------------------------------------------------------------------------- #
def test_on_color_tints_toward_the_ground_hue():
    ink = R._on_color("#0A2540")  # dark navy ground
    assert ink not in ("#FFFFFF", "#0B0B0C")  # tinted, not pure
    assert R._rel_luminance(ink) > 0.85  # still a near-white ink
    # Neutral grounds keep the neutral ink (nothing to tint toward).
    assert R._on_color("#FFFFFF") == "#0B0B0C"
    assert R._on_color("#808080") == "#FFFFFF"


# --------------------------------------------------------------------------- #
# C3 — secondary-vis guard
# --------------------------------------------------------------------------- #
def test_secondary_vis_degrades_to_accent_for_one_band_palettes():
    # Navy secondary on a navy ground: no separation → accent.
    vars_ = R._mh_role_vars({"primary": "#0A2540", "secondary": "#0E1B2C", "accent": "#E8B94E"})
    assert vars_["--mh-secondary-vis"] == vars_["--mh-accent"]
    # A genuinely separated secondary deploys itself.
    vars2 = R._mh_role_vars({"primary": "#0A2540", "secondary": "#C9A227", "accent": "#FFFFFF"})
    assert vars2["--mh-secondary-vis"] == "#C9A227"


def test_two_stroke_geometries_consume_secondary_vis():
    html = _accent_geometry_html("double_rule", 1080, 1350, False)
    assert "var(--mh-secondary-vis, var(--mh-accent))" in html
    dots = _accent_geometry_html("dot_row", 1080, 1350, False)
    assert "var(--mh-secondary-vis, var(--mh-accent))" in dots


# --------------------------------------------------------------------------- #
# C7 — brand-locked glitch
# --------------------------------------------------------------------------- #
def test_glitch_dyad_derives_from_the_accent():
    res = fx.effect_css(
        "glitch", ground="#0A2540", ink="#FFFFFF", accent="#E8B94E", on_accent="#0A2540"
    )
    assert "rgba(255,0,86" not in res.style  # not the fixed fallback dyad
    assert res.style.count("rgba(") == 2
    # Unparseable accent → the fixed fallback dyad still renders something.
    res2 = fx.effect_css("glitch", ground="#0A2540", ink="#FFFFFF", accent="", on_accent="#0A2540")
    assert "rgba(255,0,86" in res2.style


# --------------------------------------------------------------------------- #
# C8 — mesh grain dither
# --------------------------------------------------------------------------- #
def test_mesh_carries_grain_dither():
    roles = {
        "--mh-primary": "#0A2540",
        "--mh-surface": "#05121F",
        "--mh-accent": "#E8B94E",
        "--mh-on-primary": "#FFFFFF",
    }
    svg = build_mesh_svg(roles, 400, 500, seed=3)
    assert "mh-mesh-grain" in svg and 'opacity="0.05"' in svg
    # Determinism: same args → same bytes.
    assert svg == build_mesh_svg(roles, 400, 500, seed=3)


# --------------------------------------------------------------------------- #
# D1 — measured display-family widths
# --------------------------------------------------------------------------- #
def test_display_family_widths_are_measured_not_guessed():
    text = "WESTHUIZEN"
    anton = em_width(text, font_family="Anton", weight=400)
    bowlby = em_width(text, font_family="Bowlby One", weight=400)
    bebas = em_width(text, font_family="Bebas Neue", weight=400)
    assert bowlby > anton * 1.4  # Bowlby is dramatically wider — the overflow face
    assert bebas < anton  # Bebas is narrower — the under-filled face


# --------------------------------------------------------------------------- #
# D2 — tracking ramps
# --------------------------------------------------------------------------- #
def test_tracking_ramps_are_monotone_and_bounded():
    assert tracking_for_px(60) == -0.010  # clamped at the small end
    assert tracking_for_px(300) == -0.035  # clamped at the large end
    assert tracking_for_px(80) > tracking_for_px(240)  # tighter as it grows
    assert tracking_for_px(18, "label") > 0  # small caps labels OPEN
    assert tracking_for_px(100, "nonsense") == 0.0


# --------------------------------------------------------------------------- #
# D3 — balanced-wrap capability scan
# --------------------------------------------------------------------------- #
def test_surname_slot_capability_scan():
    # A mega-name archetype reports the mega var; the ticker (opt-out family,
    # but the scan itself is layout-driven) reports whatever its template uses.
    assert R._surname_slot_capability("mega_surname_bleed") == "--mh-fit-mega-name-px"
    assert R._surname_slot_capability("full_bleed_photo_lower_third") in (
        "--mh-fit-surname-px",
        "--mh-fit-mega-name-px",
    )
    assert R._surname_slot_capability("no_such_archetype") == ""


# --------------------------------------------------------------------------- #
# B5/C5 — sticker + wash treatments
# --------------------------------------------------------------------------- #
class _TreatBrief:
    decoration_strength = 0.5
    photo_mode = "cutout"

    def __init__(self, treatment):
        self.photo_treatment = treatment


def test_wash_treatment_emits_filter_and_defs():
    css, defs = R._v2_photo_treatment_assets(
        _TreatBrief("wash"), {"--mh-primary": "#0A2540"}, 1080, 1350, True
    )
    assert "url(#mh-wash)" in css
    assert "feComposite" in defs and 'operator="arithmetic"' in defs


def test_sticker_treatment_requires_a_cutout_silhouette():
    css, defs = R._v2_photo_treatment_assets(
        _TreatBrief("sticker"), {"--mh-primary": "#0A2540"}, 1080, 1350, True
    )
    assert css.count("drop-shadow") == 8 and "var(--mh-on-primary)" in css
    # A photo-mode / matte-rejected card honestly skips the contour.
    assert R._v2_photo_treatment_assets(
        _TreatBrief("sticker"), {"--mh-primary": "#0A2540"}, 1080, 1350, False
    ) == ("", "")


def test_untreated_cards_stay_byte_identical():
    assert R._v2_photo_treatment_assets(
        _TreatBrief("cutout"), {"--mh-primary": "#0A2540"}, 1080, 1350, True
    ) == ("", "")


# --------------------------------------------------------------------------- #
# E1 — measured auto-enhance
# --------------------------------------------------------------------------- #
def test_auto_recipe_corrects_a_dim_flat_photo():
    dim = Image.new("RGB", (200, 150), (30, 34, 40))
    r = pa.auto_recipe(dim)
    ops = {s.op for s in r.steps}
    assert "levels" in ops and "brightness" in ops


def test_auto_recipe_passes_a_healthy_photo_through():
    import random

    img = Image.new("RGB", (200, 150))
    px = img.load()
    rng = random.Random(7)
    for y in range(150):
        for x in range(200):
            v = rng.randint(0, 255)
            px[x, y] = (v, v, rng.randint(0, 255))
    r = pa.auto_recipe(img)
    assert r.is_noop()
    # And the sentinel path returns the image object semantics unchanged.
    assert pa.adjust_image(img, pa.get_preset("auto")) is img


def test_auto_sentinel_is_not_a_noop_and_signs_its_version():
    sent = pa.get_preset("auto")
    assert sent is not None and not sent.is_noop()
    assert sent.signature() != pa.get_preset("none").signature()


# --------------------------------------------------------------------------- #
# Mono-mode interaction — derived tokens must not leak brand colour
# --------------------------------------------------------------------------- #
def test_mono_mode_rewrites_the_derived_colour_tokens():
    from mediahub.graphic_renderer.sprint_hooks.mono_mode import (
        _rewrite_role_decls,
        mono_role_vars,
    )

    html = (
        ":root{--mh-primary:#0E5BFF;--mh-surface:#0A2540;"
        "--mh-ground-gradient:linear-gradient(180deg, #1862FF 0%, #0E5BFF 52%, #0D56F3 100%);"
        "--mh-surface-2:#0A407F;--mh-lift:#2665E0;--mh-ink-secondary:#B3C6EE;"
        # C1 tonal-container tokens also embed brand-derived hexes.
        "--mh-surface-container:#19324D;--mh-surface-raised:#253D59;"
        "--mh-accent-container:#5B4300;--mh-on-accent-container:#FFDF9E;"
        "--mh-secondary-vis:#C9A227;--mh-shadow-rgb:6,17,38;}"
    )
    out = _rewrite_role_decls(html, mono_role_vars("#0E5BFF", "#0A2540"))
    for brand_hex in (
        "#0E5BFF",
        "#1862FF",
        "#0D56F3",
        "#0A407F",
        "#2665E0",
        "#C9A227",
        "#19324D",
        "#253D59",
        "#5B4300",
        "#FFDF9E",
    ):
        assert brand_hex not in out, f"{brand_hex} leaked past the mono remap"
    assert "--mh-shadow-rgb:10,10,10" in out


# --------------------------------------------------------------------------- #
# C1 — tonal-container bridge from the brand seed into the role resolver
# --------------------------------------------------------------------------- #
def test_tonal_pick_is_deterministic_hct_and_clamped():
    from mediahub.theming.palette import tonal_pick

    # A dark navy seed rides its own HCT ramp; higher tone → lighter hex.
    assert R._rel_luminance(tonal_pick("#0A2540", 90)) > R._rel_luminance(tonal_pick("#0A2540", 20))
    assert tonal_pick("#0A2540", 20) == tonal_pick("#0A2540", 20)  # deterministic
    assert tonal_pick("#0A2540", 999) == tonal_pick("#0A2540", 100)  # tone clamped
    assert tonal_pick("not-a-hex", 30) == "#000000"  # safe fallback


def test_bridge_emits_container_tokens_gated():
    base = R._mh_role_vars({"primary": "#0A2540", "secondary": "#0E1B2C", "accent": "#E8B94E"})
    out = R._bridge_tonal_tokens(base, R._mood_tone_plan("neutral"))
    for tok in (
        "--mh-surface-container",
        "--mh-surface-raised",
        "--mh-accent-container",
        "--mh-on-accent-container",
    ):
        assert out[tok].startswith("#")
    # The accent-container carries a legible on-colour by construction.
    from mediahub.quality.compliance import is_legible

    assert is_legible(out["--mh-on-accent-container"], out["--mh-accent-container"])
    # Neutral mood emits no scrim/mesh hint (byte-identical to the C1-only set).
    assert "--mh-scrim-alpha" not in out and "--mh-mesh-intensity" not in out
    # A non-brand primary yields nothing to bridge.
    assert (
        R._bridge_tonal_tokens({"--mh-primary": "x", "--mh-accent": "y"}, R._mood_tone_plan(""))
        == {}
    )


def test_resolver_ships_the_container_tokens_and_adopted_layouts_consume_them():
    from mediahub.graphic_renderer import archetypes as arch

    class _Brief:
        palette = {"primary": "#0A2540", "secondary": "#0E1B2C", "accent": "#E8B94E"}
        colour_role_assignment: dict = {}
        mood = ""
        text_layers: dict = {}
        confidence_label = ""

    roles = R.resolved_role_vars_for_brief(_Brief())
    assert roles["--mh-surface-container"].startswith("#")
    # The three adopted archetypes reference the token with a var() fallback.
    for name in ("three_card_editorial_grid", "vertical_stat_tower", "stat_stack_sidebar"):
        text = (arch.V2_DIR / f"{name}.html").read_text(encoding="utf-8")
        assert "var(--mh-surface-container, var(--mh-surface))" in text


# --------------------------------------------------------------------------- #
# C9 — mood → derived-tone table (only derived tones move; brand hexes fixed)
# --------------------------------------------------------------------------- #
def test_mood_tone_table_covers_every_mood():
    from mediahub.creative_brief import design_spec as ds

    # Drift guard: every design_spec.MOODS token must resolve to a plan.
    for mood in ds.MOODS:
        assert mood in R._MOOD_TONE_PLANS, f"mood {mood!r} missing a tone plan"
    # neutral and minimal are the identity (no derived tone moves).
    assert R._mood_tone_plan("neutral") == R._MOOD_IDENTITY
    assert R._mood_tone_plan("minimal") == R._MOOD_IDENTITY
    assert R._mood_tone_plan("nonsense word") == R._MOOD_IDENTITY


def test_mood_moves_only_derived_tones_never_brand_hexes():
    base = R._mh_role_vars({"primary": "#0A2540", "secondary": "#0E1B2C", "accent": "#E8B94E"})
    neutral = R._bridge_tonal_tokens(base, R._mood_tone_plan("neutral"))
    stoic = R._bridge_tonal_tokens(base, R._mood_tone_plan("stoic"))
    celeb = R._bridge_tonal_tokens(base, R._mood_tone_plan("celebratory"))
    # Stoic drops the container tone (deeper), celebratory lifts it (lighter).
    assert R._rel_luminance(stoic["--mh-surface-container"]) < R._rel_luminance(
        neutral["--mh-surface-container"]
    )
    assert R._rel_luminance(celeb["--mh-surface-container"]) > R._rel_luminance(
        neutral["--mh-surface-container"]
    )
    # A moving mood emits the scrim/mesh hints; the confirmed brand hexes never shift.
    assert "--mh-scrim-alpha" in stoic and "--mh-mesh-intensity" in celeb
    assert base["--mh-primary"] == "#0A2540" and base["--mh-accent"] == "#E8B94E"


# --------------------------------------------------------------------------- #
# C6 — per-slot contrast repair + gate-filtered colourway walk
# --------------------------------------------------------------------------- #
def test_role_assignment_repairs_a_failing_slot_instead_of_reverting():
    from mediahub.quality.compliance import check_roles

    base = R._mh_role_vars({"primary": "#0E2A47", "secondary": "#C9A227", "accent": "#C9A227"})
    # ground→gold leaves accent==ground (Lc 0): the OLD engine reverted wholesale;
    # C6 steps ONLY the accent to legibility and ships the director's gold ground.
    out = R._apply_role_assignment(base, {"ground": "secondary"})
    assert out["--mh-primary"] == "#C9A227"  # director's ground kept
    assert out["--mh-accent"] != "#C9A227"  # failing slot repaired
    assert check_roles(out).passes
    assert out.get("--mh-repair-note", "").startswith("repaired-")
    # A fully-legible assignment ships unchanged with no repair note.
    ok = R._apply_role_assignment(base, {"ground": "secondary", "accent": "primary"})
    assert "--mh-repair-note" not in ok


def test_seed_walk_indexes_only_gate_surviving_permutations():
    from mediahub.creative_brief.generator import gate_surviving_seeds, _apply_palette_seed

    # maroon/black/gold: a maroon accent on a black ground is illegible, so that
    # permutation is pruned — but seeds 1..3 (the legacy contract) are preserved.
    survivors = gate_surviving_seeds("#A30D2D", "#000000", "#FFD86E")
    assert survivors and survivors[:3] == [1, 2, 3]
    for s in (1, 2, 3):
        assert _apply_palette_seed(
            "#A30D2D", "#000000", "#FFD86E", s, gate=True
        ) == _apply_palette_seed("#A30D2D", "#000000", "#FFD86E", s, gate=False)
    # An all-legible kit prunes nothing (byte-identical walk).
    assert gate_surviving_seeds("#0E2A47", "#C9A227", "#FFFFFF") == [1, 2, 3, 4, 5, 6]
