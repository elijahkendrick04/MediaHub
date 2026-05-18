"""tests/test_playbooks.py — B11. Persistent learned-strategy memory.

The playbook layer is the AI's long-term scraping memory. These tests
cover the contract handlers + learners rely on:

  - domain_for() canonicalises hosts (strips www., handles bare hosts)
  - load/save round-trip preserves the JSON structure
  - is_stale() uses last_validated_at + max_age, treats missing strategy
    as stale, treats unparseable timestamps as stale
  - needs_regeneration() flags streaks of recent failures regardless of age
  - record_attempt() advances counters + last_validated_at on success
  - audit log appends one JSON object per event, tail() reads back
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.brand import playbooks  # noqa: E402


@pytest.fixture
def iso_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    yield tmp_path


# ---------------------------------------------------------------------------
# domain_for
# ---------------------------------------------------------------------------

def test_domain_strips_www_prefix():
    assert playbooks.domain_for("https://www.instagram.com/foo") == "instagram.com"


def test_domain_preserves_subdomains_other_than_www():
    assert playbooks.domain_for("https://m.facebook.com/foo") == "m.facebook.com"


def test_domain_lowercases():
    assert playbooks.domain_for("https://Instagram.COM/foo") == "instagram.com"


def test_domain_adds_https_when_missing():
    assert playbooks.domain_for("instagram.com/foo") == "instagram.com"


def test_domain_empty_input():
    assert playbooks.domain_for("") == ""
    assert playbooks.domain_for("   ") == ""


# ---------------------------------------------------------------------------
# load / save round-trip
# ---------------------------------------------------------------------------

def test_load_returns_none_when_missing(iso_root):
    assert playbooks.load("instagram.com") is None


def test_save_then_load_roundtrips(iso_root):
    pb = playbooks.empty_playbook("instagram.com")
    pb["strategy"] = {"url_template": "https://www.instagram.com/{handle}/",
                       "parser": "html"}
    pb["last_validated_at"] = "2026-05-17T10:00:00+00:00"
    playbooks.save(pb)
    loaded = playbooks.load("instagram.com")
    assert loaded is not None
    assert loaded["strategy"]["url_template"] == "https://www.instagram.com/{handle}/"
    assert loaded["last_validated_at"] == "2026-05-17T10:00:00+00:00"


def test_save_prunes_long_history(iso_root):
    pb = playbooks.empty_playbook("instagram.com")
    pb["strategy"] = {"url_template": "x"}
    pb["history"] = [{"ts": f"2026-05-17T10:{i:02d}:00+00:00",
                       "status": "real_content",
                       "notes": ""} for i in range(40)]
    playbooks.save(pb)
    loaded = playbooks.load("instagram.com")
    assert len(loaded["history"]) <= 25


# ---------------------------------------------------------------------------
# is_stale
# ---------------------------------------------------------------------------

def test_empty_playbook_is_stale():
    assert playbooks.is_stale({})
    assert playbooks.is_stale(playbooks.empty_playbook("x.com"))


def test_recent_playbook_not_stale():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    pb = playbooks.empty_playbook("x.com")
    pb["strategy"] = {"url_template": "x"}
    pb["last_validated_at"] = now
    assert not playbooks.is_stale(pb)


def test_old_playbook_is_stale():
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
    pb = playbooks.empty_playbook("x.com")
    pb["strategy"] = {"url_template": "x"}
    pb["last_validated_at"] = old
    assert playbooks.is_stale(pb)


def test_unparseable_timestamp_is_stale():
    pb = playbooks.empty_playbook("x.com")
    pb["strategy"] = {"url_template": "x"}
    pb["last_validated_at"] = "not a date"
    assert playbooks.is_stale(pb)


def test_drift_threshold_overridable():
    short_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    pb = playbooks.empty_playbook("x.com")
    pb["strategy"] = {"url_template": "x"}
    pb["last_validated_at"] = short_ago
    # Default 7 days → not stale
    assert not playbooks.is_stale(pb)
    # Tighten to 30 minutes → stale
    assert playbooks.is_stale(pb, max_age=timedelta(minutes=30))


# ---------------------------------------------------------------------------
# needs_regeneration
# ---------------------------------------------------------------------------

def test_no_history_no_regeneration():
    pb = playbooks.empty_playbook("x.com")
    pb["strategy"] = {"url_template": "x"}
    assert not playbooks.needs_regeneration(pb)


def test_three_recent_failures_triggers_regeneration():
    pb = playbooks.empty_playbook("x.com")
    pb["strategy"] = {"url_template": "x"}
    pb["history"] = [
        {"ts": "...", "status": "real_content", "notes": ""},
        {"ts": "...", "status": "hard_blocked", "notes": ""},
        {"ts": "...", "status": "hard_blocked", "notes": ""},
        {"ts": "...", "status": "auth_walled", "notes": ""},
    ]
    assert playbooks.needs_regeneration(pb)


def test_one_recent_success_resets_regeneration():
    pb = playbooks.empty_playbook("x.com")
    pb["strategy"] = {"url_template": "x"}
    pb["history"] = [
        {"ts": "...", "status": "hard_blocked", "notes": ""},
        {"ts": "...", "status": "hard_blocked", "notes": ""},
        {"ts": "...", "status": "real_content", "notes": ""},
    ]
    assert not playbooks.needs_regeneration(pb)


# ---------------------------------------------------------------------------
# record_attempt
# ---------------------------------------------------------------------------

def test_record_attempt_advances_counters(iso_root):
    pb = playbooks.empty_playbook("x.com")
    pb["strategy"] = {"url_template": "x"}
    playbooks.record_attempt(pb, status="real_content", notes="ok")
    assert pb["success_count"] == 1
    assert pb["fail_count"] == 0
    assert pb["last_validated_at"]
    playbooks.record_attempt(pb, status="hard_blocked")
    assert pb["success_count"] == 1
    assert pb["fail_count"] == 1


def test_record_attempt_persists(iso_root):
    pb = playbooks.empty_playbook("x.com")
    pb["strategy"] = {"url_template": "x"}
    playbooks.record_attempt(pb, status="real_content", persist=True)
    loaded = playbooks.load("x.com")
    assert loaded["success_count"] == 1


# ---------------------------------------------------------------------------
# audit log
# ---------------------------------------------------------------------------

def test_audit_log_appends_and_reads_back(iso_root):
    playbooks.record_audit({"domain": "instagram.com", "action": "regenerate"})
    playbooks.record_audit({"domain": "facebook.com", "action": "replay"})
    tail = playbooks.audit_tail(50)
    assert len(tail) == 2
    assert tail[0]["domain"] == "instagram.com"
    assert tail[1]["action"] == "replay"
    assert all("ts" in event for event in tail)


def test_audit_log_tail_respects_limit(iso_root):
    for i in range(60):
        playbooks.record_audit({"domain": f"x{i}.com", "action": "replay"})
    tail = playbooks.audit_tail(10)
    assert len(tail) == 10
    # The most recent ones come back
    assert tail[-1]["domain"] == "x59.com"
