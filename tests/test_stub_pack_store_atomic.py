"""Stub pack store — atomic JSON writes (tmp + os.replace).

A crash or concurrent pill click mid-write must never leave a truncated
pack on disk: readers see either the old record or the new one.
"""

from __future__ import annotations

import json
import os

import pytest


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def _save(store):
    return store.save_pack(
        "free_text",
        {"free_text": "Big win at the gala"},
        [{"platform": "instagram", "caption": "Original caption", "confidence": 0.8}],
    )


def test_interrupted_write_leaves_original_pack_intact(data_dir, monkeypatch):
    from mediahub.club_platform import stub_pack_store as store

    rec = _save(store)
    pack_id = rec["pack_id"]
    path = data_dir / "stub_packs" / f"{pack_id}.json"
    original = path.read_text(encoding="utf-8")

    # Simulate a crash between the temp-file write and the swap.
    def boom(src, dst):
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr(store.os, "replace", boom)
    with pytest.raises(OSError):
        store.update_card_status(pack_id, 0, "approved")

    # The saved pack is untouched and still parses.
    assert path.read_text(encoding="utf-8") == original
    assert json.loads(original)["cards"][0]["caption"] == "Original caption"


def test_successful_write_swaps_in_and_leaves_no_temp_file(data_dir):
    from mediahub.club_platform import stub_pack_store as store

    rec = _save(store)
    pack_id = rec["pack_id"]
    updated = store.update_card_status(pack_id, 0, "approved")
    assert updated["cards"][0]["status"] == "approved"

    packs_dir = data_dir / "stub_packs"
    assert not list(packs_dir.glob("*.tmp"))
    on_disk = json.loads((packs_dir / f"{pack_id}.json").read_text(encoding="utf-8"))
    assert on_disk["cards"][0]["status"] == "approved"


def test_all_writers_use_the_atomic_helper(data_dir, monkeypatch):
    """Every persist path routes through _atomic_write — no direct write_text."""
    from mediahub.club_platform import stub_pack_store as store

    calls = []
    real = store._atomic_write

    def spy(path, rec):
        calls.append(path.name)
        real(path, rec)

    monkeypatch.setattr(store, "_atomic_write", spy)
    rec = _save(store)
    pid = rec["pack_id"]
    store.update_pack(pid, form_data_updates={"meet_name": "Gala"})
    store.set_planned_date(pid, "2026-07-04")
    store.update_card_status(pid, 0, "approved")
    store.replace_cards(pid, [{"platform": "x", "caption": "New"}])
    assert len(calls) == 5
