"""Regression test: a stranded fix (branch pushed, no PR opened) must leave its
bug OPEN, not stuck in 'fixing' limbo.

The finder never re-opens fix-owned statuses (report.FIX_OWNED_STATUSES), so if
fix_one marks a bug 'fixing' when no PR actually opened, the bug is excluded
from both the fix loop and the finder forever — even once PR creation works
again. fix_one must only _mark_fixing AFTER confirming a PR opened.
"""
from __future__ import annotations

import json

import pytest

from autotest import fix_loop, builder, report


@pytest.fixture
def one_open_bug(tmp_path, monkeypatch):
    """Point the ledger at a temp file holding a single open product bug."""
    led = tmp_path / "ledger.json"
    bug = {
        "fingerprint": "deadbeef01", "status": "open", "severity": "high",
        "category": "semantic:user_brain", "route": "post-upload",
        "title": "Some real product bug", "fix_attempts": 0,
    }
    led.write_text(json.dumps({"schema": 1, "bugs": {"deadbeef01": bug}}))
    monkeypatch.setattr(report, "LEDGER_PATH", led)
    fix_loop._JOURNAL.clear()
    # Neutralise the heavy side effects so fix_one reaches the PR step.
    monkeypatch.setattr(builder, "_git", lambda *a, **k: (0, ""))
    monkeypatch.setattr(builder, "implement_until_green",
                        lambda *a, **k: (True, ["src/x.py"], 3, "green"))
    # fix_one does a local `from autotest import notify` → patch the module attr.
    monkeypatch.setattr("autotest.notify.notify", lambda *a, **k: None)
    return led, bug


def _status(led):
    return json.loads(led.read_text())["bugs"]["deadbeef01"]


def test_no_pr_leaves_bug_open_not_fixing(one_open_bug, monkeypatch):
    led, bug = one_open_bug
    # PR creation is denied → _open_pr returns an error, no url.
    monkeypatch.setattr(builder, "_open_pr", lambda *a, **k: ("", "denied: not permitted to create"))
    monkeypatch.setattr(builder, "_merge_to_main", lambda *a, **k: "no PR opened — auto-merge NOT armed")

    res = fix_loop.fix_one(bug)

    assert res["result"] == "fix-pushed-no-pr"
    entry = _status(led)
    assert entry["status"] == "open", "stranded bug must stay OPEN so it's retried"
    assert not entry.get("fix_pr"), "must not set fix_pr when no PR opened (would exclude it forever)"


def test_pr_opened_marks_fixing(one_open_bug, monkeypatch):
    led, bug = one_open_bug
    url = "https://github.com/acme/repo/pull/9"
    monkeypatch.setattr(builder, "_open_pr", lambda *a, **k: (url, ""))
    monkeypatch.setattr(builder, "_merge_to_main", lambda *a, **k: "auto-merge to main enabled")

    res = fix_loop.fix_one(bug)

    assert res["result"] == "fix-opened"
    entry = _status(led)
    assert entry["status"] == "fixing"
    assert entry.get("fix_pr") == url
