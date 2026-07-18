"""B6 (Canva gap analysis) — frosted-glass chips over photos.

Guards the whole glass_chip treatment, on both surfaces and under mono:

* ``render._glass_role_vars`` — the APCA-gated alpha search: emits ``--mh-glass-*``
  only when the chip inks clear the tinted fill over pure white AND pure black,
  flooring the nominal 0.30 alpha up until legible, else ``{}`` (opaque fallback).
* ``glass_chip`` is a first-class ``ACCENT_TREATMENTS`` token executed by the still
  (``_accent_decoration_html`` margin pill + the v2 modules' ``--mh-glass-*`` tokens)
  and mirrored by ``sprint/accents/glass_chip.tsx`` (registry contract).
* The ``.mh-glass`` recipe lives in ``_base.css``; the scorebug module and the
  lower-third result chip consume the tokens with their OPAQUE value as the CSS
  ``var()`` fallback, so a non-glass card is byte-identical.
* Mono mode rewrites the brand-derived ``--mh-surface-rgb`` triple (no leak).
"""

from __future__ import annotations

from types import SimpleNamespace

from mediahub.creative_brief.design_spec import ACCENT_TREATMENTS, normalise
from mediahub.graphic_renderer import archetypes as _arch
from mediahub.graphic_renderer import render as R
from mediahub.graphic_renderer.archetypes import TOKEN_ROLES, list_archetypes
from mediahub.quality.compliance import LC_LARGE, is_legible
from mediahub.visual import motion

# A legible dark-first club (dark navy surface, light ink, bright gold accent).
_DARK_ROLES = {
    "--mh-primary": "#0A2540",
    "--mh-surface": "#0A1626",
    "--mh-on-primary": "#F2F6FA",
    "--mh-accent": "#E8B23A",
}


# --------------------------------------------------------------------------- #
# _composite_over — the analytic alpha blend the gate runs on
# --------------------------------------------------------------------------- #
def test_composite_over_is_the_alpha_blend():
    # fill fully opaque → the fill itself, regardless of base.
    assert R._composite_over("#804020", 1.0, "#FFFFFF") == "#804020"
    # fill fully transparent → the base.
    assert R._composite_over("#804020", 0.0, "#FFFFFF") == "#FFFFFF"
    # 0.5 of black over white → mid grey (#808080, rounding).
    assert R._composite_over("#000000", 0.5, "#FFFFFF").lower() in ("#808080", "#7f7f7f")


# --------------------------------------------------------------------------- #
# _glass_role_vars — the APCA-gated alpha search
# --------------------------------------------------------------------------- #
def test_glass_vars_emitted_for_a_legible_dark_club():
    g = R._glass_role_vars(_DARK_ROLES)
    assert g, "expected glass tokens for a legible dark club"
    assert "--mh-surface-rgb" in g
    # surface-rgb is the resolved surface's triple.
    r, gg, b = R._hex_to_rgb(_DARK_ROLES["--mh-surface"])
    assert g["--mh-surface-rgb"] == f"{r},{gg},{b}"
    assert g["--mh-glass-bg"].startswith("rgba(var(--mh-surface-rgb),")
    # ink rides the role var so mono's remap flows through it (never a raw hex).
    assert g["--mh-glass-ink"] == "var(--mh-on-primary)"
    assert "blur(12px) saturate(140%)" in g["--mh-glass-filter"]
    assert g["--mh-glass-border"] == "1px solid rgba(255,255,255,0.16)"


def test_glass_alpha_is_floored_up_until_the_ink_clears_apca():
    g = R._glass_role_vars(_DARK_ROLES)
    # parse the chosen alpha out of the rgba() and re-verify the gate holds:
    alpha = float(g["--mh-glass-bg"].rsplit(",", 1)[1].rstrip(")"))
    assert R._GLASS_NOMINAL_ALPHA <= alpha <= R._GLASS_MAX_ALPHA
    surface = _DARK_ROLES["--mh-surface"]
    over_white = R._composite_over(surface, alpha, "#FFFFFF")
    over_black = R._composite_over(surface, alpha, "#000000")
    for ink in (_DARK_ROLES["--mh-on-primary"], _DARK_ROLES["--mh-accent"]):
        assert is_legible(ink, over_white, min_lc=LC_LARGE)
        assert is_legible(ink, over_black, min_lc=LC_LARGE)


def test_glass_falls_back_to_opaque_when_no_alpha_clears():
    # accent barely distinct from the surface → never clears the black-backdrop
    # composite at any glassy alpha → keep the opaque fill.
    bad = {**_DARK_ROLES, "--mh-accent": "#0C1A2C", "--mh-on-primary": "#0B0B0C"}
    assert R._glass_role_vars(bad) == {}


def test_glass_vars_empty_on_junk_roles():
    assert R._glass_role_vars({"--mh-surface": "not-a-hex", "--mh-on-primary": "#FFF"}) == {}
    assert R._glass_role_vars({}) == {}


# --------------------------------------------------------------------------- #
# design-spec vocabulary + still/motion execution contract
# --------------------------------------------------------------------------- #
def test_glass_chip_is_a_directable_accent_treatment():
    assert "glass_chip" in ACCENT_TREATMENTS
    spec = normalise(
        {"accent_treatment": "glass_chip"},
        archetypes=list_archetypes(),
        token_roles=list(TOKEN_ROLES),
    )
    assert spec.accent_treatment == "glass_chip"


def test_glass_chip_has_a_still_execution_scaling_and_zeroing():
    small = R._accent_decoration_html("glass_chip", "#E8B23A", 540, 960, 0.5)
    large = R._accent_decoration_html("glass_chip", "#E8B23A", 1080, 1920, 0.5)
    assert small and large
    assert "backdrop-filter" in large and "var(--mh-surface-rgb" in large
    # scales with the canvas, not fixed px.
    assert small != large
    # zero decoration strength collapses it (shared accent contract).
    assert R._accent_decoration_html("glass_chip", "#E8B23A", 1080, 1920, 0.0) == ""


def test_motion_twin_registers_the_glass_chip_token():
    tsx = motion.REMOTION_DIR / "src" / "compositions" / "sprint" / "accents" / "glass_chip.tsx"
    assert tsx.exists(), "missing motion accent twin glass_chip.tsx"
    body = tsx.read_text(encoding="utf-8")
    assert 'name: "glass_chip"' in body
    assert "backdropFilter" in body and "roles.surface" in body


# --------------------------------------------------------------------------- #
# _base.css recipe + layout var-fallback wiring (byte-identity by construction)
# --------------------------------------------------------------------------- #
def test_base_css_carries_the_glass_recipe():
    css = (_arch.V2_DIR.parent / "_base.css").read_text(encoding="utf-8")
    assert ".mh-glass" in css
    assert "backdrop-filter: var(--mh-glass-filter" in css
    assert "var(--mh-glass-bg, rgba(var(--mh-surface-rgb" in css


def test_layout_modules_consume_glass_tokens_with_opaque_fallback():
    scorebug = (_arch.V2_DIR / "broadcast_scorebug.html").read_text(encoding="utf-8")
    assert "var(--mh-glass-bg, var(--mh-primary))" in scorebug
    assert "var(--mh-glass-border, 2px solid var(--mh-outline))" in scorebug
    assert "backdrop-filter: var(--mh-glass-filter, none)" in scorebug
    lower = (_arch.V2_DIR / "full_bleed_photo_lower_third.html").read_text(encoding="utf-8")
    assert "var(--mh-glass-bg, var(--mh-accent))" in lower
    assert "var(--mh-glass-ink, var(--mh-primary))" in lower


# --------------------------------------------------------------------------- #
# stat chips glass toggle
# --------------------------------------------------------------------------- #
def _chip_brief():
    return SimpleNamespace(
        secondary_stats=["pb_delta", "season_best"],
        hero_stat_options={"pb_delta": "−0.42s on PB", "season_best": "1:59.10"},
        text_layers={"hero_stat": ""},
    )


def test_stat_chips_glass_flag_swaps_hairline_for_the_glass_recipe():
    b = _chip_brief()
    opaque = R._stat_chips_html(b, "--mh-on-primary", glass=False)
    glass = R._stat_chips_html(b, "--mh-on-primary", glass=True)
    assert opaque and glass
    assert "border:1px solid var(--mh-outline)" in opaque
    assert 'class="mh-glass"' in glass
    assert "border:1px solid var(--mh-outline)" not in glass


# --------------------------------------------------------------------------- #
# mono mode must rewrite the brand-derived --mh-surface-rgb triple
# --------------------------------------------------------------------------- #
def test_mono_mode_rewrites_surface_rgb_no_brand_leak():
    from mediahub.graphic_renderer.sprint_hooks.mono_mode import (
        _rewrite_role_decls,
        mono_role_vars,
    )

    html = (
        ":root{--mh-primary:#0A2540;--mh-surface:#0A1626;"
        "--mh-surface-rgb:10,22,38;"
        "--mh-glass-bg:rgba(var(--mh-surface-rgb),0.70);"
        "--mh-glass-ink:var(--mh-on-primary);}"
    )
    out = _rewrite_role_decls(html, mono_role_vars("#0A2540", "#0A1626"))
    assert "--mh-surface-rgb:10,22,38" not in out, "brand surface triple leaked past mono"
    # a mono grey triple stands in.
    assert "--mh-surface-rgb:" in out
