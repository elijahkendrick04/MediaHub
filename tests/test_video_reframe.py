"""Tests for video.reframe — the pure parts of saliency reframe (roadmap 1.6).

Frame extraction + saliency need FFmpeg/images; the sampling, smoothing and
ratio maths are pure and tested here.
"""

from __future__ import annotations

from mediahub.video.reframe import (
    frame_extract_args,
    needs_reframe,
    sample_positions,
    smooth_crops,
    target_ratio,
)


def test_sample_positions_even_spacing():
    pos = sample_positions(12000, 3)
    assert pos == [3000, 6000, 9000]


def test_sample_positions_single_midpoint():
    assert sample_positions(10000, 1) == [5000]


def test_sample_positions_zero_clip():
    assert sample_positions(0, 3) == []
    assert sample_positions(12000, 0) == []


def test_smooth_crops_takes_per_axis_median():
    crops = [(0, 0, 100, 200), (10, 10, 100, 200), (5, 5, 100, 200)]
    assert smooth_crops(crops) == (5, 5, 100, 200)


def test_smooth_crops_robust_to_outlier():
    crops = [(0, 0, 100, 200), (2, 2, 100, 200), (500, 500, 100, 200)]
    # The outlier (500) does not drag the median.
    assert smooth_crops(crops) == (2, 2, 100, 200)


def test_smooth_crops_empty_is_none():
    assert smooth_crops([]) is None


def test_needs_reframe_true_for_landscape_to_portrait():
    assert needs_reframe(1920, 1080, 1080, 1920) is True


def test_needs_reframe_false_for_matching_ratio():
    assert needs_reframe(1080, 1920, 1080, 1920) is False
    # A 720p source to a 1080p story canvas is the same 9:16 → no crop needed.
    assert needs_reframe(720, 1280, 1080, 1920) is False


def test_needs_reframe_false_for_zero_dims():
    assert needs_reframe(0, 0, 1080, 1920) is False


def test_target_ratio():
    assert abs(target_ratio(1920, 1080) - (16 / 9)) < 1e-6
    assert target_ratio(0, 0) == 1.0


def test_frame_extract_args_is_pure_builder():
    args = frame_extract_args("clip.mp4", 3500, "/tmp/f.png")
    j = " ".join(args)
    assert "-ss" in args and "3.500" in j
    assert "clip.mp4" in j and "/tmp/f.png" in j
    assert "-frames:v" in args
