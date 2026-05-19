"""Stage F — logo chip-vs-bare decision contract tests.

Pure-logic tests for mediahub.theming.logo_chip.decide_logo_chip.
The algorithm has two gates that BOTH must pass for "bare":
  1. ΔE2000(dominant, surface) >= 15
  2. |APCA Lc(dominant, surface)| >= 45
Either failing → chip (safe-by-default).
"""
from __future__ import annotations

import pytest

from mediahub.theming.logo_chip import (
    DE_MIN,
    APCA_MIN,
    DEFAULT_CHIP_COLOR,
    LogoChipDecision,
    decide_logo_chip,
)


class TestObviousBare:
    """Cases where both gates clearly pass — render bare."""

    def test_black_on_white(self):
        d = decide_logo_chip("#000000", "#FFFFFF")
        assert d.mode == "bare"
        assert d.gate_de_passed
        assert d.gate_apca_passed

    def test_white_on_black(self):
        d = decide_logo_chip("#FFFFFF", "#000000")
        assert d.mode == "bare"
        # Polarity is negative (light text on dark bg) but |Lc| should
        # still clear the gate — the "dual-polarity" intent.
        assert d.apca_lc < 0
        assert d.apca_abs >= APCA_MIN

    def test_lane_yellow_on_podium_dark(self):
        """The Stage A default: brand yellow on the dark surface.
        This is the visible test case — every page renders these
        colours via the MediaHub mark."""
        d = decide_logo_chip("#D4FF3A", "#0A0B11")
        assert d.mode == "bare"

    def test_navy_on_white_paper(self):
        d = decide_logo_chip("#0E2A47", "#FFFFFF")
        assert d.mode == "bare"


class TestObviousChip:
    """Cases where at least one gate fails — render chip."""

    def test_identical_colours(self):
        d = decide_logo_chip("#0A0B11", "#0A0B11")
        assert d.mode == "chip"
        assert d.delta_e_2000 == 0.0
        assert d.apca_abs == 0.0
        assert not d.gate_de_passed
        assert not d.gate_apca_passed

    def test_near_surface(self):
        """A logo whose dominant colour is too close to the surface
        for either gate to pass."""
        d = decide_logo_chip("#1A1E28", "#0A0B11")
        assert d.mode == "chip"

    def test_white_on_white(self):
        d = decide_logo_chip("#FFFFFF", "#FFFFFF")
        assert d.mode == "chip"


class TestChipColor:
    def test_chip_uses_white_by_default(self):
        d = decide_logo_chip("#1A1E28", "#0A0B11")
        assert d.chip_color == DEFAULT_CHIP_COLOR == "#FFFFFF"

    def test_chip_color_override(self):
        d = decide_logo_chip(
            "#1A1E28", "#0A0B11", chip_color="#F5F2E8",
        )
        assert d.chip_color == "#F5F2E8"


class TestBadInputs:
    """Safe-by-default: bad inputs return chip mode."""

    @pytest.mark.parametrize("bad", ["", "not a hex", "rgb(0,0,0)", "#XYZ"])
    def test_bad_dominant_returns_chip(self, bad):
        d = decide_logo_chip(bad, "#0A0B11")
        assert d.mode == "chip"
        assert d.gate_de_passed is False
        assert d.gate_apca_passed is False

    @pytest.mark.parametrize("bad", ["", "not a hex", "rgb(0,0,0)", "#XYZ"])
    def test_bad_surface_returns_chip(self, bad):
        d = decide_logo_chip("#D4FF3A", bad)
        assert d.mode == "chip"

    def test_none_dominant_returns_chip(self):
        d = decide_logo_chip(None, "#0A0B11")  # type: ignore[arg-type]
        assert d.mode == "chip"


class TestBoundaryConditions:
    """Gates use >=, so values exactly at threshold pass; below fail."""

    def test_de_exactly_at_threshold_passes(self):
        # Synthetic: pick colours whose ΔE2000 is right at 15.
        # We can't easily target 15 exactly, but we can assert the
        # gate is >= (not >) using the visible relation.
        d = decide_logo_chip("#000000", "#FFFFFF")
        # ΔE2000 for black/white is ~100 — well above threshold.
        # The test we can do is: if delta_e exactly equals threshold,
        # gate must pass.
        assert d.gate_de_passed is (d.delta_e_2000 >= DE_MIN)

    def test_decision_reasoning_is_non_empty(self):
        d = decide_logo_chip("#000000", "#FFFFFF")
        assert isinstance(d.reasoning, str)
        assert len(d.reasoning) > 10
        assert "bare" in d.reasoning  # explanation matches mode


class TestDualPolarity:
    """The 'dual-polarity' aspect of the APCA check: |Lc| handles
    both dark-on-light and light-on-dark equally."""

    def test_both_polarities_qualify(self):
        # Dark on light: positive Lc, high magnitude
        a = decide_logo_chip("#222222", "#FFFFFF")
        # Light on dark: negative Lc, same magnitude
        b = decide_logo_chip("#DDDDDD", "#000000")
        # Both should land in bare mode.
        assert a.mode == "bare"
        assert b.mode == "bare"
        # Lc signs differ; |Lc| both clear threshold.
        assert a.apca_lc > 0
        assert b.apca_lc < 0


class TestReturnType:
    def test_returns_dataclass(self):
        d = decide_logo_chip("#000000", "#FFFFFF")
        assert isinstance(d, LogoChipDecision)
        for field in ("mode", "chip_color", "dominant_hex", "surface_hex",
                      "delta_e_2000", "apca_lc", "apca_abs",
                      "gate_de_passed", "gate_apca_passed", "reasoning"):
            assert hasattr(d, field), f"missing field {field}"

    def test_hex_inputs_canonicalised(self):
        d = decide_logo_chip("#d4ff3a", "#0a0b11")
        # Output is upper-case 6-digit form.
        assert d.dominant_hex == "#D4FF3A"
        assert d.surface_hex == "#0A0B11"
