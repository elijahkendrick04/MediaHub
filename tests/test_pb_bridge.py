"""Tests for `mediahub.pipeline.pb_bridge`.

The bridge is pure-function glue between `pb_discovery.PBDiscovery`
results and the legacy `pb_snapshots` shape consumed by the swim
recognition pipeline. Every function here is deterministic and
I/O-free, so the suite is fast and easy to reason about.
"""
from __future__ import annotations

import pytest

from mediahub.pb_discovery.discover import PBDiscovery, PBSource
from mediahub.pb_discovery.parse_pbs import PBRow
from mediahub.pipeline.pb_bridge import (
    BridgedSnapshot,
    _event_key,
    _split_event,
    _stroke_to_code,
    _time_to_seconds,
    build_pb_snapshots,
    discovery_to_snapshot,
)


# ---------------------------------------------------------------------------
# _stroke_to_code
# ---------------------------------------------------------------------------


class TestStrokeToCode:
    @pytest.mark.parametrize(
        "label, code",
        [
            ("Freestyle", "FR"),
            ("freestyle", "FR"),
            ("Free", "FR"),
            ("Backstroke", "BK"),
            ("Back", "BK"),
            ("Breaststroke", "BR"),
            ("Breast", "BR"),
            ("Butterfly", "FL"),
            ("Fly", "FL"),
            ("Individual Medley", "IM"),
            ("Medley", "IM"),
            ("IM", "IM"),
            ("im", "IM"),
        ],
    )
    def test_exact_canonical_labels(self, label: str, code: str) -> None:
        assert _stroke_to_code(label) == code

    def test_handles_whitespace_and_case(self) -> None:
        assert _stroke_to_code("  Freestyle  ") == "FR"
        assert _stroke_to_code("FREESTYLE") == "FR"

    def test_substring_match_used_as_fallback(self) -> None:
        # "200m Freestyle" leaves "Freestyle" — should still resolve once stroke is isolated,
        # but verify substring fallback path with an unusual wrapping.
        assert _stroke_to_code("400 individual medley relay") == "IM"
        assert _stroke_to_code("women's freestyle final") == "FR"

    def test_empty_and_unknown(self) -> None:
        assert _stroke_to_code("") == ""
        assert _stroke_to_code("   ") == ""
        assert _stroke_to_code(None) == ""  # type: ignore[arg-type]
        assert _stroke_to_code("scuba") == ""


# ---------------------------------------------------------------------------
# _time_to_seconds
# ---------------------------------------------------------------------------


class TestTimeToSeconds:
    def test_seconds_only_two_digit_fraction(self) -> None:
        assert _time_to_seconds("59.87") == pytest.approx(59.87)

    def test_minutes_and_seconds(self) -> None:
        assert _time_to_seconds("1:02.34") == pytest.approx(62.34)

    def test_long_distance(self) -> None:
        # 1500 free in ~15:25.10 → 925.10
        assert _time_to_seconds("15:25.10") == pytest.approx(925.10)

    def test_single_digit_fraction_scales_to_tenths(self) -> None:
        # The regex captures 1–2 fractional digits; single digit means tenths.
        assert _time_to_seconds("59.8") == pytest.approx(59.8)
        assert _time_to_seconds("1:02.3") == pytest.approx(62.3)

    def test_colon_instead_of_dot_is_accepted(self) -> None:
        # The pattern allows "[.:]" as the centisecond separator.
        assert _time_to_seconds("1:02:34") == pytest.approx(62.34)

    def test_strips_whitespace(self) -> None:
        assert _time_to_seconds("  1:02.34  ") == pytest.approx(62.34)

    def test_empty_or_invalid_returns_none(self) -> None:
        assert _time_to_seconds("") is None
        assert _time_to_seconds(None) is None  # type: ignore[arg-type]
        assert _time_to_seconds("abc") is None
        assert _time_to_seconds("99") is None  # no fraction
        assert _time_to_seconds("DNF") is None


# ---------------------------------------------------------------------------
# _event_key + _split_event
# ---------------------------------------------------------------------------


class TestEventKey:
    def test_basic_concatenation(self) -> None:
        assert _event_key(100, "FR", "LC") == "100FRLC"
        assert _event_key(50, "BR", "SC") == "50BRSC"

    def test_event_key_roundtrip_with_stroke_mapping(self) -> None:
        # The combination of _split_event + _stroke_to_code should produce stable keys.
        distance, stroke_label = _split_event("100m Freestyle")
        assert distance == 100
        assert _event_key(distance, _stroke_to_code(stroke_label), "LC") == "100FRLC"


class TestSplitEvent:
    @pytest.mark.parametrize(
        "raw, distance, stroke",
        [
            ("100m Freestyle", 100, "Freestyle"),
            ("200 IM", 200, "IM"),
            ("50 Free", 50, "Free"),
            ("1500m Freestyle", 1500, "Freestyle"),
            ("400 Individual Medley", 400, "Individual Medley"),
        ],
    )
    def test_parses_distance_and_stroke(self, raw: str, distance: int, stroke: str) -> None:
        d, s = _split_event(raw)
        assert d == distance
        assert s == stroke

    def test_handles_leading_whitespace(self) -> None:
        assert _split_event("  100m Freestyle") == (100, "Freestyle")

    def test_returns_none_on_unparseable(self) -> None:
        assert _split_event("") == (None, "")
        assert _split_event("nope") == (None, "")
        # No distance
        assert _split_event("Freestyle") == (None, "")

    def test_uppercase_m_unit(self) -> None:
        # Regex is case-insensitive on the trailing "m"
        assert _split_event("100M Backstroke") == (100, "Backstroke")


# ---------------------------------------------------------------------------
# discovery_to_snapshot
# ---------------------------------------------------------------------------


def _make_pbrow(
    event: str = "100m Freestyle",
    course: str = "LC",
    time_canonical: str = "1:02.34",
    date: str | None = "2024-05-20",
    meet: str | None = "City Champs",
    rank: int | None = 1,
) -> PBRow:
    return PBRow(
        event=event,
        course=course,
        time_canonical=time_canonical,
        date=date,
        meet=meet,
        rank=rank,
    )


def _make_discovery(
    pbs: list[PBRow] | None = None,
    *,
    confidence: float = 0.9,
    chosen_source: PBSource | None = None,
    sources_tried: list[PBSource] | None = None,
    cache_hit: bool = False,
) -> PBDiscovery:
    return PBDiscovery(
        swimmer_query="Test Swimmer",
        sources_tried=sources_tried or [],
        chosen_source=chosen_source,
        pbs=pbs or [],
        confidence=confidence,
        cache_hit=cache_hit,
    )


def _make_source(*, fetch_success: bool = True, parse_confidence: float = 0.0) -> PBSource:
    return PBSource(
        url="https://example.org/swimmers/test",
        domain="example.org",
        fetched_at="2024-05-21T12:00:00Z",
        parse_confidence=parse_confidence,
        pbs=[],
        fetch_success=fetch_success,
    )


class TestDiscoveryToSnapshot:
    def test_no_candidates_is_a_failed_lookup(self) -> None:
        # No sources were even tried — the search produced nothing (throttle,
        # network down). That IS a fetch failure, never "no PBs".
        snap = discovery_to_snapshot(_make_discovery([]), "swimmer:1")
        assert isinstance(snap, BridgedSnapshot)
        assert snap.tiref == "swimmer:1"
        assert snap.pb_times == {}
        assert snap.fetch_ok is False
        assert snap.no_history is False
        assert snap.error == "web search returned no candidate pages"

    def test_all_fetches_failed_is_a_failed_lookup(self) -> None:
        snap = discovery_to_snapshot(
            _make_discovery([], sources_tried=[_make_source(fetch_success=False)]),
            "swimmer:1",
        )
        assert snap.fetch_ok is False
        assert snap.no_history is False
        assert snap.error == "could not fetch any candidate page"

    def test_pages_reached_but_nothing_found_is_no_history_not_failure(self) -> None:
        # We saw the web and found nothing verifiable for this athlete — a
        # completed lookup with an honest empty answer, not a failed fetch.
        snap = discovery_to_snapshot(
            _make_discovery([], sources_tried=[_make_source(fetch_success=True)]),
            "swimmer:1",
        )
        assert snap.fetch_ok is True
        assert snap.no_history is True
        assert snap.error is None

    def test_cache_hit_propagates_to_from_cache(self) -> None:
        snap = discovery_to_snapshot(
            _make_discovery([_make_pbrow()], cache_hit=True), "swimmer:1"
        )
        assert snap.from_cache is True
        fresh = discovery_to_snapshot(_make_discovery([_make_pbrow()]), "swimmer:1")
        assert fresh.from_cache is False

    def test_single_pb_populates_pb_times(self) -> None:
        snap = discovery_to_snapshot(
            _make_discovery([_make_pbrow()]),
            "swimmer:1",
        )
        assert "100FRLC" in snap.pb_times
        assert snap.fetch_ok is True
        assert snap.error is None
        entry = snap.pb_times["100FRLC"][0]
        assert entry["time_sec"] == pytest.approx(62.34)
        assert entry["date_iso"] == "2024-05-20"
        assert entry["meet"] == "City Champs"
        assert entry["rank"] == 1

    def test_multiple_pbs_same_event_appended(self) -> None:
        rows = [
            _make_pbrow(time_canonical="1:02.34", date="2024-05-20"),
            _make_pbrow(time_canonical="1:01.99", date="2024-09-10"),
        ]
        snap = discovery_to_snapshot(_make_discovery(rows), "swimmer:1")
        assert len(snap.pb_times["100FRLC"]) == 2
        # Order is preserved as inserted.
        assert snap.pb_times["100FRLC"][0]["time_sec"] == pytest.approx(62.34)
        assert snap.pb_times["100FRLC"][1]["time_sec"] == pytest.approx(61.99)

    def test_unknown_course_defaults_to_lc(self) -> None:
        snap = discovery_to_snapshot(
            _make_discovery([_make_pbrow(course="??")]),
            "swimmer:1",
        )
        assert "100FRLC" in snap.pb_times

    def test_sc_and_y_courses_preserved(self) -> None:
        rows = [
            _make_pbrow(course="SC"),
            _make_pbrow(course="Y"),
        ]
        snap = discovery_to_snapshot(_make_discovery(rows), "swimmer:1")
        assert "100FRSC" in snap.pb_times
        assert "100FRY" in snap.pb_times

    def test_pb_with_unparseable_event_is_skipped(self) -> None:
        rows = [
            _make_pbrow(event="Freestyle"),  # no distance — skipped
            _make_pbrow(event="100m Freestyle"),  # kept
        ]
        snap = discovery_to_snapshot(_make_discovery(rows), "swimmer:1")
        assert list(snap.pb_times.keys()) == ["100FRLC"]
        assert len(snap.pb_times["100FRLC"]) == 1

    def test_pb_with_unparseable_time_is_skipped(self) -> None:
        rows = [_make_pbrow(time_canonical="DNF")]
        snap = discovery_to_snapshot(_make_discovery(rows), "swimmer:1")
        assert snap.pb_times == {}
        # Discovery returned PB rows (an identity-gated page listed them), so
        # the lookup completed even though no row was parseable into a time.
        assert snap.fetch_ok is True

    def test_pb_with_unknown_stroke_is_skipped(self) -> None:
        rows = [_make_pbrow(event="100m Scuba")]
        snap = discovery_to_snapshot(_make_discovery(rows), "swimmer:1")
        assert snap.pb_times == {}

    def test_chosen_source_metadata_flows_through(self) -> None:
        source = PBSource(
            url="https://example.org/swimmers/test",
            domain="example.org",
            fetched_at="2024-05-21T12:00:00Z",
            parse_confidence=0.92,
            pbs=[],
        )
        snap = discovery_to_snapshot(
            _make_discovery([_make_pbrow()], chosen_source=source),
            "swimmer:1",
        )
        assert snap.source_url == "https://example.org/swimmers/test"
        assert snap.retrieved_at == "2024-05-21T12:00:00Z"
        assert snap.source_domain == "example.org"
        # Same metadata copied into each pb_times entry.
        entry = snap.pb_times["100FRLC"][0]
        assert entry["source_url"] == "https://example.org/swimmers/test"
        assert entry["retrieved_at"] == "2024-05-21T12:00:00Z"

    def test_pbs_found_count_as_completed_even_at_zero_confidence(self) -> None:
        # The identity gate already vetted any page whose PBs were chosen;
        # a low stored confidence must not reclassify a found baseline as a
        # failed fetch (the audit would then overcount "lookups failed").
        snap = discovery_to_snapshot(
            _make_discovery([_make_pbrow()], confidence=0.0),
            "swimmer:1",
        )
        assert snap.fetch_ok is True
        assert snap.error is None


# ---------------------------------------------------------------------------
# build_pb_snapshots
# ---------------------------------------------------------------------------


class TestBuildPbSnapshots:
    def test_empty_input_yields_empty_dict(self) -> None:
        assert build_pb_snapshots([]) == {}

    def test_multiple_swimmers_keyed_correctly(self) -> None:
        a = _make_discovery([_make_pbrow()])
        b = _make_discovery([_make_pbrow(event="200 IM", time_canonical="2:15.40")])
        result = build_pb_snapshots([("swimmer:A", a), ("swimmer:B", b)])
        assert set(result.keys()) == {"swimmer:A", "swimmer:B"}
        assert "100FRLC" in result["swimmer:A"].pb_times
        assert "200IMLC" in result["swimmer:B"].pb_times

    def test_tiref_matches_provided_key(self) -> None:
        disc = _make_discovery([_make_pbrow()])
        result = build_pb_snapshots([("swimmer:99", disc)])
        assert result["swimmer:99"].tiref == "swimmer:99"
