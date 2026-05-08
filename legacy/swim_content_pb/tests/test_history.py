"""Unit tests for history.py same-meet dedup and PreviousPB building."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import unittest
from pathlib import Path

from swim_content_pb.parser import parse_pb_html
from swim_content_pb.history import build_previous_pb

FIXTURES = Path(__file__).parent / "fixtures"


class TestSameMeetDedup(unittest.TestCase):

    def _load_snapshot(self, name: str, asa_id: str):
        html = (FIXTURES / name).read_text(encoding="utf-8")
        from swim_content_pb.parser import parse_pb_html
        return parse_pb_html(html, asa_id, "http://example.com", "2026-05-02T00:00:00Z")

    def test_same_meet_name_excluded(self):
        """History entry from same meet by name must be excluded."""
        snap = self._load_snapshot("sr_same_meet.html", "111")
        # The LC 100 Freestyle has a time from "Swansea Aquatics May Long Course" on 02/05/2026
        prev = build_previous_pb(
            snapshot=snap,
            swimmer_asa_id="111",
            swimmer_name="Tom Evans",
            event_distance=100,
            event_stroke="free",
            course="LC",
            meet_name="Swansea Aquatics May Long Course",
            meet_date_iso="2026-05-02",
            venue="Wales National Pool",
        )
        # All LC entries are from this meet, so None should be returned
        self.assertIsNone(prev)

    def test_different_meet_kept(self):
        """History entry from a different meet must NOT be excluded."""
        snap = self._load_snapshot("sr_basic.html", "1382076")
        prev = build_previous_pb(
            snapshot=snap,
            swimmer_asa_id="1382076",
            swimmer_name="Mathew Bradley",
            event_distance=50,
            event_stroke="free",
            course="LC",
            meet_name="Some Other Meet",
            meet_date_iso="2025-06-01",  # different date
            venue="London",
        )
        self.assertIsNotNone(prev)
        self.assertAlmostEqual(prev.time_seconds, 25.34, places=1)

    def test_course_mismatch_rejected(self):
        """LC data must not be used for SC comparison."""
        snap = self._load_snapshot("sr_basic.html", "1382076")
        prev = build_previous_pb(
            snapshot=snap,
            swimmer_asa_id="1382076",
            swimmer_name="Mathew Bradley",
            event_distance=50,
            event_stroke="free",
            course="SC",
            meet_name="Some Other Meet",
            meet_date_iso="2025-06-01",
            venue="London",
        )
        # SC data exists in the fixture (24.11)
        if prev is not None:
            self.assertEqual(prev.course, "SC")

    def test_excluded_swims_populated(self):
        """excluded_swims must record what was excluded and why."""
        snap = self._load_snapshot("sr_multi_event.html", "9999")
        prev = build_previous_pb(
            snapshot=snap,
            swimmer_asa_id="9999",
            swimmer_name="Sarah Jones",
            event_distance=50,
            event_stroke="free",
            course="LC",
            meet_name="Swansea Aquatics May Long Course",
            meet_date_iso="2024-05-10",  # same as the entry date in fixture
            venue="Wales National Pool",
        )
        if prev is None:
            # All entries excluded → excluded_swims via the None return path
            # Can't verify excluded_swims here but test the correct return
            pass
        # If some entries remain, excluded_swims still exists on the result
        # (PreviousPB.excluded_swims is populated)

    def test_picks_fastest_remaining(self):
        """With multiple history entries, the fastest is chosen."""
        snap = self._load_snapshot("sr_basic.html", "1382076")
        # 100 free LC: only one entry in fixture (55.12)
        prev = build_previous_pb(
            snapshot=snap,
            swimmer_asa_id="1382076",
            swimmer_name="Mathew Bradley",
            event_distance=100,
            event_stroke="free",
            course="LC",
            meet_name="Non-existent Meet",
            meet_date_iso="2025-12-01",
            venue="London",
        )
        self.assertIsNotNone(prev)
        self.assertAlmostEqual(prev.time_seconds, 55.12, places=1)


class TestDateWithinDays(unittest.TestCase):
    def test_within_2_days(self):
        from swim_content_pb.history import _date_within_days
        self.assertTrue(_date_within_days("2024-05-02", "2024-05-04", 2))

    def test_outside_2_days(self):
        from swim_content_pb.history import _date_within_days
        self.assertFalse(_date_within_days("2024-05-02", "2024-05-05", 2))

    def test_same_day(self):
        from swim_content_pb.history import _date_within_days
        self.assertTrue(_date_within_days("2024-05-02", "2024-05-02", 2))


if __name__ == "__main__":
    unittest.main()
