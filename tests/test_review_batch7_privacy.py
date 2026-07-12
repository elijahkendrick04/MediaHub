"""Regression tests for deep-review batch 7 (privacy/compliance data-safety).

  #108 erasure._card_is_about uses a whole-name boundary match, so erasing one
       subject never deletes a card about a different, longer-named subject.
  #106 analytics record/delete round-trip survives the atomic-write + lock
       restructure (a torn write no longer wipes the history).
"""

from __future__ import annotations

from mediahub.privacy.erasure import _card_is_about


def test_card_is_about_does_not_match_a_longer_name():
    # Erasing "Sam Lee" must NOT match a card about "Sam Leeson".
    assert _card_is_about({"headline": "Sam Leeson wins gold"}, "sam lee") is False
    assert _card_is_about({"name": "Sam Leeson"}, "sam lee") is False
    assert _card_is_about({"title": "Leeson family relay"}, "lee") is False


def test_card_is_about_matches_the_actual_subject():
    assert _card_is_about({"name": "Sam Lee"}, "sam lee") is True
    assert _card_is_about({"headline": "Sam Lee smashes the club record"}, "sam lee") is True
    assert _card_is_about({"first_name": "Sam", "last_name": "Lee"}, "sam lee") is True


def test_analytics_sequential_records_all_survive(tmp_path):
    from mediahub.analytics import store

    r1 = store.record_metric("orgA", "achievement", "2026-01-01", {"likes": 5}, data_dir=tmp_path)
    r2 = store.record_metric("orgA", "achievement", "2026-01-02", {"likes": 7}, data_dir=tmp_path)
    assert r1 is not None and r2 is not None
    posts = store.load_metrics("orgA", data_dir=tmp_path)
    assert len(posts) == 2  # the second record did not overwrite the first
    # And the metrics file is valid JSON (atomic write, never torn).
    import json

    p = store._path("orgA", tmp_path)
    assert isinstance(json.loads(p.read_text())["posts"], list)
