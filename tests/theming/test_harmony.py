"""Stage H — Cohen-Or harmonic-template fit contract tests."""
from __future__ import annotations

import pytest

from mediahub.theming.harmony import (
    HARMONIC_TEMPLATES,
    HarmonicFit,
    fit_harmonic_template,
    template_band_edges,
)


class TestTemplates:
    def test_seven_templates_defined(self):
        # Cohen-Or 2006 §3 names exactly seven templates.
        assert set(HARMONIC_TEMPLATES.keys()) == {
            "i", "V", "L", "I", "T", "Y", "X",
        }

    def test_template_band_shapes(self):
        # Each band is a (centre_offset, width) pair.
        for name, bands in HARMONIC_TEMPLATES.items():
            assert len(bands) in (1, 2), f"template {name} has odd band count"
            for centre, width in bands:
                assert 0.0 <= centre < 360.0
                assert 0.0 < width <= 360.0


class TestEmptyAndSingleton:
    def test_empty_returns_zero_energy(self):
        r = fit_harmonic_template([])
        assert r.energy == 0.0
        assert r.hue_count == 0
        assert r.template == "i"

    def test_single_hue_zero_energy(self):
        r = fit_harmonic_template([42.0])
        # A single hue can always fit a narrow band → energy 0.
        assert r.energy == 0.0
        assert r.hue_count == 1


class TestCanonicalFits:
    def test_three_identical_lands_in_narrow(self):
        r = fit_harmonic_template([60.0, 60.0, 60.0])
        # All identical → trivial fit with energy ~ 0.
        assert r.energy <= 1.0
        assert r.template in ("i", "V", "L", "I", "T", "Y", "X")

    def test_complementary_pair_lands_in_I_template(self):
        # 60° and 240° are exactly complementary → fit the I template
        # (two narrow bands 180° apart).
        r = fit_harmonic_template([60.0, 240.0])
        assert r.energy <= 1.0
        # The I template has bands at (0,18) and (180,18) — rotated
        # to centre on 60 and 240, both hues fit cleanly.
        assert r.template == "I"

    def test_evenly_spaced_quartet_doesnt_crash(self):
        # 0/90/180/270 — none of the templates fit cleanly; the
        # search should still return a valid HarmonicFit.
        r = fit_harmonic_template([0.0, 90.0, 180.0, 270.0])
        assert isinstance(r, HarmonicFit)
        assert r.template in HARMONIC_TEMPLATES
        assert r.hue_count == 4


class TestRotationStep:
    def test_step_respected(self):
        # A coarser step (90°) gives a coarser rotation result.
        r_fine = fit_harmonic_template([45.0], rotation_step=5.0)
        r_coarse = fit_harmonic_template([45.0], rotation_step=90.0)
        # Both should converge to a fit, but the coarse result's
        # rotation is a multiple of 90.
        assert r_coarse.rotation % 90.0 < 0.01

    def test_step_clamp_at_one(self):
        # A step of 0 or negative gets clamped to 1° — no infinite loops.
        r = fit_harmonic_template([0.0, 180.0], rotation_step=0.0)
        assert isinstance(r, HarmonicFit)


class TestBandEdges:
    def test_band_edges_at_zero_rotation(self):
        # The "i" template is one 18° band centred at 0°. At rotation
        # 0, edges should be at 351° and 9° (wrapped).
        edges = template_band_edges(HARMONIC_TEMPLATES["i"], rotation=0.0)
        assert len(edges) == 1
        low, high = edges[0]
        assert abs(low - 351.0) < 0.001 or abs(low - (-9.0) % 360.0) < 0.001
        assert abs(high - 9.0) < 0.001

    def test_band_edges_rotated(self):
        # Rotate the "i" template by 90° — band should sit at [81, 99].
        edges = template_band_edges(HARMONIC_TEMPLATES["i"], rotation=90.0)
        low, high = edges[0]
        assert abs(low - 81.0) < 0.001
        assert abs(high - 99.0) < 0.001


class TestReturnShape:
    def test_to_dict(self):
        r = fit_harmonic_template([0.0, 180.0])
        d = r.to_dict()
        for key in ("template", "rotation", "energy", "hue_count",
                    "template_bands"):
            assert key in d

    def test_lower_energy_is_better(self):
        # Two cases: cleanly complementary (low energy) vs awkward
        # spacing (higher energy). The cleanly complementary case
        # should score lower.
        clean = fit_harmonic_template([0.0, 180.0])
        awkward = fit_harmonic_template([0.0, 47.0, 95.0])
        assert clean.energy <= awkward.energy
