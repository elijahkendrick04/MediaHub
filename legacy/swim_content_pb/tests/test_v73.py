"""
V7.3 unit tests for swim_content_pb.

Tests CONFIRMED_OFFICIAL_PB rule in decide_pb().
"""
import unittest
from unittest.mock import MagicMock
from swim_content_pb.schema import (
    IdentityMatch, ParsedSnapshot, ParsedSwimEntry, PBDecision
)
from swim_content_pb.matcher import decide_pb, _date_within_days


def _make_identity(safe=True, method="asa_id_verified"):
    return IdentityMatch(
        asa_id="12345",
        hy3_name="Smith, Jane",
        sr_name="Jane Smith",
        canonical_hy3_name="smith,jane",
        canonical_sr_name="jane smith",
        method=method,
        confidence=0.95,
        safe_to_use=safe,
        notes=[],
    )


def _make_snapshot(entries=None):
    snap = ParsedSnapshot(
        asa_id="12345",
        swimmer_name="Jane Smith",
        entries=entries or [],
        source_url="https://swimmingresults.org/12345",
        fetched_at="2026-05-02T10:00:00Z",
        fetch_ok=True,
    )
    return snap


def _make_entry(dist=100, stroke="free", course="LC", time_sec=60.0, date_iso="2026-05-02"):
    return ParsedSwimEntry(
        distance=dist,
        stroke=stroke,
        course=course,
        time_str="1:00.00",
        time_seconds=time_sec,
        date_iso=date_iso,
        meet_name="Swansea Aquatics May LC 2026",
        venue="Swansea",
        licence=None,
        level=None,
        is_best=True,
    )


class TestConfirmedOfficialPB(unittest.TestCase):
    """Tests for Rule 0: CONFIRMED_OFFICIAL_PB."""

    def test_time_and_date_exact_match(self):
        """Exact time and exact date match should give CONFIRMED_OFFICIAL_PB."""
        entry = _make_entry(dist=100, stroke="FR", course="LC", time_sec=60.0, date_iso="2026-05-02")
        snapshot = _make_snapshot(entries=[entry])
        identity = _make_identity(safe=True)

        decision = decide_pb(
            swim_id="test:100FRLC:timed_final",
            swimmer_asa_id="12345",
            swimmer_name="Jane Smith",
            event_distance=100,
            event_stroke="FR",
            course="LC",
            current_time_seconds=60.0,
            current_time_display="1:00.00",
            identity=identity,
            snapshot=snapshot,
            meet_name="Swansea Aquatics May LC 2026",
            meet_date_iso="2026-05-02",
            venue="Swansea",
        )
        self.assertEqual(decision.status, "CONFIRMED_OFFICIAL_PB")
        self.assertTrue(decision.safe_to_post)
        self.assertEqual(decision.confidence, "high")

    def test_time_match_date_within_1_day(self):
        """Time match + date within 1 day should give CONFIRMED_OFFICIAL_PB."""
        entry = _make_entry(time_sec=60.01, date_iso="2026-05-03")
        snapshot = _make_snapshot(entries=[entry])
        identity = _make_identity(safe=True)

        decision = decide_pb(
            swim_id="test:100FRLC:timed_final",
            swimmer_asa_id="12345",
            swimmer_name="Jane Smith",
            event_distance=100,
            event_stroke="FR",
            course="LC",
            current_time_seconds=60.01,
            current_time_display="1:00.01",
            identity=identity,
            snapshot=snapshot,
            meet_name="Swansea Aquatics May LC 2026",
            meet_date_iso="2026-05-02",
            venue="Swansea",
        )
        self.assertEqual(decision.status, "CONFIRMED_OFFICIAL_PB")

    def test_time_match_date_too_far(self):
        """Time match but date >1 day away should NOT give CONFIRMED_OFFICIAL_PB."""
        entry = _make_entry(time_sec=60.0, date_iso="2025-01-15")  # >1 day away
        snapshot = _make_snapshot(entries=[entry])
        identity = _make_identity(safe=True)

        decision = decide_pb(
            swim_id="test:100FRLC:timed_final",
            swimmer_asa_id="12345",
            swimmer_name="Jane Smith",
            event_distance=100,
            event_stroke="FR",
            course="LC",
            current_time_seconds=60.0,
            current_time_display="1:00.00",
            identity=identity,
            snapshot=snapshot,
            meet_name="Swansea Aquatics May LC 2026",
            meet_date_iso="2026-05-02",
            venue="Swansea",
        )
        self.assertNotEqual(decision.status, "CONFIRMED_OFFICIAL_PB")

    def test_time_outside_tolerance(self):
        """Time difference >0.005s should NOT give CONFIRMED_OFFICIAL_PB."""
        entry = _make_entry(time_sec=60.0, date_iso="2026-05-02")
        snapshot = _make_snapshot(entries=[entry])
        identity = _make_identity(safe=True)

        decision = decide_pb(
            swim_id="test:100FRLC:timed_final",
            swimmer_asa_id="12345",
            swimmer_name="Jane Smith",
            event_distance=100,
            event_stroke="FR",
            course="LC",
            current_time_seconds=60.5,  # 0.5s different — outside tolerance
            current_time_display="1:00.50",
            identity=identity,
            snapshot=snapshot,
            meet_name="Swansea Aquatics May LC 2026",
            meet_date_iso="2026-05-02",
            venue="Swansea",
        )
        self.assertNotEqual(decision.status, "CONFIRMED_OFFICIAL_PB")

    def test_unsafe_identity_suppressed(self):
        """Unsafe identity should still suppress, even if Rule 0 would match."""
        entry = _make_entry(time_sec=60.0, date_iso="2026-05-02")
        snapshot = _make_snapshot(entries=[entry])
        identity = _make_identity(safe=False, method="needs_verification")

        decision = decide_pb(
            swim_id="test:100FRLC:timed_final",
            swimmer_asa_id="12345",
            swimmer_name="Jane Smith",
            event_distance=100,
            event_stroke="FR",
            course="LC",
            current_time_seconds=60.0,
            current_time_display="1:00.00",
            identity=identity,
            snapshot=snapshot,
            meet_name="Swansea Aquatics May LC 2026",
            meet_date_iso="2026-05-02",
            venue="Swansea",
        )
        self.assertEqual(decision.status, "SUPPRESSED_NEEDS_VERIFICATION")


class TestDateWithinDays(unittest.TestCase):
    def test_same_day(self):
        self.assertTrue(_date_within_days("2026-05-02", "2026-05-02", 1))

    def test_one_day_apart(self):
        self.assertTrue(_date_within_days("2026-05-01", "2026-05-02", 1))

    def test_two_days_apart(self):
        self.assertFalse(_date_within_days("2026-04-30", "2026-05-02", 1))


if __name__ == "__main__":
    unittest.main()
