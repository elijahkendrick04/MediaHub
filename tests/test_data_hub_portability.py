"""data_hub.portability — CSV/XLSX import/export round-trip + flagging (1.13)."""

from __future__ import annotations

import importlib.util

import pytest

from mediahub.data_hub import portability
from mediahub.data_hub.models import DataColumn, Provenance

_HAS_OPENPYXL = importlib.util.find_spec("openpyxl") is not None

CLEAN_CSV = (
    "Swimmer,PBs,Time,Joined\n"
    "Maya Patel,3,1:05.32,2024-05-01\n"
    "Sam Okafor,2,31.24,2023-09-10\n"
)


def test_clean_import_infers_types():
    res = portability.import_bytes(CLEAN_CSV.encode(), "roster.csv")
    assert res.ok
    assert res.table.row_count == 2
    types = {c.key: c.type for c in res.table.columns}
    assert types == {"swimmer": "text", "pbs": "int", "time": "time", "joined": "date"}
    # Time is stored canonically (centiseconds) but shown human-readably.
    assert res.table.cell(0, "time").value == 6532
    assert res.table.cell(0, "time").display == "1:05.32"
    # Imported cells are stamped IMPORTED.
    assert res.table.cell(0, "swimmer").provenance == Provenance.IMPORTED


def test_typed_reimport_flags_bad_cells():
    cols = [
        DataColumn("swimmer", "Swimmer", "text"),
        DataColumn("pbs", "PBs", "int"),
        DataColumn("time", "Time", "time"),
        DataColumn("joined", "Joined", "date"),
    ]
    bad = "Swimmer,PBs,Time,Joined\nMaya Patel,3,1:05.32,2024-05-01\nBad Row,x,notatime,nope\n"
    res = portability.import_bytes(bad.encode(), "r.csv", existing_columns=cols)
    assert res.table.row_count == 2
    assert res.table.flagged_count == 3  # x, notatime, nope
    assert len(res.warnings) == 3
    # The raw value is kept (never coerced to zero/None) so a human can fix it.
    assert res.table.cell(1, "pbs").value == "x"
    assert res.table.cell(1, "pbs").flagged is True


def test_empty_file_is_honest_error():
    res = portability.import_bytes(b"", "empty.csv")
    assert not res.ok
    assert any(w.severity == "error" for w in res.warnings)


def test_header_only_is_error():
    res = portability.import_bytes(b"A,B,C\n", "h.csv")
    assert not res.ok
    assert any("No data rows" in w.message for w in res.warnings)


def test_blank_lines_skipped_silently():
    csv_text = "Name,N\nAaa,1\n\n\nBbb,2\n"
    res = portability.import_bytes(csv_text.encode(), "x.csv")
    assert res.table.row_count == 2


def test_extra_cells_warn_not_crash():
    csv_text = "Name,N\nAaa,1,EXTRA\n"
    res = portability.import_bytes(csv_text.encode(), "x.csv")
    assert res.table.row_count == 1
    assert any("more cells" in w.message for w in res.warnings)


def test_csv_export_roundtrip():
    res = portability.import_bytes(CLEAN_CSV.encode(), "roster.csv")
    text = portability.export_csv(res.table)
    again = portability.import_bytes(text.encode(), "rt.csv")
    assert again.table.row_count == res.table.row_count
    assert [c.title for c in again.table.columns] == [c.title for c in res.table.columns]
    # Display values survive the round-trip.
    assert again.table.cell(0, "time").display == "1:05.32"


def test_tsv_delimiter_sniffed():
    tsv = "Name\tN\nAaa\t1\nBbb\t2\n"
    res = portability.import_bytes(tsv.encode(), "x.csv")
    assert res.table.row_count == 2
    assert res.table.column_keys == ["name", "n"]


@pytest.mark.skipif(not _HAS_OPENPYXL, reason="openpyxl not installed")
def test_xlsx_roundtrip():
    res = portability.import_bytes(CLEAN_CSV.encode(), "roster.csv")
    xb = portability.export_xlsx(res.table)
    assert xb[:2] == b"PK"  # a real xlsx (zip) container
    again = portability.import_bytes(xb, "rt.xlsx")
    assert again.table.row_count == 2
    assert [c.title for c in again.table.columns] == ["Swimmer", "PBs", "Time", "Joined"]


@pytest.mark.skipif(_HAS_OPENPYXL, reason="exercises the no-openpyxl honest error")
def test_xlsx_without_openpyxl_is_honest_error():
    res = portability.import_bytes(b"PK\x03\x04rest", "book.xlsx")
    assert not res.ok
    assert any("openpyxl" in w.message for w in res.warnings)
