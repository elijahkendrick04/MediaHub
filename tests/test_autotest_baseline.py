"""FIND hardening (council baseline-diff): catch silent primary-flow regressions
on a fixed golden input. Committed/human-blessed baseline (never auto-advanced),
infra-failure guard, never false-fire."""
from __future__ import annotations

import json

import pytest

from autotest import baseline


@pytest.fixture
def base_file(tmp_path, monkeypatch):
    p = tmp_path / "golden-baseline.json"
    monkeypatch.setattr(baseline, "BASELINE_PATH", p)
    return p


def _seed(p, **vals):
    p.write_text(json.dumps(vals))


def _check(metrics, completed=True, golden=True):
    return baseline.check(metrics, completed=completed, golden=golden)


def test_big_drop_is_high_regression(base_file):
    _seed(base_file, cards=12, achievements=8, export_ok=True)
    f = _check({"cards": 3, "achievements": 8, "export_ok": True})  # 12->3 >40% drop
    assert f is not None and f.severity == "high" and f.category == "baseline:regression"


def test_below_absolute_floor_is_regression(base_file):
    _seed(base_file, cards=2, achievements=2, export_ok=True)
    assert _check({"cards": 0, "achievements": 2, "export_ok": True}) is not None


def test_export_break_is_regression(base_file):
    _seed(base_file, cards=10, achievements=5, export_ok=True)
    f = _check({"cards": 10, "achievements": 5, "export_ok": False})
    assert f is not None and "export_ok" in f.actual


def test_small_dip_is_noise(base_file):
    _seed(base_file, cards=12, achievements=8, export_ok=True)
    assert _check({"cards": 11, "achievements": 8, "export_ok": True}) is None


def test_improvement_emits_low_drift_note_not_bug(base_file):
    _seed(base_file, cards=2, achievements=2, export_ok=True)
    f = _check({"cards": 12, "achievements": 8, "export_ok": True})  # well above 2*1.5
    assert f is not None and f.category == "baseline:drift" and f.severity == "low"
    assert f.is_bug is False


def test_never_writes_the_baseline(base_file):
    _seed(base_file, cards=12, achievements=8, export_ok=True)
    before = base_file.read_text()
    _check({"cards": 30, "achievements": 20, "export_ok": True})   # improvement
    _check({"cards": 1, "achievements": 1, "export_ok": True})     # regression
    assert base_file.read_text() == before, "baseline is human-blessed; never auto-written"


def test_incomplete_run_is_infra_skip(base_file):
    _seed(base_file, cards=12, achievements=8, export_ok=True)
    # A crashed/timed-out golden run reports completed=False -> must NOT alarm.
    assert _check({"cards": 0, "achievements": 0, "export_ok": False}, completed=False) is None


def test_non_golden_skips(base_file):
    _seed(base_file, cards=12, achievements=8, export_ok=True)
    assert _check({"cards": 0}, golden=False) is None


def test_no_baseline_file_skips(base_file):
    # bootstrap: before a baseline is committed, never fire
    assert _check({"cards": 0, "achievements": 0, "export_ok": False}) is None


def test_missing_metrics_never_fires(base_file):
    _seed(base_file, cards=12, achievements=8, export_ok=True)
    assert _check(None) is None
    assert _check({}) is None
