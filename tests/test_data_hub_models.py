"""data_hub.models — table/column/cell shapes + provenance (roadmap 1.13)."""

from __future__ import annotations

from mediahub.data_hub.models import (
    COLUMN_TYPES,
    DataCell,
    DataColumn,
    DataTable,
    DataWarning,
    Provenance,
    text_cell,
)


def test_provenance_normalise_and_label():
    assert Provenance.normalise("PARSED") == Provenance.PARSED
    assert Provenance.normalise("nonsense") == Provenance.UNKNOWN
    assert Provenance.label(Provenance.DERIVED) == "Calculated"
    assert Provenance.label("bogus") == Provenance.LABELS[Provenance.UNKNOWN]


def test_cell_defaults_and_roundtrip():
    c = DataCell(value=3, provenance="parsed", confidence="high")
    assert c.display == "3"  # display auto-filled from value
    d = c.to_dict()
    again = DataCell.from_dict(d)
    assert again.value == 3
    assert again.provenance == Provenance.PARSED
    assert again.confidence == "high"


def test_cell_from_bare_value_is_tolerated():
    c = DataCell.from_dict("hello")
    assert c.value == "hello"
    assert c.display == "hello"


def test_text_cell_defaults_hand_entered():
    c = text_cell("Maya")
    assert c.provenance == Provenance.HAND_ENTERED
    assert c.value == "Maya" and c.display == "Maya"


def test_column_type_falls_back_and_derived_is_readonly():
    col = DataColumn("k", "K", type="bogus", editable=True)
    assert col.type == "text"
    assert col.type in COLUMN_TYPES
    derived = DataColumn("d", "D", type="number", editable=True, derived=True)
    assert derived.editable is False  # derived columns are never hand-editable


def test_column_roundtrip():
    col = DataColumn("pbs", "PBs", "int", editable=True, frozen=True, width=80)
    again = DataColumn.from_dict(col.to_dict())
    assert again.key == "pbs" and again.type == "int" and again.frozen and again.width == 80


def test_table_summary_counts_flags():
    cols = [DataColumn("a", "A", "text"), DataColumn("b", "B", "int")]
    rows = [
        {"a": DataCell("x"), "b": DataCell(1, "1")},
        {"a": DataCell("y", flagged=True), "b": DataCell("nope", flagged=True)},
    ]
    t = DataTable("t1", "T", "org", columns=cols, rows=rows, editable=True)
    s = t.summary()
    assert s["n_rows"] == 2
    assert s["n_columns"] == 2
    assert s["n_flagged"] == 2
    assert t.cell(0, "b").value == 1
    assert t.cell(99, "a").display == ""  # out of range → empty cell


def test_table_roundtrip_preserves_cells_and_warnings():
    cols = [DataColumn("a", "A", "text")]
    rows = [{"a": DataCell("x", provenance="imported", flagged=True, note="iffy")}]
    t = DataTable(
        "t1",
        "T",
        "org",
        profile_id="club-a",
        columns=cols,
        rows=rows,
        editable=True,
        warnings=[DataWarning(1, "something", cell="x")],
    )
    again = DataTable.from_dict(t.to_dict())
    assert again.table_id == "t1"
    assert again.profile_id == "club-a"
    assert again.cell(0, "a").provenance == Provenance.IMPORTED
    assert again.cell(0, "a").flagged is True
    assert again.warnings[0].message == "something"


def test_unknown_kind_falls_back_to_org():
    t = DataTable("t", "T", kind="weird")
    assert t.kind == "org"
