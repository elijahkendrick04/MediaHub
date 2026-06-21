"""Roadmap 1.11 build 2 — chart series builders over real run data."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

from mediahub.charts.aggregates import compute_aggregates
from mediahub.charts.render import render_chart_svg
from mediahub.charts.series import (
    build_chart_candidates,
    club_record_board_chart,
    medal_table_chart,
    pbs_per_swimmer_chart,
    progression_chart,
    split_ladder_chart,
)


def _run() -> dict:
    return {
        "canonical_meet": {
            "name": "County Champs",
            "swimmers": {
                "s1": {"first_name": "Tunde", "last_name": "Adeyemi"},
                "s2": {"first_name": "Jess", "last_name": "Smith"},
            },
            "results": [
                {"swimmer_key": "s1", "distance": 100, "stroke": "FR", "course": "LC",
                 "finals_time_cs": 5198,
                 "splits": [
                     {"distance_marker": 50, "cumulative_cs": 2510, "differential_cs": 2510},
                     {"distance_marker": 100, "cumulative_cs": 5198, "differential_cs": 2688},
                 ]},
            ],
            "relays": [
                {"distance": 400, "stroke": "FR", "course": "LC", "finals_time_cs": 20800,
                 "legs": [
                     {"swimmer_key": "s1", "leg_index": 0, "leg_time_cs": 5198},
                     {"swimmer_key": "s2", "leg_index": 1, "leg_time_cs": 5240},
                 ]},
            ],
        },
        "recognition_report": {
            "meet_name": "County Champs",
            "n_swims_analysed": 12,
            "ranked_achievements": [
                {"achievement": {"type": "pb_confirmed", "swimmer_name": "Tunde Adeyemi", "swimmer_id": "s1", "event": "100m Free", "swim_id": "a1", "raw_facts": {"drop_seconds": 1.42}}},
                {"achievement": {"type": "pb_confirmed", "swimmer_name": "Jess Smith", "swimmer_id": "s2", "event": "200m Free", "swim_id": "a2", "raw_facts": {"drop_seconds": 2.6}}},
                {"achievement": {"type": "medal_gold", "swimmer_name": "Tunde Adeyemi", "swimmer_id": "s1", "event": "100m Free", "swim_id": "a1"}},
                {"achievement": {"type": "medal_silver", "swimmer_name": "Jess Smith", "swimmer_id": "s2", "event": "200m Free", "swim_id": "a2"}},
            ],
        },
    }


def test_candidates_cover_the_available_charts_and_all_render():
    cands = build_chart_candidates(_run())
    ids = {c.chart_id for c in cands}
    assert {"pbs_per_swimmer", "medal_split", "medal_table", "biggest_drops"} <= ids
    # split ladder available (the individual swim has real splits)
    assert "split_ladder" in ids
    for c in cands:
        svg = render_chart_svg(c.spec, embed_fonts=False)
        ET.fromstring(svg)  # every candidate renders to well-formed SVG
        assert c.headline_stat


def test_candidate_to_dict_round_trips_the_spec():
    c = build_chart_candidates(_run())[0]
    d = c.to_dict()
    assert d["chart_id"] and d["spec"]["kind"] == c.kind


def test_pbs_per_swimmer_is_sorted_desc():
    agg = compute_aggregates(_run())
    spec = pbs_per_swimmer_chart(agg)
    assert spec is not None
    vals = [p.value for p in spec.series[0].points]
    assert vals == sorted(vals, reverse=True)
    # each point carries provenance
    assert all(p.source_ref for p in spec.series[0].points)


def test_medal_table_rows_ranked_and_shaped():
    agg = compute_aggregates(_run())
    spec = medal_table_chart(agg)
    assert spec is not None
    assert spec.columns == ("Swimmer", "Gold", "Silver", "Bronze")
    assert all(len(r) == 4 for r in spec.rows)


def test_split_ladder_prefers_individual_then_relay():
    spec = split_ladder_chart(_run())
    assert spec is not None and spec.kind == "split_ladder"
    assert len(spec.series[0].points) == 2
    # times come through as clock-formatted displays
    assert spec.series[0].points[0].display


def test_builders_return_none_when_data_absent():
    empty = {"canonical_meet": {}, "recognition_report": {"ranked_achievements": []}}
    agg = compute_aggregates(empty)
    assert pbs_per_swimmer_chart(agg) is None
    assert medal_table_chart(agg) is None
    assert split_ladder_chart(empty) is None
    assert build_chart_candidates(empty) == []


def test_progression_needs_two_real_points_and_is_lower_is_better():
    assert progression_chart("Jess Smith", [("Oct", 6312)]) is None  # one point → honest None
    spec = progression_chart("Jess Smith", [("Oct", 6312), ("Dec", 6248), ("Feb", 0)], event="100m Free")
    assert spec is not None
    assert spec.y_axis.lower_is_better is True
    assert len(spec.series[0].points) == 2  # the zero/invalid time is dropped, not plotted


def test_club_record_board_from_recordrow_like_objects():
    @dataclass
    class _Rec:
        distance: int
        stroke: str
        course: str
        gender: str
        age_group: str
        holder: str
        time_cs: int
        set_date: Optional[str] = None

        @property
        def time_str(self) -> str:
            cs = self.time_cs
            return f"{cs // 6000}:{(cs % 6000) // 100:02d}.{cs % 100:02d}" if cs >= 6000 else f"{cs // 100}.{cs % 100:02d}"

    records = [
        _Rec(100, "FR", "LC", "F", "open", "Jess Smith", 5712),
        _Rec(50, "FL", "SC", "M", "13-14", "Tunde Adeyemi", 2901),
    ]
    spec = club_record_board_chart(records)
    assert spec is not None and spec.kind == "table"
    assert spec.columns == ("Event", "Category", "Time", "Holder")
    assert len(spec.rows) == 2
    assert "Jess Smith" in spec.rows[0]
    assert club_record_board_chart([]) is None
