"""Tests for export_engine.options — the export option schema (roadmap 1.19)."""

from __future__ import annotations

import pytest

from mediahub.export_engine.options import (
    QUALITY_MAX,
    QUALITY_MIN,
    SCALE_MAX,
    SCALE_MIN,
    ExportOptions,
    render_quality_profile,
)


class TestClamping:
    def test_defaults_are_sane(self):
        o = ExportOptions().clamped()
        assert o.quality == 90
        assert o.scale == 1.0
        assert o.transparent is False
        assert o.colour_profile == "screen"
        assert o.background == "#ffffff"

    @pytest.mark.parametrize(
        "raw,expected",
        [(999, QUALITY_MAX), (-5, QUALITY_MIN), (0, QUALITY_MIN), (55, 55), ("70", 70)],
    )
    def test_quality_clamped(self, raw, expected):
        assert ExportOptions(quality=raw).clamped().quality == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [(99.0, SCALE_MAX), (0.0, SCALE_MIN), (-1.0, SCALE_MIN), (2.0, 2.0)],
    )
    def test_scale_clamped(self, raw, expected):
        assert ExportOptions(scale=raw).clamped().scale == expected

    def test_bad_numbers_fall_back_to_default(self):
        o = ExportOptions(quality="oops", scale="nope").clamped()
        assert o.quality == 90 and o.scale == 1.0

    def test_nan_scale_falls_back(self):
        assert ExportOptions(scale=float("nan")).clamped().scale == 1.0

    def test_unknown_colour_profile_becomes_screen(self):
        assert ExportOptions(colour_profile="cmyk-ish").clamped().colour_profile == "screen"
        assert ExportOptions(colour_profile="PRINT").clamped().colour_profile == "print"

    @pytest.mark.parametrize(
        "raw,expected",
        [("#abcdef", "#abcdef"), ("abcdef", "#abcdef"), ("nope", "#ffffff"), ("#fff", "#ffffff")],
    )
    def test_background_hex_normalised(self, raw, expected):
        assert ExportOptions(background=raw).clamped().background == expected


class TestAccessors:
    def test_quality_fraction(self):
        assert ExportOptions(quality=50).quality_fraction() == 0.5

    def test_is_print(self):
        assert ExportOptions(colour_profile="print").is_print
        assert not ExportOptions().is_print

    def test_scaled_size(self):
        assert ExportOptions(scale=2.0).scaled_size((1080, 1350)) == (2160, 2700)
        assert ExportOptions(scale=0.5).scaled_size((1080, 1080)) == (540, 540)

    def test_scaled_size_floors_at_one_pixel(self):
        assert ExportOptions(scale=0.1).scaled_size((1, 1)) == (1, 1)


class TestSerialisation:
    def test_round_trip(self):
        o = ExportOptions(quality=42, scale=1.5, transparent=True, colour_profile="print")
        again = ExportOptions.from_dict(o.to_dict())
        assert again == o.clamped()

    def test_from_dict_tolerates_none_and_partial(self):
        assert ExportOptions.from_dict(None) == ExportOptions().clamped()
        assert ExportOptions.from_dict({"quality": 30}).quality == 30

    def test_cache_token_is_stable_and_reflects_changes(self):
        a = ExportOptions(quality=80, scale=1.0).cache_token()
        b = ExportOptions(quality=80, scale=1.0).cache_token()
        c = ExportOptions(quality=81, scale=1.0).cache_token()
        assert a == b
        assert a != c

    def test_cache_token_distinguishes_transparency(self):
        opaque = ExportOptions(transparent=False).cache_token()
        clear = ExportOptions(transparent=True).cache_token()
        assert opaque != clear


class TestQualityProfileMapping:
    def test_scale_one_keeps_standard(self):
        # The historic default must not move — keeps existing renders byte-stable.
        assert render_quality_profile(1.0) == "standard"

    def test_small_scale_is_fast(self):
        assert render_quality_profile(0.5) == "fast"

    def test_large_scale_is_high(self):
        assert render_quality_profile(2.0) == "high"

    def test_clamped_input(self):
        assert render_quality_profile(99) == "high"
        assert render_quality_profile(-3) == "fast"
