"""Regression guards for the discovery PB parser (F01 / F09 / F20).

These pin the three baseline-corruption defects fixed in
``mediahub.pb_discovery.parse_pbs``:

* **F01** — a relay leg ("4 x 100m Freestyle Relay 3:45.00") must never seed an
  individual-event PB baseline (it made real swims ship as absurd new PBs, e.g.
  −165 s). The guard covers BOTH the heuristic and interpreter paths.
* **F09** — course is resolved per row/section, not flattened per page; a mixed
  long-/short-course page keeps both courses distinct instead of filing every
  row under whichever marker was matched first.
* **F20** — a dotted calendar date ("12.03.2024") ahead of the time column must
  not be read as a 12.03 s time (which silently suppressed every real PB in
  that event).

The parser is deterministic engine code (no LLM), so these assert exact output.
"""

from __future__ import annotations

import pytest

from mediahub.pb_discovery.fetch_profile import ProfilePage
from mediahub.pb_discovery.parse_pbs import (
    _detect_course,
    _extract_times,
    _heuristic_extract_pbs,
    _interpreter_extract_pbs,
    _is_relay_row,
    parse_pbs_from_page,
)


def _page(*, text: str = "", tables=None) -> ProfilePage:
    return ProfilePage(
        url="http://example.test/profile",
        fetched_at="2026-01-01T00:00:00Z",
        text=text,
        tables=tables or [],
        fetch_success=True,
    )


# ── F01 · relay rows never become individual-event baselines ─────────────────


class TestF01RelayRejection:
    @pytest.mark.parametrize(
        "text,is_relay",
        [
            ("4 x 100m Freestyle Relay 3:45.00", True),
            ("4x100 Free Relay", True),
            ("4 × 100 Medley Relay", True),  # unicode multiplication sign
            ("4X50 Free", True),  # bare N x DIST, capital X
            ("Freestyle Relay 3:45.00", True),  # word after stroke, no "N x"
            ("Relay 100m Free 3:45", True),  # word before distance
            ("Medley Relay 200m", True),
            ("IM Relay 1:52", True),
            ("Mixed 4 x 50m Medley Relay 1:52.33", True),
            ("100m Freestyle 58.90", False),  # individual — must survive
            ("200m Individual Medley 2:20.10", False),  # 'Medley' alone is not a relay
            # A bare meet/venue name containing "relay" must NOT flag an
            # individual row: "relay" here is not adjacent to a stroke/distance.
            ("100m Freestyle 58.21 LC 15/03/2024 City of Manchester Relays", False),
            ("50m Freestyle 24.10 Summer 2024 Relays", False),
            # The "N x DIST" leg count must never false-positive on individual
            # rows (event / time / date / course digits do not form "\d x \d").
            ("100m Freestyle 58.90 15/03/2024", False),
            ("50m Backstroke 31.45 SC", False),
            ("4x100 3:45.00", True),  # …but a real bare leg count is still a relay
        ],
    )
    def test_is_relay_row(self, text, is_relay):
        assert _is_relay_row(text) is is_relay

    def test_relay_named_meet_does_not_drop_individual_pb(self):
        # Regression (adversarial finding): the heuristic scans the whole row,
        # incl. a Meet column. A meet named "…Relays" must not suppress the real
        # individual PB in that row.
        page = _page(
            tables=[
                [
                    ["Event", "Time", "Course", "Date", "Meet"],
                    ["100m Freestyle", "58.21", "LC", "15/03/2024", "City of Manchester Relays"],
                    ["200m Freestyle", "2:05.43", "LC", "10/02/2024", "Summer Meet"],
                ]
            ]
        )
        rows = _heuristic_extract_pbs(page)
        got = {r.event: r.time_canonical for r in rows}
        assert got.get("100m Freestyle") == "58.21"
        assert got.get("200m Freestyle") == "2:05.43"

    def test_qualified_relay_meet_name_does_not_drop_individual_pb(self):
        # Deeper adversarial finding: a *stroke/distance-qualified* relay token in
        # a Meet/venue column ("Freestyle Relay Cup", "City 400m Relay Gala")
        # trips a whole-row relay check even though the row IS an individual swim.
        # The relay guard is scoped to the event descriptor, so both PBs survive.
        page = _page(
            tables=[
                [
                    ["Event", "Time", "Course", "Date", "Meet"],
                    ["100m Freestyle", "58.21", "LC", "15/03/2024", "Freestyle Relay Cup"],
                    ["200m Backstroke", "2:18.90", "LC", "10/02/2024", "City 400m Relay Gala"],
                ]
            ]
        )
        rows = _heuristic_extract_pbs(page)
        got = {r.event: r.time_canonical for r in rows}
        assert got == {"100m Freestyle": "58.21", "200m Backstroke": "2:18.90"}

    def test_qualified_relay_meet_name_freetext(self):
        page = _page(text="100m Butterfly 1:02.30 Medley Relay Open 2024\n")
        rows = _heuristic_extract_pbs(page)
        assert any(r.event == "100m Butterfly" and r.time_canonical == "1:02.30" for r in rows)

    def test_heuristic_table_drops_relay_keeps_individual(self):
        page = _page(
            tables=[
                [
                    ["4 x 100m Freestyle Relay", "3:45.00", "SC"],
                    ["4 x 50m Medley Relay", "1:52.33", "SC"],
                    ["100m Freestyle", "59.90", "SC"],  # real individual PB
                ]
            ]
        )
        rows = _heuristic_extract_pbs(page)
        # No relay leg leaked as an individual baseline.
        assert all("Relay" not in r.event for r in rows)
        assert not any(r.time_canonical in ("3:45.00", "1:52.33") for r in rows)
        # The genuine individual swim is preserved unchanged.
        assert any(r.event == "100m Freestyle" and r.time_canonical == "59.90" for r in rows)

    def test_heuristic_freetext_drops_relay(self):
        page = _page(text=("4 x 100m Freestyle Relay 3:45.00\n" "100m Backstroke 1:05.50 LC\n"))
        rows = _heuristic_extract_pbs(page)
        assert not any(r.time_canonical == "3:45.00" for r in rows)
        assert any(r.event == "100m Backstroke" for r in rows)

    def test_interpreter_path_drops_relay(self):
        # Real interpreter: a relay listing followed by an individual event.
        page = _page(
            text=(
                "Club Relay Results\n"
                "Event 1 Girls 4 x 100m Freestyle Relay\n"
                "1 Anytown SC 3:45.00\n"
                "Event 2 Girls 100m Freestyle\n"
                "1 Smith, Jane 2008 Anytown 59.90\n"
            )
        )
        rows, _conf = _interpreter_extract_pbs(page)
        # The relay split must not appear as a 100m Freestyle @ 3:45.00 baseline.
        assert not any(r.time_canonical == "3:45.00" for r in rows)
        assert all(r.time_canonical != "3:45.00" for r in rows)


# ── F09 · course resolved per row, mixed pages stay distinct ─────────────────


class TestF09PerRowCourse:
    def test_detect_course_unambiguous(self):
        assert _detect_course("Long Course results") == "LC"
        assert _detect_course("Short Course results") == "SC"
        assert _detect_course("times in the 50m pool") == "LC"
        assert _detect_course("times in the 25m pool") == "SC"

    def test_detect_course_ambiguous_or_absent_is_none(self):
        # A page carrying BOTH markers is ambiguous → None (resolve per row).
        assert _detect_course("Long Course ... Short Course") is None
        # No marker at all → None (caller supplies the fallback).
        assert _detect_course("just some text with no pool marker") is None

    def test_mixed_page_keeps_lc_and_sc_distinct(self):
        page = _page(
            text="Long Course section ... Short Course section",
            tables=[
                [["100m Freestyle", "1:00.10", "LC", "12/03/2024"]],
                [["100m Freestyle", "57.80", "SC", "05/01/2024"]],
            ],
        )
        rows = _heuristic_extract_pbs(page)
        by_time = {r.time_canonical: r.course for r in rows}
        assert by_time.get("1:00.10") == "LC"
        # Regression: the faster SC time must NOT be flattened to LC.
        assert by_time.get("57.80") == "SC"

    def test_single_course_page_unchanged(self):
        # A page with only LC markers: every row is LC (no behaviour change).
        page = _page(
            text="Long Course personal bests",
            tables=[
                [
                    ["100m Freestyle", "58.90"],
                    ["200m Backstroke", "2:18.90"],
                ]
            ],
        )
        rows = _heuristic_extract_pbs(page)
        assert rows
        assert all(r.course == "LC" for r in rows)

    def test_unmarked_page_falls_back_to_lc(self):
        # Contract preserved: with no marker anywhere, rows default to "LC"
        # (the bridge coerces empty→LC downstream, and existing tests pin this).
        page = _page(tables=[[["100m Freestyle", "58.90"]]])
        rows = _heuristic_extract_pbs(page)
        assert rows and rows[0].course == "LC"

    def test_club_suffix_course_is_a_documented_limitation(self):
        # CHARACTERIZATION of the documented heuristic-path limitation: a bare
        # "SC" club suffix in a marker-less row, on a page that also carries a
        # stray "Long Course" header, resolves to the club's course. This is a
        # tolerated safe false-negative (never a fabricated PB), NOT desired
        # behaviour — pinned so any future change to page/row course precedence
        # is intentional and visible, not silent. If finding A is ever hardened,
        # flip this to assert "LC".
        page = _page(
            text=(
                "Long Course PBs\n"
                "Anytown SC 100m Freestyle 58.21\n"
                "Anytown SC 200m Backstroke 2:18.90\n"
            )
        )
        rows = _heuristic_extract_pbs(page)
        assert rows
        assert all(r.course == "SC" for r in rows)  # documented club-'SC' limitation


class TestF09InterpreterCourse:
    """The interpreter path resolves per-event course from the section header
    (event.course → header marker → page marker → 'LC'), not a flattened page."""

    def test_interpreter_resolves_course_from_section_header(self, monkeypatch):
        from types import SimpleNamespace

        import mediahub.interpreter as interp_mod

        def _swim(t):
            return SimpleNamespace(
                time=t, place=1, swimmer_name="Jane Doe", raw_row=f"1 Jane Doe {t}"
            )

        fake = SimpleNamespace(
            meet_name="Mixed-course PBs",
            overall_confidence=0.9,
            events=[
                # course unset on the event; only the raw_header names the course.
                SimpleNamespace(
                    distance_m=50,
                    stroke="Freestyle",
                    course=None,
                    raw_header="Event 1 SCM 50m Freestyle",
                    swims=[_swim("24.10")],
                ),
                SimpleNamespace(
                    distance_m=100,
                    stroke="Freestyle",
                    course=None,
                    raw_header="Event 2 LCM 100m Freestyle",
                    swims=[_swim("52.30")],
                ),
                SimpleNamespace(
                    distance_m=200,
                    stroke="Backstroke",
                    course=None,
                    raw_header="Event 3 200m Backstroke",
                    swims=[_swim("2:18.90")],
                ),
            ],
        )
        monkeypatch.setattr(interp_mod, "interpret_document", lambda *a, **k: fake)

        # Page text mixes both markers → page_course is None (ambiguous), so the
        # per-event header must decide.
        page = _page(text="Long Course and Short Course personal bests")
        rows, _conf = _interpreter_extract_pbs(page)
        by_event = {r.event: r.course for r in rows}
        assert by_event["50m Freestyle"] == "SC"  # SCM in header
        assert by_event["100m Freestyle"] == "LC"  # LCM in header
        assert by_event["200m Backstroke"] == "LC"  # no marker → 'LC' fallback


# ── F20 · dotted dates are not swim times ────────────────────────────────────


class TestF20DateNotTime:
    @pytest.mark.parametrize(
        "text,times",
        [
            ("100m Freestyle 12.03.2024 58.90", ["58.90"]),  # dotted date before time
            ("100m Freestyle 12.03.24 58.90", ["58.90"]),  # 2-digit year
            ("100m Freestyle 1.3.2024 58.90", ["58.90"]),  # single-digit d/m
            ("100m Freestyle 12/03/2024 58.90", ["58.90"]),  # slashes
            ("100m Freestyle 58.90 12.03.2024", ["58.90"]),  # date after the time
            ("100m Freestyle 2024-03-12 58.90", ["58.90"]),  # ISO date
            ("100m Free 28.50", ["28.50"]),  # plain time, no date
            # A ':'-delimited time must survive beside a dotted date — a colon
            # time can never be eaten by _DATE_RE. This freezes the highest-value
            # invariant against a future broadening of the date separators.
            ("200m Butterfly 12.03.2024 2:14.30", ["2:14.30"]),
            ("15/03/2024 1:02.34 58.90", ["1:02.34", "58.90"]),  # date first, two real times
            ("1:02.34", ["1:02.34"]),  # colon time alone
        ],
    )
    def test_extract_times_excludes_dates(self, text, times):
        assert _extract_times(text) == times

    def test_heuristic_reads_time_not_date_fragment(self):
        page = _page(tables=[[["100m Freestyle", "12.03.2024", "58.90"]]])
        rows = _heuristic_extract_pbs(page)
        assert len(rows) == 1
        row = rows[0]
        # The fake 12.03 s baseline must be gone; the real time is used…
        assert row.time_canonical == "58.90"
        # …and the date is still captured as a date.
        assert row.date == "12.03.2024"

    def test_freetext_reads_time_not_date_fragment(self):
        page = _page(text="200m Butterfly 05.11.2023 2:14.30 City Meet")
        rows = _heuristic_extract_pbs(page)
        assert rows and rows[0].time_canonical == "2:14.30"
        assert rows[0].date == "05.11.2023"


# ── end-to-end · a relay+date listing yields no fabricated baselines ─────────


def test_relay_and_date_page_produces_no_fabricated_baseline():
    """Acceptance: a relay-listing / date-bearing page produces zero
    individual-event baselines from those rows, on the public entry point."""
    page = _page(
        tables=[
            [
                ["4 x 100m Freestyle Relay", "3:45.00", "LC", "12.03.2024"],
                ["4 x 50m Medley Relay", "1:52.33", "LC", "10.02.2024"],
            ]
        ]
    )
    rows, _conf = parse_pbs_from_page(page, use_interpreter=False)
    assert rows == []
