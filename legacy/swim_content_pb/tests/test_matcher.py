"""Unit tests for matcher.py decide_pb."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import unittest
from pathlib import Path

from swim_content_pb.parser import parse_pb_html
from swim_content_pb.matcher import decide_pb
from swim_content_pb.schema import IdentityMatch, ParsedSnapshot

FIXTURES = Path(__file__).parent / "fixtures"


def _verified_identity(hy3_name="BRADLEY, MATHEW J", asa_id="1382076", sr_name="Mathew Bradley"):
    from swim_content_pb.identity import canonicalise_name
    return IdentityMatch(
        asa_id=asa_id,
        hy3_name=hy3_name,
        sr_name=sr_name,
        canonical_hy3_name=canonicalise_name(hy3_name),
        canonical_sr_name=canonicalise_name(sr_name),
        method="asa_id_verified",
        confidence=1.0,
        safe_to_use=True,
        notes=["verified"],
        alternative_matches=[],
    )


def _unverified_identity(method="needs_verification"):
    from swim_content_pb.identity import canonicalise_name
    return IdentityMatch(
        asa_id="123",
        hy3_name="WRONG, NAME",
        sr_name="Different Name",
        canonical_hy3_name=canonicalise_name("WRONG, NAME"),
        canonical_sr_name=canonicalise_name("Different Name"),
        method=method,
        confidence=0.0,
        safe_to_use=False,
        notes=["mismatch"],
        alternative_matches=[],
    )


class TestDecidePb(unittest.TestCase):

    def _load_snapshot(self, name: str, asa_id: str):
        html = (FIXTURES / name).read_text(encoding="utf-8")
        return parse_pb_html(html, asa_id, "http://example.com", "2024-01-01T00:00:00Z")

    def test_suppressed_when_not_safe(self):
        identity = _unverified_identity("needs_verification")
        result = decide_pb(
            swim_id="swim1",
            swimmer_asa_id="123",
            swimmer_name="Wrong Name",
            event_distance=100,
            event_stroke="free",
            course="LC",
            current_time_seconds=54.0,
            current_time_display="54.00",
            identity=identity,
            snapshot=None,
            meet_name="Test Meet",
            meet_date_iso="2024-06-01",
            venue="Test Venue",
        )
        self.assertEqual(result.status, "SUPPRESSED_NEEDS_VERIFICATION")
        self.assertFalse(result.safe_to_post)
        self.assertGreater(len(result.audit_trail), 0)

    def test_unverified_when_no_snapshot(self):
        identity = _verified_identity()
        result = decide_pb(
            swim_id="swim2",
            swimmer_asa_id="1382076",
            swimmer_name="Mathew Bradley",
            event_distance=100,
            event_stroke="free",
            course="LC",
            current_time_seconds=54.0,
            current_time_display="54.00",
            identity=identity,
            snapshot=None,
            meet_name="Test Meet",
            meet_date_iso="2024-06-01",
            venue="Test Venue",
        )
        self.assertEqual(result.status, "PB_UNVERIFIED")
        self.assertFalse(result.safe_to_post)

    def test_confirmed_pb(self):
        identity = _verified_identity()
        snap = self._load_snapshot("sr_basic.html", "1382076")
        # Previous LC 50 free PB = 25.34s; swim 24.0s = improvement
        result = decide_pb(
            swim_id="swim3",
            swimmer_asa_id="1382076",
            swimmer_name="Mathew Bradley",
            event_distance=50,
            event_stroke="free",
            course="LC",
            current_time_seconds=24.0,
            current_time_display="24.00",
            identity=identity,
            snapshot=snap,
            meet_name="Other Meet",
            meet_date_iso="2025-06-01",
            venue="London",
        )
        self.assertEqual(result.status, "CONFIRMED_PB")
        self.assertTrue(result.safe_to_post)
        self.assertLess(result.delta_seconds, 0)
        self.assertIsNotNone(result.improvement_percentage)
        self.assertGreater(len(result.audit_trail), 3)

    def test_not_pb(self):
        identity = _verified_identity()
        snap = self._load_snapshot("sr_basic.html", "1382076")
        # Previous LC 50 free PB = 25.34s; swim 26.0s = slower
        result = decide_pb(
            swim_id="swim4",
            swimmer_asa_id="1382076",
            swimmer_name="Mathew Bradley",
            event_distance=50,
            event_stroke="free",
            course="LC",
            current_time_seconds=26.0,
            current_time_display="26.00",
            identity=identity,
            snapshot=snap,
            meet_name="Other Meet",
            meet_date_iso="2025-06-01",
            venue="London",
        )
        self.assertEqual(result.status, "NOT_PB")
        self.assertFalse(result.safe_to_post)
        self.assertGreater(result.delta_seconds, 0)

    def test_likely_pb_all_entries_excluded(self):
        """When all history is from this meet, should return LIKELY_PB."""
        identity = _verified_identity(hy3_name="EVANS, TOM", sr_name="Tom Evans", asa_id="111")
        snap = self._load_snapshot("sr_same_meet.html", "111")
        # The LC 100 free entry is from the same meet
        result = decide_pb(
            swim_id="swim5",
            swimmer_asa_id="111",
            swimmer_name="Tom Evans",
            event_distance=100,
            event_stroke="free",
            course="LC",
            current_time_seconds=52.5,
            current_time_display="52.50",
            identity=identity,
            snapshot=snap,
            meet_name="Swansea Aquatics May Long Course",
            meet_date_iso="2026-05-02",
            venue="Wales National Pool",
        )
        self.assertEqual(result.status, "LIKELY_PB")
        self.assertFalse(result.safe_to_post)  # LIKELY_PB is not safe_to_post

    def test_audit_trail_populated(self):
        """Every decision must have a non-empty audit_trail."""
        identity = _verified_identity()
        snap = self._load_snapshot("sr_basic.html", "1382076")
        result = decide_pb(
            swim_id="swim6",
            swimmer_asa_id="1382076",
            swimmer_name="Mathew Bradley",
            event_distance=50,
            event_stroke="free",
            course="LC",
            current_time_seconds=24.5,
            current_time_display="24.50",
            identity=identity,
            snapshot=snap,
            meet_name="Other Meet",
            meet_date_iso="2025-06-01",
            venue="London",
        )
        self.assertIsInstance(result.audit_trail, list)
        self.assertGreater(len(result.audit_trail), 0)
        self.assertIn("DECISION:", "\n".join(result.audit_trail))


if __name__ == "__main__":
    unittest.main()
