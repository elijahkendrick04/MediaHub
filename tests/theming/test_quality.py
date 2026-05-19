"""Tests for mediahub.theming.quality."""
from __future__ import annotations

import pytest

from mediahub.theming.palette import derive_palette
from mediahub.theming.roles import derive_roles
from mediahub.theming.quality import (
    audit_palette,
    PaletteQualityReport,
    APCA_BODY_FLOOR,
    APCA_UI_FLOOR,
    WCAG2_AA_FLOOR,
    ADJACENT_DELTA_E_FLOOR,
    STATUS_DELTA_E_HARD,
    CVD_DELTA_E_HARD,
    CVD_DELTA_E_FLOOR,
)


_CALIBRATION_SEEDS = [
    "#D4FF3A", "#0E2A47", "#A30D2D", "#06D6A0",
    "#8B5CF6", "#FFD700", "#F472B6", "#00FFFF",
]


class TestReportShape:
    def test_report_carries_full_detail(self):
        palette = derive_palette("#D4FF3A")
        report = audit_palette(palette, derive_roles(palette))
        assert isinstance(report, PaletteQualityReport)
        assert report.contrast       # text + UI pairs, ≥ 10
        assert report.adjacency      # one per (palette × adjacent-tone-pair)
        assert report.status_distance # one per (seed × {error,success,warning,info})
        assert report.cvd            # 3 CVD × 4 status pairs = 12
        # passed = no errors
        assert report.passed == (not report.errors)

    def test_summary_dict_serialises(self):
        palette = derive_palette("#D4FF3A")
        report = audit_palette(palette, derive_roles(palette))
        summary = report.to_summary()
        for key in ("passed", "n_contrast_checks", "n_contrast_failures",
                    "n_adjacency_checks", "n_status_distance_checks",
                    "n_cvd_checks", "warnings", "errors"):
            assert key in summary


class TestCalibration:
    """The thresholds must be tuned so the bulk of representative seeds
    PASS without repair — if every palette fails, the gates are
    miscalibrated, not the seeds. We expect most "ordinary" seeds to
    pass; hostile seeds may need repair but converge."""

    @pytest.mark.parametrize("seed", _CALIBRATION_SEEDS)
    def test_calibration_seed_does_not_explode(self, seed):
        palette = derive_palette(seed)
        report = audit_palette(palette, derive_roles(palette))
        # Errors must be a list (never None / garbage).
        assert isinstance(report.errors, list)
        assert isinstance(report.warnings, list)
        # No unhandled exceptions.

    def test_lane_yellow_passes_clean(self):
        """The existing 'Podium After Dark' lane yellow MUST pass
        the gates without repair — it's the calibration anchor."""
        palette = derive_palette("#D4FF3A")
        report = audit_palette(palette, derive_roles(palette))
        assert report.passed, f"lane yellow fails: {report.errors}"

    def test_navy_passes_clean(self):
        """Generic default navy is the unconfigured-deployment fallback —
        it must also pass without repair."""
        palette = derive_palette("#0E2A47")
        report = audit_palette(palette, derive_roles(palette))
        assert report.passed, f"navy fails: {report.errors}"


class TestThresholds:
    """The thresholds themselves must be sane values."""

    def test_apca_floors_within_published_range(self):
        # APCA Lc scale is roughly -108 to +106. Body text floor should
        # sit between Bronze (60) and Silver (75).
        assert 50.0 <= APCA_BODY_FLOOR <= 90.0
        assert 20.0 <= APCA_UI_FLOOR <= 60.0

    def test_wcag2_aa_floor_is_4_5(self):
        # WCAG 2.x AA body-text floor is exactly 4.5:1 by spec.
        assert WCAG2_AA_FLOOR == 4.5

    def test_cvd_thresholds_ordered(self):
        # Hard floor < soft floor.
        assert CVD_DELTA_E_HARD < CVD_DELTA_E_FLOOR

    def test_status_distance_thresholds_ordered(self):
        from mediahub.theming.quality import STATUS_DELTA_E_HARD, STATUS_DELTA_E_SOFT
        assert STATUS_DELTA_E_HARD < STATUS_DELTA_E_SOFT


class TestEachGateFires:
    """Synthetic failure cases — by mutating a palette directly, each
    gate should report exactly the failure we induce."""

    def test_contrast_failure_when_on_primary_too_close(self):
        from dataclasses import replace
        palette = derive_palette("#D4FF3A")
        roles = derive_roles(palette)
        # Force on_primary to be near-identical to primary in light mode.
        bad_roles = replace(
            roles,
            light=replace(roles.light, on_primary=roles.light.primary),
        )
        report = audit_palette(palette, bad_roles)
        # APCA Lc between identical colours is 0 → contrast error.
        assert any("primary/on_primary" in e for e in report.errors)

    def test_status_distance_failure_when_seed_equals_error(self):
        """If the seed IS our error red, distance check fails."""
        palette = derive_palette("#BA1A1A")   # very close to error tone 40
        roles = derive_roles(palette)
        report = audit_palette(palette, roles)
        # Either status_distance or CVD will catch it.
        assert any(
            s.status_name == "error" and not s.passes_hard
            for s in report.status_distance
        ) or any(
            "error" in e for e in report.errors
        )
