"""Unit tests for parser.py."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import unittest
from pathlib import Path

from swim_content_pb.parser import parse_pb_html, parse_swim_time, parse_site_date, _parse_event_label

FIXTURES = Path(__file__).parent / "fixtures"


class TestParseSwimTime(unittest.TestCase):
    def test_mmss(self):
        self.assertAlmostEqual(parse_swim_time("1:07.97"), 67.97)

    def test_ss(self):
        self.assertAlmostEqual(parse_swim_time("25.34"), 25.34)

    def test_longer(self):
        self.assertAlmostEqual(parse_swim_time("5:48.50"), 348.50)

    def test_none_on_empty(self):
        self.assertIsNone(parse_swim_time(""))

    def test_none_on_garbage(self):
        self.assertIsNone(parse_swim_time("abc"))


class TestParseSiteDate(unittest.TestCase):
    def test_ddmmyyyy(self):
        self.assertEqual(parse_site_date("15/03/2024"), "2024-03-15")

    def test_ddmmyy(self):
        self.assertEqual(parse_site_date("15/03/24"), "2024-03-15")

    def test_dd_mon_yyyy(self):
        self.assertEqual(parse_site_date("21-Mar-2024"), "2024-03-21")

    def test_dd_mon_yy(self):
        self.assertEqual(parse_site_date("21-Mar-24"), "2024-03-21")

    def test_dd_space_mon_space_yyyy(self):
        self.assertEqual(parse_site_date("21 Mar 2024"), "2024-03-21")

    def test_none_on_empty(self):
        self.assertIsNone(parse_site_date(""))


class TestParseEventLabel(unittest.TestCase):
    def test_freestyle(self):
        result = _parse_event_label("50 Freestyle")
        self.assertEqual(result, (50, "free"))

    def test_individual_medley(self):
        result = _parse_event_label("200 Individual Medley")
        self.assertEqual(result, (200, "im"))

    def test_backstroke(self):
        result = _parse_event_label("100 Backstroke")
        self.assertEqual(result, (100, "back"))

    def test_invalid_distance(self):
        result = _parse_event_label("300 Freestyle")
        self.assertIsNone(result)

    def test_invalid_stroke(self):
        result = _parse_event_label("100 Crawl")
        self.assertIsNone(result)


class TestParsePbHtml(unittest.TestCase):
    def _load_fixture(self, name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    def test_basic_fixture(self):
        html = self._load_fixture("sr_basic.html")
        snap = parse_pb_html(html, "1382076", "http://example.com", "2024-01-01T00:00:00Z")
        self.assertTrue(snap.fetch_ok)
        self.assertEqual(snap.swimmer_name, "Mathew Bradley")
        # Should have LC and SC entries
        lc = [e for e in snap.entries if e.course == "LC"]
        sc = [e for e in snap.entries if e.course == "SC"]
        self.assertGreater(len(lc), 0, "Should have LC entries")
        self.assertGreater(len(sc), 0, "Should have SC entries")

    def test_multi_event_fixture(self):
        html = self._load_fixture("sr_multi_event.html")
        snap = parse_pb_html(html, "9999", "http://example.com", "2024-01-01T00:00:00Z")
        self.assertEqual(snap.swimmer_name, "Sarah Jones")
        lc = [e for e in snap.entries if e.course == "LC"]
        self.assertGreaterEqual(len(lc), 3)

    def test_same_meet_fixture_has_meet_name(self):
        html = self._load_fixture("sr_same_meet.html")
        snap = parse_pb_html(html, "111", "http://example.com", "2026-05-02T00:00:00Z")
        lc = [e for e in snap.entries if e.course == "LC"]
        self.assertGreater(len(lc), 0)
        self.assertIsNotNone(lc[0].meet_name)

    def test_404_fixture_empty(self):
        html = self._load_fixture("sr_404.html")
        snap = parse_pb_html(html, "000", "http://example.com", "2024-01-01T00:00:00Z")
        # 404 pages should have no entries (no valid tables)
        lc = [e for e in snap.entries if e.course == "LC"]
        sc = [e for e in snap.entries if e.course == "SC"]
        # May have empty list — 404 pages have no PB tables
        self.assertEqual(len(lc) + len(sc), 0)

    def test_entry_time_parseable(self):
        html = self._load_fixture("sr_basic.html")
        snap = parse_pb_html(html, "1382076", "http://example.com", "2024-01-01T00:00:00Z")
        for e in snap.entries:
            self.assertGreater(e.time_seconds, 0)

    def test_entry_date_parseable(self):
        html = self._load_fixture("sr_basic.html")
        snap = parse_pb_html(html, "1382076", "http://example.com", "2024-01-01T00:00:00Z")
        for e in snap.entries:
            if e.date_iso:
                self.assertRegex(e.date_iso, r"^\d{4}-\d{2}-\d{2}$")


if __name__ == "__main__":
    unittest.main()
