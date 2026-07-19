"""Finding #51 — non-numeric time markers keep their distinct status.

The bridge collapsed EVERY non-numeric time (DNS/NS/DNC/SCR/WD/DNF) into a
disqualification (`dq=True, status="dq"`) because `_time_to_cs` returns None for
any marker. `interpreter/rows._marker_or_time` already preserves the real marker
in `swim.time`, so the bridge now maps it: DQ->dq, DNS/NS/DNC->dns, SCR/WD->
scratch, DNF->dnf. Every such swim still has `finals_time_cs=None`, so the shared
`dq or finals_time_cs is None` gate keeps them out of PB/record/medal detection
exactly as before — only the human-facing status label becomes accurate.
"""

from __future__ import annotations

from collections import Counter

from mediahub.interpreter.schema_dataclasses import (
    InterpretedEvent,
    InterpretedMeet,
    InterpretedSwim,
)
from mediahub.pipeline.interpreter_bridge import interpreted_to_canonical


def _swim(name: str, time_marker: str) -> InterpretedSwim:
    return InterpretedSwim(
        swimmer_name=name,
        yob=2008,
        club="Test SC",
        place=None,
        time=time_marker,
        reaction=None,
        confidence=0.9,
        raw_row=f"{name} {time_marker}",
    )


def _results():
    swims = [
        _swim("Alice Adams", "29.10"),  # completed
        _swim("Bella Brown", "DNS"),  # did not start
        _swim("Cara Clark", "NS"),  # no swim
        _swim("Dana Doyle", "DNC"),  # did not compete
        _swim("Ella Evans", "SCR"),  # scratch
        _swim("Fiona Ford", "WD"),  # withdrawn
        _swim("Gina Green", "DNF"),  # did not finish
        _swim("Hana Hill", "DQ"),  # genuine disqualification
    ]
    event = InterpretedEvent(
        gender="F", distance_m=50, stroke="Freestyle", course="LC", age_band="", swims=swims
    )
    meet = InterpretedMeet(
        meet_name="T",
        venue=None,
        dates=None,
        course_default="LC",
        governing_body_hint=None,
        events=[event],
    )
    return interpreted_to_canonical(meet, source_filename="x.pdf").results


def test_markers_map_to_distinct_statuses():
    results = _results()
    assert len(results) == 8, "no row added or dropped"
    statuses = Counter(r.status for r in results)
    assert statuses == Counter(
        {"dns": 3, "scratch": 2, "completed": 1, "dnf": 1, "dq": 1}
    ), statuses


def test_only_dq_marker_is_flagged_dq():
    results = _results()
    dq_flagged = [r for r in results if r.dq]
    assert len(dq_flagged) == 1
    assert dq_flagged[0].status == "dq"


def test_every_no_time_marker_still_excluded_from_detection():
    # The detector exclusion gate is `dq or finals_time_cs is None`. Every marker
    # swim must still have finals_time_cs None so it never enters PB/medal logic.
    results = _results()
    for r in results:
        if r.status != "completed":
            assert r.finals_time_cs is None, f"{r.status} must have no finals time"
    completed = [r for r in results if r.status == "completed"]
    assert len(completed) == 1 and completed[0].finals_time_cs == 2910
