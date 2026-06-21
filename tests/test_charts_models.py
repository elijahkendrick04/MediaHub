"""Roadmap 1.11 build 1 — chart data model: round-trip + deterministic formatting."""

from __future__ import annotations

import pytest

from mediahub.charts.models import (
    CHART_KINDS,
    Axis,
    ChartSpec,
    DataPoint,
    Series,
    format_time_cs,
    format_value,
)


def test_chart_kinds_are_unique_and_nonempty():
    assert CHART_KINDS
    assert len(CHART_KINDS) == len(set(CHART_KINDS))


def test_datapoint_round_trip():
    p = DataPoint("Smith, J", 3.0, x=2.0, display="3", source_ref="swim:42", note="PB")
    again = DataPoint.from_dict(p.to_dict())
    assert again == p


def test_datapoint_from_dict_requires_value():
    assert DataPoint.from_dict({"label": "x"}) is None
    assert DataPoint.from_dict("nonsense") is None
    assert DataPoint.from_dict({"value": 5}).value == 5.0


def test_series_round_trip_and_role_normalised():
    s = Series(
        name="PBs",
        points=(DataPoint("A", 1), DataPoint("B", 2)),
        role="accent",
    )
    again = Series.from_dict(s.to_dict())
    assert again == s
    # unknown role falls back to auto
    assert Series.from_dict({"role": "rainbow", "points": []}).role == "auto"


def test_chartspec_round_trip_preserves_everything():
    spec = ChartSpec(
        kind="bar",
        title="PBs per swimmer",
        subtitle="County Champs",
        series=(Series(name="PBs", points=(DataPoint("A", 3), DataPoint("B", 4))),),
        x_axis=Axis(title="Swimmer", kind="category"),
        y_axis=Axis(title="PBs", value_format="integer"),
        width=1200,
        height=800,
        source_note="Source: results file",
        footnote="n=12",
        chart_id="c1",
        meta={"highlight_label": "A"},
    )
    again = ChartSpec.from_dict(spec.to_dict())
    assert again is not None
    assert again.to_dict() == spec.to_dict()


def test_chartspec_table_round_trip():
    spec = ChartSpec(
        kind="medal_table",
        columns=("Swimmer", "G", "S", "B"),
        rows=(("Smith, J", "2", "1", "0"), ("Lee, M", "1", "0", "1")),
    )
    again = ChartSpec.from_dict(spec.to_dict())
    assert again is not None
    assert again.rows == spec.rows
    assert again.columns == spec.columns


def test_chartspec_from_dict_rejects_bad_kind():
    assert ChartSpec.from_dict({"kind": "hologram"}) is None
    assert ChartSpec.from_dict({}) is None
    assert ChartSpec.from_dict("nope") is None


def test_chartspec_from_dict_tolerates_unknown_keys_and_clamps_size():
    spec = ChartSpec.from_dict(
        {"kind": "bar", "width": 99999, "height": -5, "surprise": "ignored"}
    )
    assert spec is not None
    assert spec.width == 10000  # clamped to max
    assert spec.height == 200  # clamped to min


def test_is_empty_and_all_points():
    empty_bar = ChartSpec(kind="bar")
    assert empty_bar.is_empty()
    full_bar = ChartSpec(kind="bar", series=(Series(points=(DataPoint("A", 1),)),))
    assert not full_bar.is_empty()
    assert len(full_bar.all_points()) == 1
    empty_table = ChartSpec(kind="table", columns=("A",))
    assert empty_table.is_empty()
    full_table = ChartSpec(kind="table", rows=(("1",),))
    assert not full_table.is_empty()


@pytest.mark.parametrize(
    "value,fmt,expected",
    [
        (12.0, "integer", "12"),
        (12.4, "integer", "12"),
        (66.66, "percent", "66.7%"),
        (1.2, "seconds", "1.20s"),
        (12.0, "number", "12"),
        (1.20, "number", "1.2"),
        (1.234, "number", "1.23"),
        (6234, "time_cs", "1:02.34"),
        (5012, "time_cs", "50.12"),
    ],
)
def test_format_value(value, fmt, expected):
    assert format_value(value, fmt) == expected


def test_format_value_unknown_format_falls_back_to_number():
    assert format_value(5.0, "klingon") == "5"


def test_format_time_cs_edges():
    assert format_time_cs(0) == "0.00"
    assert format_time_cs(100) == "1.00"
    assert format_time_cs(6000) == "1:00.00"
    assert format_time_cs(-50) == "0.00"  # clamps negative


def test_axis_from_dict_defaults_and_validation():
    a = Axis.from_dict(None)
    assert a.kind == "linear" and a.value_format == "number"
    b = Axis.from_dict({"kind": "weird", "value_format": "bogus"})
    assert b.kind == "linear" and b.value_format == "number"
    c = Axis.from_dict({"kind": "time", "value_format": "time_cs", "lower_is_better": True})
    assert c.kind == "time" and c.value_format == "time_cs" and c.lower_is_better is True
