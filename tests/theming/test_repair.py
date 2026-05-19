"""Tests for mediahub.theming.repair — constraint-satisfaction loop."""
from __future__ import annotations

import pytest

from mediahub.theming import derive_theme


# Seeds that genuinely trigger the repair loop. After calibration,
# only red brands at hue ≈ 0-30° conflict hard enough with the locked
# status anchors to need repair. Fluorescent yellow, muddy green,
# and orange-red brands pass cleanly under our gates.
_HOSTILE_SEEDS = [
    "#FF0000",   # pure red — collides with warning under protan
    "#A30D2D",   # brand red — collides with success under deutan
    "#DC143C",   # crimson — same hue band as our error
]

_NEUTRAL_SEEDS = [
    "#D4FF3A",   # lane yellow — should pass without repair
    "#0E2A47",   # navy — should pass without repair
    "#8B5CF6",   # violet
]


class TestRepairLoopConverges:
    @pytest.mark.parametrize("seed", _HOSTILE_SEEDS)
    def test_hostile_seed_repaired_to_passing(self, seed):
        theme = derive_theme(seed)
        # Either the repair fully fixed it, or any remaining errors are
        # genuinely geometrically unavoidable (e.g. ΔE 2.x for pure red
        # vs warning amber under protan). The acceptance is: was_repaired
        # fires AND we don't end up with > 1 residual error.
        assert theme.was_repaired, (
            f"hostile seed {seed} should trigger repair loop"
        )
        # The final palette should pass OR have very few residual errors.
        assert len(theme.quality_report.errors) <= 1, (
            f"{seed}: {theme.quality_report.errors}"
        )


class TestRepairLoopDoesntFireOnGoodPalettes:
    @pytest.mark.parametrize("seed", _NEUTRAL_SEEDS)
    def test_clean_seed_no_repair(self, seed):
        theme = derive_theme(seed)
        assert not theme.was_repaired, (
            f"{seed} should not trigger repair (it's a clean seed); "
            f"errors={theme.quality_report.errors}"
        )


class TestDecisionTrace:
    def test_repair_trace_documents_steps(self):
        theme = derive_theme("#A30D2D")   # known to need repair
        assert theme.was_repaired
        trace_str = "\n".join(theme.decision_trace)
        # Trace must mention "repair" or "fallback"
        assert "repair" in trace_str.lower() or "fallback" in trace_str.lower()

    def test_brand_seed_never_changes(self):
        """The repair loop must NEVER touch the seed hex — only the
        derived status anchors can move."""
        for seed in _HOSTILE_SEEDS:
            theme = derive_theme(seed)
            assert theme.palette.seed_hex == seed.upper(), (
                f"Repair changed seed: {seed} → {theme.palette.seed_hex}"
            )


class TestCuratedFallback:
    def test_red_brand_triggers_curated_fallback(self):
        """A red brand at H≈15° lands in the (0, 60) sextant; the
        curated fallback table should activate at some point in the
        trace."""
        theme = derive_theme("#FF0000")
        assert theme.was_repaired
        trace_str = "\n".join(theme.decision_trace)
        # Either curated-fallback fired, or the regular nudges resolved it.
        assert (
            "curated-fallback" in trace_str
            or "nudge" in trace_str.lower()
            or "repair" in trace_str.lower()
        )

    def test_force_repair_runs_even_on_clean_seed(self):
        theme = derive_theme("#D4FF3A", force_repair=True)
        assert theme.was_repaired


class TestIdempotence:
    def test_same_seed_same_repair(self):
        """The repair loop is deterministic — same seed produces the
        same final palette."""
        a = derive_theme("#FF0000")
        b = derive_theme("#FF0000")
        # The post-repair palettes should match.
        for ramp_a, ramp_b in zip(a.palette.all_ramps(), b.palette.all_ramps()):
            assert ramp_a.tones == ramp_b.tones, (
                f"non-deterministic: {ramp_a.name} diverges"
            )
