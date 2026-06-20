"""Roadmap 1.10 build 1 — the renderer sprint hook that injects elements."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mediahub.graphic_renderer.sprint_hooks import RenderHookCtx, apply_render_hooks
from mediahub.graphic_renderer.sprint_hooks import elements as elements_hook

_HTML = "<html><body><main>card</main></body></html>"


def _brief(elements=None):
    return SimpleNamespace(
        profile_id="club-1",
        palette={"primary": "#0A2540", "accent": "#FFB81C"},
        colour_role_assignment={},
        text_layers={},
        inspiration_pattern_id="",
        elements=elements if elements is not None else [],
    )


def _ctx(brief, width=1080, height=1350):
    return RenderHookCtx(
        brief=brief,
        width=width,
        height=height,
        family="big_number_dominant",
        format_name="feed_portrait",
        is_v2=True,
    )


def test_byte_identical_when_no_elements():
    out = elements_hook.apply(_HTML, _ctx(_brief([])))
    assert out == _HTML


def test_byte_identical_when_elements_attr_missing():
    brief = SimpleNamespace(profile_id="c", palette={}, colour_role_assignment={}, text_layers={})
    out = elements_hook.apply(_HTML, _ctx(brief))
    assert out == _HTML


def test_injects_overlay_for_valid_placement():
    brief = _brief([{"element_id": "pictogram.trophy", "x": 0.8, "y": 0.2, "scale": 0.18}])
    out = elements_hook.apply(_HTML, _ctx(brief))
    assert out != _HTML
    assert "mh-elements-overlay" in out
    assert 'data-element="pictogram.trophy"' in out
    assert "<svg" in out
    assert "#FFB81C" in out  # recoloured to brand accent
    assert "__" not in out.split("mh-elements-overlay")[1]  # no leftover tokens


def test_unknown_element_is_skipped_byte_identical():
    brief = _brief([{"element_id": "nope.ghost", "x": 0.5, "y": 0.5}])
    out = elements_hook.apply(_HTML, _ctx(brief))
    assert out == _HTML


def test_multiple_placements_all_painted():
    brief = _brief(
        [
            {"element_id": "pictogram.trophy", "x": 0.2, "y": 0.2},
            {"element_id": "chip.pb", "x": 0.8, "y": 0.8},
            {"element_id": "divider.wave", "x": 0.5, "y": 0.5, "scale": 0.5},
        ]
    )
    out = elements_hook.apply(_HTML, _ctx(brief))
    assert out.count('class="mh-element"') == 3


def test_zero_size_canvas_is_noop():
    brief = _brief([{"element_id": "pictogram.trophy"}])
    out = elements_hook.apply(_HTML, _ctx(brief, width=0, height=0))
    assert out == _HTML


def test_hook_is_autodiscovered_in_registry():
    # the elements hook must be picked up by the auto-discovery seam and ordered
    # below the icon-overlay badges
    brief = _brief([{"element_id": "pictogram.trophy", "x": 0.5, "y": 0.5}])
    out = apply_render_hooks(_HTML, _ctx(brief))
    assert "mh-elements-overlay" in out


def test_deterministic_output():
    brief = _brief([{"element_id": "pictogram.stopwatch", "x": 0.5, "y": 0.5}])
    a = elements_hook.apply(_HTML, _ctx(brief))
    b = elements_hook.apply(_HTML, _ctx(brief))
    assert a == b


def test_order_below_icon_overlay():
    from mediahub.graphic_renderer.sprint_hooks import icon_overlay

    assert elements_hook.ORDER < icon_overlay.ORDER


def test_illegible_text_element_is_dropped(monkeypatch):
    # force an illegible role set; a text-carrying chip must be skipped
    from mediahub.elements import recolour

    clash = {
        "--mh-primary": "#FFFFFF",
        "--mh-secondary": "#FEFEFE",
        "--mh-surface": "#FDFDFD",
        "--mh-accent": "#FFFFFF",
        "--mh-on-primary": "#FFFFFF",
        "--mh-on-surface": "#FCFCFC",
        "--mh-outline": "rgba(255,255,255,0.2)",
    }
    monkeypatch.setattr(recolour, "role_vars_for_brief", lambda brief, brand_kit=None: clash)
    brief = _brief([{"element_id": "chip.pb", "x": 0.5, "y": 0.5}])
    out = elements_hook.apply(_HTML, _ctx(brief))
    assert out == _HTML  # the illegible text chip was dropped → byte-identical


def test_nontext_element_survives_even_in_low_contrast(monkeypatch):
    from mediahub.elements import recolour

    clash = {
        "--mh-primary": "#FFFFFF",
        "--mh-secondary": "#FEFEFE",
        "--mh-surface": "#FDFDFD",
        "--mh-accent": "#EEEEEE",
        "--mh-on-primary": "#FFFFFF",
        "--mh-on-surface": "#FCFCFC",
        "--mh-outline": "rgba(0,0,0,0.2)",
    }
    monkeypatch.setattr(recolour, "role_vars_for_brief", lambda brief, brand_kit=None: clash)
    brief = _brief([{"element_id": "pictogram.freestyle", "x": 0.5, "y": 0.5}])
    out = elements_hook.apply(_HTML, _ctx(brief))
    assert "mh-elements-overlay" in out  # non-text pictogram is not contrast-gated
