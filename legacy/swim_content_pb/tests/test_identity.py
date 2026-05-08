"""Unit tests for identity.py canonicalise_name and match_swimmer."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import unittest

from swim_content_pb.identity import canonicalise_name, match_swimmer
from swim_content_pb.corrections import CorrectionsStore
from swim_content_pb.schema import ParsedSnapshot


class TestCanonicalise(unittest.TestCase):

    def test_hy3_vs_sr_same_person(self):
        """BRADLEY, MATHEW J (HY3) == Mathew Bradley (SR)"""
        self.assertEqual(
            canonicalise_name("BRADLEY, MATHEW J"),
            canonicalise_name("Mathew Bradley"),
        )

    def test_no_fuzzy_initial_only(self):
        """'SMITH, J' must NOT match 'John Smith' — no fuzzy matching."""
        self.assertNotEqual(
            canonicalise_name("SMITH, J"),
            canonicalise_name("John Smith"),
        )

    def test_uppercase_normalisation(self):
        self.assertEqual(canonicalise_name("alice smith"), canonicalise_name("ALICE SMITH"))

    def test_punctuation_stripped(self):
        """Hyphens and apostrophes should be stripped."""
        self.assertEqual(canonicalise_name("O'BRIEN, SEAN"), canonicalise_name("Sean Obrien"))

    def test_different_names(self):
        """Genuinely different names must not match."""
        self.assertNotEqual(
            canonicalise_name("JONES, SARAH"),
            canonicalise_name("Sarah Bradley"),
        )

    def test_empty_string(self):
        self.assertEqual(canonicalise_name(""), "")

    def test_middle_name_ignored(self):
        """Middle names (multi-char) are included; middle INITIALS (1 char) are stripped."""
        # "MATHEW J BRADLEY" - J is initial, stripped
        # "Mathew Bradley" - same person
        c1 = canonicalise_name("MATHEW J BRADLEY")
        c2 = canonicalise_name("Mathew Bradley")
        self.assertEqual(c1, c2)

    def test_whitespace_collapse(self):
        self.assertEqual(
            canonicalise_name("  Alice   Smith  "),
            canonicalise_name("Alice Smith"),
        )


class TestMatchSwimmer(unittest.TestCase):
    """Test the full match_swimmer strategy."""

    def _make_snapshot(self, fetch_ok: bool, swimmer_name=None, error=None):
        return ParsedSnapshot(
            asa_id="123456",
            swimmer_name=swimmer_name,
            entries=[],
            source_url="http://example.com",
            fetched_at="2024-01-01T00:00:00+00:00",
            fetch_ok=fetch_ok,
            error=error,
        )

    def test_no_id(self):
        cs = CorrectionsStore()
        result = match_swimmer(
            hy3_name="JONES, SARAH",
            asa_id=None,
            sr_snapshot=None,
            corrections=cs,
            run_id="test_run",
        )
        self.assertEqual(result.method, "no_id")
        self.assertFalse(result.safe_to_use)
        self.assertEqual(result.confidence, 0.0)

    def test_verified(self):
        cs = CorrectionsStore()
        snap = self._make_snapshot(True, swimmer_name="Mathew Bradley")
        result = match_swimmer(
            hy3_name="BRADLEY, MATHEW J",
            asa_id="1382076",
            sr_snapshot=snap,
            corrections=cs,
            run_id="test_run",
        )
        self.assertEqual(result.method, "asa_id_verified")
        self.assertTrue(result.safe_to_use)
        self.assertEqual(result.confidence, 1.0)

    def test_needs_verification(self):
        cs = CorrectionsStore()
        snap = self._make_snapshot(True, swimmer_name="Matthew Bradly")  # different spelling
        result = match_swimmer(
            hy3_name="BRADLEY, MATHEW J",
            asa_id="1382076",
            sr_snapshot=snap,
            corrections=cs,
            run_id="test_run",
        )
        self.assertEqual(result.method, "needs_verification")
        self.assertFalse(result.safe_to_use)
        self.assertEqual(result.confidence, 0.0)

    def test_fetch_failed(self):
        cs = CorrectionsStore()
        snap = self._make_snapshot(False, error="HTTP 503")
        result = match_swimmer(
            hy3_name="JONES, SARAH",
            asa_id="999999",
            sr_snapshot=snap,
            corrections=cs,
            run_id="test_run",
        )
        self.assertEqual(result.method, "asa_id_unverified")
        self.assertFalse(result.safe_to_use)

    def test_manual_override_ignore(self):
        cs = CorrectionsStore()
        cs.set_ignore_pb("test_run", "1382076", reason="Wrong swimmer")
        snap = self._make_snapshot(True, swimmer_name="Mathew Bradley")
        result = match_swimmer(
            hy3_name="BRADLEY, MATHEW J",
            asa_id="1382076",
            sr_snapshot=snap,
            corrections=cs,
            run_id="test_run",
        )
        self.assertEqual(result.method, "manual_override")
        self.assertFalse(result.safe_to_use)
        # Cleanup
        cs.remove_override("test_run", "1382076")

    def test_manual_override_new_id(self):
        cs = CorrectionsStore()
        cs.set_override_asa_id("test_run", "1382076", "9999999", note="corrected")
        snap = self._make_snapshot(True, swimmer_name="Mathew Bradley")
        result = match_swimmer(
            hy3_name="BRADLEY, MATHEW J",
            asa_id="1382076",
            sr_snapshot=snap,
            corrections=cs,
            run_id="test_run",
        )
        self.assertEqual(result.method, "manual_override")
        self.assertTrue(result.safe_to_use)
        self.assertEqual(result.asa_id, "9999999")
        # Cleanup
        cs.remove_override("test_run", "1382076")


if __name__ == "__main__":
    unittest.main()
