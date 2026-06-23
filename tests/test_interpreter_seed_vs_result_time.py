"""QA-014 regression: the results parser must read the SWUM result, never the SEED.

Root cause (deterministic PDF/text results parser, no AI): HY-TEK MEET MANAGER
prints a swimmer's *Seed* (entry) time immediately before the time they actually
swam (the *Finals Time*, or *Prelim Time* on a prelim-only sheet). The result is
the RIGHTMOST time column before the FINA points; "Seed Time" is NEVER the result.

The line parser used to close a record at the FIRST time token, so it took the
Seed as the swum time and discarded the real result — inverting every PB,
time-drop, barrier and medal-time claim built on it (a swimmer who swam SLOWER
than their seed was reported as setting a big PB).

These tests pin the fix on both extraction paths:

  * the header-driven schema path (priority Finals Time > Prelim Time; never
    Seed Time — selected by column LABEL, not fixed position), and
  * the collapsed-line parser (the path that actually fired on the Sussex PDF),
    where the result is the last time token of a record's trailing time run and
    the seed is the one before it.

Objective proof is the Sussex County Championships 2026 file (run 72c223c97b54):
Event 207 Oscar Yu placed 6th (227 FINA pts) so he SWAM 3:03.47, not his
2:55.80 seed; Event 202 Birdy Raleigh swam 2:22.28, not her 2:19.80 seed (so no
"first time under 2:20").
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Legacy v5 detectors live under <repo>/legacy on the import path (registered by
# `import mediahub`); add it defensively so this test is import-order robust.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "legacy"))

from mediahub.interpreter.ontology_loader import OntologyLoader  # noqa: E402
from mediahub.interpreter.rows import (  # noqa: E402
    _extract_swim_from_cells,
    _parse_records_from_line,
    assign_rows_to_events,
)
from mediahub.interpreter.schema_dataclasses import (  # noqa: E402
    IngestStream,
    Line,
    TableCandidate,
)
from mediahub.interpreter.schema_induce import induce_schema  # noqa: E402
from mediahub.interpreter.events_induce import induce_events  # noqa: E402

ONTOLOGY_ROOT = Path(__file__).resolve().parents[1] / "data" / "ontology"


# ===========================================================================
# Path B — the collapsed-line parser (the path that fired on the real PDF)
# ===========================================================================


class TestLineParserSelectsResultNotSeed:
    def test_event_207_oscar_yu_swam_finals_not_seed(self) -> None:
        # "6 Yu, Oscar 12 <club> <seed> <finals> <pts>" — seed 2:55.80, finals 3:03.47.
        swims = _parse_records_from_line(
            "6 Yu, Oscar 12 City of Brighton & Hove 2:55.80 3:03.47 227"
        )
        assert len(swims) == 1
        sw = swims[0]
        # The SWUM time is the Finals column, never the Seed.
        assert sw.time == "3:03.47"
        assert sw.seed_time == "2:55.80"
        assert sw.place == 6

    def test_event_202_birdy_raleigh_swam_over_220(self) -> None:
        # Identical first-column seed (2:19.80) as Effie Maxted, but different
        # finals — proof the first column is the seed, not the swum time.
        swims = _parse_records_from_line(
            "3 Raleigh, Birdy 13 City of Brighton & Hove 2:19.80 2:22.28 500"
        )
        assert len(swims) == 1
        sw = swims[0]
        assert sw.time == "2:22.28"  # OVER 2:20 — no "first time under 2:20"
        assert sw.seed_time == "2:19.80"

    def test_prelim_finals_layout_takes_finals(self) -> None:
        # A row with Prelim then Finals time: result is the Finals (rightmost).
        sw = _parse_records_from_line("4 Smith, Joe 14 Some SC 28.91 28.40 612")[0]
        assert sw.time == "28.40"
        assert sw.seed_time == "28.91"

    def test_single_time_column_is_the_result(self) -> None:
        # No seed column at all — the lone time is the result, seed stays None.
        sw = _parse_records_from_line("1 Jones, Amy 15 Some SC 27.31")[0]
        assert sw.time == "27.31"
        assert sw.seed_time is None

    def test_trailing_reaction_time_is_not_the_result(self) -> None:
        # A start-reaction column ("0.63") is time-shaped but must never be read
        # as the swum result (it would otherwise become a sub-second "PB").
        sw = _parse_records_from_line("1 Smith Jane 2006 SPAC 27.31 0.63")[0]
        assert sw.time == "27.31"
        assert sw.seed_time is None

    def test_seed_finals_and_reaction_together(self) -> None:
        # Seed, Finals, then a reaction column: result is the Finals time.
        sw = _parse_records_from_line("1 Smith Jane 2006 SPAC 27.00 27.31 0.63")[0]
        assert sw.time == "27.31"
        assert sw.seed_time == "27.00"

    def test_seed_time_is_not_absorbed_into_the_club(self) -> None:
        # The seed time sits between club and finals; it must not pollute the
        # club cell (which would have been rejected as race-data and dropped).
        sw = _parse_records_from_line(
            "6 Yu, Oscar 12 City of Brighton & Hove 2:55.80 3:03.47 227"
        )[0]
        assert sw.club == "City of Brighton & Hove"

    def test_dq_result_after_a_seed_is_the_dq_not_the_seed(self) -> None:
        # A seeded swimmer who is disqualified: the result is the DQ marker, and
        # the seed is still captured — never reported as the swum time.
        sw = _parse_records_from_line("Yu, Oscar 12 City of Brighton 2:55.80 DQ")[0]
        assert sw.time == "DQ"
        assert sw.seed_time == "2:55.80"


class TestLineParserMultiRecordStillSplits:
    """The seed-aware grouping must not break the two-records-per-line layout."""

    def test_two_swimmers_per_line_without_seeds(self) -> None:
        swims = _parse_records_from_line(
            "1 Arthur, Andrew 23 UoAPS 28.73     33 Warner, Liam 16 East Lothian 32.82"
        )
        assert [s.time for s in swims] == ["28.73", "32.82"]
        assert [s.seed_time for s in swims] == [None, None]
        assert [s.place for s in swims] == [1, 33]

    def test_two_swimmers_per_line_each_with_a_seed(self) -> None:
        swims = _parse_records_from_line(
            "1 Arthur, Andrew 23 UoAPS 28.00 28.73   "
            "33 Warner, Liam 16 East Lothian 31.50 32.82"
        )
        assert [s.time for s in swims] == ["28.73", "32.82"]
        assert [s.seed_time for s in swims] == ["28.00", "31.50"]


# ===========================================================================
# Path A — the header-driven schema path: select by LABEL, never the seed
# ===========================================================================


def _induce_and_extract(header: list[str], row: list[str]):
    """Induce a ColumnSchema from a header row and extract the data row."""
    table = TableCandidate(rows=[header, row], page_no=0)
    stream = IngestStream(text="", lines=[], tables=[table], format_detected="pdf")
    schemas = induce_schema(stream, ontology=OntologyLoader(root=ONTOLOGY_ROOT))
    return _extract_swim_from_cells(row, schemas)


class TestSchemaHeaderDrivenResultSelection:
    BASE = ["Place", "Name", "Age", "Club"]
    ROW_TAIL = ["6", "Oscar Yu", "12", "City of Brighton", "2:55.80", "3:03.47"]

    def test_seed_then_finals(self) -> None:
        sw = _induce_and_extract(self.BASE + ["Seed Time", "Finals Time"], self.ROW_TAIL)
        assert sw is not None
        assert sw.time == "3:03.47"  # Finals
        assert sw.seed_time == "2:55.80"  # Seed, kept separate

    def test_prelim_then_finals_prefers_finals(self) -> None:
        # No seed column; result is Finals (the rightmost time), seed stays None.
        sw = _induce_and_extract(self.BASE + ["Prelim Time", "Finals Time"], self.ROW_TAIL)
        assert sw is not None
        assert sw.time == "3:03.47"  # Finals beats Prelim
        assert sw.seed_time is None

    def test_seed_then_prelim_takes_prelim(self) -> None:
        # Prelim-only sheet (no Finals): result is the Prelim, never the Seed.
        sw = _induce_and_extract(self.BASE + ["Seed Time", "Prelim Time"], self.ROW_TAIL)
        assert sw is not None
        assert sw.time == "3:03.47"  # Prelim
        assert sw.seed_time == "2:55.80"  # Seed

    def test_seed_header_is_not_classified_as_a_result_time(self) -> None:
        table = TableCandidate(
            rows=[self.BASE + ["Seed Time", "Finals Time"], self.ROW_TAIL], page_no=0
        )
        stream = IngestStream(text="", lines=[], tables=[table], format_detected="pdf")
        schemas = induce_schema(stream, ontology=OntologyLoader(root=ONTOLOGY_ROOT))
        by_header = {s.header_text: s.col_type for s in schemas}
        assert by_header["Seed Time"] == "seed_time"
        assert by_header["Finals Time"] == "time"


# ===========================================================================
# Full extraction path: assign_rows_to_events over a Sussex-shaped stream
# ===========================================================================


def _build_stream(event_header: str, rows: list[str]) -> IngestStream:
    lines = [Line(text=event_header, page_no=0, y_position=0.0)]
    lines.append(Line(text="Name  Age  Team  Seed Time  Finals Time  Points", page_no=0, y_position=1.0))
    for i, r in enumerate(rows, start=2):
        lines.append(Line(text=r, page_no=0, y_position=float(i)))
    return IngestStream(text="\n".join(l.text for l in lines), lines=lines, tables=[],
                        format_detected="pdf")


class TestEndToEndSussexRows:
    def test_event_207_full_field_uses_finals_times(self) -> None:
        stream = _build_stream(
            "Event 207  Boys 12 Year Olds 200 LC Meter Backstroke",
            [
                "1 Oman, Alexander 12 City of Brighton & Hove 2:37.00 2:41.44 333",
                "2 Woodward, Charlie 12 Crawley 2:48.70 2:50.45 283",
                "5 Evans, Jake 12 Brighton 3:03.50 3:00.18 239",
                "6 Yu, Oscar 12 City of Brighton & Hove 2:55.80 3:03.47 227",
            ],
        )
        ont = OntologyLoader(root=ONTOLOGY_ROOT)
        events = induce_events(stream, ontology=ont)
        assign_rows_to_events(stream, events, induce_schema(stream, ontology=ont))

        swims = {s.swimmer_name: s for ev in events for s in ev.swims}
        # Oscar Yu (6th, 227 pts) swam 3:03.47 — slower than his 2:55.80 seed.
        assert swims["Oscar Yu"].time == "3:03.47"
        assert swims["Oscar Yu"].seed_time == "2:55.80"
        # Winner's finals time, not seed.
        assert swims["Alexander Oman"].time == "2:41.44"
        # Finals times are monotonic with finishing order (FINA points descend).
        ordered = ["Alexander Oman", "Charlie Woodward", "Jake Evans", "Oscar Yu"]
        secs = []
        for nm in ordered:
            mm, ss = swims[nm].time.split(":")
            secs.append(int(mm) * 60 + float(ss))
        assert secs == sorted(secs), f"finals times not monotonic with place: {secs}"


# ===========================================================================
# Downstream: a swim SLOWER than the prior best yields NO PB / improvement
# ===========================================================================


class _StubHistory:
    """Minimal SwimmerHistory stand-in: a single prior-best time (seconds)."""

    swimmer_name = "Oscar Yu"

    def __init__(self, prior_best_sec: float) -> None:
        self._prior = prior_best_sec

    def best_time_in_event(self, distance, stroke, course):  # noqa: ANN001
        return self._prior

    def source_name(self):
        return "PB lookup"

    def source_url(self):
        return "https://example.org/pb"

    def retrieved_at(self):
        return None


def _swim(finals_time_cs: int):
    return SimpleNamespace(
        dq=False,
        finals_time_cs=finals_time_cs,
        distance=200,
        stroke="BK",
        course="LC",
        swimmer_key="oscar-yu",
        round="timed_final",
    )


class TestSlowerSwimYieldsNoPB:
    """With the correct (slower) result, no PB fires; the buggy seed fabricated one."""

    def _detector(self):
        from swim_content_v5.achievements.pb import PBConfirmedDetector

        return PBConfirmedDetector()

    def test_correct_finals_slower_than_seed_is_no_pb(self) -> None:
        det = self._detector()
        # Prior best 2:55.80 (= his seed). He SWAM 3:03.47 — slower → no PB.
        history = _StubHistory(175.80)
        achievements = det.detect(_swim(18347), ctx=SimpleNamespace(), history=history)
        assert achievements == []

    def test_detector_does_fire_for_a_genuinely_faster_swim(self) -> None:
        # Positive control: same history, a real improvement DOES fire — proving
        # the no-fire above is due to the slower time, not a broken stub.
        det = self._detector()
        history = _StubHistory(175.80)
        achievements = det.detect(_swim(17000), ctx=SimpleNamespace(), history=history)
        assert len(achievements) == 1

    def test_seed_as_result_would_have_fabricated_a_pb(self) -> None:
        # Demonstrates the inverted bug: feeding the SEED (2:55.80) as the result
        # against the real prior best (3:03.47) fabricates a 7.67s PB. The parser
        # fix prevents the seed from ever reaching the detector as the result.
        det = self._detector()
        history = _StubHistory(183.47)  # 3:03.47 prior best
        fabricated = det.detect(_swim(17580), ctx=SimpleNamespace(), history=history)
        assert len(fabricated) == 1
        assert "PB" in fabricated[0].headline
