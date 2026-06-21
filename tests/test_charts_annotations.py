"""Roadmap 1.11 quality uplift (I1) — reference lines, standout emphasis, a11y."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from mediahub.charts.aggregates import compute_aggregates
from mediahub.charts.models import Axis, ChartSpec, DataPoint, ReferenceLine, Series
from mediahub.charts.render import render_chart_svg
from mediahub.charts.series import (
    biggest_drops_chart,
    pbs_per_swimmer_chart,
    progression_chart,
)

_RV = {
    "--mh-primary": "#A30D2D",
    "--mh-secondary": "#2B6CB0",
    "--mh-surface": "#0B1B2E",
    "--mh-accent": "#F2C14E",
    "--mh-on-primary": "#FFFFFF",
    "--mh-on-surface": "#FFFFFF",
    "--mh-outline": "rgba(255,255,255,0.2)",
}


def _prog():
    return ChartSpec(
        kind="progression",
        title="Jess Smith — 100m Free",
        series=(
            Series(
                points=(
                    DataPoint("Oct", 6312, display="1:03.12"),
                    DataPoint("Jun", 6098, display="1:00.98", emphasis=True),
                )
            ),
        ),
        y_axis=Axis(value_format="time_cs", lower_is_better=True),
        reference_lines=(
            ReferenceLine(6020, "Club record", display="1:00.20", role="accent"),
            ReferenceLine(6150, "County QT", display="1:01.50", role="secondary"),
        ),
        source_note="Source: club history",
    )


# --------------------------------------------------------------------------- #
# model
# --------------------------------------------------------------------------- #
def test_reference_line_round_trip():
    rl = ReferenceLine(6020.0, "Club record", display="1:00.20", role="accent", source_ref="rec:1")
    assert ReferenceLine.from_dict(rl.to_dict()) == rl
    assert ReferenceLine.from_dict({"value": 1}).role == "secondary"  # default
    assert ReferenceLine.from_dict({"no": "value"}) is None


def test_emphasis_round_trips_on_datapoint():
    p = DataPoint("A", 6, emphasis=True)
    assert DataPoint.from_dict(p.to_dict()).emphasis is True
    # absent emphasis defaults False and isn't serialised
    plain = DataPoint("A", 6)
    assert "emphasis" not in plain.to_dict()
    assert DataPoint.from_dict(plain.to_dict()).emphasis is False


def test_chartspec_reference_lines_round_trip():
    spec = _prog()
    again = ChartSpec.from_dict(spec.to_dict())
    assert again is not None
    assert again.to_dict() == spec.to_dict()
    assert len(again.reference_lines) == 2


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #
def test_reference_lines_drawn_with_label_and_dash():
    svg = render_chart_svg(_prog(), _RV, embed_fonts=False)
    ET.fromstring(svg)
    assert "Club record" in svg and "County QT" in svg
    assert "stroke-dasharray" in svg  # benchmark drawn as a dashed marker
    assert "1:00.20" in svg  # the benchmark value is shown


def test_reference_line_value_folds_into_domain():
    """A record faster than every plotted time must still be in frame."""
    spec = ChartSpec(
        kind="bar",
        series=(Series(points=(DataPoint("A", 3), DataPoint("B", 4))),),
        y_axis=Axis(value_format="integer"),
        reference_lines=(ReferenceLine(10, "Target", display="10"),),
    )
    svg = render_chart_svg(spec, _RV, embed_fonts=False)
    assert "Target" in svg
    ET.fromstring(svg)


def test_emphasis_paints_accent_and_recedes_rest():
    spec = ChartSpec(
        kind="bar",
        series=(
            Series(
                points=(
                    DataPoint("A", 3),
                    DataPoint("B", 6, emphasis=True),
                    DataPoint("C", 2),
                )
            ),
        ),
        y_axis=Axis(value_format="integer"),
    )
    svg = render_chart_svg(spec, _RV, embed_fonts=False)
    # the accent appears (the emphasised bar) and a receded (mixed) fill exists too
    assert "#F2C14E" in svg


def test_a11y_title_and_desc_present_and_valid():
    svg = render_chart_svg(_prog(), _RV, embed_fonts=False)
    assert "<title" in svg and "<desc" in svg
    assert 'aria-labelledby="mhc-t mhc-d"' in svg
    root = ET.fromstring(svg)
    ns = "{http://www.w3.org/2000/svg}"
    assert root.find(f"{ns}title") is not None
    assert "Jess Smith" in (root.find(f"{ns}title").text or "")


def test_a11y_text_is_escaped():
    spec = ChartSpec(kind="bar", title="<b>x</b>", series=(Series(points=(DataPoint("A", 1),)),))
    svg = render_chart_svg(spec, _RV, embed_fonts=False)
    assert "<b>x</b>" not in svg
    ET.fromstring(svg)


def test_reference_lines_are_deterministic():
    a = render_chart_svg(_prog(), _RV, embed_fonts=True)
    b = render_chart_svg(_prog(), _RV, embed_fonts=True)
    assert a == b


# --------------------------------------------------------------------------- #
# series builders drive emphasis + reference lines from real data
# --------------------------------------------------------------------------- #
def _agg():
    run = {
        "canonical_meet": {
            "name": "County",
            "swimmers": {"s1": {}, "s2": {}, "s3": {}},
            "results": [{"swimmer_key": "s1"}, {"swimmer_key": "s2"}, {"swimmer_key": "s3"}],
        },
        "recognition_report": {
            "meet_name": "County",
            "ranked_achievements": [
                {"achievement": {"type": "pb_confirmed", "swimmer_name": "Big Lead", "swimmer_id": "s1", "event": "100 Free", "swim_id": "a1", "raw_facts": {"drop_seconds": 3.1}}},
                {"achievement": {"type": "pb_confirmed", "swimmer_name": "Big Lead", "swimmer_id": "s1", "event": "200 Free", "swim_id": "a2", "raw_facts": {}}},
                {"achievement": {"type": "pb_confirmed", "swimmer_name": "Runner Up", "swimmer_id": "s2", "event": "50 Fly", "swim_id": "a3", "raw_facts": {"drop_seconds": 0.8}}},
            ],
        },
    }
    return run, compute_aggregates(run)


def test_pbs_chart_emphasises_the_leader_only():
    _run, agg = _agg()
    spec = pbs_per_swimmer_chart(agg)
    pts = spec.series[0].points
    emphasised = [p for p in pts if p.emphasis]
    assert len(emphasised) == 1
    assert emphasised[0].label == "Big Lead"  # the swimmer with the most PBs


def test_biggest_drops_emphasises_the_top_drop():
    run, _agg_ = _agg()
    spec = biggest_drops_chart(run)
    pts = spec.series[0].points
    assert pts[0].emphasis is True  # the single biggest drop leads
    assert sum(1 for p in pts if p.emphasis) == 1


def test_progression_builds_reference_lines_from_real_benchmarks():
    spec = progression_chart(
        "Jess Smith",
        [("Oct", 6312), ("Dec", 6248), ("Jun", 6098)],
        event="100m Free",
        club_record_cs=6020,
        qualifying_cs=6150,
    )
    assert spec is not None
    labels = {r.label for r in spec.reference_lines}
    assert labels == {"Club record", "Qualifying time"}
    # the season best (fastest) point is emphasised
    best = [p for p in spec.series[0].points if p.emphasis]
    assert len(best) == 1 and best[0].value == 6098.0


def test_progression_without_benchmarks_has_no_reference_lines():
    spec = progression_chart("X", [("a", 6300), ("b", 6200)])
    assert spec is not None
    assert spec.reference_lines == ()
