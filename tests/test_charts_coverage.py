"""Roadmap 1.11 quality uplift (I3) — richer deterministic chart coverage."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from mediahub.charts.aggregates import compute_aggregates
from mediahub.charts.render import render_chart_svg
from mediahub.charts.series import (
    build_chart_candidates,
    entries_by_stroke_chart,
    finals_by_swimmer_chart,
    gender_split_chart,
)


def _run():
    return {
        "canonical_meet": {
            "name": "County",
            "swimmers": {"s1": {}, "s2": {}},
            "results": [
                {"swimmer_key": "s1", "stroke": "FR", "gender": "M"},
                {"swimmer_key": "s1", "stroke": "BK", "gender": "M"},
                {"swimmer_key": "s1", "stroke": "FR", "gender": "M"},
                {"swimmer_key": "s2", "stroke": "FR", "gender": "F"},
                {"swimmer_key": "s2", "stroke": "FL", "gender": "F"},
            ],
        },
        "recognition_report": {
            "meet_name": "County",
            "ranked_achievements": [
                {
                    "achievement": {
                        "type": "final_appearance",
                        "swimmer_name": "Lead",
                        "swimmer_id": "s1",
                        "event": "100 Free",
                        "swim_id": "a1",
                    }
                },
                {
                    "achievement": {
                        "type": "heat_to_final",
                        "swimmer_name": "Lead",
                        "swimmer_id": "s1",
                        "event": "50 Fly",
                        "swim_id": "a2",
                    }
                },
                {
                    "achievement": {
                        "type": "final_appearance",
                        "swimmer_name": "Other",
                        "swimmer_id": "s2",
                        "event": "200 Free",
                        "swim_id": "a3",
                    }
                },
            ],
        },
    }


def test_entries_by_stroke_counts_and_orders():
    spec = entries_by_stroke_chart(_run())
    assert spec is not None and spec.kind == "bar"
    labels = [p.label for p in spec.series[0].points]
    assert labels == ["Free", "Back", "Fly"]  # canonical stroke order, only present ones
    free = [p for p in spec.series[0].points if p.label == "Free"][0]
    assert free.value == 3.0  # three freestyle swims
    ET.fromstring(render_chart_svg(spec, embed_fonts=False))


def test_entries_by_stroke_gates_on_variety():
    one = {"canonical_meet": {"results": [{"stroke": "FR"}, {"stroke": "FR"}]}}
    assert entries_by_stroke_chart(one) is None


def test_gender_split_counts_both():
    spec = gender_split_chart(_run())
    assert spec is not None and spec.kind == "donut"
    by = {p.label: p.value for p in spec.series[0].points}
    assert by["Boys"] == 3.0 and by["Girls"] == 2.0


def test_gender_split_gates_on_single_gender():
    one = {"canonical_meet": {"results": [{"gender": "M"}, {"gender": "M"}]}}
    assert gender_split_chart(one) is None


def test_finals_by_swimmer_from_aggregates_with_emphasis():
    agg = compute_aggregates(_run())
    assert agg.finals_by_swimmer == {"Lead": 2, "Other": 1}
    assert "a1" in agg.sources_for("finals")
    spec = finals_by_swimmer_chart(agg)
    assert spec is not None
    pts = spec.series[0].points
    assert pts[0].label == "Lead" and pts[0].emphasis is True
    assert sum(1 for p in pts if p.emphasis) == 1


def test_finals_chart_none_without_finals():
    agg = compute_aggregates({"recognition_report": {"ranked_achievements": []}})
    assert finals_by_swimmer_chart(agg) is None


def test_candidates_include_the_new_charts():
    ids = {c.chart_id for c in build_chart_candidates(_run())}
    assert {"entries_by_stroke", "gender_split", "finals_by_swimmer"} <= ids
