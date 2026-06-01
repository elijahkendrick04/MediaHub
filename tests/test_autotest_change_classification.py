"""Governance gate (council Q4 + autotest/CHANGE_CLASSIFICATION.md): the loop applies
a HUMAN-AUTHORED product-vs-harness rule to decide whether a fix may auto-merge or must
stop for a human merge. The loop never classifies its own changes — it applies this
fixed rule. These tests pin the rule's behaviour."""
from __future__ import annotations

from autotest import gitops


# --- classify_change -------------------------------------------------------
def test_pure_product_change_is_product():
    assert gitops.classify_change(["src/mediahub/web/web.py"]) == "product"
    assert gitops.classify_change(["src/mediahub/web/web.py", "tests/test_web.py"]) == "product"


def test_harness_change_is_harness():
    assert gitops.classify_change(["autotest/fix_loop.py"]) == "harness"
    assert gitops.classify_change(["autotest/reports/ledger.json"]) == "harness"


def test_workflow_and_deploy_are_harness():
    assert gitops.classify_change([".github/workflows/ci.yml"]) == "harness"
    assert gitops.classify_change(["render.yaml"]) == "harness"
    assert gitops.classify_change(["Dockerfile"]) == "harness"
    assert gitops.classify_change(["pyproject.toml"]) == "harness"
    assert gitops.classify_change(["requirements.txt"]) == "harness"


def test_governance_docs_are_harness():
    assert gitops.classify_change(["CLAUDE.md"]) == "harness"
    assert gitops.classify_change(["autotest/CHANGE_CLASSIFICATION.md"]) == "harness"
    assert gitops.classify_change(["autotest/PROOF_CRITERION.md"]) == "harness"


def test_mixed_diff_is_harness_stricter_wins():
    assert gitops.classify_change(["src/mediahub/web/web.py", "autotest/x.py"]) == "harness"


def test_empty_set_fails_safe_to_harness():
    # An unknown/empty change must never auto-merge.
    assert gitops.classify_change([]) == "harness"


# --- _merge_to_main governance gate ----------------------------------------
def _completed(rc, stdout="", stderr=""):
    import types
    return types.SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


def test_merge_gate_blocks_harness_automerge(monkeypatch):
    # The classification gate returns BEFORE any gh call for a harness change.
    monkeypatch.setenv("AUTOTEST_BUILD_MERGE", "1")
    called = []
    monkeypatch.setattr(gitops.subprocess, "run",
                        lambda *a, **k: called.append(a) or _completed(0))
    msg = gitops._merge_to_main("b", has_pr=True, files=["autotest/fix_loop.py"])
    assert "human merge" in msg.lower()
    assert not called, "gh pr merge must NOT be called for a harness change"


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
