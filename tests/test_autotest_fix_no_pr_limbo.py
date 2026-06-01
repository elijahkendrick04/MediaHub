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

from autotest import fix_loop, gitops, report


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
    # Neutralise the heavy side effects so fix_one reaches the PR step, recording
    # the git invocations so a test can assert how the branch was pushed.
    git_calls: list[tuple] = []

    def _rec_git(*a, **k):
        git_calls.append(a)
        return (0, "")

    monkeypatch.setattr(gitops, "_git", _rec_git)
    monkeypatch.setattr(gitops, "implement_until_green",
                        lambda *a, **k: (True, ["src/x.py"], 3, "green"))
    # fix_one does a local `from autotest import notify` → patch the module attr.
    monkeypatch.setattr("autotest.notify.notify", lambda *a, **k: None)
    return led, bug, git_calls


def _status(led):
    return json.loads(led.read_text())["bugs"]["deadbeef01"]


def test_no_pr_leaves_bug_open_not_fixing(one_open_bug, monkeypatch):
    led, bug, _ = one_open_bug
    # PR creation is denied → _open_pr returns an error, no url.
    monkeypatch.setattr(gitops, "_open_pr", lambda *a, **k: ("", "denied: not permitted to create"))
    monkeypatch.setattr(gitops, "_merge_to_main", lambda *a, **k: "no PR opened — auto-merge NOT armed")

    res = fix_loop.fix_one(bug)

    assert res["result"] == "fix-pushed-no-pr"
    entry = _status(led)
    assert entry["status"] == "open", "stranded bug must stay OPEN so it's retried"
    assert not entry.get("fix_pr"), "must not set fix_pr when no PR opened (would exclude it forever)"


def test_branch_push_is_forced(one_open_bug, monkeypatch):
    """The fix branch is rebuilt fresh from main each attempt, so its push must
    be forced to overwrite any leftover (prior attempt / stranded no-PR push) —
    else the push is rejected and the PR opens against stale content."""
    led, bug, git_calls = one_open_bug
    monkeypatch.setattr(gitops, "_open_pr", lambda *a, **k: ("https://x/pr/1", ""))
    monkeypatch.setattr(gitops, "_merge_to_main", lambda *a, **k: "enabled")

    fix_loop.fix_one(bug)

    pushes = [c for c in git_calls if c and c[0] == "push"]
    assert pushes, "expected a git push"
    assert any("--force" in c for c in pushes), f"branch push must be forced, got: {pushes}"


def test_pr_opened_marks_fixing(one_open_bug, monkeypatch):
    led, bug, _ = one_open_bug
    url = "https://github.com/acme/repo/pull/9"
    monkeypatch.setattr(gitops, "_open_pr", lambda *a, **k: (url, ""))
    monkeypatch.setattr(gitops, "_merge_to_main", lambda *a, **k: "auto-merge to main enabled")

    res = fix_loop.fix_one(bug)

    assert res["result"] == "fix-opened"
    entry = _status(led)
    assert entry["status"] == "fixing"
    assert entry.get("fix_pr") == url
