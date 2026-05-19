"""Stage H — PaletteQualityReport.to_detail() contract tests."""
from __future__ import annotations

import json

import pytest

from mediahub.theming.palette import derive_palette
from mediahub.theming.roles import derive_roles
from mediahub.theming.quality import audit_palette


@pytest.fixture
def report():
    p = derive_palette("#0E2A47")
    return audit_palette(p, derive_roles(p))


class TestToDetailShape:
    def test_keys_present(self, report):
        d = report.to_detail()
        for k in ("passed", "harmonic_fit", "contrast", "adjacency",
                  "status_distance", "cvd", "warnings", "errors"):
            assert k in d, f"missing key {k!r}"

    def test_contrast_rows_carry_per_check_data(self, report):
        rows = report.to_detail()["contrast"]
        assert len(rows) > 0
        first = rows[0]
        for k in ("scheme", "role_pair", "foreground", "background",
                  "apca_lc", "wcag2_ratio", "passes_apca"):
            assert k in first, f"contrast row missing {k!r}"

    def test_adjacency_rows_carry_per_check_data(self, report):
        rows = report.to_detail()["adjacency"]
        assert len(rows) > 0
        first = rows[0]
        for k in ("palette", "tone_a", "tone_b", "hex_a", "hex_b",
                  "delta_e_2000", "distinguishable"):
            assert k in first, f"adjacency row missing {k!r}"

    def test_status_distance_rows_carry_per_check_data(self, report):
        rows = report.to_detail()["status_distance"]
        assert len(rows) >= 4   # error, success, warning, info
        first = rows[0]
        for k in ("seed_hex", "status_name", "status_hex",
                  "delta_e_2000", "passes_hard"):
            assert k in first

    def test_cvd_rows_carry_per_check_data(self, report):
        rows = report.to_detail()["cvd"]
        assert len(rows) >= 12   # 3 cvd types × 4 pairs
        first = rows[0]
        for k in ("cvd", "pair", "a_hex", "b_hex",
                  "delta_e_2000", "distinguishable"):
            assert k in first


class TestHarmonicFitIncluded:
    def test_harmonic_fit_populated(self, report):
        d = report.to_detail()
        hf = d.get("harmonic_fit")
        assert hf is not None
        for k in ("template", "rotation", "energy", "hue_count"):
            assert k in hf


class TestJSONRoundTrip:
    def test_detail_is_json_serialisable(self, report):
        d = report.to_detail()
        # Round-trip — JSON dump + load should not lose data.
        s = json.dumps(d)
        d2 = json.loads(s)
        assert d2["passed"] == d["passed"]
        assert len(d2["contrast"]) == len(d["contrast"])
        assert len(d2["cvd"]) == len(d["cvd"])


class TestSummaryStillExists:
    def test_to_summary_unchanged(self, report):
        # Stage G consumers depend on to_summary() — must still work.
        s = report.to_summary()
        for k in ("passed", "n_contrast_checks", "n_contrast_failures",
                  "n_adjacency_checks", "n_status_distance_checks",
                  "n_cvd_checks", "warnings", "errors"):
            assert k in s
