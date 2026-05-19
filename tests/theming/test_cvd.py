"""Tests for mediahub.theming.cvd."""
from __future__ import annotations

import pytest

from mediahub.theming.cvd import (
    simulate,
    delta_e_under_cvd,
    CVD_TYPES,
    DEUTAN_MATRIX,
    PROTAN_MATRIX,
    TRITAN_MATRIX,
)


class TestMatrices:
    def test_machado_matrices_are_3x3(self):
        for mat in (DEUTAN_MATRIX, PROTAN_MATRIX, TRITAN_MATRIX):
            assert mat.shape == (3, 3)

    def test_deutan_protan_differ(self):
        import numpy as np
        assert not np.array_equal(DEUTAN_MATRIX, PROTAN_MATRIX)

    def test_tritan_differs_from_red_green_pair(self):
        import numpy as np
        assert not np.array_equal(TRITAN_MATRIX, DEUTAN_MATRIX)
        assert not np.array_equal(TRITAN_MATRIX, PROTAN_MATRIX)


class TestSimulate:
    @pytest.mark.parametrize("cvd", CVD_TYPES)
    def test_white_simulates_to_white(self, cvd):
        sim = simulate("#FFFFFF", cvd)
        # Should remain near-white (Machado matrices roughly preserve
        # the equal-energy point).
        r, g, b = int(sim[1:3], 16), int(sim[3:5], 16), int(sim[5:7], 16)
        assert r > 240 and g > 240 and b > 240, f"{cvd}: white → {sim}"

    @pytest.mark.parametrize("cvd", CVD_TYPES)
    def test_black_simulates_to_black(self, cvd):
        sim = simulate("#000000", cvd)
        r, g, b = int(sim[1:3], 16), int(sim[3:5], 16), int(sim[5:7], 16)
        assert r < 15 and g < 15 and b < 15, f"{cvd}: black → {sim}"

    def test_red_under_deutan_shifts_toward_yellow_brown(self):
        """A pure red #FF0000 should NOT remain pure red under
        deuteranopia — it gets pulled toward yellow-brown."""
        sim = simulate("#FF0000", "deutan")
        # Red channel should drop; green channel should rise.
        sim_r = int(sim[1:3], 16)
        sim_g = int(sim[3:5], 16)
        assert sim_r < 255, f"deutan red should not stay pure red, got {sim}"
        assert sim_g > sim_r * 0.2, f"deutan red should pick up green, got {sim}"

    def test_invalid_cvd_raises(self):
        with pytest.raises(ValueError):
            simulate("#FF0000", "monochrome")   # not a valid CVD type


class TestDeltaEUnderCVD:
    def test_red_vs_green_under_deutan_close(self):
        # Red and green collapse under deutan — ΔE2000 should be SMALL.
        r = delta_e_under_cvd("#FF0000", "#00FF00", "deutan")
        # Surprise expectation: deutan-simulated red ≈ deutan-simulated green ≠ identical,
        # but ΔE is much smaller than under normal vision.
        assert r.delta_e_2000 < 30, (
            f"deutan(red) vs deutan(green) ΔE={r.delta_e_2000}, expected < 30"
        )

    def test_red_vs_blue_under_deutan_clearly_distinct(self):
        # Red ≠ Blue under any CVD (it's S-cone independent).
        r = delta_e_under_cvd("#FF0000", "#0000FF", "deutan")
        assert r.delta_e_2000 > 30
        assert r.distinguishable

    def test_yellow_vs_blue_under_tritan_collapses(self):
        # Tritanopia is the yellow-blue confusion axis.
        r = delta_e_under_cvd("#FFFF00", "#0000FF", "tritan")
        # ΔE between tritan-simulated yellow and tritan-simulated blue
        # is significantly reduced vs normal vision (which would be ≥ 90).
        assert r.delta_e_2000 < 90, (
            f"tritan(yellow) vs tritan(blue) ΔE={r.delta_e_2000}, expected < 90"
        )

    def test_threshold_flag(self):
        r = delta_e_under_cvd("#FF0000", "#00FF00", "deutan", threshold=5.0)
        assert (r.delta_e_2000 >= 5.0) == r.distinguishable
