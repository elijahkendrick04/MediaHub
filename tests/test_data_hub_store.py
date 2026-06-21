"""data_hub.store — editable org tables, org-scoped (roadmap 1.13)."""

from __future__ import annotations

import pytest

from mediahub.data_hub import store
from mediahub.data_hub.models import DataCell, DataColumn, Provenance, text_cell


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "data.db"


def _cols():
    return [
        DataColumn("name", "Name", "text", editable=True),
        DataColumn("pbs", "PBs", "int", editable=True),
    ]


def test_create_and_load_table(db):
    tid = store.create_table("club-a", "Roster", _cols(), description="our swimmers", db_path=db)
    assert tid.startswith("org")
    t = store.get_org_table("club-a", tid, db_path=db)
    assert t is not None
    assert t.title == "Roster"
    assert t.editable is True
    assert t.column_keys == ["name", "pbs"]
    assert t.row_count == 0
    assert t.description == "our swimmers"


def test_upsert_row_and_cell_edit(db):
    tid = store.create_table("club-a", "Roster", _cols(), db_path=db)
    rid = store.upsert_row(
        "club-a",
        tid,
        {"name": text_cell("Maya Patel"), "pbs": DataCell(3, "3", provenance=Provenance.HAND_ENTERED)},
        db_path=db,
    )
    t = store.get_org_table("club-a", tid, db_path=db)
    assert t.row_count == 1
    assert t.cell(0, "name").display == "Maya Patel"
    assert t.cell(0, "pbs").value == 3
    assert store.row_ids_for(t) == [rid]

    # Edit one cell; the rest of the row survives.
    store.set_cell("club-a", tid, rid, "pbs", DataCell(4, "4"), db_path=db)
    t2 = store.get_org_table("club-a", tid, db_path=db)
    assert t2.cell(0, "pbs").value == 4
    assert t2.cell(0, "name").display == "Maya Patel"


def test_rows_keep_insertion_order(db):
    tid = store.create_table("club-a", "Roster", _cols(), db_path=db)
    for nm in ["Aaa", "Bbb", "Ccc"]:
        store.upsert_row("club-a", tid, {"name": text_cell(nm)}, db_path=db)
    t = store.get_org_table("club-a", tid, db_path=db)
    assert [t.cell(i, "name").display for i in range(3)] == ["Aaa", "Bbb", "Ccc"]


def test_delete_row_and_table(db):
    tid = store.create_table("club-a", "Roster", _cols(), db_path=db)
    rid = store.upsert_row("club-a", tid, {"name": text_cell("Maya")}, db_path=db)
    assert store.delete_row("club-a", tid, rid, db_path=db) is True
    assert store.get_org_table("club-a", tid, db_path=db).row_count == 0
    assert store.delete_table("club-a", tid, db_path=db) is True
    assert store.get_org_table("club-a", tid, db_path=db) is None


def test_org_isolation(db):
    tid = store.create_table("club-a", "Roster", _cols(), db_path=db)
    store.upsert_row("club-a", tid, {"name": text_cell("Maya")}, db_path=db)
    # club-b cannot see club-a's table at all.
    assert store.list_org_tables("club-b", db_path=db) == []
    assert store.get_org_table("club-b", tid, db_path=db) is None
    # ...nor edit or delete it.
    assert store.set_cell("club-b", tid, "rowx", "name", DataCell("hack"), db_path=db) is False
    assert store.delete_table("club-b", tid, db_path=db) is False
    # club-a still intact.
    assert store.get_org_table("club-a", tid, db_path=db).row_count == 1


def test_list_org_tables_summary(db):
    tid = store.create_table("club-a", "Roster", _cols(), db_path=db)
    store.upsert_row("club-a", tid, {"name": text_cell("Maya")}, db_path=db)
    listed = store.list_org_tables("club-a", db_path=db)
    assert len(listed) == 1
    s = listed[0]
    assert s["table_id"] == tid
    assert s["n_rows"] == 1
    assert s["n_columns"] == 2
    assert s["editable"] is True


def test_set_columns_replaces_definition(db):
    tid = store.create_table("club-a", "Roster", _cols(), db_path=db)
    new_cols = _cols() + [DataColumn("medals", "Medals", "int", editable=True)]
    assert store.set_columns("club-a", tid, new_cols, db_path=db) is True
    t = store.get_org_table("club-a", tid, db_path=db)
    assert "medals" in t.column_keys
