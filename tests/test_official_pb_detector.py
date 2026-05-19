"""Tests for `mediahub.recognition_swim.achievements.official_pb`.

The OfficialPBDetector fires when the PB audit pipeline marks a swim
as `CONFIRMED_OFFICIAL_PB` — the strongest PB confirmation possible.
Per CLAUDE.md the detector + PB-audit chain stays deterministic;
these tests pin the fire / no-fire / formatting contracts.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from mediahub.recognition_swim.achievements.official_pb import (
    OfficialPBDetector,
    _cs_to_str,
    _swim_id,
)


# ---------------------------------------------------------------------------
# _cs_to_str — centiseconds → display string
# ---------------------------------------------------------------------------


class TestCsToStr:
    @pytest.mark.parametrize(
        "cs, expected",
        [
            (5987, "59.87"),       # sub-minute
            (10234, "1:42.34"),    # one minute
            (6000, "1:00.00"),     # exactly one minute
            (7521, "1:15.21"),     # arbitrary middle case
            (92500, "15:25.00"),   # long-form, 1500m freestyle territory
            (0, "0.00"),           # zero
        ],
    )
    def test_known_centisecond_values(self, cs: int, expected: str) -> None:
        assert _cs_to_str(cs) == expected

    def test_none_returns_em_dash(self) -> None:
        assert _cs_to_str(None) == "—"

    def test_rounds_subhundredth_centiseconds(self) -> None:
        # Spec uses round(); 5987.6 → 5988
        assert _cs_to_str(5987.6) == "59.88"
        assert _cs_to_str(5987.4) == "59.87"


# ---------------------------------------------------------------------------
# _swim_id — composite ID assembly
# ---------------------------------------------------------------------------


class TestSwimId:
    def test_basic_composite(self) -> None:
        swim = SimpleNamespace(
            swimmer_key="jane-smith-001",
            distance=100,
            stroke="FR",
            course="LC",
            round="F",
        )
        assert _swim_id(swim) == "jane-smith-001:100FRLC:F"

    def test_suffix_appended(self) -> None:
        swim = SimpleNamespace(
            swimmer_key="x",
            distance=200,
            stroke="IM",
            course="SC",
            round="P",
        )
        assert _swim_id(swim, ":official_pb") == "x:200IMSC:P:official_pb"

    def test_missing_attrs_fall_back_to_blanks(self) -> None:
        swim = SimpleNamespace()
        # All attrs missing → all defaults
        assert _swim_id(swim) == ":0:"


# ---------------------------------------------------------------------------
# Detector test scaffolding
# ---------------------------------------------------------------------------


def _make_swim(
    *,
    swimmer_key: str = "jane-smith-001",
    distance: int = 100,
    stroke: str = "FR",
    course: str = "LC",
    round_: str = "F",
    dq: bool = False,
    finals_time_cs: int | None = 6234,
):
    """Minimal duck-typed swim object matching what the detector reads."""
    return SimpleNamespace(
        swimmer_key=swimmer_key,
        distance=distance,
        stroke=stroke,
        course=course,
        round=round_,
        dq=dq,
        finals_time_cs=finals_time_cs,
    )


def _make_history(*, swimmer_name: str = "Jane Smith", pb_decision=None):
    return SimpleNamespace(
        swimmer_name=swimmer_name,
        pb_decision=pb_decision,
    )


def _confirmed_decision(
    *,
    reason: str = "Time and date match the listed official PB.",
    source_url: str = "https://pb.example.org/swimmer/jane-smith",
    source_name: str = "Example PB Lookup",
):
    return {
        "status": "CONFIRMED_OFFICIAL_PB",
        "reason": reason,
        "evidence": [
            {"source_url": source_url, "source_name": source_name},
        ],
    }


# ---------------------------------------------------------------------------
# Detector fire / no-fire matrix
# ---------------------------------------------------------------------------


class TestOfficialPBDetectorNoFire:
    def test_no_history_pb_decision_no_fire(self) -> None:
        det = OfficialPBDetector()
        swim = _make_swim()
        history = _make_history(pb_decision=None)
        assert det.detect(swim, ctx={}, history=history) == []

    def test_dq_swim_no_fire(self) -> None:
        det = OfficialPBDetector()
        swim = _make_swim(dq=True)
        history = _make_history(pb_decision=_confirmed_decision())
        assert det.detect(swim, ctx={}, history=history) == []

    def test_missing_finals_time_no_fire(self) -> None:
        det = OfficialPBDetector()
        swim = _make_swim(finals_time_cs=None)
        history = _make_history(pb_decision=_confirmed_decision())
        assert det.detect(swim, ctx={}, history=history) == []

    def test_non_confirmed_status_no_fire(self) -> None:
        det = OfficialPBDetector()
        swim = _make_swim()
        history = _make_history(
            pb_decision={"status": "AMBIGUOUS", "reason": "", "evidence": []}
        )
        assert det.detect(swim, ctx={}, history=history) == []

    def test_no_fire_reason_explains_missing_decision(self) -> None:
        det = OfficialPBDetector()
        swim = _make_swim()
        history = _make_history(pb_decision=None)
        assert "no PB decision" in det._no_fire_reason(swim, {}, history)

    def test_no_fire_reason_explains_wrong_status(self) -> None:
        det = OfficialPBDetector()
        swim = _make_swim()
        history = _make_history(
            pb_decision={"status": "AMBIGUOUS", "reason": "", "evidence": []}
        )
        msg = det._no_fire_reason(swim, {}, history)
        assert "AMBIGUOUS" in msg


class TestOfficialPBDetectorFires:
    def test_fires_on_confirmed_pb(self) -> None:
        det = OfficialPBDetector()
        swim = _make_swim()
        history = _make_history(pb_decision=_confirmed_decision())
        achievements = det.detect(swim, ctx={}, history=history)
        assert len(achievements) == 1
        ach = achievements[0]
        assert ach.type == "official_pb_confirmed"
        assert ach.swimmer_id == "jane-smith-001"
        assert ach.swimmer_name == "Jane Smith"
        assert ach.confidence == pytest.approx(0.98)
        assert ach.confidence_label == "high"
        assert ach.detector_name == "official_pb_confirmed"

    def test_headline_includes_time_string(self) -> None:
        det = OfficialPBDetector()
        swim = _make_swim(finals_time_cs=6234)  # 1:02.34
        history = _make_history(pb_decision=_confirmed_decision())
        ach = det.detect(swim, ctx={}, history=history)[0]
        assert "1:02.34" in ach.headline
        assert ach.raw_facts["time_str"] == "1:02.34"

    def test_swim_id_uses_official_pb_suffix(self) -> None:
        det = OfficialPBDetector()
        swim = _make_swim()
        history = _make_history(pb_decision=_confirmed_decision())
        ach = det.detect(swim, ctx={}, history=history)[0]
        assert ach.swim_id.endswith(":official_pb")
        assert "jane-smith-001" in ach.swim_id

    def test_evidence_includes_results_file_and_live_source(self) -> None:
        det = OfficialPBDetector()
        swim = _make_swim()
        history = _make_history(pb_decision=_confirmed_decision())
        ach = det.detect(swim, ctx={}, history=history)[0]
        types = [e.source_type for e in ach.evidence]
        assert "results_file" in types
        assert "live_research" in types
        live = next(e for e in ach.evidence if e.source_type == "live_research")
        assert live.source_url == "https://pb.example.org/swimmer/jane-smith"
        assert live.source_name == "Example PB Lookup"

    def test_source_name_falls_back_to_host_when_missing(self) -> None:
        det = OfficialPBDetector()
        swim = _make_swim()
        # Decision with URL but no source_name → must derive from host
        decision = {
            "status": "CONFIRMED_OFFICIAL_PB",
            "reason": "ok",
            "evidence": [
                {"url": "https://www.pb-example.co.uk/swim/123"}
            ],
        }
        history = _make_history(pb_decision=decision)
        ach = det.detect(swim, ctx={}, history=history)[0]
        live = next(e for e in ach.evidence if e.source_type == "live_research")
        # www. should be stripped
        assert live.source_name == "pb-example.co.uk"

    def test_source_name_falls_back_to_pb_lookup_when_no_url(self) -> None:
        det = OfficialPBDetector()
        swim = _make_swim()
        decision = {
            "status": "CONFIRMED_OFFICIAL_PB",
            "reason": "ok",
            "evidence": [],
        }
        history = _make_history(pb_decision=decision)
        ach = det.detect(swim, ctx={}, history=history)[0]
        # No source_url → no live_research evidence; only the results_file entry
        assert len(ach.evidence) == 1
        assert ach.evidence[0].source_type == "results_file"

    def test_swimmer_name_override_via_extra(self) -> None:
        det = OfficialPBDetector()
        swim = _make_swim()
        history = _make_history(
            swimmer_name="Wrong Name",
            pb_decision=_confirmed_decision(),
        )
        ach = det.detect(
            swim, ctx={}, history=history,
            extra={"swimmer_name": "Correct Name"},
        )[0]
        assert ach.swimmer_name == "Correct Name"
        assert "Correct Name" in ach.headline

    def test_raw_facts_capture_status_and_time(self) -> None:
        det = OfficialPBDetector()
        swim = _make_swim(finals_time_cs=6500)
        history = _make_history(pb_decision=_confirmed_decision(reason="match w/in 0.005s"))
        ach = det.detect(swim, ctx={}, history=history)[0]
        assert ach.raw_facts["pb_decision_status"] == "CONFIRMED_OFFICIAL_PB"
        assert ach.raw_facts["time_cs"] == 6500
        assert ach.raw_facts["reason"] == "match w/in 0.005s"

    def test_no_fire_reason_when_firing_returns_default(self) -> None:
        # _no_fire_reason is queried as a diagnostic — even for the firing
        # case the string should be a non-empty plain-English status.
        det = OfficialPBDetector()
        swim = _make_swim()
        history = _make_history(pb_decision=_confirmed_decision())
        msg = det._no_fire_reason(swim, {}, history)
        # Confirmed status passes both gates → "did not fire" is the literal default
        assert msg == "did not fire"


class TestPBDecisionShapes:
    """The detector tolerates the PB decision arriving as a dict OR a dataclass-like object."""

    def test_dataclass_like_decision_accepted(self) -> None:
        det = OfficialPBDetector()
        swim = _make_swim()
        decision_obj = SimpleNamespace(
            status="CONFIRMED_OFFICIAL_PB",
            reason="dataclass path",
            evidence=[
                {"source_url": "https://x.example/x", "source_name": "X"},
            ],
        )
        history = _make_history(pb_decision=decision_obj)
        result = det.detect(swim, ctx={}, history=history)
        assert len(result) == 1
        assert result[0].raw_facts["reason"] == "dataclass path"

    def test_unrecognised_decision_type_returns_no_decision(self) -> None:
        det = OfficialPBDetector()
        swim = _make_swim()
        history = _make_history(pb_decision="not a dict and not a dataclass")
        assert det.detect(swim, ctx={}, history=history) == []
