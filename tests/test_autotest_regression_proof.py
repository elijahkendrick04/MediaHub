"""FIX hardening (council regression-proof): prove the coder's new test actually
exercises the bug — fail/error on pre-fix source, pass after. Advisory by
default. These unit-test the status mapping by mocking git + pytest (the real
thing does live git ops, exercised by the loop)."""
from __future__ import annotations

import subprocess
import types

import pytest

from autotest import builder


def _make_git(changed_all="tests/test_x.py\nsrc/mediahub/web/web.py",
              added_diff="+def test_x():", parent="P", src_in_parent=True):
    """A fake _git dispatching on subcommand, mirroring prove_regression's calls."""
    def g(*args, **kw):
        a = list(args)
        if a and a[0] == "merge-base":
            return 0, parent + "\n"
        if a and a[0] == "cat-file":
            return (0 if src_in_parent else 1), ""
        if a and a[0] in ("checkout", "reset"):
            return 0, ""
        if a and a[0] == "diff" and "--name-only" in a:
            if a[-1] == "tests/":                       # test files only
                tf = "\n".join(f for f in changed_all.split("\n") if f.startswith("tests/"))
                return 0, tf + "\n"
            return 0, changed_all + "\n"                # all changed files
        if a and a[0] == "diff":                        # per-file content diff
            return 0, added_diff + "\n"
        return 0, ""
    return g


def _patch(monkeypatch, git, pytest_rc):
    monkeypatch.setattr(builder, "_git", git)
    monkeypatch.setattr(builder.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=pytest_rc, stdout="", stderr=""))


def test_proven_when_new_test_fails_on_prefix(monkeypatch):
    _patch(monkeypatch, _make_git(), pytest_rc=1)        # new test FAILS on pre-fix → proven
    status, _ = builder.prove_regression()
    assert status == "proven"


def test_error_on_prefix_counts_as_proven(monkeypatch):
    _patch(monkeypatch, _make_git(), pytest_rc=2)        # collection ERROR (imports new helper)
    status, _ = builder.prove_regression()
    assert status == "proven"


def test_hollow_when_new_test_passes_on_prefix(monkeypatch):
    _patch(monkeypatch, _make_git(), pytest_rc=0)        # passes even pre-fix → hollow
    status, _ = builder.prove_regression()
    assert status == "hollow"


def test_no_test_when_none_added(monkeypatch):
    _patch(monkeypatch, _make_git(added_diff="+    some_non_test_change = 1"), pytest_rc=1)
    status, _ = builder.prove_regression()
    assert status == "no-test"


def test_no_selector_match_is_no_test(monkeypatch):
    _patch(monkeypatch, _make_git(), pytest_rc=5)        # pytest: no tests collected
    status, _ = builder.prove_regression()
    assert status == "no-test"


def test_unproven_when_only_tests_changed(monkeypatch):
    # A test-only diff has nothing to revert → can't prove.
    _patch(monkeypatch, _make_git(changed_all="tests/test_x.py"), pytest_rc=1)
    status, _ = builder.prove_regression()
    assert status == "unproven"


def test_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("git exploded")
    monkeypatch.setattr(builder, "_git", boom)
    status, detail = builder.prove_regression()
    assert status == "unproven" and "could not run" in detail
