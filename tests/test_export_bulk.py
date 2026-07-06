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


class TestAtomicZip:
    def test_crash_mid_build_leaves_no_zip_or_tmp(self, tmp_path, monkeypatch):
        """A crash while the archive is being written must not leave a truncated
        ZIP at the served path (nor a stray .tmp sibling)."""
        from mediahub.export_engine import bulk as bulk_mod

        def _boom(label, manifest):
            raise RuntimeError("simulated crash mid-build")

        monkeypatch.setattr(bulk_mod, "_readme", _boom)
        out = tmp_path / "exports" / "bulk_test.zip"
        spec = BulkExportSpec(items=_items(tmp_path, ["Eira 200 Free"]), formats=["jpg"])
        with pytest.raises(RuntimeError):
            run_bulk_export(spec, out=out)
        assert not out.exists()
        assert list(out.parent.glob("*.tmp")) == []


class TestMaybeGc:
    def _backdate(self, path: Path, seconds: float) -> None:
        import os
        import time

        old = time.time() - seconds
        os.utime(path, (old, old))

    def test_aged_artifacts_swept_fresh_kept(self, tmp_path):
        from mediahub.export_engine import cache as ee_cache

        quick = ee_cache.cache_dir() / "quick"
        quick.mkdir(parents=True, exist_ok=True)
        aged_quick = quick / "card-convert-deadbeef.png"
        fresh_quick = quick / "card-resize-cafebabe.png"
        aged_quick.write_bytes(b"x" * 10)
        fresh_quick.write_bytes(b"y" * 10)
        self._backdate(aged_quick, ee_cache._CACHE_MAX_AGE_S + 3600)

        exports = ee_cache._runs_dir() / "run1" / "exports"
        exports.mkdir(parents=True, exist_ok=True)
        aged_zip = exports / "bulk_old.zip"
        fresh_zip = exports / "bulk_new.zip"
        aged_zip.write_bytes(b"z" * 10)
        fresh_zip.write_bytes(b"w" * 10)
        self._backdate(aged_zip, ee_cache._BULK_ZIP_MAX_AGE_S + 3600)

        ee_cache.maybe_gc(force=True)

        assert not aged_quick.exists()
        assert fresh_quick.exists()
        assert not aged_zip.exists()
        assert fresh_zip.exists()

    def test_size_cap_evicts_oldest_first(self, tmp_path, monkeypatch):
        from mediahub.export_engine import cache as ee_cache

        monkeypatch.setattr(ee_cache, "_CACHE_MAX_BYTES", 150)
        d = ee_cache.cache_dir()
        oldest = d / "aaa.png"
        middle = d / "bbb.png"
        newest = d / "ccc.png"
        for i, f in enumerate((oldest, middle, newest)):
            f.write_bytes(b"x" * 60)
            self._backdate(f, 3600 * (3 - i))

        ee_cache.maybe_gc(force=True)

        assert not oldest.exists()  # evicted to bring 180 bytes under the cap
        assert middle.exists()
        assert newest.exists()

    def test_throttled_run_is_a_noop(self, tmp_path):
        from mediahub.export_engine import cache as ee_cache

        ee_cache.maybe_gc(force=True)  # stamps the throttle marker
        aged = ee_cache.cache_dir() / "quick-old.png"
        aged.write_bytes(b"x")
        self._backdate(aged, ee_cache._CACHE_MAX_AGE_S + 3600)
        ee_cache.maybe_gc()  # throttled: must not sweep yet
        assert aged.exists()
        ee_cache.maybe_gc(force=True)
        assert not aged.exists()


def test_bulk_export_js_retries_poll_before_giving_up():
    """A transient poll failure must not abandon a still-running export job:
    the client retries with backoff before declaring the job lost."""
    from pathlib import Path

    import mediahub.web as web_pkg

    js = (Path(web_pkg.__file__).parent / "static" / "js" / "bulk_export.js").read_text(
        encoding="utf-8"
    )
    assert "POLL_MAX_RETRIES" in js
    assert "pollRetries = 0" in js  # retry budget resets on a successful poll
    assert "Lost contact with the export job" in js  # terminal copy kept
