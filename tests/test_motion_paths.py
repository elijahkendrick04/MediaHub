"""Motion paths (1.5): SVG sampling, orient-to-path, and the three compilers."""
from __future__ import annotations

import pytest

from mediahub.motion import paths


def test_horizontal_line_samples_evenly():
    p = paths.from_svg("M0,0 L100,0")
    assert p.length == pytest.approx(100.0, abs=0.5)
    assert p.point_at(0.0) == pytest.approx((0.0, 0.0), abs=0.5)
    assert p.point_at(0.5) == pytest.approx((50.0, 0.0), abs=0.5)
    assert p.point_at(1.0) == pytest.approx((100.0, 0.0), abs=0.5)
    assert p.angle_at(0.5) == pytest.approx(0.0, abs=1.0)


def test_vertical_line_orients_downward():
    p = paths.from_svg("M0,0 L0,100")
    # SVG y grows downward; atan2(+100, 0) == +90°.
    assert p.angle_at(0.5) == pytest.approx(90.0, abs=1.0)


def test_relative_commands_match_absolute():
    a = paths.from_svg("M10,10 L110,10")
    b = paths.from_svg("M10,10 l100,0")
    assert a.point_at(1.0) == pytest.approx(b.point_at(1.0), abs=0.5)


def test_cubic_curve_parses_with_correct_endpoints():
    p = paths.from_svg("M0,0 C0,50 100,50 100,0")
    assert p.length > 100  # a curve is longer than the straight chord
    assert p.point_at(0.0) == pytest.approx((0.0, 0.0), abs=0.5)
    assert p.point_at(1.0) == pytest.approx((100.0, 0.0), abs=1.0)


def test_quadratic_and_hv_commands():
    p = paths.from_svg("M0,0 H50 V50 Q100,50 100,0")
    assert p.length > 0
    assert p.point_at(0.0) == pytest.approx((0.0, 0.0), abs=0.5)


def test_closed_path_returns_to_start():
    p = paths.from_svg("M0,0 L100,0 L100,100 Z")
    assert p.point_at(1.0) == pytest.approx((0.0, 0.0), abs=1.0)


def test_locate_clamps_out_of_range_t():
    p = paths.from_svg("M0,0 L100,0")
    assert p.point_at(-1.0) == pytest.approx((0.0, 0.0), abs=0.5)
    assert p.point_at(2.0) == pytest.approx((100.0, 0.0), abs=0.5)


def test_css_compiles_offset_path_with_orient():
    p = paths.from_svg("M0,0 L100,0")
    css = p.to_css(class_name="mv-path", duration_sec=2.0, orient=True)
    assert "offset-path:path('M0,0 L100,0')" in css
    assert "offset-rotate:auto" in css
    assert "offset-distance:0%" in css and "offset-distance:100%" in css


def test_css_orient_off_locks_rotation():
    css = paths.from_svg("M0,0 L100,0").to_css(class_name="x", duration_sec=1, orient=False)
    assert "offset-rotate:0deg" in css


def test_remotion_tokens_sample_with_angles():
    tok = paths.from_svg("M0,0 L100,0").to_remotion_tokens(samples=8)
    assert tok["d"] == "M0,0 L100,0"
    assert len(tok["samples"]) == 9
    assert tok["samples"][0]["offset"] == 0.0
    assert tok["samples"][-1]["offset"] == 1.0
    assert all("angle" in s for s in tok["samples"])


def test_ffmpeg_overlay_expressions_reference_frame_counter():
    xe, ye = paths.from_svg("M0,0 L100,0").to_ffmpeg_overlay(frames=120, samples=4)
    assert "on/120" in xe
    assert isinstance(ye, str)
