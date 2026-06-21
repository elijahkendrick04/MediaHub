"""Roadmap 1.11 build 2 — CSV/table import (deterministic + honest about bad rows)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from mediahub.charts.csv_input import parse_csv_to_spec
from mediahub.charts.render import render_chart_svg


def test_simple_single_value_column():
    imp = parse_csv_to_spec("Swimmer,PBs\nSmith J,3\nOkafor A,2\n")
    assert imp.ok
    assert len(imp.spec.series) == 1
    pts = imp.spec.series[0].points
    assert [p.label for p in pts] == ["Smith J", "Okafor A"]
    assert [p.value for p in pts] == [3.0, 2.0]
    ET.fromstring(render_chart_svg(imp.spec, embed_fonts=False))


def test_multi_series_grouped():
    imp = parse_csv_to_spec("Swimmer,PBs,Medals\nSmith J,3,2\nOkafor A,2,1\n")
    assert imp.ok
    assert len(imp.spec.series) == 2
    assert imp.spec.series[0].name == "PBs"
    assert imp.spec.series[1].name == "Medals"


def test_non_numeric_cell_is_flagged_not_guessed():
    imp = parse_csv_to_spec("Swimmer,PBs\nSmith J,3\nBad,oops\n")
    assert imp.ok  # the good row still charts
    assert len(imp.spec.series[0].points) == 1  # 'oops' was NOT coerced to 0
    assert any("isn't a number" in w.message for w in imp.warnings)
    assert any(w.cell == "oops" for w in imp.warnings)


def test_missing_label_row_flagged():
    imp = parse_csv_to_spec("Swimmer,PBs\n,5\nReal,2\n")
    assert any("no label" in w.message for w in imp.warnings)
    assert len(imp.spec.series[0].points) == 1


def test_blank_lines_skipped_silently():
    imp = parse_csv_to_spec("Swimmer,PBs\nSmith J,3\n\n\nOkafor A,2\n")
    assert len(imp.spec.series[0].points) == 2
    # blank lines don't raise warnings
    assert not any("no label" in w.message for w in imp.warnings)


def test_tab_delimited_sniffed():
    imp = parse_csv_to_spec("Swimmer\tPBs\nSmith J\t3\nOkafor A\t2\n")
    assert imp.ok
    assert len(imp.spec.series[0].points) == 2


def test_numbers_with_separators_and_units():
    # Tab-delimited so "1,240" stays one field (a thousands separator), not two cells.
    imp = parse_csv_to_spec("Event\tScore\nFree\t1,240\nBack\t88%\nFly\t1.2s\n")
    vals = [p.value for p in imp.spec.series[0].points]
    assert vals == [1240.0, 88.0, 1.2]


def test_empty_and_single_column_are_honest():
    empty = parse_csv_to_spec("")
    assert not empty.ok
    assert empty.spec is None
    assert any("empty" in w.message.lower() for w in empty.warnings)

    one_col = parse_csv_to_spec("JustLabels\nA\nB\n")
    assert not one_col.ok
    assert any("two columns" in w.message for w in one_col.warnings)


def test_all_non_numeric_yields_no_chart():
    imp = parse_csv_to_spec("Name,Note\nA,hello\nB,world\n")
    assert not imp.ok
    assert any("No numeric" in w.message or "nothing could be charted" in w.message for w in imp.warnings)


def test_to_dict_shape():
    imp = parse_csv_to_spec("Swimmer,PBs\nSmith J,3\n")
    d = imp.to_dict()
    assert d["ok"] is True
    assert d["spec"]["kind"] == "bar"
    assert isinstance(d["warnings"], list)
