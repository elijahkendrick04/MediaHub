"""Microsite engine (roadmap 1.16) — build 3: poll vote tallies."""

from __future__ import annotations

import pytest

from mediahub.sites import widget_state as ws


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def test_record_and_count():
    ws.record_vote("club-a", "site1", "w1", "Fly")
    ws.record_vote("club-a", "site1", "w1", "Fly")
    counts = ws.record_vote("club-a", "site1", "w1", "Free")
    assert counts == {"Fly": 2, "Free": 1}
    assert ws.vote_counts("club-a", "site1", "w1") == {"Fly": 2, "Free": 1}


def test_scoped_by_org_site_widget():
    ws.record_vote("club-a", "site1", "w1", "A")
    # different org, site, or widget are independent tallies
    assert ws.vote_counts("club-b", "site1", "w1") == {}
    assert ws.vote_counts("club-a", "site2", "w1") == {}
    assert ws.vote_counts("club-a", "site1", "w2") == {}


def test_no_votes_is_empty():
    assert ws.vote_counts("club-a", "s", "w") == {}
