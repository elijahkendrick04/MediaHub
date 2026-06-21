"""data_hub.derive — deterministic derived columns + AI suggestion (1.13)."""

from __future__ import annotations

import pytest

from mediahub.ai_core import ProviderNotConfigured
from mediahub.data_hub import derive
from mediahub.data_hub.models import DataCell, DataColumn, DataTable, Provenance


def _table():
    cols = [
        DataColumn("first", "First", "text"),
        DataColumn("last", "Last", "text"),
        DataColumn("by", "Birth year", "int"),
        DataColumn("a", "A", "number"),
        DataColumn("b", "B", "number"),
    ]
    rows = [
        {
            "first": DataCell("Maya"),
            "last": DataCell("Patel"),
            "by": DataCell(2012, "2012"),
            "a": DataCell(10, "10"),
            "b": DataCell(3, "3"),
        }
    ]
    return DataTable("t", "T", "org", columns=cols, rows=rows, editable=True)


def test_row_derivations():
    t = _table()
    derive.apply_derivation(t, "full", "Full name", "full_name", {"first": "first", "last": "last"})
    derive.apply_derivation(t, "age", "Age", "age_from_birth_year", {"birth_year": "by", "ref_year": 2026})
    derive.apply_derivation(t, "grp", "Age group", "age_group_band", {"age": "age"})
    derive.apply_derivation(t, "ini", "Initials", "initials", {"name": "full"})
    derive.apply_derivation(t, "diff", "Diff", "difference", {"a": "a", "b": "b"})
    derive.apply_derivation(t, "tot", "Total", "sum", {"columns": ["a", "b"]})

    assert t.cell(0, "full").value == "Maya Patel"
    assert t.cell(0, "age").value == 14
    assert t.cell(0, "grp").value == "13-14"
    assert t.cell(0, "ini").value == "M.P."
    assert t.cell(0, "diff").value == 7
    assert t.cell(0, "tot").value == 13
    # Derived columns are read-only and stamped DERIVED.
    assert t.column("age").derived is True
    assert t.column("age").editable is False
    assert t.cell(0, "age").provenance == Provenance.DERIVED


def test_age_group_bands():
    t = DataTable(
        "t",
        "T",
        "org",
        columns=[DataColumn("age", "Age", "int")],
        rows=[{"age": DataCell(a, str(a))} for a in (9, 11, 12, 14, 19, 25)],
        editable=True,
    )
    derive.apply_derivation(t, "grp", "Age group", "age_group_band", {"age": "age"})
    got = [t.cell(i, "grp").value for i in range(t.row_count)]
    assert got == ["10 & under", "11-12", "11-12", "13-14", "Open", "Open"]


def test_bad_input_is_flagged_not_zeroed():
    t = DataTable(
        "t",
        "T",
        "org",
        columns=[DataColumn("by", "Birth year", "text")],
        rows=[{"by": DataCell("not-a-year")}],
        editable=True,
    )
    derive.apply_derivation(t, "age", "Age", "age_from_birth_year", {"birth_year": "by"})
    cell = t.cell(0, "age")
    assert cell.flagged is True
    assert cell.value is None  # never silently zeroed
    assert "number" in cell.note


def test_season_best_table_derivation():
    cols = [DataColumn("sw", "Swimmer", "text"), DataColumn("time", "Time", "time")]
    rows = [
        {"sw": DataCell("Maya"), "time": DataCell(6532, "1:05.32")},
        {"sw": DataCell("Maya"), "time": DataCell(6400, "1:04.00")},
        {"sw": DataCell("Sam"), "time": DataCell(7000, "1:10.00")},
    ]
    t = DataTable("t", "T", "org", columns=cols, rows=rows, editable=True)
    derive.apply_derivation(t, "sb", "Season best", "season_best", {"group": "sw", "value": "time"})
    assert t.cell(0, "sb").display == "1:04.00"  # Maya's fastest
    assert t.cell(1, "sb").display == "1:04.00"
    assert t.cell(2, "sb").display == "1:10.00"  # Sam's only swim


def test_unknown_derivation_raises():
    with pytest.raises(KeyError):
        derive.apply_derivation(_table(), "x", "X", "no_such_derivation", {})


def test_list_derivations_has_builtins():
    ids = {d["id"] for d in derive.list_derivations()}
    assert {"full_name", "age_from_birth_year", "age_group_band", "season_best"} <= ids


def test_suggest_derivation_honest_error(monkeypatch):
    def _boom(*a, **k):
        raise ProviderNotConfigured("no key")

    monkeypatch.setattr(derive, "ask", _boom)
    with pytest.raises(ProviderNotConfigured):
        derive.suggest_derivation(_table(), "work out the age group")


def test_suggest_derivation_success(monkeypatch):
    t = _table()
    derive.apply_derivation(t, "age", "Age", "age_from_birth_year", {"birth_year": "by", "ref_year": 2026})
    monkeypatch.setattr(
        derive,
        "ask",
        lambda s, u, **k: '{"derivation_id":"age_group_band","output_title":"Age group","params":{"age":"age"},"rationale":"band it"}',
    )
    sug = derive.suggest_derivation(t, "put ages into bands")
    assert sug.ok is True
    assert sug.derivation_id == "age_group_band"
    assert sug.params == {"age": "age"}


def test_suggest_rejects_unknown_column(monkeypatch):
    monkeypatch.setattr(
        derive,
        "ask",
        lambda s, u, **k: '{"derivation_id":"initials","params":{"name":"does_not_exist"}}',
    )
    sug = derive.suggest_derivation(_table(), "initials")
    assert sug.ok is False
    assert "doesn't exist" in sug.reason


def test_suggest_rejects_unknown_derivation(monkeypatch):
    monkeypatch.setattr(derive, "ask", lambda s, u, **k: '{"derivation_id":"made_up"}')
    sug = derive.suggest_derivation(_table(), "do a thing")
    assert sug.ok is False
