"""B3 (Tier B): the deterministic visual-regression backbone — pixel-diff a captured
surface against a committed baseline, emit a ``visual_regression`` finding above
tolerance, honest-skip when no baseline exists. No browser; images built in-memory.
"""
from __future__ import annotations

import pytest

from autotest import report, visual_regression

PIL = pytest.importorskip("PIL")   # Pillow is a runtime dep; skip cleanly if absent here
from PIL import Image  # noqa: E402


def _png(tmp_path, name, color, size=(80, 60)):
    p = tmp_path / name
    Image.new("RGB", size, color).save(p)
    return p


# --- diff_ratio --------------------------------------------------------------
def test_identical_images_zero_diff(tmp_path):
    a = _png(tmp_path, "a.png", (10, 20, 30))
    b = _png(tmp_path, "b.png", (10, 20, 30))
    assert visual_regression.diff_ratio(a, b) == 0.0


def test_fully_different_images_high_diff(tmp_path):
    a = _png(tmp_path, "a.png", (0, 0, 0))
    b = _png(tmp_path, "b.png", (255, 255, 255))
    assert visual_regression.diff_ratio(a, b) == 1.0


def test_size_mismatch_is_full_diff(tmp_path):
    a = _png(tmp_path, "a.png", (0, 0, 0), size=(80, 60))
    b = _png(tmp_path, "b.png", (0, 0, 0), size=(40, 60))
    assert visual_regression.diff_ratio(a, b) == 1.0


# --- check() lifecycle -------------------------------------------------------
def test_no_baseline_honest_skips(tmp_path, monkeypatch):
    monkeypatch.setattr(visual_regression, "BASELINE_DIR", tmp_path / "nope")
    shot = _png(tmp_path, "home.png", (10, 10, 10))
    out = visual_regression.check("home", str(shot), "chromium")
    assert len(out) == 1 and out[0].is_bug is False
    assert out[0].category == "visual_skipped"


def test_regression_emitted_above_tolerance(tmp_path, monkeypatch):
    monkeypatch.setattr(visual_regression, "BASELINE_DIR", tmp_path / "baseline")
    (tmp_path / "baseline" / "chromium").mkdir(parents=True)
    Image.new("RGB", (80, 60), (0, 0, 0)).save(tmp_path / "baseline" / "chromium" / "home.png")
    shot = _png(tmp_path, "home.png", (255, 255, 255))   # 100% changed
    monkeypatch.setenv("AUTOTEST_VISUAL", "1")
    out = visual_regression.check("home", str(shot), "chromium")
    assert len(out) == 1
    f = out[0]
    assert f.category == "visual_regression" and f.is_bug is True
    assert report.is_subjective(f.category) is False   # deterministic → opens immediately


def test_within_tolerance_no_finding(tmp_path, monkeypatch):
    monkeypatch.setattr(visual_regression, "BASELINE_DIR", tmp_path / "baseline")
    (tmp_path / "baseline" / "chromium").mkdir(parents=True)
    Image.new("RGB", (80, 60), (10, 10, 10)).save(tmp_path / "baseline" / "chromium" / "home.png")
    shot = _png(tmp_path, "home.png", (10, 10, 10))      # identical
    assert visual_regression.check("home", str(shot), "chromium") == []


def test_flag_off_disables(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOTEST_VISUAL", "0")
    shot = _png(tmp_path, "home.png", (10, 10, 10))
    assert visual_regression.check("home", str(shot), "chromium") == []


def test_missing_screenshot_no_finding(tmp_path):
    assert visual_regression.check("home", str(tmp_path / "ghost.png"), "chromium") == []
    assert visual_regression.check("home", None, "chromium") == []
