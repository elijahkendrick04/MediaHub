"""Roadmap 1.11 build 2 — deterministic aggregates over a processed run."""

from __future__ import annotations

from mediahub.charts.aggregates import compute_aggregates


def _run() -> dict:
    return {
        "canonical_meet": {
            "name": "County Champs",
            "swimmers": {
                "s1": {"first_name": "Tunde", "last_name": "Adeyemi"},
                "s2": {"first_name": "Jess", "last_name": "Smith"},
                "s3": {"first_name": "Mo", "last_name": "Lee"},
            },
            "results": [
                {"swimmer_key": "s1", "distance": 100, "stroke": "FR", "course": "LC"},
                {"swimmer_key": "s2", "distance": 200, "stroke": "FR", "course": "LC"},
                {"swimmer_key": "s3", "distance": 50, "stroke": "FL", "course": "LC"},
            ],
        },
        "recognition_report": {
            "meet_name": "County Champs",
            "n_swims_analysed": 18,
            "ranked_achievements": [
                {"achievement": {"type": "pb_confirmed", "swimmer_name": "Tunde Adeyemi", "swimmer_id": "s1", "event": "100m Free", "swim_id": "a1", "raw_facts": {"drop_seconds": 1.42}}},
                {"achievement": {"type": "pb_confirmed", "swimmer_name": "Jess Smith", "swimmer_id": "s2", "event": "200m Free", "swim_id": "a2", "raw_facts": {"drop_seconds": 2.6}}},
                {"achievement": {"type": "official_pb_confirmed", "swimmer_name": "Jess Smith", "swimmer_id": "s2", "event": "100m Back", "swim_id": "a3", "raw_facts": {}}},
                {"achievement": {"type": "medal_gold", "swimmer_name": "Tunde Adeyemi", "swimmer_id": "s1", "event": "100m Free", "swim_id": "a1"}},
                {"achievement": {"type": "medal_silver", "swimmer_name": "Jess Smith", "swimmer_id": "s2", "event": "200m Free", "swim_id": "a2"}},
                {"achievement": {"type": "club_record", "swimmer_name": "Jess Smith", "swimmer_id": "s2", "event": "100m Back", "swim_id": "a3"}},
            ],
        },
    }


def test_counts_consume_detector_output():
    agg = compute_aggregates(_run())
    assert agg.n_swims == 18
    assert agg.n_swimmers == 3  # distinct racers from the roster
    assert agg.n_pbs == 3  # three PB achievements
    assert agg.n_medals == 2 and agg.n_gold == 1 and agg.n_silver == 1
    assert agg.n_club_records == 1


def test_pb_conversion_is_distinct_swimmers_over_racers_capped_100():
    agg = compute_aggregates(_run())
    # Two distinct swimmers PB'd (s1, s2) out of three who raced.
    assert agg.swimmers_with_pb == 2
    assert 0 < agg.pb_rate_pct <= 100
    assert round(agg.pb_rate_pct, 1) == round(100 * 2 / 3, 1)


def test_most_pbs_and_biggest_drop():
    agg = compute_aggregates(_run())
    assert agg.most_pbs == ("Jess Smith", 2)
    assert agg.biggest_drop is not None
    assert agg.biggest_drop["swimmer"] == "Jess Smith"
    assert round(agg.biggest_drop["seconds"], 2) == 2.6


def test_sources_recorded_for_explainability():
    agg = compute_aggregates(_run())
    assert agg.sources_for("medals_total") == ["a1", "a2"]
    assert "a3" in agg.sources_for("club_records")
    assert set(agg.sources_for("personal_bests")) == {"a1", "a2", "a3"}


def test_to_facts_is_numbers_only():
    facts = compute_aggregates(_run()).to_facts()
    assert facts["personal_bests"] == 3
    assert facts["gold"] == 1
    assert facts["swimmers_with_pb"] == 2
    assert facts["pb_conversion_percent"] <= 100
    # no nested structures — just headline facts the LLM may phrase
    assert all(not isinstance(v, (list, dict)) for v in facts.values())


def test_empty_run_is_empty_aggregates():
    agg = compute_aggregates({})
    assert agg.is_empty()
    assert agg.n_pbs == 0 and agg.n_medals == 0
    assert compute_aggregates(None).is_empty()  # type: ignore[arg-type]
