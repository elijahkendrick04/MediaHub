"""
test_interpreter_bridge_dedup.py — exact-reprint de-duplication at the
canonical seam (``pipeline/interpreter_bridge.py``).

HY-TEK MEET MANAGER printouts repeat an event's header (and its result rows)
whenever the event spills onto a new page, so the interpreter emits the event
twice and the same physical swim is parsed twice. Left unchecked that surfaces
as duplicate review cards — and breaks per-card approval, because every card is
keyed by ``swim_id`` and the approve handler flips every element sharing that
id at once, so approving one duplicate approves them all.

``interpreted_to_canonical`` is the single seam every parse path funnels
through, so it collapses exact reprints there. These tests pin both halves of
the contract: true reprints collapse to one canonical result, but genuinely
distinct swims (a heat and a final of the same event, even at the same time)
are preserved because they differ in round / A-B-final label.
"""
from __future__ import annotations

import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mediahub.interpreter import interpret_document  # noqa: E402
from mediahub.interpreter.schema_dataclasses import (  # noqa: E402
    InterpretedEvent,
    InterpretedMeet,
    InterpretedSwim,
)
from mediahub.pipeline.interpreter_bridge import interpreted_to_canonical  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _swim(name="Oscar Earthrowl", place=1, time="4:43.40", club="Sussex County"):
    return InterpretedSwim(
        swimmer_name=name,
        yob=2010,
        club=club,
        place=place,
        time=time,
        reaction=None,
        confidence=0.9,
        raw_row=f"{place} {name} {time} {club}",
    )


def _event(header, swims):
    return InterpretedEvent(
        gender="M",
        distance_m=400,
        stroke="Individual Medley",
        course="LC",
        age_band="",
        swims=list(swims),
        confidence=0.9,
        raw_header=header,
    )


def _meet(events):
    return InterpretedMeet(
        meet_name="Sussex County ASA LC Champ",
        venue="K2 Crawley",
        dates=("2026-02-15", "2026-02-15"),
        course_default="LC",
        governing_body_hint=None,
        events=list(events),
    )


def _identity(r):
    return (r.swimmer_key, r.distance, r.stroke, r.course, r.finals_time_cs, r.place)


# ---------------------------------------------------------------------------
# Unit: bridge-level de-dup
# ---------------------------------------------------------------------------


def test_exact_reprinted_event_collapses_to_one_result_per_swim():
    """The same event (identical swims) parsed twice → one result per swim."""
    header = "Event 12  Boys 400m Individual Medley"
    meet = _meet(
        [
            _event(header, [_swim(place=1), _swim("Jacob Smith", 2, "4:48.20", "Brighton SC")]),
            _event(header, [_swim(place=1), _swim("Jacob Smith", 2, "4:48.20", "Brighton SC")]),
        ]
    )

    canonical = interpreted_to_canonical(meet, source_filename="reprint.txt")

    assert len(canonical.results) == 2
    # No two canonical results share a full identity.
    idents = [_identity(r) for r in canonical.results]
    assert len(idents) == len(set(idents))


def test_collapse_emits_explainable_info_warning():
    """Dropped reprints are recorded as an auditable (non-blocking) warning."""
    header = "Event 12  Boys 400m Individual Medley"
    meet = _meet([_event(header, [_swim()]), _event(header, [_swim()])])

    canonical = interpreted_to_canonical(meet, source_filename="reprint.txt")

    codes = {w.code: w.severity for w in canonical.warnings}
    assert codes.get("duplicate_results_collapsed") == "info"
    assert not canonical.has_blocking_errors()


def test_heat_and_final_same_time_are_kept_distinct():
    """A heat and an A-final of the same event at the same time are two swims."""
    meet = _meet(
        [
            _event("Event 12  Boys 400m Individual Medley", [_swim(time="4:43.40")]),  # heat
            _event("Event 12  Boys 400m Individual Medley A Final", [_swim(time="4:43.40")]),
        ]
    )

    canonical = interpreted_to_canonical(meet, source_filename="rounds.txt")

    assert len(canonical.results) == 2
    labels = sorted((r.extra or {}).get("final_label", "") for r in canonical.results)
    assert labels == ["", "A Final"]


def test_distinct_swims_are_not_merged():
    """Different swimmers / times in one event are never collapsed."""
    meet = _meet(
        [
            _event(
                "Event 12  Boys 400m Individual Medley",
                [
                    _swim("Oscar Earthrowl", 1, "4:43.40", "Sussex County"),
                    _swim("Jacob Smith", 2, "4:48.20", "Brighton SC"),
                    _swim("Harry Jones", 3, "4:52.10", "Worthing SC"),
                ],
            )
        ]
    )

    canonical = interpreted_to_canonical(meet, source_filename="ok.txt")

    assert len(canonical.results) == 3
    assert not any(w.code == "duplicate_results_collapsed" for w in canonical.warnings)


# ---------------------------------------------------------------------------
# End-to-end: the real interpreter on a page-broken HY-TEK printout
# ---------------------------------------------------------------------------


_REPRINT_PRINTOUT = b"""Sussex County ASA- LC Champ - HY-TEK's MEET MANAGER 8.0 - 6:29 PM 15/02/2026 Page 1

Event 12  Boys 400m Individual Medley (LC)
Name                    Age  Team                 Seed Time   Finals Time
1 Earthrowl, Oscar       16  Sussex County         4:50.10     4:43.40
2 Smith, Jacob           16  Brighton SC           4:55.00     4:48.20
3 Jones, Harry           15  Worthing SC           4:58.30     4:52.10

Sussex County ASA- LC Champ - HY-TEK's MEET MANAGER 8.0 - 6:29 PM 15/02/2026 Page 2

Event 12  Boys 400m Individual Medley (LC)
Name                    Age  Team                 Seed Time   Finals Time
1 Earthrowl, Oscar       16  Sussex County         4:50.10     4:43.40
2 Smith, Jacob           16  Brighton SC           4:55.00     4:48.20
3 Jones, Harry           15  Worthing SC           4:58.30     4:52.10
"""


def test_end_to_end_repeated_header_does_not_duplicate_results():
    """The full parse of a page-broken printout yields one result per swimmer."""
    interpreted = interpret_document(_REPRINT_PRINTOUT, hint="text")
    canonical = interpreted_to_canonical(interpreted, source_filename="printout.txt")

    # Three swimmers, each appearing once despite the repeated header/page.
    assert len(canonical.results) == 3
    idents = [_identity(r) for r in canonical.results]
    assert len(idents) == len(set(idents))
