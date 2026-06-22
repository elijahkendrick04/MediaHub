"""Tests for export_engine.bulk — bulk export jobs (roadmap 1.19).

Driven with card PNGs and image target formats, so the whole job runs without
FFmpeg/Chromium. The honest-error path (a still asked for as a video) is
exercised directly.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from mediahub.export_engine.bulk import (
    BulkExportSpec,
    BulkItem,
    run_bulk_export,
)
from mediahub.export_engine.engine import ExportError
from mediahub.export_engine.options import ExportOptions


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    yield


def _items(tmp_path: Path, names) -> list[BulkItem]:
    items = []
    for i, nm in enumerate(names):
        p = tmp_path / f"card{i}.png"
        Image.new("RGBA", (120, 150), (10, 80, 200, 255)).save(p)
        items.append(BulkItem(name=nm, source=p, caption=f"Caption {i}"))
    return items


def _manifest(zip_path: Path) -> dict:
    with zipfile.ZipFile(zip_path) as zf:
        name = next(n for n in zf.namelist() if n.endswith("manifest.json"))
        return json.loads(zf.read(name))


class TestRunBulkExport:
    def test_builds_zip_with_all_files(self, tmp_path):
        spec = BulkExportSpec(
            items=_items(tmp_path, ["Eira 200 Free", "Tom 50 Fly"]),
            formats=["jpg", "webp"],
            label="Manchester Open",
        )
        res = run_bulk_export(spec)
        assert res.item_count == 2
        assert res.file_count == 4  # 2 items × 2 formats
        assert res.error_count == 0
        with zipfile.ZipFile(res.zip_path) as zf:
            names = zf.namelist()
        assert any(n.endswith("/manifest.json") for n in names)
        assert any(n.endswith("/README.txt") for n in names)
        assert sum(1 for n in names if n.endswith(".jpg")) == 2
        assert sum(1 for n in names if n.endswith(".webp")) == 2
        assert sum(1 for n in names if n.endswith("caption.txt")) == 2

    def test_progress_callback_fires_per_item(self, tmp_path):
        spec = BulkExportSpec(items=_items(tmp_path, ["a", "b", "c"]), formats=["jpg"])
        seen = []
        run_bulk_export(spec, progress=lambda d, t, n: seen.append((d, t)))
        assert seen == [(1, 3), (2, 3), (3, 3)]

    def test_single_format_names_file_after_item(self, tmp_path):
        spec = BulkExportSpec(items=_items(tmp_path, ["solo"]), formats=["png"])
        res = run_bulk_export(spec)
        with zipfile.ZipFile(res.zip_path) as zf:
            names = zf.namelist()
        # With one format the file is named after the item, not the format.
        assert any(n.endswith("/solo/solo.png") for n in names)

    def test_impossible_format_is_recorded_not_fatal(self, tmp_path):
        spec = BulkExportSpec(items=_items(tmp_path, ["x"]), formats=["jpg", "mp4"])
        res = run_bulk_export(spec)
        assert res.file_count == 1  # jpg made
        assert res.error_count == 1  # mp4 from a still is impossible
        man = _manifest(res.zip_path)
        assert man["items"][0]["errors"][0]["format"] == "mp4"
        assert man["summary"]["errors"] == 1

    def test_duplicate_names_are_disambiguated(self, tmp_path):
        spec = BulkExportSpec(items=_items(tmp_path, ["Same", "Same"]), formats=["png"])
        res = run_bulk_export(spec)
        with zipfile.ZipFile(res.zip_path) as zf:
            folders = {n.split("/")[1] for n in zf.namelist() if n.count("/") >= 2}
        assert "same" in folders and "same-2" in folders

    def test_no_formats_raises(self, tmp_path):
        spec = BulkExportSpec(items=_items(tmp_path, ["a"]), formats=[])
        with pytest.raises(ExportError):
            run_bulk_export(spec)

    def test_explicit_out_path(self, tmp_path):
        spec = BulkExportSpec(items=_items(tmp_path, ["a"]), formats=["png"])
        out = tmp_path / "mine.zip"
        res = run_bulk_export(spec, out=out)
        assert res.zip_path == out
        assert out.is_file()

    def test_manifest_shape(self, tmp_path):
        spec = BulkExportSpec(
            items=_items(tmp_path, ["a"]), formats=["jpg"], options=ExportOptions(quality=55)
        )
        res = run_bulk_export(spec)
        man = _manifest(res.zip_path)
        assert man["kind"] == "mediahub-bulk-export"
        assert man["formats"] == ["jpg"]
        assert man["options"]["quality"] == 55
        assert set(man["summary"]) == {"items", "files", "errors", "bytes"}


class TestCaching:
    def test_second_run_is_cache_hit(self, tmp_path):
        spec = BulkExportSpec(items=_items(tmp_path, ["a", "b"]), formats=["jpg"])
        first = run_bulk_export(spec)
        second = run_bulk_export(spec)
        assert first.zip_path == second.zip_path
        assert second.from_cache is True
        assert second.file_count == first.file_count

    def test_changed_options_busts_cache(self, tmp_path):
        items = _items(tmp_path, ["a"])
        a = run_bulk_export(BulkExportSpec(items=items, formats=["jpg"], options=ExportOptions(quality=40)))
        b = run_bulk_export(BulkExportSpec(items=items, formats=["jpg"], options=ExportOptions(quality=90)))
        assert a.zip_path != b.zip_path


class TestSpec:
    def test_normalised_formats_dedup_and_alias(self, tmp_path):
        spec = BulkExportSpec(items=[], formats=["JPG", "jpeg", "png", "png"])
        assert spec.normalised_formats() == ["jpg", "png"]
