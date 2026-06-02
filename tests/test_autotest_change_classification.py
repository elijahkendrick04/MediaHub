"""Governance gate (council 2026-06-02 + autotest/CHANGE_CLASSIFICATION.md): the loop
applies a HUMAN-AUTHORED 3-way classification to decide whether a fix may auto-merge or
must stop for a human merge. The loop never classifies its own changes — it applies this
fixed rule. These tests pin the rule's behaviour.

The 3 classes:
  * product         — src/mediahub product code / tests   → auto-merge
  * harness         — ordinary autotest machinery          → auto-merge (the armed autonomy)
  * self_governance — files that GOVERN the loop           → HUMAN merge (the boundary)
"""
from __future__ import annotations

from autotest import gitops


# --- classify_change: product (auto-merge) ---------------------------------
def test_pure_product_change_is_product():
    assert gitops.classify_change(["src/mediahub/web/web.py"]) == "product"
    assert gitops.classify_change(["src/mediahub/web/web.py", "tests/test_web.py"]) == "product"


# --- classify_change: ordinary harness CODE now AUTO-MERGES (the new autonomy) ---
def test_ordinary_harness_code_is_harness():
    # finders, judges, the report lifecycle, metrics, coverage finders → auto-merge.
    for f in ("autotest/report.py", "autotest/semantic.py", "autotest/run.py",
              "autotest/metrics.py", "autotest/a11y.py", "autotest/vision.py",
              "autotest/reports/ledger.json"):
        assert gitops.classify_change([f]) == "harness", f


# --- classify_change: self_governance (HUMAN merge — the boundary) ---------
def test_loop_decision_and_guard_code_is_self_governance():
    # The merge gate + this classifier (gitops.py) and the fixer's decision logic
    # (fix_loop.py) govern the loop → the loop may NOT auto-merge a change to them.
    assert gitops.classify_change(["autotest/gitops.py"]) == "self_governance"
    assert gitops.classify_change(["autotest/fix_loop.py"]) == "self_governance"
    assert gitops.classify_change(["autotest/STOP"]) == "self_governance"


def test_governance_docs_are_self_governance():
    for f in ("CLAUDE.md", "src/mediahub/CLAUDE.md", "autotest/CHANGE_CLASSIFICATION.md",
              "autotest/AUTONOMY_BOUNDARY.md", "autotest/PROOF_CRITERION.md"):
        assert gitops.classify_change([f]) == "self_governance", f


def test_workflow_deploy_deps_and_codeowners_are_self_governance():
    for f in (".github/workflows/ci.yml", ".github/CODEOWNERS", "render.yaml",
              "Dockerfile", "pyproject.toml", "requirements.txt", "requirements-dev.txt"):
        assert gitops.classify_change([f]) == "self_governance", f


def test_tripwire_and_classifier_tests_are_self_governance():
    # The loop must not be able to auto-merge a weakening of its own safety tests.
    assert gitops.classify_change(["tests/test_autonomy_tripwire.py"]) == "self_governance"
    assert gitops.classify_change(
        ["tests/test_autotest_change_classification.py"]) == "self_governance"


# --- precedence + fail-safe -------------------------------------------------
def test_self_governance_wins_over_product_and_harness():
    # Stricter wins: any self-governance file makes the whole diff self_governance.
    assert gitops.classify_change(
        ["src/mediahub/web/web.py", "autotest/gitops.py"]) == "self_governance"
    assert gitops.classify_change(
        ["autotest/report.py", "autotest/fix_loop.py"]) == "self_governance"


def test_product_plus_ordinary_harness_is_harness_both_automerge():
    # product + ordinary harness code (neither self-governance) → auto-merge.
    assert gitops.classify_change(["src/mediahub/web/web.py", "autotest/report.py"]) == "harness"


def test_empty_set_fails_safe_to_self_governance():
    # An unknown/empty change must never auto-merge — it fails safe to a human merge.
    assert gitops.classify_change([]) == "self_governance"


# --- _merge_to_main governance gate ----------------------------------------
def _completed(rc, stdout="", stderr=""):
    import types
    return types.SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


def test_merge_gate_blocks_self_governance_automerge(monkeypatch):
    # The classification gate returns BEFORE any gh call for a self-governance change.
    monkeypatch.setenv("AUTOTEST_BUILD_MERGE", "1")
    called = []
    monkeypatch.setattr(gitops.subprocess, "run",
                        lambda *a, **k: called.append(a) or _completed(0))
    msg = gitops._merge_to_main("b", has_pr=True, files=["autotest/gitops.py"])
    assert "human merge" in msg.lower()
    assert not called, "gh pr merge must NOT be called for a self-governance change"


def test_merge_gate_arms_product_automerge(monkeypatch):
    import shutil
    monkeypatch.setenv("AUTOTEST_BUILD_MERGE", "1")
    monkeypatch.setattr(shutil, "which", lambda _x: "/usr/bin/gh")
    called = []
    monkeypatch.setattr(gitops.subprocess, "run",
                        lambda *a, **k: called.append(a[0]) or _completed(0))
    msg = gitops._merge_to_main("b", has_pr=True, files=["src/mediahub/web/web.py"])
    assert "enabled" in msg.lower()
    assert called and "merge" in called[0], "gh pr merge must be called for a product change"


def test_merge_gate_arms_ordinary_harness_automerge(monkeypatch):
    # The NEW autonomy: ordinary harness code auto-merges too (council 2026-06-02).
    import shutil
    monkeypatch.setenv("AUTOTEST_BUILD_MERGE", "1")
    monkeypatch.setattr(shutil, "which", lambda _x: "/usr/bin/gh")
    called = []
    monkeypatch.setattr(gitops.subprocess, "run",
                        lambda *a, **k: called.append(a[0]) or _completed(0))
    msg = gitops._merge_to_main("b", has_pr=True, files=["autotest/report.py"])
    assert "enabled" in msg.lower()
    assert called and "merge" in called[0], "gh pr merge must be called for ordinary harness code"
