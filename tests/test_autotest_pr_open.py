"""Tests for the autotest PR-open / auto-merge honesty (gitops._open_pr,
gitops._merge_to_main).

Regression guard for the silent-failure bug: the fixer pushed a fix
branch, then ran `gh pr merge --auto` without a PR and ignored `gh pr create`'s
exit code — so a blocked creation produced an empty `pr` *and* a false
"auto-merge enabled", stranding the branch with nothing landing. These tests
pin that a failed creation is reported (never silently swallowed), the merge is
only armed when a PR truly exists, and an existing PR is recovered idempotently.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from autotest import gitops


def _completed(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def gh_present(monkeypatch):
    """Pretend the gh CLI is installed (both helpers `import shutil` internally,
    which resolves to the global module patched here)."""
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/gh")


# --------------------------------------------------------------------------- #
# _open_pr
# --------------------------------------------------------------------------- #
def test_open_pr_success_returns_url_no_error(monkeypatch, gh_present):
    url = "https://github.com/acme/repo/pull/42"
    monkeypatch.setattr(gitops.subprocess, "run",
                        lambda *a, **k: _completed(0, stdout=url + "\n"))
    got, err = gitops._open_pr("autotest/fix-abc", "fix: x", "body")
    assert got == url
    assert err == ""


def test_open_pr_denied_surfaces_actionable_error(monkeypatch, gh_present):
    """The GITHUB_TOKEN policy block must produce a loud, actionable message —
    not an empty url that the caller mistakes for success."""
    stderr = ("pull request create failed: GraphQL: GitHub Actions is not "
              "permitted to create or approve pull requests (createPullRequest)")
    monkeypatch.setattr(gitops.subprocess, "run",
                        lambda *a, **k: _completed(1, stdout="", stderr=stderr))
    got, err = gitops._open_pr("autotest/fix-abc", "fix: x", "body")
    assert got == ""
    assert err  # non-empty
    assert "not permitted to create" in err.lower()
    # Names the concrete remedies so the operator can act without digging.
    assert "AUTOTEST_GH_PAT" in err
    assert "create and approve pull requests" in err.lower()


def test_open_pr_empty_branch_not_misread_as_permissions(monkeypatch, gh_present):
    """Every GraphQL createPullRequest failure mentions "createPullRequest" — an
    empty pushed branch ("No commits between ...") must be reported as exactly
    that, NOT as the Actions PR-permission block, which sent the operator to
    repo settings that were already correct (2026-06-12 incident)."""
    stderr = ("pull request create failed: GraphQL: No commits between main and "
              "autotest/fix-6df9d960412d (createPullRequest)")
    monkeypatch.setattr(gitops.subprocess, "run",
                        lambda *a, **k: _completed(1, stdout="", stderr=stderr))
    got, err = gitops._open_pr("autotest/fix-6df9d960412d", "fix: x", "body")
    assert got == ""
    assert "no commits" in err.lower()
    assert "AUTOTEST_GH_PAT" not in err
    assert "not permitted" not in err.lower()


def test_open_pr_already_exists_recovers_url(monkeypatch, gh_present):
    """A re-run on the same branch must read as success by recovering the PR."""
    existing = "https://github.com/acme/repo/pull/7"
    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        if cmd[:3] == ["gh", "pr", "create"]:
            return _completed(1, stderr="a pull request for branch ... already exists")
        if cmd[:3] == ["gh", "pr", "view"]:
            return _completed(0, stdout=existing + "\n")
        return _completed(0)

    monkeypatch.setattr(gitops.subprocess, "run", fake_run)
    got, err = gitops._open_pr("autotest/fix-abc", "fix: x", "body")
    assert got == existing
    assert err == ""
    assert any(c[:3] == ["gh", "pr", "view"] for c in calls)  # actually recovered


def test_open_pr_no_gh_is_reported(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    got, err = gitops._open_pr("b", "t", "x")
    assert got == ""
    assert "gh CLI not found" in err


# --------------------------------------------------------------------------- #
# _merge_to_main
# --------------------------------------------------------------------------- #
def test_merge_not_armed_without_flag(monkeypatch):
    monkeypatch.delenv("AUTOTEST_BUILD_MERGE", raising=False)
    assert "not armed" in gitops._merge_to_main("b", has_pr=True)


def test_merge_refuses_without_a_pr(monkeypatch):
    """The core fix: armed but no PR must NOT claim auto-merge was enabled."""
    monkeypatch.setenv("AUTOTEST_BUILD_MERGE", "1")
    msg = gitops._merge_to_main("b", has_pr=False)
    assert "NOT armed" in msg
    assert "no PR" in msg.lower() or "no pr" in msg.lower()


def test_merge_armed_with_pr_enables(monkeypatch, gh_present):
    monkeypatch.setenv("AUTOTEST_BUILD_MERGE", "1")
    calls = []
    monkeypatch.setattr(gitops.subprocess, "run",
                        lambda cmd, *a, **k: (calls.append(cmd), _completed(0))[1])
    # A PRODUCT change is auto-merge eligible (governance gate: CHANGE_CLASSIFICATION.md).
    assert "auto-merge to main enabled" in gitops._merge_to_main(
        "b", has_pr=True, files=["src/mediahub/web/web.py"])
    # The throwaway branch is tidied once the auto-merge lands.
    assert any("--delete-branch" in c for c in calls), f"merge should delete the branch: {calls}"


def test_merge_armed_with_pr_reports_gh_failure(monkeypatch, gh_present):
    """If `gh pr merge` itself fails, say so — don't claim success."""
    monkeypatch.setenv("AUTOTEST_BUILD_MERGE", "1")
    monkeypatch.setattr(gitops.subprocess, "run",
                        lambda *a, **k: _completed(1, stderr="required checks missing"))
    msg = gitops._merge_to_main("b", has_pr=True, files=["src/mediahub/web/web.py"])
    assert "NOT armed" in msg
    assert "required checks missing" in msg
