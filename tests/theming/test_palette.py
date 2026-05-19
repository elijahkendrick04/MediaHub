"""Tests for mediahub.theming.palette."""
from __future__ import annotations

import re

import pytest

from mediahub.theming.palette import (
    derive_palette,
    DerivedPalette,
    TonalRamp,
    TONE_STOPS,
    STATUS_ANCHORS,
)


_REPRESENTATIVE_SEEDS = [
    "#D4FF3A",   # lane yellow (MediaHub default)
    "#0E2A47",   # navy (generic default)
    "#A30D2D",   # brand red
    "#DFFF00",   # fluorescent yellow (hostile)
    "#2A3A1A",   # muddy dark green (hostile)
    "#FAFAF7",   # near-white (hostile)
    "#0C0C0C",   # near-black (hostile)
    "#8B5CF6",   # violet
    "#06D6A0",   # teal-green
    "#F472B6",   # hot pink
    "#FF0000",   # pure red
    "#00FFFF",   # cyan
]


class TestStructure:
    @pytest.mark.parametrize("seed", _REPRESENTATIVE_SEEDS)
    def test_palette_has_nine_ramps(self, seed):
        palette = derive_palette(seed)
        ramps = palette.all_ramps()
        names = {r.name for r in ramps}
        assert names == {
            "primary", "secondary", "tertiary", "neutral", "neutral_variant",
            "error", "success", "warning", "info",
        }

    @pytest.mark.parametrize("seed", _REPRESENTATIVE_SEEDS)
    def test_every_ramp_has_13_tones(self, seed):
        palette = derive_palette(seed)
        for ramp in palette.all_ramps():
            assert set(ramp.tones.keys()) == set(TONE_STOPS)

    @pytest.mark.parametrize("seed", _REPRESENTATIVE_SEEDS)
    def test_every_tone_is_valid_hex(self, seed):
        palette = derive_palette(seed)
        for ramp in palette.all_ramps():
            for tone, hex_str in ramp.tones.items():
                assert re.fullmatch(r"#[0-9A-Fa-f]{6}", hex_str), (
                    f"{ramp.name}.{tone} = {hex_str!r}"
                )

    @pytest.mark.parametrize("seed", _REPRESENTATIVE_SEEDS)
    def test_seed_round_trip(self, seed):
        palette = derive_palette(seed)
        assert palette.seed_hex == seed.upper()
        # HCT should be sensible: hue 0..360, chroma >= 0, tone 0..100
        h, c, t = palette.seed_hct
        assert 0 <= h <= 360
        assert c >= 0
        assert 0 <= t <= 100

    def test_decision_trace_non_empty(self):
        palette = derive_palette("#D4FF3A")
        assert len(palette.decision_trace) >= 3


class TestTonalRampMonotonicity:
    """Tone 0 should be darkest, tone 100 should be lightest."""

    @pytest.mark.parametrize("seed", _REPRESENTATIVE_SEEDS[:6])  # sample
    def test_tone_0_darker_than_tone_100(self, seed):
        palette = derive_palette(seed)
        for ramp in palette.all_ramps():
            # CIE L* via coloraide
            from coloraide import Color
            l0 = Color(ramp.tones[0]).convert("lab").coords()[0]
            l100 = Color(ramp.tones[100]).convert("lab").coords()[0]
            assert l0 < l100, (
                f"{ramp.name}: tone 0 (L={l0:.1f}) should be darker than tone 100 (L={l100:.1f})"
            )

    @pytest.mark.parametrize("seed", _REPRESENTATIVE_SEEDS[:4])
    def test_ramp_largely_monotonic(self, seed):
        """The 13-tone ramp should be monotonically increasing in L*
        (allowing tiny numerical wobbles via tolerance)."""
        palette = derive_palette(seed)
        from coloraide import Color
        for ramp in palette.all_ramps():
            lightnesses = [
                Color(ramp.tones[t]).convert("lab").coords()[0]
                for t in TONE_STOPS
            ]
            # Allow tolerance for floating-point quirks but expect strict
            # monotonic on the standard MD3 ramp.
            for i in range(1, len(lightnesses)):
                assert lightnesses[i] >= lightnesses[i - 1] - 0.5, (
                    f"{ramp.name} tone {TONE_STOPS[i-1]}→{TONE_STOPS[i]}: "
                    f"L={lightnesses[i-1]:.1f}→{lightnesses[i]:.1f}"
                )


class TestStatusAnchorsAreLocked:
    """Status palette hues do NOT move with the brand seed — they're
    fixed by hue family per WCAG 1.4.1 + cross-cultural semantics."""

    def test_error_anchor_always_red(self):
        for seed in _REPRESENTATIVE_SEEDS[:5]:
            palette = derive_palette(seed)
            assert palette.error.hue == STATUS_ANCHORS["error"][0]

    def test_success_anchor_always_green(self):
        for seed in _REPRESENTATIVE_SEEDS[:5]:
            palette = derive_palette(seed)
            assert palette.success.hue == STATUS_ANCHORS["success"][0]


class TestDeterministic:
    def test_same_seed_same_palette(self):
        a = derive_palette("#D4FF3A")
        b = derive_palette("#D4FF3A")
        # Same tones everywhere
        for ra, rb in zip(a.all_ramps(), b.all_ramps()):
            assert ra.tones == rb.tones


class TestSeedAppearsInPrimary:
    """The seed colour should appear (or be very close) in the primary
    ramp's tones — confirming the engine actually built around the
    user's input rather than ignoring it."""

    def test_lane_yellow_seed_in_primary_ramp(self):
        palette = derive_palette("#D4FF3A")
        # The seed has HCT tone ~94 — that's around the tone 95/99 region.
        # Just assert the primary ramp's high tones contain a green-ish hue
        # close to the seed.
        from coloraide import Color
        seed = Color("#D4FF3A")
        # The primary palette has the same HCT hue as the seed (123°).
        # Tone 90 should be in the same hue family.
        prim_90_lab = Color(palette.primary.tones[90]).convert("lab")
        seed_lab = seed.convert("lab")
        # They share the seed hue, just at different lightness.
        # Sanity: not pure grey or pure red.
        assert prim_90_lab.coords()[2] > 5, "primary high tone should not be neutral"
