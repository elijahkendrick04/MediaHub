"""Regression tests for the batch-15 deterministic-engine accuracy fixes.

Each test pins the NEW behaviour of a batch-15 deterministic-engine fix so the
old defect cannot creep back:

* #67 — native-parser overall confidence is no longer floored at 0.5, so a
  broken parse reads as broken.
* #50 — native parsers populate ``round_hint`` from the HY3 E2 code / the SDIF
  prelim-vs-finals fields / the LENEX event round, so a non-final place-1 can no
  longer surface as a fabricated medal.
* #55 — ``build_weekend_in_numbers`` de-dupes PB derivatives and final
  derivatives of the SAME swim, so a single PB / final is counted once.
* #58 — ``ClubRecordDetector`` emits one achievement per broken record key, so a
  swim that beats both an age-band and the open record updates both (no stale
  open record → no future false "NEW CLUB RECORD (open)").
* #61 — ``MilestoneDetector`` fires nothing for a swimmer who is unknown to a
  non-empty registry (indistinguishable first-timer vs name-drift veteran), but
  still fires a confident debut for a swimmer KNOWN with zero prior races.

Unit-level, deterministic, no network.
"""

from __future__ import annotations

from types import SimpleNamespace

from mediahub.interpreter.hytek_parser import parse_hy3
from mediahub.interpreter.lenex_parser import parse_lenex
from mediahub.interpreter.sdif_parser import parse_sdif
from mediahub.recognition.weekend_in_numbers import build_weekend_in_numbers
from mediahub.recognition_swim.achievements.club_record import ClubRecordDetector
from mediahub.recognition_swim.achievements.milestones import MilestoneDetector


# ---------------------------------------------------------------------------
# Shared synthetic HY3 fragments (columns verified against the V8.1 corpus)
# ---------------------------------------------------------------------------

_HY3_A1 = "A107SystemHeader                              Hy-Tek MM 7.0"
_HY3_B1 = (
    "B1Spring Meet                                 City Pool"
    "                                    050120250502202505022025"
)
_HY3_C1 = (
    "C1NADX Test Swim Club                                        "
    "                                              0"
)
_HY3_D1 = (
    "D1M  001Smith               John                            "
    "        USS123456789    000000000000000101201210     0"
)
# Well-formed E1 (distance 50, stroke A=Free) and its E2 finals result.
_HY3_E1 = (
    "E1M  001SmithMS    50A 10 11  0A  0.00101A   30.00S   30.00S "
    "   0.00    0.00   NN               N                               00"
)
_HY3_E2 = (
    "E2F   30.00S       0  1  4  0   1  0   30.00    0.00    0.00 "
    "       30.00     0.00     05012025                           0     00"
)


def _hy3(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode("latin-1")


# ---------------------------------------------------------------------------
# #67 — confidence floor removed (native parsers)
# ---------------------------------------------------------------------------


def test_hy3_broken_parse_reads_below_half_not_floored():
    # Blank the distance + stroke columns → the single event scores 0.4, which
    # previously was clamped up to a misleading 0.5.
    broken_e1 = _HY3_E1[:17] + "     " + _HY3_E1[22:]
    meet = parse_hy3(_hy3(_HY3_A1, _HY3_B1, _HY3_C1, _HY3_D1, broken_e1, _HY3_E2))
    assert meet.events, "a swim should still be recorded"
    assert meet.events[0].distance_m is None and meet.events[0].stroke is None
    assert 0.0 < meet.overall_confidence < 0.5, meet.overall_confidence


def test_hy3_healthy_parse_still_reads_high():
    meet = parse_hy3(_hy3(_HY3_A1, _HY3_B1, _HY3_C1, _HY3_D1, _HY3_E1, _HY3_E2))
    assert meet.overall_confidence >= 0.7


def _sdif_line(**cols: str) -> str:
    line = list(" " * 170)
    line[0:2] = list("D0")
    line[11 : 11 + len("Smith, Jane")] = list("Smith, Jane")
    for start, text in cols.items():
        i = int(start[1:])  # keyword like "c67"
        line[i : i + len(text)] = list(text)
    return "".join(line)


def _sdif(*lines: str) -> bytes:
    return ("\n".join(["A0".ljust(170)] + [ln.ljust(170) for ln in lines]) + "\n").encode("latin-1")


def test_sdif_broken_parse_reads_below_half_not_floored():
    # No distance / stroke → event scores 0.4 (was floored to 0.5).
    meet = parse_sdif(_sdif(_sdif_line()))
    assert meet.events
    assert 0.0 < meet.overall_confidence < 0.5, meet.overall_confidence


# ---------------------------------------------------------------------------
# #50 — round_hint populated so a non-final can't fabricate a medal
# ---------------------------------------------------------------------------


def test_hy3_finals_round_has_no_hint():
    meet = parse_hy3(_hy3(_HY3_A1, _HY3_B1, _HY3_C1, _HY3_D1, _HY3_E1, _HY3_E2))
    assert meet.events[0].swims[0].round_hint is None


def test_hy3_prelim_round_code_marks_prelim():
    prelim_e2 = "E2P" + _HY3_E2[3:]  # round code P (prelim) in col 2
    meet = parse_hy3(_hy3(_HY3_A1, _HY3_B1, _HY3_C1, _HY3_D1, _HY3_E1, prelim_e2))
    assert meet.events[0].swims[0].round_hint == "prelim"


def test_sdif_prelim_only_swim_marks_prelim():
    # distance 100 Free, sex F, a prelim time but NO finals time.
    d0 = _sdif_line(c66="F", c67=" 100", c71="1", c97="1:05.00")
    meet = parse_sdif(_sdif(d0))
    swim = meet.events[0].swims[0]
    assert swim.round_hint == "prelim"
    assert swim.time == "1:05.00"


def test_sdif_finals_swim_has_no_hint():
    d0 = _sdif_line(c66="F", c67=" 100", c71="1", c115="1:04.50")
    meet = parse_sdif(_sdif(d0))
    swim = meet.events[0].swims[0]
    assert swim.round_hint is None
    assert swim.time == "1:04.50"


_LENEX_TMPL = (
    '<LENEX version="3.0"><MEETS><MEET name="Test" city="X" course="LCM">'
    '<SESSIONS><SESSION date="2026-06-06"><EVENTS>'
    '<EVENT eventid="1" number="1" gender="F" round="{round}">'
    '<SWIMSTYLE distance="100" stroke="FREE"/></EVENT>'
    "</EVENTS></SESSION></SESSIONS>"
    '<CLUBS><CLUB name="Club"><ATHLETES>'
    '<ATHLETE firstname="Jane" lastname="Smith" gender="F" birthdate="2010-01-01">'
    '<RESULTS><RESULT resultid="10" eventid="1" swimtime="00:01:05.00" status="OK"/>'
    "</RESULTS></ATHLETE></ATHLETES></CLUB></CLUBS>"
    "</MEET></MEETS></LENEX>"
)


def test_lenex_prelim_round_marks_prelim():
    meet = parse_lenex(_LENEX_TMPL.format(round="PRE").encode("utf-8"))
    assert meet.events[0].swims[0].round_hint == "prelim"


def test_lenex_final_round_has_no_hint():
    meet = parse_lenex(_LENEX_TMPL.format(round="FIN").encode("utf-8"))
    assert meet.events[0].swims[0].round_hint is None


# ---------------------------------------------------------------------------
# #55 — weekend_in_numbers de-dupes same-swim PB / final derivatives
# ---------------------------------------------------------------------------


def _ra(atype: str, swim_id: str, *, swimmer: str = "Maya", event: str = "100 Free") -> dict:
    return {
        "achievement": {
            "type": atype,
            "swimmer_id": swimmer,
            "swimmer_name": swimmer,
            "event": event,
            "swim_id": swim_id,
            "raw_facts": {},
        }
    }


def _stats(report: dict) -> dict:
    return {s["label"]: s["value"] for s in build_weekend_in_numbers(report)["stats"]}


def test_weekend_pb_derivatives_of_one_swim_count_once():
    ranked = [
        _ra("pb_confirmed", "k1:100FRLC:timed_final:pb"),
        _ra("pb_magnitude_huge", "k1:100FRLC:timed_final:mag_huge"),
        _ra("official_pb_confirmed", "k1:100FRLC:timed_final:official_pb"),
        # a genuine second PB on a different swim still counts
        _ra("pb_confirmed", "k2:50FRLC:timed_final:pb", swimmer="Sam"),
    ]
    stats = _stats({"meet_name": "M", "ranked_achievements": ranked, "n_swims_analysed": 10})
    assert stats["PBs"] == "2"


def test_weekend_final_derivatives_of_one_swim_count_once():
    ranked = [
        _ra("final_appearance", "k1:200BKLC:timed_final:final_appearance"),
        _ra("heat_to_final", "k1:200BKLC:timed_final:h2f"),
    ]
    stats = _stats({"meet_name": "M", "ranked_achievements": ranked, "n_swims_analysed": 10})
    assert stats["Finals"] == "1"


def test_weekend_without_swim_id_preserves_per_row_count():
    # No swim_id → cannot dedupe, so each PB row still counts (no data loss).
    ranked = [
        {
            "achievement": {
                "type": "pb_confirmed",
                "swimmer_name": "A",
                "event": "e",
                "raw_facts": {},
            }
        },
        {
            "achievement": {
                "type": "pb_confirmed",
                "swimmer_name": "B",
                "event": "e",
                "raw_facts": {},
            }
        },
    ]
    stats = _stats({"meet_name": "M", "ranked_achievements": ranked, "n_swims_analysed": 10})
    assert stats["PBs"] == "2"


# ---------------------------------------------------------------------------
# #58 — club_record emits one achievement per broken key
# ---------------------------------------------------------------------------


def _record_swim(time_cs: int) -> SimpleNamespace:
    return SimpleNamespace(
        swimmer_key="k1",
        distance=100,
        stroke="FR",
        course="LC",
        finals_time_cs=time_cs,
        dq=False,
        gender="F",
        swim_date="2026-06-06",
        round="F",
    )


def _records() -> dict:
    return {
        (100, "FR", "LC", "F", "open"): {
            "time_cs": 6210,
            "holder": "Erin",
            "set_date": "2019-05-01",
        },
        (100, "FR", "LC", "F", "13-14"): {
            "time_cs": 6500,
            "holder": "Cara",
            "set_date": "2021-03-02",
        },
    }


def test_club_record_emits_one_achievement_per_broken_key():
    swim = _record_swim(6150)  # beats BOTH the 13-14 (6500) and open (6210) marks
    extra = {
        "swimmer_name": "Maya Patel",
        "club_records": _records(),
        "swimmer_meta": {"k1": {"gender": "F", "age": 14}},
    }
    achs = ClubRecordDetector().detect(
        swim, SimpleNamespace(), SimpleNamespace(swimmer_name="Maya Patel"), [swim], extra
    )
    assert len(achs) == 2
    assert {a.raw_facts["age_group"] for a in achs} == {"open", "13-14"}
    # distinct swim ids so the two cards don't collapse downstream
    assert len({a.swim_id for a in achs}) == 2
    # most-specific band still leads
    assert achs[0].raw_facts["age_group"] == "13-14"


def test_club_record_single_key_when_only_one_broken():
    swim = _record_swim(6150)  # age 16 → 13-14 band does not apply, only open breaks
    extra = {
        "swimmer_name": "Maya Patel",
        "club_records": _records(),
        "swimmer_meta": {"k1": {"gender": "F", "age": 16}},
    }
    achs = ClubRecordDetector().detect(
        swim, SimpleNamespace(), SimpleNamespace(swimmer_name="Maya Patel"), [swim], extra
    )
    assert len(achs) == 1
    assert achs[0].raw_facts["age_group"] == "open"


# ---------------------------------------------------------------------------
# #61 — milestones: unknown-to-registry vs known-with-zero-prior-races
# ---------------------------------------------------------------------------


def _milestone_swim() -> SimpleNamespace:
    return SimpleNamespace(
        swimmer_key="maya-patel-2010",
        distance=100,
        stroke="FR",
        course="LC",
        finals_time_cs=6532,
        dq=False,
        round="F",
        swim_date="2026-06-06",
        place=1,
    )


def test_milestone_silent_for_unknown_registry_swimmer():
    swim = _milestone_swim()
    extra = {
        "swimmer_name": "Maya Patel",
        "athlete_milestones": {
            "someone else": {"athlete_id": "x", "prior_races": 3, "prior_events": []}
        },
    }
    achs = MilestoneDetector().detect(
        swim, SimpleNamespace(), SimpleNamespace(swimmer_name="Maya Patel"), [swim], extra
    )
    assert achs == []


def test_milestone_debut_fires_for_known_swimmer_with_zero_prior_races():
    swim = _milestone_swim()
    extra = {
        "swimmer_name": "Maya Patel",
        "athlete_milestones": {
            "maya patel": {"athlete_id": "a1", "prior_races": 0, "prior_events": []}
        },
    }
    achs = MilestoneDetector().detect(
        swim, SimpleNamespace(), SimpleNamespace(swimmer_name="Maya Patel"), [swim], extra
    )
    assert [a.type for a in achs] == ["club_debut"]
