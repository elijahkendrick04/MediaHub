"""Stage H — on-disk theme JSON carries quality_detail + harmonic_fit.

After BrandKit.ensure_derived_palette() runs, the cached file at
DATA_DIR/themes/<pid>.json should carry the new Stage H keys
alongside the existing Stage G shape.
"""
from __future__ import annotations

import json

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.theming.theme_store import read_theme, theme_path


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.theming.theme_store import _read_cached
    _read_cached.cache_clear()
    return tmp_path


def _seed_theme(pid, primary):
    kit = BrandKit(profile_id=pid, display_name=f"Test {pid}",
                   primary_colour=primary)
    return kit.ensure_derived_palette()


class TestNewKeysOnDisk:
    def test_quality_detail_present(self, isolated_data_dir):
        _seed_theme("h-disk-1", "#0E2A47")
        on_disk = read_theme("h-disk-1")
        assert "quality_detail" in on_disk
        qd = on_disk["quality_detail"]
        assert isinstance(qd, dict)
        assert "contrast" in qd
        assert len(qd["contrast"]) > 0

    def test_harmonic_fit_present(self, isolated_data_dir):
        _seed_theme("h-disk-2", "#0E2A47")
        on_disk = read_theme("h-disk-2")
        hf = on_disk.get("harmonic_fit")
        assert hf is not None
        assert "template" in hf
        assert "energy" in hf
        assert hf["energy"] >= 0.0

    def test_summary_still_present(self, isolated_data_dir):
        _seed_theme("h-disk-3", "#0E2A47")
        on_disk = read_theme("h-disk-3")
        # Stage G's summary form lives alongside the new detail form.
        assert "quality" in on_disk
        assert "n_contrast_checks" in on_disk["quality"]


class TestSchemaVersion:
    def test_schema_version_unchanged(self, isolated_data_dir):
        _seed_theme("h-disk-4", "#0E2A47")
        on_disk = read_theme("h-disk-4")
        # Additive change → schema_version stays "1".
        assert on_disk["schema_version"] == "1"


class TestDiskRoundTrip:
    def test_json_round_trip(self, isolated_data_dir):
        _seed_theme("h-disk-5", "#A30D2D")
        path = theme_path("h-disk-5")
        # Re-read raw JSON from disk and confirm structure.
        raw = json.loads(path.read_text())
        assert "quality_detail" in raw
        assert "harmonic_fit" in raw
        # The contrast detail should be present and non-trivial.
        assert len(raw["quality_detail"]["contrast"]) >= 12
        assert len(raw["quality_detail"]["cvd"]) >= 12
