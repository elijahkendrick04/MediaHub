"""Roadmap 1.18 build 2 — @mention parsing & resolution (collab.mentions)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.collab import mentions as mn

MEMBERS = [
    ("coach@club.org", "Jane Doe"),
    ("chair@club.org", "Sam Patel"),
    ("vol@club.org", ""),
]


def test_extract_tokens():
    assert mn.extract_tokens("hi @coach and @chair@club.org") == ["coach", "chair@club.org"]
    assert mn.extract_tokens("no mentions here") == []
    assert mn.extract_tokens("") == []


def test_resolve_by_local_part():
    assert mn.resolve_mentions("ping @coach please", MEMBERS) == ["coach@club.org"]


def test_resolve_by_full_email():
    assert mn.resolve_mentions("ping @chair@club.org", MEMBERS) == ["chair@club.org"]


def test_resolve_by_name_slug():
    assert mn.resolve_mentions("hey @JaneDoe", MEMBERS) == ["coach@club.org"]


def test_resolve_distinct_and_ordered():
    out = mn.resolve_mentions("@coach @chair @coach", MEMBERS)
    assert out == ["coach@club.org", "chair@club.org"]


def test_unknown_mention_ignored():
    assert mn.resolve_mentions("@nobody here", MEMBERS) == []


def test_email_addresses_dont_falsely_mention():
    # A literal email in prose (preceded by a word char) is not a mention.
    assert mn.resolve_mentions("write to coach@club.org", MEMBERS) == []


def test_assistant_handles_not_resolved_to_humans():
    assert mn.resolve_mentions("@assistant help", MEMBERS) == []
    assert mn.mentions_assistant("hey @assistant") is True
    assert mn.mentions_assistant("@ai @copilot") is True
    assert mn.mentions_assistant("@coach") is False


def test_members_accepts_bare_email_strings():
    assert mn.resolve_mentions("@vol", ["vol@club.org"]) == ["vol@club.org"]
