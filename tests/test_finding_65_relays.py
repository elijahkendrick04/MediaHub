"""Finding #65 - relays are unmodelled in the free-text interpreter.

A relay event header ("4 x 100m Freestyle Relay", "Girls 200m Medley Relay")
reuses the same distance + stroke vocabulary as an individual event, so the
free-text inducer (events_induce.py) turns it into a bogus *individual* event
("100m Freestyle", "200m Individual Medley"). Its legs then flow through the
canonical bridge as individual RaceResults and can seed individual PB / medal
detection with wrong event keys.

The deterministic fix adds an ``is_relay`` flag to InterpretedEvent, sets it in
``induce_events`` from a precise relay-header regex, and makes
``interpreted_to_canonical`` skip relay events. These tests FAIL on the pre-fix
tree (no is_relay flag; the bridge emits a phantom individual result) and PASS
after it. Tiny synthetic inputs only - no corpus ZIPs/PDFs.
"""
from __future__ import annotations

import pytest

from mediahub.interpreter.events_induce import induce_events
from mediahub.interpreter.schema_dataclasses import (
    IngestStream,
    InterpretedMeet,
    InterpretedSwim,
    Line,
)
from mediahub.pipeline.interpreter_bridge import interpreted_to_canonical


def _induce_one(header: str):
    stream = IngestStream(text=header, lines=[Line(text=header)], tables=[])
    events = induce_events(stream)
    assert len(events) == 1, f"expected exactly one induced event for {header!r}"
    return events[0]


@pytest.mark.parametrize(
    "header",
    [
        "Event 12 Girls 4 x 50m Medley Relay",
        "Boys 4 x 100m Freestyle Relay",
        "Girls 4x50m Freestyle Relay",
        "Mixed 400m Freestyle Relay",
        "Girls 200m Medley Relay",
    ],
)
def test_relay_header_is_flagged(header):
    ev = _induce_one(header)
    assert getattr(ev, "is_relay", False) is True


@pytest.mark.parametrize(
    "header",
    [
        "Boys 100m Freestyle",
        "Girls 200m Individual Medley",
        "Event 5 Womens 50m Butterfly",
        "Manchester Relays 100m Freestyle",  # relay-named meet, individual event
        "City Relay Gala 200m Backstroke",
    ],
)
def test_individual_header_not_flagged(header):
    ev = _induce_one(header)
    assert getattr(ev, "is_relay", False) is False


def _swim(name: str, time: str) -> InterpretedSwim:
    return InterpretedSwim(
        swimmer_name=name,
        yob=None,
        club="Test SC",
        place=1,
        time=time,
        reaction=None,
        confidence=0.9,
        raw_row=f"1 {name} Test SC {time}",
    )


def test_bridge_skips_relay_events_but_keeps_individuals():
    # Induce both stubs through the real inducer (so is_relay is set by the
    # production code path), then attach one swim to each and run the bridge.
    individual = _induce_one("Boys 200m Backstroke")
    relay = _induce_one("Boys 4 x 100m Freestyle Relay")

    individual.swims = [_swim("Solo Swimmer", "2:05.00")]
    relay.swims = [_swim("Relay Legone", "3:45.00")]

    meet = InterpretedMeet(
        meet_name="Test Meet",
        venue="Test Pool",
        dates=("2026-02-15", "2026-02-15"),
        course_default="LC",
        governing_body_hint=None,
        events=[individual, relay],
    )

    canonical = interpreted_to_canonical(meet, source_filename="relay.txt")

    distances = sorted(r.distance for r in canonical.results)

    # Pre-fix the bridge also emits the relay leg as a phantom individual
    # "100m Freestyle" result -> distances == [100, 200]. After the fix only the
    # genuine individual 200m Backstroke survives.
    assert distances == [200], f"relay leg leaked into individual results: {distances}"
    assert len(canonical.results) == 1
