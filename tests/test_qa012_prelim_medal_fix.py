"""
QA-012 — medals must come ONLY from finals, with the FINAL time.

A HY-TEK combined prelim/final event prints two rows for one swimmer's event:
a Preliminaries row (qualified to the final, marked with a "q"/"q430" finals-
qualification flag) and a Finals row. Each row prints two time columns — the
previous round's time and the achieved time (Seed+Prelim, or Prelim+Finals).

The old line parser truncated every row at its FIRST time token, so it:
  * surfaced the SEED/prelim time as the result (discarding the achieved time);
  * threw away the trailing "q" marker that distinguishes a heat from a final.
Both faults fed the medal detector, which then awarded a GOLD from the prelim
place-1 (with the seed time) AND a SILVER from the final with the wrong time.

Reported case — Birdy Raleigh, 50m Butterfly, City of Brighton & Hove:
  * PRELIM:  place 1, seed 32.60, swum 32.36, "q430"  (a heat — NO medal)
  * FINAL:   place 2, seed 32.36, swum 31.86          (SILVER, 31.86)
The truthful result is ONE medal: SILVER, 31.86.

These tests pin the fix at three layers: the line parser (achieved time + round
marker), the canonical bridge (prelim → "heat" round), and the medal detector
(a heat never medals; a single event yields exactly one medal moment).
"""

from __future__ import annotations

import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import mediahub  # noqa: E402,F401  (registers legacy-name shim used below)
from mediahub.interpreter import interpret_document  # noqa: E402
from mediahub.interpreter.rows import _parse_records_from_line  # noqa: E402
from mediahub.pipeline.interpreter_bridge import interpreted_to_canonical  # noqa: E402
from mediahub.recognition_swim.achievements import MedalDetector  # noqa: E402
from mediahub.web.canonical import RaceResult  # noqa: E402
from swim_content_v5.history import SwimmerHistory  # noqa: E402
from swim_content_v5.schema import MeetContext  # noqa: E402


def _t(time_str: str) -> int:
    """'mm:ss.cc' / 'ss.cc' → centiseconds (for asserting canonical times)."""
    if ":" in time_str:
        mm, rest = time_str.split(":", 1)
        ss, cc = rest.split(".")
        return int(mm) * 6000 + int(ss) * 100 + int(cc)
    ss, cc = time_str.split(".")
    return int(ss) * 100 + int(cc)


# ---------------------------------------------------------------------------
# Layer 1 — line parser: achieved (last) time + finals-qualification marker
# ---------------------------------------------------------------------------


def test_prelim_row_uses_swum_time_and_is_marked_prelim():
    """A heat row "seed swum q430" → achieved time = the SWUM time (not the
    seed), and the "q" marker flags it as a preliminary."""
    (swim,) = _parse_records_from_line(
        "1 Raleigh, Birdy 13 City of Brighton & Hove 32.60 32.36 q430"
    )
    assert swim.place == 1
    assert swim.time == "32.36"  # the swum prelim time, NOT the seed 32.60
    assert swim.round_hint == "prelim"


def test_final_row_uses_swum_time_and_is_not_prelim():
    """A finals row "prelim swum" (no "q") → achieved time = the SWUM final
    time, and the row carries no prelim marker."""
    (swim,) = _parse_records_from_line(
        "2 Raleigh, Birdy 13 City of Brighton & Hove 32.36 31.86"
    )
    assert swim.place == 2
    assert swim.time == "31.86"  # the swum final time, NOT the prelim 32.36
    assert swim.round_hint is None


def test_finals_row_with_fina_points_is_not_mistaken_for_a_prelim():
    """Plain FINA points trailing a finals time ("445", no "q") are not a
    qualification marker — the row stays a final and keeps the swum time."""
    (swim,) = _parse_records_from_line(
        "2 Raleigh, Birdy 13 City of Brighton & Hove 32.36 31.86 445"
    )
    assert swim.time == "31.86"
    assert swim.round_hint is None


def test_seed_plus_finals_timed_final_uses_finals_time():
    """A timed-final row "seed finals" → the achieved (finals) time wins; the
    old parser wrongly reported the seed."""
    (swim,) = _parse_records_from_line(
        "1 Earthrowl, Oscar 16 Sussex County 4:50.10 4:43.40"
    )
    assert swim.time == "4:43.40"
    assert swim.round_hint is None


def test_reaction_time_is_not_taken_as_the_result():
    """A sub-second reaction time printed after the swim time must never be
    read as the achieved time."""
    (swim,) = _parse_records_from_line("1 Smith Jane 2006 SPAC 27.31 0.63")
    assert swim.time == "27.31"


def test_two_competitors_on_one_line_still_split():
    """The multi-record fix must not merge two competitors who each end in a
    single time on one printed line."""
    swims = _parse_records_from_line(
        "1 Arthur, Andrew 23 UoAPS 28.73     33 Warner, Liam 16 East Lothian 32.82"
    )
    assert [(s.place, s.time) for s in swims] == [(1, "28.73"), (33, "32.82")]
    assert all(s.round_hint is None for s in swims)


# ---------------------------------------------------------------------------
# Layer 2 — canonical bridge: prelim → "heat" round; final stays medal-eligible
# ---------------------------------------------------------------------------


_PRELIM_FINAL_PRINTOUT = b"""Sussex County ASA- LC Champ - HY-TEK's MEET MANAGER 8.0 - 6:29 PM 15/02/2026 Page 1
Sussex County Long Course Championships 26 - 14/02/2026 to 01/03/2026

Event 206  Female 13 Year Olds 50 LC Meter Butterfly
Name                    Age  Team                     Seed Time   Prelim Time
Preliminaries
1 Raleigh, Birdy          13  City of Brighton & Hove   32.60       32.36   q430
Name                    Age  Team                     Prelim Time Finals Time
Finals
2 Raleigh, Birdy          13  City of Brighton & Hove   32.36       31.86
"""


def test_bridge_marks_prelim_as_heat_and_keeps_final_medal_eligible():
    """End-to-end: the prelim row becomes a 'heat' (never medal-eligible) and
    the final row stays medal-eligible with the swum FINAL time."""
    interpreted = interpret_document(_PRELIM_FINAL_PRINTOUT, hint="text")
    meet = interpreted_to_canonical(interpreted, source_filename="sussex.pdf")

    raleigh = [r for r in meet.results if "raleigh" in r.swimmer_key.lower()]
    # The heat and the final are two distinct swims (different rounds + times).
    assert len(raleigh) == 2, [(r.round, r.place, r.finals_time_cs) for r in raleigh]

    by_round = {r.round: r for r in raleigh}
    assert set(by_round) == {"heat", "timed_final"}

    heat = by_round["heat"]
    assert heat.place == 1
    assert heat.finals_time_cs == _t("32.36")  # swum prelim time, not seed 32.60

    final = by_round["timed_final"]
    assert final.place == 2
    assert final.finals_time_cs == _t("31.86")  # swum final time, not prelim 32.36


# ---------------------------------------------------------------------------
# Layer 3 — medal detector: one event → exactly one medal, from the FINAL only
# ---------------------------------------------------------------------------


def _result(place: int, time_str: str, rnd: str) -> RaceResult:
    return RaceResult(
        swimmer_key="city_of_brighton_hove:Raleigh,Birdy",
        club_code="city_of_brighton_hove",
        distance=50,
        stroke="FL",
        course="LC",
        gender="F",
        finals_time_cs=_t(time_str),
        place=place,
        round=rnd,
    )


def test_prelim_place_one_plus_final_place_two_yields_one_silver_only():
    """The reported case: a swimmer with a PRELIM place-1 and a FINAL place-2 in
    one event must yield exactly ONE medal — SILVER, with the final time — and
    NO gold from the prelim."""
    prelim = _result(1, "32.36", "heat")  # heats/prelim — must NOT medal
    final = _result(2, "31.86", "timed_final")  # the genuine SILVER
    results = [prelim, final]

    ctx = MeetContext(meet_name="Sussex County Champs 2026", meet_level="county")
    history = SwimmerHistory("city_of_brighton_hove:Raleigh,Birdy", "Birdy Raleigh")
    extra = {"swimmer_name": "Birdy Raleigh"}
    detector = MedalDetector()

    medals = []
    for swim in results:
        medals += detector.detect(swim, ctx, history, all_results=results, extra=extra)

    # Exactly one medal moment, and it is the SILVER from the final.
    assert len(medals) == 1, [m.type for m in medals]
    (medal,) = medals
    assert medal.type == "medal_silver"
    assert medal.raw_facts["place"] == 2
    assert medal.raw_facts["time_str"] == "31.86"
    # The fabricated gold is gone.
    assert not any(m.type == "medal_gold" for m in medals)


def test_end_to_end_raw_printout_yields_one_silver_no_gold():
    """The whole chain on the reported printout: raw HY-TEK text → canonical
    bridge → medal detector must produce exactly ONE medal moment (the SILVER
    final, 31.86) and NO fabricated gold from the prelim place-1."""
    interpreted = interpret_document(_PRELIM_FINAL_PRINTOUT, hint="text")
    meet = interpreted_to_canonical(interpreted, source_filename="sussex.pdf")
    results = [r for r in meet.results if "raleigh" in r.swimmer_key.lower()]

    ctx = MeetContext(meet_name="Sussex County Champs 2026", meet_level="county")
    history = SwimmerHistory("city_of_brighton_hove:Raleigh,Birdy", "Birdy Raleigh")
    extra = {"swimmer_name": "Birdy Raleigh"}
    detector = MedalDetector()

    medals = []
    for swim in results:
        medals += detector.detect(swim, ctx, history, all_results=results, extra=extra)

    assert [m.type for m in medals] == ["medal_silver"]
    assert medals[0].raw_facts["time_str"] == "31.86"


def test_prelim_heat_place_one_never_medals():
    """A heat/prelim place-1 on its own must never produce a (gold) medal."""
    prelim = _result(1, "32.36", "heat")
    ctx = MeetContext(meet_name="Sussex County Champs 2026", meet_level="county")
    history = SwimmerHistory("city_of_brighton_hove:Raleigh,Birdy", "Birdy Raleigh")
    detector = MedalDetector()

    medals = detector.detect(
        prelim, ctx, history, all_results=[prelim], extra={"swimmer_name": "Birdy Raleigh"}
    )
    assert medals == []


# ---------------------------------------------------------------------------
# Layer 1b — structured-table (cell) path: the "q" marker marks a prelim too
# ---------------------------------------------------------------------------


def _prelim_schemas():
    from mediahub.interpreter.schema_dataclasses import ColumnSchema

    return [
        ColumnSchema(name="place", col_type="place", confidence=0.9, col_index=0),
        ColumnSchema(name="name", col_type="name", confidence=0.9, col_index=1),
        ColumnSchema(name="club", col_type="club", confidence=0.9, col_index=3),
        ColumnSchema(name="seed_time", col_type="seed_time", confidence=0.9, col_index=4),
        ColumnSchema(name="time", col_type="time", confidence=0.9, col_index=5),
    ]


def test_cell_path_prelim_row_with_qualifier_cell_is_marked_prelim():
    """QA-012, cell path: a structured-table prelim row whose qualifier marker
    ("q430") lands in its own cell must set round_hint='prelim' — exactly as
    the token path does — so the bridge maps it to a heat and it can never
    surface as a fabricated final/medal."""
    from mediahub.interpreter.rows import _extract_swim_from_cells

    cells = ["1", "Raleigh, Birdy", "13", "City of Brighton & Hove", "32.60", "32.36", "q430"]
    swim = _extract_swim_from_cells(cells, _prelim_schemas())
    assert swim is not None
    assert swim.time == "32.36"
    assert swim.round_hint == "prelim"


def test_cell_path_qualifier_trailing_time_cell_is_marked_prelim():
    """The marker can also trail the time inside the time cell ("32.36 q")."""
    from mediahub.interpreter.rows import _extract_swim_from_cells

    cells = ["1", "Raleigh, Birdy", "13", "City of Brighton & Hove", "32.60", "32.36 q"]
    swim = _extract_swim_from_cells(cells, _prelim_schemas())
    assert swim is not None
    assert swim.round_hint == "prelim"


def test_cell_path_final_row_without_qualifier_has_no_round_hint():
    """A finals row (no "q" marker) stays medal-eligible: round_hint is None so
    the bridge treats it as a timed final."""
    from mediahub.interpreter.rows import _extract_swim_from_cells

    cells = ["2", "Raleigh, Birdy", "13", "City of Brighton & Hove", "32.36", "31.86"]
    swim = _extract_swim_from_cells(cells, _prelim_schemas())
    assert swim is not None
    assert swim.round_hint is None
