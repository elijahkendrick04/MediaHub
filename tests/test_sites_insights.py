"""Microsite engine (roadmap 1.16) — build 3: privacy-respecting view counts."""

from __future__ import annotations

import pytest

from mediahub.sites import insights


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def test_record_and_aggregate():
    insights.record_view("club-a", "s1", "", day="2026-06-01")
    insights.record_view("club-a", "s1", "", day="2026-06-01")
    insights.record_view("club-a", "s1", "results", day="2026-06-02")
    counts = insights.view_counts("club-a", "s1")
    assert counts["total"] == 3
    assert counts["by_page"]["index"] == 2  # empty slug → "index"
    assert counts["by_page"]["results"] == 1
    assert counts["by_day"]["2026-06-01"] == 2
    assert counts["by_day"]["2026-06-02"] == 1


def test_scoped_by_org_and_site():
    insights.record_view("club-a", "s1", "")
    assert insights.view_counts("club-b", "s1")["total"] == 0
    assert insights.view_counts("club-a", "s2")["total"] == 0


def test_empty_site():
    assert insights.view_counts("club-a", "none")["total"] == 0
