"""Shared-element transitions (1.5): Match & Move geometry + colour, keyed by a
stable element id, compiled to CSS (FLIP) and Remotion tokens."""
from __future__ import annotations

import pytest

from mediahub.motion.shared_element import SharedElementTransition


def _t(**kw):
    base = dict(element_id="photo", from_rect=(0, 0, 100, 100), to_rect=(200, 200, 300, 300))
    base.update(kw)
    return SharedElementTransition(**base)


def test_endpoints_are_exact():
    t = _t()
    a = t.at(0.0)
    assert (a["x"], a["y"], a["w"], a["h"]) == pytest.approx((0, 0, 100, 100))
    b = t.at(1.0)
    assert (b["x"], b["y"], b["w"], b["h"]) == pytest.approx((200, 200, 300, 300))


def test_midpoint_lies_between():
    g = _t(easing="linear").at(0.5)
    assert (g["x"], g["y"], g["w"], g["h"]) == pytest.approx((100, 100, 200, 200))


def test_colour_interpolates_when_both_given():
    t = _t(from_color="#000000", to_color="#FFFFFF", easing="linear")
    assert t.at(0.0)["color"] == "#000000"
    assert t.at(1.0)["color"] == "#FFFFFF"
    assert t.at(0.5)["color"] in ("#7F7F7F", "#808080")


def test_no_colour_key_without_both_colours():
    assert "color" not in _t().at(0.5)
    assert "color" not in _t(from_color="#000000").at(0.5)


def test_css_is_a_flip_keyframe_keyed_by_id():
    css = _t().to_css()
    assert "mh-shared-photo-kf" in css
    assert ".mh-shared-photo{" in css
    assert "transform:translate3d" in css
    # starts displaced/scaled, ends at identity
    assert "scale(1,1)" in css


def test_css_includes_colour_when_present():
    css = _t(from_color="#102030", to_color="#A0B0C0").to_css()
    assert "background-color:#102030" in css
    assert "background-color:#A0B0C0" in css


def test_remotion_tokens_start_displaced_end_identity():
    tok = _t(easing="linear").to_remotion_tokens(samples=4)
    assert tok["elementId"] == "photo"
    first, last = tok["stops"][0], tok["stops"][-1]
    # at t=0 the element is offset back to the source rect…
    assert first["translateX"] == pytest.approx(-200)
    assert first["translateY"] == pytest.approx(-200)
    assert first["scaleX"] == pytest.approx(100 / 300, abs=1e-4)  # token rounds to 5dp
    # …and at t=1 it is exactly in place.
    assert last["translateX"] == pytest.approx(0)
    assert last["scaleX"] == pytest.approx(1.0)


def test_stable_id_threads_through_outputs():
    t = _t(element_id="hero_stat")
    assert "hero_stat" in t.to_css()
    assert t.to_remotion_tokens()["elementId"] == "hero_stat"
