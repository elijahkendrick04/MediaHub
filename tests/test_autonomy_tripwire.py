"""Autonomy tripwire (council 2026-06-02) — the DETERMINISTIC gate that stands in for
the human merge once the autotest harness auto-merges its own code.

The loop can auto-merge ordinary harness CODE now. The danger the council named: a PR
that quietly disarms a safety net (and deletes the test that checked it) can still go
green. This test is that missing check — it asserts every safety net is still WIRED, so a
change that removes one fails CI and cannot auto-merge.

It is itself in gitops.SELF_GOVERNANCE (+ CODEOWNERS), so the loop cannot auto-merge a
change that weakens THIS file — only a human can. The in-repo half; the platform half is
GitHub branch protection + CODEOWNERS (the real stop, since an in-repo guard is run by the
same identity that writes the code).
"""
from __future__ import annotations

import inspect
from pathlib import Path

from autotest import fix_loop, gitops, report

REPO_ROOT = gitops.REPO_ROOT

# Human-owned floors (this file is self-governance → only a human can lower them). They
# catch the loop silently deleting tests to go green; set below the current inventory
# (158 `test_*.py` files / 2091 `def test_` functions on 2026-06-02) with headroom for
# normal churn — a removal large enough to trip this is exactly what a human should see.
MIN_TEST_FILES = 150
MIN_TEST_FUNCTIONS = 2000


# --- kill switch -------------------------------------------------------------
def test_kill_switch_is_wired():
    assert gitops.STOP_FILE.name == "STOP" and gitops.STOP_FILE.parent.name == "autotest"
    # the fixer must consult it before doing work
    assert "STOP_FILE" in inspect.getsource(fix_loop.fix_one)


# --- protected deterministic engine -----------------------------------------
def test_protected_engine_guard_intact():
    joined = " ".join(gitops.PROTECTED)
    for must in ("interpreter", "pb_discovery", "recognition", "ranker", "logo_chip"):
        assert must in joined, f"protected engine lost coverage of {must}"
    # the guard is actually applied in the gate loop
    assert "_touches_protected" in inspect.getsource(gitops.implement_until_green)


# --- scope caps --------------------------------------------------------------
def test_scope_caps_are_wired():
    assert isinstance(gitops.MAX_FILES, int) and gitops.MAX_FILES > 0
    assert isinstance(gitops.MAX_INSERTIONS, int) and gitops.MAX_INSERTIONS > 0
    src = inspect.getsource(gitops.implement_until_green)
    assert "MAX_FILES" in src and "MAX_INSERTIONS" in src


# --- the A6 corroboration gate (subjective fixes need a deterministic repro) --
def test_a6_corroboration_gate_present():
    src = inspect.getsource(fix_loop.fix_one)
    assert "AUTOTEST_FIX_REQUIRE_REPRO" in src and "is_subjective" in src
    assert callable(report.is_subjective)


# --- the self-governance boundary (the constitution set) --------------------
def test_self_governance_covers_the_constitution_set():
    sg = set(gitops.SELF_GOVERNANCE)
    for must in ("autotest/gitops.py", "autotest/fix_loop.py", "autotest/STOP",
                 "autotest/CHANGE_CLASSIFICATION.md", ".github/workflows/",
                 ".github/CODEOWNERS", "CLAUDE.md", "render.yaml", "Dockerfile",
                 "pyproject.toml", "requirements.txt",
                 "tests/test_autonomy_tripwire.py"):
        assert must in sg, f"self-governance set no longer protects {must}"


def test_classifier_fails_safe_and_protects_itself():
    # The classifier itself is self-governance (else the loop reclassifies its own diff).
    assert gitops.classify_change(["autotest/gitops.py"]) == "self_governance"
    assert gitops.classify_change([]) == "self_governance"          # empty fails safe
    assert gitops.classify_change(["src/mediahub/web/web.py"]) == "product"


def test_merge_gate_never_arms_self_governance(monkeypatch):
    monkeypatch.setenv("AUTOTEST_BUILD_MERGE", "1")
    called = []
    monkeypatch.setattr(gitops.subprocess, "run", lambda *a, **k: called.append(a) or None)
    msg = gitops._merge_to_main("b", has_pr=True, files=["autotest/CHANGE_CLASSIFICATION.md"])
    assert "human merge" in msg.lower() and not called


# --- platform layer present (CODEOWNERS) ------------------------------------
def test_codeowners_protects_the_constitution_set():
    co = REPO_ROOT / ".github" / "CODEOWNERS"
    assert co.exists(), "CODEOWNERS missing — the platform-enforced human-review boundary"
    text = co.read_text(encoding="utf-8")
    for must in ("gitops.py", "fix_loop.py", "CHANGE_CLASSIFICATION.md", "CLAUDE.md",
                 ".github/", "test_autonomy_tripwire.py"):
        assert must in text, f"CODEOWNERS no longer requires human review for {must}"


# --- no silent test deletion -------------------------------------------------
def test_test_suite_not_silently_shrunk():
    files = list((REPO_ROOT / "tests").glob("test_*.py"))
    assert len(files) >= MIN_TEST_FILES, (
        f"test files dropped below the floor ({len(files)} < {MIN_TEST_FILES}) — "
        "a human must lower MIN_TEST_FILES in this self-governance file")
    n = 0
    for f in files:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lstrip().startswith("def test_"):
                n += 1
    assert n >= MIN_TEST_FUNCTIONS, (
        f"test functions dropped below the floor ({n} < {MIN_TEST_FUNCTIONS})")
