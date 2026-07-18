"""Finding #54 regression: schema-path swims must bucket into events by the line
they were extracted from, NOT by blind positional chunking.

The schema/table extraction path used to distribute its swims across events with
``all_swims[i*chunk:(i+1)*chunk]`` where ``chunk = len(swims)//len(events)`` —
an even split that assumes every event has the same number of competitors. When
events have unequal entry counts (Event 1 has 3 swimmers, Event 2 has 1) this
silently files swims under the wrong event: a 3+1 meet becomes a 2+2 meet, so a
50m Free swimmer surfaces under the 100m Free event (wrong distance -> wrong PB,
wrong plausibility, wrong card).

Deterministic engine: the fix recovers each schema-path swim's source line index
by exact-matching its preserved raw cells against ``stream.lines`` and buckets it
into the most-recent event header at/above that line — no heuristics, no AI.
"""

from __future__ import annotations

import sys
from pathlib import Path

# legacy v5 detectors are registered on the path by ``import mediahub``; add it
# defensively so this test is import-order robust (mirrors the sibling tests).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "legacy"))

from mediahub.interpreter.rows import assign_rows_to_events  # noqa: E402
from mediahub.interpreter.schema_dataclasses import (  # noqa: E402
    ColumnSchema,
    IngestStream,
    InterpretedEvent,
    Line,
    TableCandidate,
)


def _build():
    """A 2-event meet with UNEQUAL entry counts (3 in Event 1, 1 in Event 2).

    The table rows are split from the exact same line text the ``stream.lines``
    carry, so the schema path fires and its swims can be line-matched back.
    """
    line_texts = [
        "Event 1 Girls 50 Free",
        "Alice Adams   10.00",
        "Bob Brown   20.00",
        "Cara Clark   30.00",
        "Event 2 Girls 100 Free",
        "Dana Davis   40.00",
    ]
    lines = [Line(text=t, y_position=float(i)) for i, t in enumerate(line_texts)]
    rows = [
        ["Alice Adams", "10.00"],
        ["Bob Brown", "20.00"],
        ["Cara Clark", "30.00"],
        ["Dana Davis", "40.00"],
    ]
    stream = IngestStream(
        text="\\n".join(line_texts),
        lines=lines,
        tables=[TableCandidate(rows=rows)],
    )
    schemas = [
        ColumnSchema(name="name", col_type="name", confidence=0.9, col_index=0),
        ColumnSchema(name="time", col_type="time", confidence=0.9, col_index=1),
    ]
    events = [
        InterpretedEvent(
            gender="F", distance_m=50, stroke="Free", course=None,
            age_band=None, raw_header="Event 1 Girls 50 Free",
        ),
        InterpretedEvent(
            gender="F", distance_m=100, stroke="Free", course=None,
            age_band=None, raw_header="Event 2 Girls 100 Free",
        ),
    ]
    return stream, events, schemas


def test_schema_swims_bucketed_by_line_not_chunked():
    stream, events, schemas = _build()
    assign_rows_to_events(stream, events, schemas)

    ev1_names = {s.swimmer_name for s in events[0].swims}
    ev2_names = {s.swimmer_name for s in events[1].swims}

    # No swim lost or duplicated across the two events.
    assert len(events[0].swims) + len(events[1].swims) == 4

    # Correct, line-anchored bucketing: 3 in Event 1, 1 in Event 2.
    assert ev1_names == {"Alice Adams", "Bob Brown", "Cara Clark"}
    assert ev2_names == {"Dana Davis"}

    # The exact blind-chunk regression signature: Cara Clark (a 50 Free swimmer)
    # must never fall under the 100 Free event just because the split was even.
    assert "Cara Clark" not in ev2_names
