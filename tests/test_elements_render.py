"""Roadmap 1.10 build 1 — element render + gradient presets."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mediahub.elements import catalog, gradients, render
from mediahub.elements.models import ElementPlacement


def _brief(palette=None):
    return SimpleNamespace(
        palette=palette or {"primary": "#0A2540", "accent": "#FFB81C"},
        colour_role_assignment={},
        text_layers={},
        inspiration_pattern_id="",
    )


def test_render_markup_recolours_and_sizes():
    el = catalog.get_element("pictogram.stopwatch")
    rv = {
        "--mh-primary": "#0A2540",
        "--mh-accent": "#FFB81C",
        "--mh-surface": "#051433",
        "--mh-on-surface": "#FFFFFF",
        "--mh-secondary": "#1B3D5C",
    }
    out = render.render_element_markup(el, rv, uid="sw")
    assert out is not None
    assert "<svg" in out
    assert "width:100%;height:100%" in out
    assert "__" not in out  # no leftover slot/uid tokens
    assert "#FFB81C" in out


def test_render_for_brief_uses_card_colours():
    el = catalog.get_element("chip.pb")
    out = render.render_for_brief(el, _brief())
    assert out is not None
    assert "#FFB81C" in out  # accent ground from the palette


def test_render_for_palette_thumbnail():
    el = catalog.get_element("pictogram.trophy")
    out = render.render_for_palette(el, palette={"primary": "#222", "accent": "#0F0"})
    assert out is not None and "<svg" in out


def test_render_unknown_file_returns_none():
    from mediahub.elements.models import Element

    ghost = Element(id="x.ghost", name="Ghost", kind="pictogram", sport="general", svg_file="does_not_exist.svg")
    assert render.render_element_markup(ghost, {"--mh-accent": "#fff"}) is None


def test_placement_box_css_centres_and_scales():
    p = ElementPlacement(element_id="x", x=0.5, y=0.5, scale=0.2)
    css = render.placement_box_css(p, width=1000, height=2000, z_index=60)
    assert "position:absolute" in css
    assert "z-index:60" in css
    assert "pointer-events:none" in css
    # box = 0.2 * short(1000) = 200, centred at 500,1000 → left 400, top 900
    assert "left:400px" in css
    assert "top:900px" in css
    assert "width:200px" in css


def test_placement_rotation_and_opacity():
    p = ElementPlacement(element_id="x", rotation=15, opacity=0.5)
    css = render.placement_box_css(p, width=800, height=800, z_index=60)
    assert "rotate(15.00deg)" in css
    assert "opacity:0.500" in css


def test_placement_from_dict_clamps():
    p = ElementPlacement.from_dict({"element_id": "x", "x": 5, "y": -2, "opacity": 9, "scale": 99})
    assert 0.0 <= p.x <= 1.0
    assert 0.0 <= p.y <= 1.0
    assert 0.0 <= p.opacity <= 1.0
    assert p.scale <= 1.5


def test_uid_for_is_stable_and_colour_sensitive():
    rv1 = {"--mh-accent": "#FFB81C", "--mh-primary": "#0A2540"}
    rv2 = {"--mh-accent": "#FF0000", "--mh-primary": "#0A2540"}
    a = render._uid_for("pictogram.trophy", rv1)
    assert a == render._uid_for("pictogram.trophy", rv1)  # stable
    assert a != render._uid_for("pictogram.trophy", rv2)  # colour-sensitive


# --- gradients ---------------------------------------------------------------
def test_gradient_presets_nonempty_and_unique():
    presets = gradients.list_presets()
    assert presets
    ids = [p.id for p in presets]
    assert len(ids) == len(set(ids))


def test_gradient_css_linear_and_radial():
    rv = {"--mh-primary": "#0A2540", "--mh-surface": "#051433", "--mh-accent": "#FFB81C", "--mh-secondary": "#1B3D5C"}
    linear = gradients.gradient_css(gradients.get_preset("grad.brand_descent"), rv)
    assert linear.startswith("linear-gradient(")
    assert "#0A2540" in linear and "#051433" in linear

    radial = gradients.gradient_css(gradients.get_preset("grad.spotlight"), rv)
    assert radial.startswith("radial-gradient(")
    assert "#FFB81C" in radial


def test_gradient_css_for_palette():
    css = gradients.gradient_css_for_palette("grad.duotone", palette={"primary": "#111111", "secondary": "#222222"})
    assert css and "#111111" in css


def test_gradient_unknown_preset_is_none():
    assert gradients.get_preset("nope") is None
    assert gradients.gradient_css_for_palette("nope") is None
