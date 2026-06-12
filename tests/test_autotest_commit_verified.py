"""Regression tests for the stranded-EMPTY-fix-branch incident (2026-06-12).

A bare Actions runner has no ambient git identity, so the fixer's `git commit`
failed ("Author identity unknown") — and fix_one ignored the exit code, force-
pushing a branch IDENTICAL to main. `gh pr create` then refused it ("No commits
between main and autotest/fix-..."), which _classify_pr_error misread as the
Actions PR-permission block. Pinned here:

  * the fix commit carries its own bot identity (no reliance on runner config)
    and its exit code is VERIFIED — a failed commit aborts the attempt BEFORE
    the push, leaving the bug open for retry;
  * a failed push likewise aborts honestly — no PR attempt, no
    "fix-pushed-no-pr" claim for a branch that never reached origin.
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
        "fingerprint": "deadbeef02", "status": "open", "severity": "high",
        "category": "semantic:user_brain", "route": "post-upload",
        "title": "Some real product bug", "fix_attempts": 0,
    }
    led.write_text(json.dumps({"schema": 1, "bugs": {"deadbeef02": bug}}))
    monkeypatch.setattr(report, "LEDGER_PATH", led)
    fix_loop._JOURNAL.clear()
    monkeypatch.setattr(gitops, "implement_until_green",
                        lambda *a, **k: (True, ["src/x.py"], 3, "green"))
    monkeypatch.setattr("autotest.notify.notify", lambda *a, **k: None)
    return led, bug


def _entry(led):
    return json.loads(led.read_text())["bugs"]["deadbeef02"]


# --------------------------------------------------------------------------- #
# gitops.commit_fix
# --------------------------------------------------------------------------- #
def test_fix_commit_carries_bot_identity(monkeypatch):
    """The commit must be self-sufficient on an identity-less runner: -c
    user.name/user.email BEFORE the subcommand, exactly the state-branch bot."""
    seen: list[tuple] = []
    monkeypatch.setattr(gitops, "_git", lambda *a, **k: (seen.append(a), (0, ""))[1])
    ok, err = gitops.commit_fix("fix: x")
    assert ok and err == ""
    (args,) = seen
    assert f"user.name={gitops.BOT_NAME}" in args
    assert f"user.email={gitops.BOT_EMAIL}" in args
    assert args.index(f"user.name={gitops.BOT_NAME}") < args.index("commit")
    assert args[args.index("commit"):] == ("commit", "-m", "fix: x")


def test_commit_fix_reports_failure_text(monkeypatch):
    monkeypatch.setattr(
        gitops, "_git",
        lambda *a, **k: (1, "fatal: unable to auto-detect email address (got 'runner@fv-az.(none)')"))
    ok, err = gitops.commit_fix("fix: x")
    assert not ok
    assert "auto-detect email" in err


# --------------------------------------------------------------------------- #
# fix_one honesty: verified commit, verified push
# --------------------------------------------------------------------------- #
def test_commit_failure_aborts_before_push(one_open_bug, monkeypatch):
    led, bug = one_open_bug
    calls: list[tuple] = []

    def fake_git(*a, **k):
        calls.append(a)
        if "commit" in a:
            return 1, "fatal: unable to auto-detect email address (got 'runner@fv-az.(none)')"
        return 0, ""

    monkeypatch.setattr(gitops, "_git", fake_git)
    monkeypatch.setattr(gitops, "_open_pr",
                        lambda *a, **k: pytest.fail("must not attempt a PR for an uncommitted fix"))

    res = fix_loop.fix_one(bug)

    assert res["result"].startswith("failed")
    assert "commit failed" in res["result"]
    assert not any(c and c[0] == "push" for c in calls), "must not push an empty branch"
    # The failed attempt resets so the NEXT bug in the same pass starts clean.
    assert any(c[:2] == ("reset", "--hard") for c in calls)
    entry = _entry(led)
    assert entry["status"] == "open", "bug must stay open so it's retried"
    assert not entry.get("fix_pr")
    assert entry["fix_attempts"] == 1, "the failed attempt still counts (de-prioritise)"


def test_push_failure_is_honest_and_skips_pr(one_open_bug, monkeypatch):
    led, bug = one_open_bug

    def fake_git(*a, **k):
        if a and a[0] == "push":
            return 1, "remote: Internal Server Error"
        return 0, ""

    monkeypatch.setattr(gitops, "_git", fake_git)
    monkeypatch.setattr(
        gitops, "_open_pr",
        lambda *a, **k: pytest.fail("must not open a PR for a branch that never reached origin"))

    res = fix_loop.fix_one(bug)

    assert res["result"].startswith("failed")
    assert "push failed" in res["result"]
    entry = _entry(led)
    assert entry["status"] == "open"
    assert not entry.get("fix_pr")
