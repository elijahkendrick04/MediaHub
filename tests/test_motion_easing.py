"""Easing tokens — the shared curve maths behind the motion vocabulary (1.5).

One easing must mean the same thing on all three render targets, so these tests
pin the curve's behaviour (endpoints, character, overshoot) in the one place the
CSS / Remotion / FFmpeg outputs all derive from.
"""
from __future__ import annotations

import pytest

from mediahub.motion import easing as E


def test_every_easing_hits_its_endpoints():
    for name, e in E.EASINGS.items():
        assert abs(e.sample(0.0)) < 1e-3, f"{name} must start at 0"
        assert abs(e.sample(1.0) - 1.0) < 1e-3, f"{name} must end at 1"


def test_sample_clamps_outside_unit_interval():
    e = E.get_easing("ease_out_cubic")
    assert e.sample(-2.0) == pytest.approx(e.sample(0.0), abs=1e-6)
    assert e.sample(5.0) == pytest.approx(e.sample(1.0), abs=1e-6)


def test_linear_is_identity():
    lin = E.get_easing("linear")
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        assert lin.sample(t) == pytest.approx(t, abs=1e-6)


def test_ease_out_front_loads_progress():
    # An ease-OUT is fast first: it is already past halfway at t=0.5.
    assert E.get_easing("ease_out_cubic").sample(0.5) > 0.55


def test_ease_in_back_loads_progress():
    # An ease-IN is slow first: well below halfway at t=0.5.
    assert E.get_easing("ease_in_cubic").sample(0.5) < 0.45


def test_ease_out_back_overshoots_past_one():
    back = E.get_easing("ease_out_back")
    peak = max(back.sample(t / 100) for t in range(101))
    assert peak > 1.0, "ease_out_back is meant to overshoot the target"


def test_non_back_easings_are_monotonic():
    for name in ("linear", "ease_out_cubic", "ease_in_cubic", "ease_in_out_cubic",
                 "ease_in_out_sine", "ease_out_quad", "ease_in_quad"):
        e = E.get_easing(name)
        prev = -1.0
        for t in range(0, 101):
            v = e.sample(t / 100)
            assert v >= prev - 1e-6, f"{name} regressed at t={t}"
            prev = v


def test_css_serialisation_is_a_cubic_bezier():
    css = E.get_easing("ease_out_cubic").css()
    assert css.startswith("cubic-bezier(") and css.endswith(")")
    # four comma-separated numbers
    assert css.count(",") == 3


def test_ffmpeg_expr_substitutes_progress():
    expr = E.get_easing("ease_out_cubic").ffmpeg_expr("on/30")
    assert "(on/30)" in expr
    assert "P" not in expr.replace("PI", "")  # the placeholder is gone (PI kept)


def test_unknown_easing_falls_back_to_default():
    assert E.get_easing("does_not_exist") is E.EASINGS[E.DEFAULT_EASING]
