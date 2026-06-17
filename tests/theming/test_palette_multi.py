"""G1.20 — multi-colour palette + theme derivation.

Tests for ``derive_palette_multi`` (palette.py) and ``derive_theme_multi``
(__init__.py). The headline contract is **exact single-seed back-compat**:
with ≤ 1 brandable colour the multi path must reproduce the single-seed
engine bit-for-bit, so no existing club's theme drifts.
"""
from __future__ import annotations

import re

import pytest

from mediahub.theming import derive_theme, derive_theme_multi
from mediahub.theming.palette import (
    derive_palette,
    derive_palette_multi,
    TONE_STOPS,
    STATUS_ANCHORS,
)


_HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}")

# Seeds spanning identity / common / hostile, mirroring the palette suite.
_SEEDS = ["#D4FF3A", "#0E2A47", "#A30D2D", "#06D6A0", "#DFFF00", "#0C0C0C"]


def _ramps_equal(a, b) -> bool:
    return a.seed_hex == b.seed_hex and all(
        ra.name == rb.name and ra.tones == rb.tones
        for ra, rb in zip(a.all_ramps(), b.all_ramps())
    )


class TestSingleSeedBackCompat:
    """≤ 1 brandable colour → byte-identical to derive_palette."""

    @pytest.mark.parametrize("seed", _SEEDS)
    def test_one_colour_matches_single_seed(self, seed):
        assert _ramps_equal(derive_palette_multi([seed]), derive_palette(seed))

    @pytest.mark.parametrize("seed", _SEEDS)
    def test_non_brandable_extra_is_ignored(self, seed):
        # #000000 (default secondary) and grey are not brandable → no change.
        multi = derive_palette_multi([seed, "#000000", "#808080"])
        assert _ramps_equal(multi, derive_palette(seed))

    @pytest.mark.parametrize("seed", _SEEDS)
    def test_theme_multi_no_extras_matches_derive_theme(self, seed):
        t1 = derive_theme(seed).to_json()
        t2 = derive_theme_multi(seed, []).to_json()
        t1.pop("generated_at")
        t2.pop("generated_at")
        assert t1 == t2

    def test_theme_multi_non_brandable_extras_match_derive_theme(self):
        t1 = derive_theme("#A30D2D").to_json()
        t2 = derive_theme_multi("#A30D2D", ["#000000", None, ""]).to_json()
        t1.pop("generated_at")
        t2.pop("generated_at")
        assert t1 == t2


class TestMultiColourExpansion:
    def test_secondary_ramp_uses_real_colour_hue(self):
        """Gold secondary should carry gold's hue (~91°), not the navy-derived
        secondary hue (~256°)."""
        p = derive_palette_multi(["#0E2A47", "#C9A227"])
        assert 80 <= p.secondary.hue <= 100, p.secondary.hue

    def test_tertiary_ramp_uses_real_colour_hue(self):
        p = derive_palette_multi(["#0E2A47", "#C9A227", "#A30D2D"])
        # crimson hue ~16°
        assert 0 <= p.tertiary.hue <= 30 or 350 <= p.tertiary.hue <= 360, p.tertiary.hue

    def test_secondary_keeps_full_chroma_not_md3_muted(self):
        """The club's real gold (chroma ~49) is far more saturated than the
        MD3-derived muted secondary (~16)."""
        p = derive_palette_multi(["#0E2A47", "#C9A227"])
        assert p.secondary.chroma > 30

    def test_primary_ramp_unchanged_from_single_seed(self):
        """Primary always comes from the MD3 scheme, so it equals the
        single-seed primary ramp exactly."""
        multi = derive_palette_multi(["#0E2A47", "#C9A227", "#A30D2D"])
        single = derive_palette("#0E2A47")
        assert multi.primary.tones == single.primary.tones

    def test_neutral_ramps_unchanged_from_single_seed(self):
        multi = derive_palette_multi(["#0E2A47", "#C9A227"])
        single = derive_palette("#0E2A47")
        assert multi.neutral.tones == single.neutral.tones
        assert multi.neutral_variant.tones == single.neutral_variant.tones

    def test_seed_hex_is_the_primary(self):
        p = derive_palette_multi(["#0E2A47", "#C9A227"])
        assert p.seed_hex == "#0E2A47"

    @pytest.mark.parametrize("bad", [[], ["garbage"], ["", None, "xyz"], ["#zzz"]])
    def test_garbage_input_never_raises_and_falls_back(self, bad):
        """No parseable hex → safe fallback to the generic-default navy,
        byte-identical to derive_palette('#0E2A47')."""
        p = derive_palette_multi(bad)
        assert _ramps_equal(p, derive_palette("#0E2A47"))

    def test_decision_trace_records_expansion(self):
        p = derive_palette_multi(["#0E2A47", "#C9A227"])
        joined = "\n".join(p.decision_trace)
        assert "multi-colour expansion" in joined
        assert "#C9A227" in joined


class TestStructuralInvariants:
    @pytest.mark.parametrize(
        "colours",
        [
            ["#0E2A47", "#C9A227"],
            ["#0E2A47", "#C9A227", "#A30D2D"],
            ["#D4FF3A", "#A30D2D", "#06D6A0"],
        ],
    )
    def test_nine_ramps_thirteen_valid_tones(self, colours):
        p = derive_palette_multi(colours)
        names = {r.name for r in p.all_ramps()}
        assert names == {
            "primary", "secondary", "tertiary", "neutral", "neutral_variant",
            "error", "success", "warning", "info",
        }
        for ramp in p.all_ramps():
            assert set(ramp.tones.keys()) == set(TONE_STOPS)
            for hex_str in ramp.tones.values():
                assert _HEX_RE.fullmatch(hex_str), hex_str

    def test_status_anchors_stay_locked_in_multi(self):
        """Brand expansion must never move the locked status hues."""
        p = derive_palette_multi(["#0E2A47", "#C9A227", "#A30D2D"])
        assert p.error.hue == STATUS_ANCHORS["error"][0]
        assert p.success.hue == STATUS_ANCHORS["success"][0]
        assert p.warning.hue == STATUS_ANCHORS["warning"][0]
        assert p.info.hue == STATUS_ANCHORS["info"][0]


class TestDeriveThemeMulti:
    def test_returns_full_theme_shape(self):
        t = derive_theme_multi("#0E2A47", ["#C9A227", "#A30D2D"])
        j = t.to_json()
        for key in ("schema_version", "seed_hex", "palettes", "roles",
                    "quality", "decision_trace", "was_repaired"):
            assert key in j
        assert set(j["roles"].keys()) == {"light", "dark"}

    def test_seed_source_reflects_primary_hex(self):
        t = derive_theme_multi("#0E2A47", ["#C9A227"])
        assert t.seed_result.source_kind == "hex"
        assert t.to_json()["seed_hex"] == "#0E2A47"

    def test_assignment_trace_threaded_into_decision_trace(self):
        t = derive_theme_multi("#0E2A47", ["#C9A227"])
        joined = "\n".join(t.decision_trace)
        assert "multi-colour expansion" in joined

    @pytest.mark.parametrize(
        "primary,extras",
        [
            ("#0E2A47", ["#C9A227", "#A30D2D"]),
            ("#A30D2D", ["#C9A227"]),
            ("#D4FF3A", ["#0E2A47", "#A30D2D"]),
        ],
    )
    def test_audit_runs_and_palette_is_valid(self, primary, extras):
        """The materialised multi-colour palette flows through the standard
        audit + repair pipeline and ends in a consistent (passed-or-repaired)
        state."""
        t = derive_theme_multi(primary, extras)
        # audit always produces a report; if it didn't pass, repair must have
        # fired (was_repaired) and produced a final report object.
        assert t.quality_report is not None
        assert t.quality_report.passed or t.was_repaired

    def test_deterministic(self):
        a = derive_theme_multi("#0E2A47", ["#C9A227", "#A30D2D"]).to_json()
        b = derive_theme_multi("#0E2A47", ["#C9A227", "#A30D2D"]).to_json()
        a.pop("generated_at")
        b.pop("generated_at")
        assert a == b
