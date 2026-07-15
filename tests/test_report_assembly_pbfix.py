"""Regression tests for P9 — ``legacy/swim_content_v5/report.py``.

Covers two diagnosed defects in the V5 recognition-report assembly:

* **F10** — the Phase W ``MilestoneDetector`` / ``ClubRecordDetector`` must be
  registered exactly *once*. report.py used to append a second copy on top of
  ``production_detectors()`` (which already ends with them), so every
  milestone / club-record achievement was detected, ranked, counted and
  exported in duplicate (duplicate review rows sharing one workflow state,
  inflated counts, twin ``~n`` export stubs).
* **F57** — the V5 path counted a ghost ``pb_likely`` achievement type that no
  V5 detector ever emits (a V5 PB requires a real prior-best baseline; there is
  no "likely PB" achievement). Only ``pb_confirmed`` is real in the V5 suite.
"""

from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

import pytest

# Importing ``mediahub`` registers the legacy top-level package aliases
# (``swim_content_v5`` -> ``mediahub.…``) the rest of the suite relies on.
import mediahub  # noqa: F401

from swim_content_v5.report import (  # noqa: E402
    _add_multi_pb_achievements,
    _assemble_detectors,
)
from swim_content_v5.schema import Achievement  # noqa: E402
from swim_content_v5.history import SwimmerHistory  # noqa: E402


# --------------------------------------------------------------------------- #
# F10 — Phase W detectors are registered exactly once
# --------------------------------------------------------------------------- #

def _class_counts(detectors) -> Counter:
    return Counter(type(d).__name__ for d in detectors)


def test_assemble_detectors_registers_phase_w_detectors_once():
    """MilestoneDetector, ClubRecordDetector and OfficialPBDetector each once."""
    pytest.importorskip("mediahub.recognition_swim")
    counts = _class_counts(_assemble_detectors())
    # This env has ``mediahub.recognition_swim`` importable, so the production
    # detector set (which includes all three) is what report.py assembles.
    assert counts.get("MilestoneDetector", 0) == 1, counts
    assert counts.get("ClubRecordDetector", 0) == 1, counts
    assert counts.get("OfficialPBDetector", 0) == 1, counts


def test_assemble_detectors_has_no_duplicated_detector_class():
    """No detector class is registered more than once (F10 regression).

    The original defect double-registered Milestone/ClubRecord; guard the whole
    set so any future accidental duplication is caught, not only those two.
    """
    counts = _class_counts(_assemble_detectors())
    dups = {name: n for name, n in counts.items() if n > 1}
    assert not dups, f"detector class(es) double-registered: {dups}"


def test_report_adds_nothing_on_top_of_production_detectors():
    """report.py must use ``production_detectors()`` verbatim, adding nothing.

    Pins the exact F10 fix: re-introducing a
    ``+ [MilestoneDetector(), ClubRecordDetector()]`` append in report.py would
    make ``_assemble_detectors()`` diverge from the upstream production set.
    """
    pytest.importorskip("mediahub.recognition_swim")
    from mediahub.recognition_swim import production_detectors

    assert _class_counts(_assemble_detectors()) == _class_counts(production_detectors())


def test_club_debut_fires_exactly_once_through_detection_run():
    """F10 symptom guard: a single club-debut swim yields exactly ONE club_debut.

    This drives report.py's real detection path (``_run_detectors_for_swim``
    with the assembled detector set) rather than only inspecting list
    composition. ``base.trace()`` runs ``detect()`` once per registered
    detector instance, so a double-registered MilestoneDetector would emit
    ``club_debut`` twice — the exact duplicate-achievement symptom F10 fixes.
    Only MilestoneDetector emits ``club_debut``, so other detectors firing or
    erroring under ``ctx=None`` (their exceptions are swallowed by
    ``_run_detectors_for_swim``) cannot affect the count.
    """
    pytest.importorskip("mediahub.recognition_swim")
    from mediahub.athletes.registry import normalise_name
    from swim_content_v5.report import _run_detectors_for_swim

    swimmer_name = "Jane Doe"
    swim = SimpleNamespace(
        swimmer_key="sk1",
        distance=50,
        stroke="FR",
        course="LC",
        finals_time_cs=3000,
        dq=False,
        round="",
    )
    detectors = _assemble_detectors()
    extra_context = {
        "athlete_milestones": {
            normalise_name(swimmer_name): {
                "prior_races": 0,
                "prior_events": set(),
                "athlete_id": "a1",
            }
        }
    }
    achievements, _ = _run_detectors_for_swim(
        swim=swim,
        swimmer_name=swimmer_name,
        ctx=None,
        history=SwimmerHistory("sk1", swimmer_name),
        all_results=[swim],
        standards=[],
        club_code="",
        detectors=detectors,
        extra_context=extra_context,
    )
    debuts = [a for a in achievements if a.type == "club_debut"]
    assert len(debuts) == 1, [a.type for a in achievements]


# --------------------------------------------------------------------------- #
# F57 — the ghost ``pb_likely`` type is not counted
# --------------------------------------------------------------------------- #

def _pb_achievement(a_type: str, swimmer_id: str, event: str) -> Achievement:
    return Achievement(
        type=a_type,
        swim_id=f"{swimmer_id}:{event}",
        swimmer_id=swimmer_id,
        swimmer_name="Test Swimmer",
        event=event,
        headline="headline",
        angle_hint="angle",
        confidence=0.95,
        confidence_label="high",
    )


def _run_multi_pb(all_achievements):
    swim = SimpleNamespace(swimmer_key="swkey")
    history_map = {"swkey": SwimmerHistory("swkey", "Test Swimmer")}
    return _add_multi_pb_achievements(
        all_achievements, [swim], history_map, ctx=None, detectors=[]
    )


def test_multi_pb_weekend_still_fires_on_three_confirmed_pbs():
    """Three confirmed PBs for one swimmer still fire MultiPBWeekend."""
    confirmed = [
        _pb_achievement("pb_confirmed", "swkey", f"{dist}m FR")
        for dist in (50, 100, 200)
    ]
    out = _run_multi_pb(confirmed)
    assert any(a.type == "multi_pb_weekend" for a in out)


def test_ghost_pb_likely_is_not_counted_toward_multi_pb():
    """F57: ``pb_likely`` is emitted by no V5 detector, so it must not count.

    Before the fix, three ghost ``pb_likely`` achievements would (incorrectly)
    trip the >=3-PB MultiPBWeekend threshold. They are synthetic here only to
    prove the removed branch no longer counts a type nothing produces.
    """
    likely = [
        _pb_achievement("pb_likely", "swkey", f"{dist}m FR")
        for dist in (50, 100, 200)
    ]
    out = _run_multi_pb(likely)
    assert not any(a.type == "multi_pb_weekend" for a in out)
