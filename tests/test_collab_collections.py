"""Roadmap 1.18 build 5 — collab.collections store (folders over runs/packs)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.collab import collections as col


@pytest.fixture
def db(tmp_path):
    return tmp_path / "data.db"


def test_create_and_list(db):
    c = col.create_collection("org1", "Summer League", db_path=db)
    assert c["name"] == "Summer League" and c["count"] == 0
    rows = col.list_collections("org1", db_path=db)
    assert [r["name"] for r in rows] == ["Summer League"]


def test_empty_name_rejected(db):
    with pytest.raises(col.CollectionError):
        col.create_collection("org1", "   ", db_path=db)


def test_add_remove_items_and_count(db):
    c = col.create_collection("org1", "C", db_path=db)
    assert col.add_item("org1", c["id"], "run", "runA", db_path=db) is True
    assert col.add_item("org1", c["id"], "pack", "packB", db_path=db) is True
    # idempotent add
    col.add_item("org1", c["id"], "run", "runA", db_path=db)
    items = col.list_items("org1", c["id"], db_path=db)
    assert len(items) == 2
    assert col.list_collections("org1", db_path=db)[0]["count"] == 2
    assert col.remove_item("org1", c["id"], "run", "runA", db_path=db) is True
    assert len(col.list_items("org1", c["id"], db_path=db)) == 1


def test_bad_item_type_rejected(db):
    c = col.create_collection("org1", "C", db_path=db)
    with pytest.raises(col.CollectionError):
        col.add_item("org1", c["id"], "widget", "x", db_path=db)


def test_org_isolation(db):
    c = col.create_collection("org1", "C", db_path=db)
    # another org can't add to / read / delete this collection
    assert col.add_item("org2", c["id"], "run", "x", db_path=db) is False
    assert col.list_items("org2", c["id"], db_path=db) is None
    assert col.delete_collection("org2", c["id"], db_path=db) is False
    # and org2 sees no collections
    assert col.list_collections("org2", db_path=db) == []


def test_rename_and_delete(db):
    c = col.create_collection("org1", "Old", db_path=db)
    assert col.rename_collection("org1", c["id"], "New", db_path=db) is True
    assert col.list_collections("org1", db_path=db)[0]["name"] == "New"
    assert col.delete_collection("org1", c["id"], db_path=db) is True
    assert col.list_collections("org1", db_path=db) == []


def test_collections_for_item(db):
    a = col.create_collection("org1", "A", db_path=db)
    b = col.create_collection("org1", "B", db_path=db)
    col.add_item("org1", a["id"], "run", "runX", db_path=db)
    col.add_item("org1", b["id"], "run", "runX", db_path=db)
    names = {x["name"] for x in col.collections_for_item("org1", "run", "runX", db_path=db)}
    assert names == {"A", "B"}


def test_delete_run_everywhere(db):
    a = col.create_collection("org1", "A", db_path=db)
    b = col.create_collection("org1", "B", db_path=db)
    col.add_item("org1", a["id"], "run", "runX", db_path=db)
    col.add_item("org1", b["id"], "run", "runX", db_path=db)
    col.add_item("org1", a["id"], "pack", "packY", db_path=db)
    assert col.delete_run_everywhere("runX", db_path=db) == 2
    # the pack membership survives; the run is gone from both
    assert col.collections_for_item("org1", "run", "runX", db_path=db) == []
    assert len(col.list_items("org1", a["id"], db_path=db)) == 1


def test_delete_for_org(db):
    a = col.create_collection("org1", "A", db_path=db)
    col.add_item("org1", a["id"], "run", "runX", db_path=db)
    col.create_collection("org2", "Other", db_path=db)
    assert col.delete_for_org("org1", db_path=db) == 1
    assert col.list_collections("org1", db_path=db) == []
    assert len(col.list_collections("org2", db_path=db)) == 1
