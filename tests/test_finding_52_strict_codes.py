"""Finding #52 — an unresolved stroke/course must not silently default to FR/LC.

interpreter_bridge._stroke_code/_course_code used to return "FR"/"LC" for any
unresolved input, so a swim whose event could not be classified was silently
bucketed as Freestyle / Long Course and compared for PBs under that guessed
event key. The fix returns None for unresolved input, stores an honest-empty
stroke/course on the RaceResult (so the PB lookup — keyed by the real event —
naturally misses instead of fabricating a PB), and raises a meet-level
`unresolved_event` needs-review warning. Well-formed events are untouched.

These tests FAIL on the pre-fix tree (_stroke_code(None) == "FR", the result's
stroke == "FR", no warning) and PASS after the fix. Tiny synthetic inputs only.
"""
from __future__ import annotations

from mediahub.interpreter.schema_dataclasses import (
    InterpretedMeet,
    InterpretedEvent,
    InterpretedSwim,
)
from mediahub.pipeline.interpreter_bridge import (
    interpreted_to_canonical,
    _stroke_code,
    _course_code,
)


def _swim(name="Jo Bloggs", club="Test SC", place=1, time="29.50"):
    return InterpretedSwim(
        swimmer_name=name,
        yob=None,
        club=club,
        place=place,
        time=time,
        reaction=None,
        confidence=0.9,
        raw_row="row",
    )


def _meet(event, course_default=None):
    return InterpretedMeet(
        meet_name="M",
        venue=None,
        dates=None,
        course_default=course_default,
        governing_body_hint=None,
        events=[event],
    )


def test_unresolved_codes_return_none_not_a_guess():
    assert _stroke_code(None) is None
    assert _stroke_code("Sidestroke") is None  # not in the canonical map
    assert _course_code(None) is None
    assert _course_code("Metric") is None      # not LC/SC/Y and no long/short token


def test_unresolved_event_swim_gets_empty_codes_and_needs_review_warning():
    ev = InterpretedEvent(
        gender="F",
        distance_m=50,
        stroke="Sidestroke",   # unmapped stroke
        course=None,           # + no course, and course_default is None below
        age_band="Open",
        swims=[_swim()],
        raw_header="Event 1 50 Sidestroke",
    )
    meet = interpreted_to_canonical(_meet(ev), source_filename="x.pdf")

    assert len(meet.results) == 1, "the swim must be kept, not dropped"
    r = meet.results[0]
    # No silent Freestyle / Long Course guess.
    assert r.stroke == "", f"expected honest-empty stroke, got {r.stroke!r}"
    assert r.course == "", f"expected honest-empty course, got {r.course!r}"
    # The real swim is retained honestly (not DQ'd, not a fake status).
    assert r.dq is False
    assert r.status == "completed"
    # A meet-level needs-review warning is surfaced.
    assert "unresolved_event" in {w.code for w in meet.warnings}


def test_wellformed_event_is_unchanged():
    ev = InterpretedEvent(
        gender="F",
        distance_m=100,
        stroke="Freestyle",
        course="Long Course",
        age_band="Open",
        swims=[_swim(time="1:02.30")],
        raw_header="Event 2 100 Freestyle",
    )
    meet = interpreted_to_canonical(_meet(ev), source_filename="x.pdf")
    r = meet.results[0]
    assert r.stroke == "FR"
    assert r.course == "LC"
    assert "unresolved_event" not in {w.code for w in meet.warnings}
