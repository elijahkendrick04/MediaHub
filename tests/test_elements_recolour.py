"""Roadmap 1.10 build 1 — brand-token recolour engine."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from mediahub.elements import catalog, recolour
from mediahub.elements.models import Element

_ROLE_VARS = {
    "--mh-primary": "#0A2540",
    "--mh-secondary": "#1B3D5C",
    "--mh-surface": "#051433",
    "--mh-accent": "#FFB81C",
    "--mh-on-primary": "#FFFFFF",
    "--mh-on-surface": "#FFFFFF",
    "--mh-outline": "rgba(255,255,255,0.20)",
}


def _brief(palette=None, assignment=None, text_layers=None):
    return SimpleNamespace(
        palette=palette or {"primary": "#0A2540", "accent": "#FFB81C"},
        colour_role_assignment=assignment or {},
        text_layers=text_layers or {},
        inspiration_pattern_id="",
    )


def test_recolour_substitutes_all_slots():
    svg = (
        '<svg viewBox="0 0 10 10"><rect fill="__ACCENT__"/>'
        '<rect fill="__GROUND__"/><text fill="__ON_GROUND__">hi</text>'
        '<line stroke="__OUTLINE__"/></svg>'
    )
    out = recolour.recolour_svg(svg, _ROLE_VARS, uid="abc")
    assert "#FFB81C" in out  # accent
    assert "#0A2540" in out  # ground
    assert "#FFFFFF" in out  # on-ground
    assert "rgba(255,255,255,0.20)" in out  # outline


def test_no_placeholders_left_after_recolouring_real_elements():
    """Every bundled element fully resolves — no stray __SLOT__ survives."""
    token_re = re.compile(r"__[A-Z_]+__")
    for el in catalog.load_catalog():
        svg = catalog.load_svg(el)
        assert svg is not None
        out = recolour.recolour_svg(svg, _ROLE_VARS, uid="t")
        leftovers = token_re.findall(out)
        assert not leftovers, f"{el.id} left unresolved tokens: {leftovers}"


def test_uid_substitution_makes_ids_unique():
    svg = '<svg><linearGradient id="g__UID__"/><rect fill="url(#g__UID__)"/></svg>'
    a = recolour.recolour_svg(svg, _ROLE_VARS, uid="one")
    b = recolour.recolour_svg(svg, _ROLE_VARS, uid="two")
    assert "g one" not in a  # uid sanitised, but distinct
    assert "__UID__" not in a and "__UID__" not in b
    assert a != b


def test_uid_is_sanitised():
    svg = '<svg><filter id="f__UID__"></filter></svg>'
    out = recolour.recolour_svg(svg, _ROLE_VARS, uid="bad id/with*chars")
    # the id value (between the quotes) must contain no unsafe chars
    id_value = out.split('id="')[1].split('"')[0]
    assert "/" not in id_value
    assert "*" not in id_value
    assert " " not in id_value
    assert id_value == "fbadidwithchars"


def test_recolour_is_deterministic():
    svg = catalog.load_svg(catalog.get_element("pictogram.trophy"))
    a = recolour.recolour_svg(svg, _ROLE_VARS, uid="x")
    b = recolour.recolour_svg(svg, _ROLE_VARS, uid="x")
    assert a == b


def test_role_vars_for_brief_returns_full_set():
    rv = recolour.role_vars_for_brief(_brief())
    for key in _ROLE_VARS:
        assert key in rv
        assert isinstance(rv[key], str) and rv[key]


def test_role_vars_for_brief_falls_back_on_garbage():
    # a brief missing the attributes the resolver reads must not raise
    rv = recolour.role_vars_for_brief(object())
    assert rv["--mh-primary"]
    assert rv["--mh-accent"]


def test_role_vars_from_palette_honours_palette():
    rv = recolour.role_vars_from_palette({"primary": "#112233", "accent": "#AABBCC"})
    assert rv["--mh-primary"].lower() == "#112233"
    assert rv["--mh-accent"].lower() == "#aabbcc"


def test_element_is_legible_passes_for_nontext():
    el = catalog.get_element("pictogram.freestyle")
    assert el.carries_text is False
    assert recolour.element_is_legible(el, _ROLE_VARS) is True


def test_element_is_legible_for_text_chip_on_brand():
    el = catalog.get_element("chip.pb")
    assert el.carries_text is True
    # gold accent ground with navy text is a classic legible pairing
    assert recolour.element_is_legible(el, _ROLE_VARS) is True


def test_element_is_legible_false_when_text_clashes():
    el = catalog.get_element("chip.pb")  # carries text
    clash = {
        "--mh-primary": "#FFFFFF",
        "--mh-secondary": "#FEFEFE",
        "--mh-surface": "#FDFDFD",
        "--mh-accent": "#FFFFFF",
        "--mh-on-primary": "#FFFFFF",  # white ink on white everything → illegible
        "--mh-on-surface": "#FCFCFC",
        "--mh-outline": "rgba(255,255,255,0.2)",
    }
    assert recolour.element_is_legible(el, clash) is False


def test_outline_role_passthrough_when_rgba():
    out = recolour.recolour_svg('<svg><line stroke="__OUTLINE__"/></svg>', _ROLE_VARS, uid="z")
    assert "rgba(" in out
