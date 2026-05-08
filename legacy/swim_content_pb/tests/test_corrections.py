"""Unit tests for corrections.py."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestCorrectionsStore(unittest.TestCase):

    def setUp(self):
        """Use a temp directory so we don't pollute runs_v4/."""
        self.tmpdir = tempfile.mkdtemp()

    def _make_store(self):
        from swim_content_pb import corrections as corr_module
        store = corr_module.CorrectionsStore()
        # Patch the runs dir to use tmpdir
        self._orig_runs_dir = corr_module._RUNS_DIR
        corr_module._RUNS_DIR = Path(self.tmpdir)
        return store

    def tearDown(self):
        import swim_content_pb.corrections as corr_module
        corr_module._RUNS_DIR = getattr(self, "_orig_runs_dir", corr_module._RUNS_DIR)

    def test_no_override_initially(self):
        store = self._make_store()
        result = store.get_override("run1", "123456")
        self.assertIsNone(result)

    def test_set_and_get_override_asa_id(self):
        store = self._make_store()
        store.set_override_asa_id("run1", "123456", "999999", note="corrected")
        result = store.get_override("run1", "123456")
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "override_asa_id")
        self.assertEqual(result["new_asa_id"], "999999")

    def test_set_and_get_ignore_pb(self):
        store = self._make_store()
        store.set_ignore_pb("run1", "name:JONES, SARAH", reason="Wrong person")
        result = store.get_override("run1", "name:JONES, SARAH")
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "ignore_pb")
        self.assertIn("Wrong person", result["reason"])

    def test_all_for_run(self):
        store = self._make_store()
        store.set_ignore_pb("run1", "aaa", reason="a")
        store.set_override_asa_id("run1", "bbb", "999", note="b")
        all_items = store.all_for_run("run1")
        self.assertEqual(len(all_items), 2)

    def test_remove_override(self):
        store = self._make_store()
        store.set_ignore_pb("run1", "123", reason="test")
        store.remove_override("run1", "123")
        self.assertIsNone(store.get_override("run1", "123"))

    def test_different_runs_isolated(self):
        """Overrides for run1 must not affect run2."""
        store = self._make_store()
        store.set_ignore_pb("run1", "123", reason="test")
        result = store.get_override("run2", "123")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
