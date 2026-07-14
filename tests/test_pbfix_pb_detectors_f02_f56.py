"""Regression tests for the V5 PB detectors (package P4).

Covers two verified flaws in ``legacy/swim_content_v5/achievements/pb.py``:

* **F02** — same-meet folding. A swimmer who beats their online baseline twice
  in one meet (heats then final) must fire exactly ONE ``pb_confirmed`` — for
  the fastest swim — and never re-announce a slower final as a new PB. The
  ``PBImprovementMagnitudeDetector`` gets the same treatment so the magnitude
  moment is not double-counted.
* **F56** — a non-positive ``finals_time_cs`` (0.00 or negative) and a ``None``
  time are 'no swim' and must never seed a fabricated PB of 0.00.

Swims are ``SimpleNamespace`` stand-ins (the detectors read canonical
``RaceResult`` fields purely via ``getattr``) — the same lightweight idiom used
by ``tests/test_interpreter_seed_vs_result_time.py`` — so this file needs no
web/Flask import.
"""
from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import mediahub  # noqa: E402,F401  (registers the legacy-name shim for swim_content_v5)
from swim_content_v5.achievements.pb import (  # noqa: E402
    PBConfirmedDetector,
    PBImprovementMagnitudeDetector,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------
class _StubHistory:
    """Minimal SwimmerHistory stand-in: one prior-best time (seconds) for every
    event lookup. Mirrors the stub used elsewhere in the suite."""

    swimmer_name = "Alex Doe"

    def __init__(self, prior_best_sec):
        self._prior = prior_best_sec

    def best_time_in_event(self, distance, stroke, course):
        return self._prior

    def source_name(self):
        return "PB lookup"

    def source_url(self):
        return "https://example.org/pb"

    def retrieved_at(self):
        return None


def _swim(cs, *, rnd="timed_final", swimmer="alex", dist=100, stroke="FR", course="LC"):
    return SimpleNamespace(
        dq=False,
        finals_time_cs=cs,
        distance=dist,
        stroke=stroke,
        course=course,
        swimmer_key=swimmer,
        round=rnd,
    )


def _run(detector, results, history, extra=None):
    """Run ``detector`` over every swim in ``results`` with the full meet as
    ``all_results`` (exactly as ``report.py`` does), returning all fired
    achievements."""
    fired = []
    for swim in results:
        fired += detector.detect(
            swim, SimpleNamespace(), history, all_results=results, extra=extra
        )
    return fired


# ---------------------------------------------------------------------------
# F56 — zero / None / negative time is never a PB
# ---------------------------------------------------------------------------
def test_zero_time_is_not_a_pb_confirmed():
    det = PBConfirmedDetector()
    assert det.detect(_swim(0), SimpleNamespace(), _StubHistory(61.0), all_results=None) == []


def test_none_time_is_not_a_pb_confirmed():
    det = PBConfirmedDetector()
    assert det.detect(_swim(None), SimpleNamespace(), _StubHistory(61.0), all_results=None) == []


def test_negative_time_is_not_a_pb_confirmed():
    det = PBConfirmedDetector()
    assert det.detect(_swim(-5), SimpleNamespace(), _StubHistory(61.0), all_results=None) == []


def test_zero_and_none_time_are_not_a_pb_magnitude():
    det = PBImprovementMagnitudeDetector()
    assert det.detect(_swim(0), SimpleNamespace(), _StubHistory(65.0), all_results=None) == []
    assert det.detect(_swim(None), SimpleNamespace(), _StubHistory(65.0), all_results=None) == []


def test_valid_positive_time_still_fires_control():
    """Positive control: a real, faster time DOES fire — proving the no-fire
    cases above are the zero-time guard, not a broken stub."""
    det = PBConfirmedDetector()
    achs = det.detect(_swim(6000), SimpleNamespace(), _StubHistory(61.0), all_results=None)
    assert len(achs) == 1
    assert achs[0].type == "pb_confirmed"


# ---------------------------------------------------------------------------
# F02 — same-meet folding: exactly one PB per event per meet, the fastest swim
# ---------------------------------------------------------------------------
def test_heats_then_slower_final_yields_one_pb_the_heat():
    """The headline case: heat 1:00.50 (beats 1:01.00 baseline), slower final
    1:00.90. Exactly one pb_confirmed fires — the heat — with the honest online
    prior, and the slower final is never announced as a PB."""
    det = PBConfirmedDetector()
    heat = _swim(6050, rnd="heat")
    final = _swim(6090, rnd="final")
    fired = _run(det, [heat, final], _StubHistory(61.0), extra={"swimmer_name": "Alex Doe"})

    assert len(fired) == 1
    ach = fired[0]
    assert ach.raw_facts["time_str"] == "1:00.50"  # the heat, not the final
    assert ach.raw_facts["prior_pb_str"] == "1:01.00"  # the real online baseline
    assert "1:00.90" not in ach.headline


def test_heats_then_slower_final_is_order_independent():
    """The same meet, results listed final-first: a strictly-faster same-meet
    swim suppresses the slower one regardless of list order."""
    det = PBConfirmedDetector()
    heat = _swim(6050, rnd="heat")
    final = _swim(6090, rnd="final")
    fired = _run(det, [final, heat], _StubHistory(61.0))

    assert len(fired) == 1
    assert fired[0].raw_facts["time_str"] == "1:00.50"


def test_heats_then_faster_final_yields_one_pb_the_final():
    """Both swims beat the baseline but the final is faster: only the fastest
    (the final) fires; the slower heat folds into the baseline.

    The fired card reports the online baseline (1:01.00) as its prior, not the
    earlier heat — a deliberate, chronology-safe choice: firing is decided by
    the order-independent "strictly faster" rule, but showing the earlier
    same-meet swim as the prior would require reliable heat/final ordering the
    results feed does not guarantee, and the same rule applied to the
    heats-then-SLOWER-final case would wrongly surface the later swim as the
    prior. The pre-meet PB is always the honest reference."""
    det = PBConfirmedDetector()
    heat = _swim(6090, rnd="heat")
    final = _swim(6050, rnd="final")
    fired = _run(det, [heat, final], _StubHistory(61.0))

    assert len(fired) == 1
    assert fired[0].raw_facts["time_str"] == "1:00.50"  # the final
    assert fired[0].raw_facts["prior_pb_str"] == "1:01.00"


def test_magnitude_not_double_counted_across_same_meet_swims():
    """Both the heat (huge drop) and the slower final (big drop) clear the
    notable threshold, but only the fastest swim's magnitude fires."""
    det = PBImprovementMagnitudeDetector()
    heat = _swim(6000, rnd="heat")   # 60.00 vs 65.00 -> 7.7% (huge)
    final = _swim(6200, rnd="final")  # 62.00 vs 65.00 -> 4.6% (big) but superseded
    fired = _run(det, [heat, final], _StubHistory(65.0))

    assert len(fired) == 1
    assert fired[0].type == "pb_magnitude_huge"
    assert fired[0].raw_facts["time_str"] == "1:00.00"


def test_exact_tie_same_meet_fires_exactly_once():
    """Two identical same-meet times both beating the baseline: exactly one
    card fires (the earlier-listed), never zero and never two."""
    det = PBConfirmedDetector()
    a = _swim(6050, rnd="heat")
    b = _swim(6050, rnd="final")
    fired = _run(det, [a, b], _StubHistory(61.0))
    assert len(fired) == 1


def test_same_time_different_events_both_fire():
    det = PBConfirmedDetector()
    free = _swim(6050, stroke="FR")
    back = _swim(6050, stroke="BK")
    fired = _run(det, [free, back], _StubHistory(61.0))
    assert len(fired) == 2


def test_same_event_different_swimmers_both_fire():
    det = PBConfirmedDetector()
    alex = _swim(6050, swimmer="alex")
    sam = _swim(6050, swimmer="sam")
    fired = _run(det, [alex, sam], _StubHistory(61.0))
    assert len(fired) == 2


def test_single_swim_still_fires_normally():
    """No same-meet duplicate: the common case is unchanged."""
    det = PBConfirmedDetector()
    fired = _run(det, [_swim(6050)], _StubHistory(61.0))
    assert len(fired) == 1


def test_all_results_none_is_backward_compatible():
    det = PBConfirmedDetector()
    achs = det.detect(_swim(6050), SimpleNamespace(), _StubHistory(61.0), all_results=None)
    assert len(achs) == 1


def test_dq_same_meet_swim_does_not_suppress():
    """A DQ'd faster same-meet swim is not a real time and must not fold into
    the baseline: the valid slower swim still fires as the PB."""
    det = PBConfirmedDetector()
    dq_fast = _swim(6000, rnd="heat")
    dq_fast.dq = True
    valid = _swim(6050, rnd="final")
    fired = _run(det, [dq_fast, valid], _StubHistory(61.0))
    assert len(fired) == 1
    assert fired[0].raw_facts["time_str"] == "1:00.50"


def test_three_same_meet_swims_faster_progression_one_survivor():
    """Heat/semi/final all beat the baseline and get progressively faster:
    exactly one PB fires — the fastest (final)."""
    det = PBConfirmedDetector()
    swims = [_swim(6090, rnd="heat"), _swim(6070, rnd="semi"), _swim(6050, rnd="final")]
    fired = _run(det, swims, _StubHistory(61.0))
    assert len(fired) == 1
    assert fired[0].raw_facts["time_str"] == "1:00.50"


def test_three_same_meet_swims_slower_progression_one_survivor():
    """Fastest swim comes first (heat), then progressively slower: exactly one
    PB fires — still the fastest (heat), regardless of the two slower swims."""
    det = PBConfirmedDetector()
    swims = [_swim(6050, rnd="heat"), _swim(6070, rnd="semi"), _swim(6090, rnd="final")]
    fired = _run(det, swims, _StubHistory(61.0))
    assert len(fired) == 1
    assert fired[0].raw_facts["time_str"] == "1:00.50"


def test_three_way_exact_tie_fires_once():
    """Three identical same-meet times all beating the baseline: exactly one
    card (the earliest-listed), never three and never zero."""
    det = PBConfirmedDetector()
    swims = [_swim(6050, rnd="heat"), _swim(6050, rnd="semi"), _swim(6050, rnd="final")]
    fired = _run(det, swims, _StubHistory(61.0))
    assert len(fired) == 1


def test_magnitude_faster_final_only_final_fires():
    """Magnitude detector, heats-then-faster-final: only the fastest swim's
    magnitude fires (the huge drop), not the slower heat's big drop."""
    det = PBImprovementMagnitudeDetector()
    heat = _swim(6200, rnd="heat")   # 62.00 vs 65.00 -> 4.6% (big)
    final = _swim(6000, rnd="final")  # 60.00 vs 65.00 -> 7.7% (huge)
    fired = _run(det, [heat, final], _StubHistory(65.0))
    assert len(fired) == 1
    assert fired[0].type == "pb_magnitude_huge"


def test_magnitude_supersession_is_order_independent():
    """Magnitude detector suppresses the slower same-meet swim regardless of
    list order."""
    det = PBImprovementMagnitudeDetector()
    heat = _swim(6000, rnd="heat")   # 60.00 -> huge
    final = _swim(6200, rnd="final")  # 62.00 -> big, superseded
    forward = _run(det, [heat, final], _StubHistory(65.0))
    reverse = _run(det, [final, heat], _StubHistory(65.0))
    assert len(forward) == len(reverse) == 1
    assert forward[0].type == reverse[0].type == "pb_magnitude_huge"


def test_magnitude_all_results_none_is_backward_compatible():
    det = PBImprovementMagnitudeDetector()
    achs = det.detect(_swim(6000), SimpleNamespace(), _StubHistory(65.0), all_results=None)
    assert len(achs) == 1
    assert achs[0].type == "pb_magnitude_huge"


# ---------------------------------------------------------------------------
# Explainability — the no-fire reasons stay honest
# ---------------------------------------------------------------------------
def test_no_fire_reason_reports_zero_time():
    det = PBConfirmedDetector()
    reason = det._no_fire_reason(_swim(0), SimpleNamespace(), _StubHistory(61.0))
    assert "no valid time" in reason


def test_no_fire_reason_reports_same_meet_supersession():
    det = PBConfirmedDetector()
    heat = _swim(6050, rnd="heat")
    final = _swim(6090, rnd="final")
    reason = det._no_fire_reason(
        final, SimpleNamespace(), _StubHistory(61.0), all_results=[heat, final]
    )
    assert "same meet" in reason
