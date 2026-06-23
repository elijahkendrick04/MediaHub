"""
test_dq_excluded_from_moments.py — QA-013 [P0 ACCURACY/TRUST].

A DISQUALIFIED (DQ) swim has no valid result. It must be excluded ENTIRELY
from PB / time-drop / medal / achievement detection and must never become a
swimmer's PB. A club posting "new PB — biggest drop of the meet!" for a swim
that was disqualified is factually false and reputational poison.

The regression reproduced live: Kenneth Powell's only 200 Backstroke at the
Sussex County Champs was printed ``--- Kenneth Powell 11 City of Brighton &
Hove 3:29.20 DQ`` — place "---", a struck-out time, status DQ. The deterministic
interpreter split that line at the printed time and emitted a *valid* swim of
3:29.20, dropping the trailing ``DQ``. With an external prior PB of 3:43.21 the
engine then "celebrated" a fabricated 14.01s PB / huge-improvement / biggest-
drop-of-meet for a swim that never legally happened.

Root cause is the interpreter (deterministic — no AI): both extraction paths
(the multi-record line parser and the schema/table path) ignored the DSQ
marker when a printed time co-occurred. Once the interpreter emits the marker
as the swim's "time", ``interpreter_bridge`` maps a non-numeric time to
``finals_time_cs=None`` / ``dq=True`` / ``status="dq"`` and every downstream
detector (which already guards on ``dq`` / ``finals_time_cs is None``) skips it.

These tests pin the whole contract end-to-end: raw DQ line → parse → canonical
→ detection produces NO moment, while an otherwise-identical valid swim still
does.
"""

from __future__ import annotations

import pathlib
import sys
import types

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mediahub.interpreter.rows import (  # noqa: E402
    _extract_swim_from_cells,
    _parse_records_from_line,
)
from mediahub.interpreter.schema_dataclasses import (  # noqa: E402
    ColumnSchema,
    InterpretedEvent,
    InterpretedMeet,
    InterpretedSwim,
)
from mediahub.pipeline.interpreter_bridge import interpreted_to_canonical  # noqa: E402

# Detectors that produced the three fabricated "achievements" in the live repro.
from swim_content_v5.achievements.pb import (  # noqa: E402
    PBConfirmedDetector,
    PBImprovementMagnitudeDetector,
)
from swim_content_v5.achievements.standout_history import (  # noqa: E402
    BiggestDropDetector,
)
from swim_content_v5.history import SwimmerHistory  # noqa: E402
from mediahub.recognition_swim.achievements.official_pb import (  # noqa: E402
    OfficialPBDetector,
)


# The exact line shape from the source PDF (pdftotext -layout): place "---",
# the struck-out time, then the DQ status marker.
DQ_LINE = "--- Kenneth Powell 11 City of Brighton & Hove 3:29.20 DQ"

# His prior all-time PB for 200 BK LC, in seconds (3:43.21). A naive engine
# treating 3:29.20 as valid computes a fake 14.01s / 6.3% drop against this.
PRIOR_PB_SEC = 3 * 60 + 43.21  # 223.21


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _history_with_prior_pb(swimmer_key: str) -> SwimmerHistory:
    """A SwimmerHistory whose listed 200 BK LC PB is 3:43.21 — the baseline a
    fake 14.01s drop would be measured against."""
    snap = types.SimpleNamespace(
        fetch_ok=True,
        source_domain="example-results",
        pb_times={
            "200BKLC": [
                {
                    "time_sec": PRIOR_PB_SEC,
                    "date_iso": "2025-06-01",
                    "source_url": "https://example-results/x",
                    "retrieved_at": "2026-01-01",
                }
            ]
        },
    )
    return SwimmerHistory(swimmer_key, "Kenneth Powell", snap)


def _event(distance: int, stroke: str, course: str, header: str, line: str) -> InterpretedEvent:
    return InterpretedEvent(
        gender="M",
        distance_m=distance,
        stroke=stroke,
        course=course,
        age_band="11",
        swims=_parse_records_from_line(line),
        raw_header=header,
    )


def _canonical_from_events(events: list) -> "object":
    meet_i = InterpretedMeet(
        meet_name="Sussex County Champs 2026",
        venue=None,
        dates=("2026-02-01", "2026-02-02"),
        course_default="LC",
        governing_body_hint="Swim England",
        events=events,
    )
    return interpreted_to_canonical(meet_i, source_filename="sussex.pdf", source_format="pdf")


def _canonical_from_line(line: str) -> "object":
    """Parse one printed 200 BK line → canonical Meet via the real bridge."""
    return _canonical_from_events(
        [_event(200, "Backstroke", "LC", "Event 207 Open/Male 200 LC Meter Backstroke", line)]
    )


def _run_pb_detectors(result, history, swimmer_name: str = "Kenneth Powell") -> list:
    """Drive every PB / time-drop / official-PB detector over one result."""
    ctx = types.SimpleNamespace(start_date="2026-02-01", end_date="2026-02-02")
    out = []
    for det in (
        PBConfirmedDetector(),
        PBImprovementMagnitudeDetector(),
        BiggestDropDetector(),
        OfficialPBDetector(),
    ):
        out.extend(
            det.detect(
                result,
                ctx,
                history,
                all_results=[result],
                extra={"swimmer_name": swimmer_name},
            )
        )
    return out


# ---------------------------------------------------------------------------
# 1. Interpreter root cause — the DSQ marker must void the printed time
# ---------------------------------------------------------------------------


def test_line_parser_voids_printed_time_on_dq():
    """``... 3:29.20 DQ`` parses to ONE swim whose time is the DSQ marker, not
    the struck-out 3:29.20 (the bug emitted a valid 3:29.20)."""
    swims = _parse_records_from_line(DQ_LINE)
    assert len(swims) == 1
    swim = swims[0]
    assert swim.swimmer_name == "Kenneth Powell"
    assert swim.club == "City of Brighton & Hove"  # club preserved, not eaten
    assert swim.time == "DQ"
    assert swim.time != "3:29.20"


def test_line_parser_dq_without_printed_time_still_marked():
    """A DQ with no printed time at all still yields the marker."""
    swims = _parse_records_from_line("--- Jane Doe 12 Some Club DQ")
    assert len(swims) == 1
    assert swims[0].time == "DQ"


def test_line_parser_valid_swim_unaffected():
    """A normal finish keeps its real time — the fix must not touch valid rows."""
    swims = _parse_records_from_line("1 Kenneth Powell 11 City of Brighton & Hove 3:43.21")
    assert len(swims) == 1
    assert swims[0].time == "3:43.21"
    assert swims[0].place == 1


def test_line_parser_two_up_valid_plus_dq():
    """A two-records-per-line layout splits a valid swim from a DQ correctly."""
    line = "1 A Smith 12 ClubA 28.73   --- B Jones 13 ClubB 32.10 DQ"
    swims = _parse_records_from_line(line)
    by_name = {s.swimmer_name: s.time for s in swims}
    assert by_name == {"A Smith": "28.73", "B Jones": "DQ"}


def test_schema_path_voids_printed_time_on_dq_cell():
    """The schema/table extraction path also honours a DQ status cell that sits
    alongside a printed time."""
    schemas = [
        ColumnSchema("place", "place", 0.9, col_index=0),
        ColumnSchema("name", "name", 0.9, col_index=1),
        ColumnSchema("yob", "yob", 0.9, col_index=2),
        ColumnSchema("club", "club", 0.9, col_index=3),
        ColumnSchema("time", "time", 0.9, col_index=4),
        ColumnSchema("status", "status", 0.5, col_index=5),
    ]
    dq_swim = _extract_swim_from_cells(
        ["---", "Kenneth Powell", "11", "City of Brighton & Hove", "3:29.20", "DQ"],
        schemas,
    )
    assert dq_swim is not None
    assert dq_swim.time == "DQ"

    valid_swim = _extract_swim_from_cells(
        ["1", "Kenneth Powell", "11", "City of Brighton & Hove", "3:43.21", ""],
        schemas,
    )
    assert valid_swim is not None
    assert valid_swim.time == "3:43.21"


# ---------------------------------------------------------------------------
# 2. Canonical bridge — DQ rows become dq / status=dq / no finals time
# ---------------------------------------------------------------------------


def test_bridge_marks_dq_result_no_finals_time():
    """Parsing the DQ line and bridging to canonical yields a disqualified
    result with NO valid finals time."""
    meet = _canonical_from_line(DQ_LINE)
    assert len(meet.results) == 1
    r = meet.results[0]
    assert r.dq is True
    assert r.status == "dq"
    assert r.finals_time_cs is None


def test_bridge_keeps_valid_result_completed():
    """A valid swim bridges to a completed result with a real finals time."""
    meet = _canonical_from_line("1 Kenneth Powell 11 City of Brighton & Hove 3:43.21")
    assert len(meet.results) == 1
    r = meet.results[0]
    assert r.dq is False
    assert r.status == "completed"
    assert r.finals_time_cs == 3 * 6000 + 43 * 100 + 21  # 22321 cs


# ---------------------------------------------------------------------------
# 3. End-to-end — a DQ swim produces NO moment and never becomes a PB
# ---------------------------------------------------------------------------


def test_dq_swim_produces_no_pb_or_timedrop_moment():
    """The headline regression: raw DQ line → canonical → detection fires NOTHING,
    even with a prior PB of 3:43.21 that would otherwise yield a fake 14.01s drop.

    Before the fix the interpreter emitted a valid 3:29.20 here, so all three
    detectors fired (confirmed PB, huge improvement, biggest drop of meet) — this
    assertion failed. After the fix the swim is disqualified and excluded.
    """
    meet = _canonical_from_line(DQ_LINE)
    dq_result = meet.results[0]
    history = _history_with_prior_pb(dq_result.swimmer_key)

    moments = _run_pb_detectors(dq_result, history)
    assert moments == [], f"DQ swim must yield no moment, got {[m.type for m in moments]}"


def test_dq_swim_does_not_update_pb_history():
    """The DQ swim must not become the swimmer's PB: their listed best stays
    3:43.21 and the disqualified 3:29.20 is not treated as a faster time."""
    meet = _canonical_from_line(DQ_LINE)
    dq_result = meet.results[0]
    history = _history_with_prior_pb(dq_result.swimmer_key)

    # The prior PB is unchanged, and the void swim carries no comparable time.
    assert history.best_time_in_event(200, "BK", "LC") == PRIOR_PB_SEC
    assert dq_result.finals_time_cs is None


def test_valid_swim_control_still_fires_pb_moment():
    """Control: an otherwise-identical *valid* 3:29.20 (faster than the 3:43.21
    prior PB) DOES fire moments — proving the detector wiring is live and that
    the DQ exclusion, not broken plumbing, is what silences the disqualified
    swim above."""
    meet = _canonical_from_line("1 Kenneth Powell 11 City of Brighton & Hove 3:29.20")
    valid_result = meet.results[0]
    assert valid_result.dq is False
    assert valid_result.finals_time_cs is not None

    history = _history_with_prior_pb(valid_result.swimmer_key)
    moments = _run_pb_detectors(valid_result, history)
    fired = {m.type for m in moments}
    assert "pb_confirmed" in fired
    assert "biggest_drop_candidate" in fired


# ---------------------------------------------------------------------------
# 4. Cross-event control — drop the DQ swim, keep the same swimmer's valid swim
# ---------------------------------------------------------------------------


def test_dq_in_one_event_does_not_suppress_valid_swim_in_another():
    """Oscar Yu has a DQ'd 200 IM (Event 302, "2:55.00 DQ") AND a valid 200
    Backstroke (Event 207, 2:55.80). The DQ IM must yield NO moment — even
    though 2:55.00 would beat a prior IM PB, proving the filter acts per-swim at
    parse/detection independent of any PB comparison — while the valid 200 Back
    must STILL produce its real PB (was 3:03.47, -7.67s).
    """
    meet = _canonical_from_events(
        [
            _event(
                200,
                "Individual Medley",
                "LC",
                "Event 302 Open/Male 200 LC Meter IM",
                "--- Oscar Yu 13 City of Brighton & Hove 2:55.00 DQ",
            ),
            _event(
                200,
                "Backstroke",
                "LC",
                "Event 207 Open/Male 200 LC Meter Backstroke",
                "1 Oscar Yu 13 City of Brighton & Hove 2:55.80",
            ),
        ]
    )
    by_event = {(r.distance, r.stroke): r for r in meet.results}
    im = by_event[(200, "IM")]
    back = by_event[(200, "BK")]

    # One swimmer, two events: IM disqualified, Back a valid finish.
    assert im.swimmer_key == back.swimmer_key
    assert im.dq is True and im.finals_time_cs is None
    assert back.dq is False and back.finals_time_cs == 2 * 6000 + 55 * 100 + 80  # 17580 cs

    # Prior PBs: an IM best (3:10.00) the DQ 2:55.00 WOULD beat if treated as
    # valid, and a Back best (3:03.47) the valid 2:55.80 genuinely beats.
    snap = types.SimpleNamespace(
        fetch_ok=True,
        source_domain="example-results",
        pb_times={
            "200IMLC": [
                {
                    "time_sec": 190.00,
                    "date_iso": "2025-06-01",
                    "source_url": "https://example-results/x",
                    "retrieved_at": "2026-01-01",
                }
            ],
            "200BKLC": [
                {
                    "time_sec": 3 * 60 + 3.47,  # 183.47
                    "date_iso": "2025-06-01",
                    "source_url": "https://example-results/x",
                    "retrieved_at": "2026-01-01",
                }
            ],
        },
    )
    history = SwimmerHistory(im.swimmer_key, "Oscar Yu", snap)

    # (a) DQ IM → no moment, despite a beatable prior IM PB.
    im_moments = _run_pb_detectors(im, history, swimmer_name="Oscar Yu")
    assert im_moments == [], f"DQ IM must yield no moment, got {[m.type for m in im_moments]}"

    # (b) valid 200 Back in the SAME meet by the SAME swimmer → real PB stands.
    back_moments = _run_pb_detectors(back, history, swimmer_name="Oscar Yu")
    back_fired = {m.type for m in back_moments}
    assert "pb_confirmed" in back_fired, f"valid 200 Back must still PB, got {back_fired}"
