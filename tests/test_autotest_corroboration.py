"""A6 (Tier A): the fixer only changes product code for a finding it can
deterministically corroborate.

A SUBJECTIVE finding (semantic/vision/council) must be backed by a failing-first
deterministic repro before the fix lands — an LLM verdict alone is not enough to
touch the codebase (the report's A6; the Shortest lesson that LLM tests lack the
determinism for CI gating). This reuses the existing prove_regression machinery:
"hollow"/"no-test" → block; "proven"/"unproven" → pass. Deterministic findings
keep the existing advisory behaviour.

These assert on ground truth (the fix_one result + ledger status), with the heavy
side effects stubbed — never on a live coder.
"""
from __future__ import annotations

import json

import pytest

from autotest import fix_loop, gitops, report


@pytest.fixture
def bug_with_repro(tmp_path, monkeypatch):
    """fix_one against a single bug, with everything heavy stubbed and
    prove_regression controllable. Returns an installer(category, reg_status)."""
    def _install(category: str, reg_status: str, *, require_repro="1"):
        fp = "deadbeefa6"
        bug = {"fingerprint": fp, "status": "open", "severity": "high",
               "category": category, "route": "/review", "title": "a finding",
               "fix_attempts": 0}
        led = tmp_path / "ledger.json"
        led.write_text(json.dumps({"schema": report.SCHEMA_VERSION,
                                   "bugs": {fp: bug}, "skipped": {}}))
        monkeypatch.setattr(report, "LEDGER_PATH", led)
        fix_loop._JOURNAL.clear()
        monkeypatch.setenv("AUTOTEST_FIX_REQUIRE_REPRO", require_repro)
        monkeypatch.delenv("AUTOTEST_REQUIRE_REGRESSION_PROOF", raising=False)
        monkeypatch.setattr(gitops, "_git", lambda *a, **k: (0, ""))
        monkeypatch.setattr(gitops, "implement_until_green",
                            lambda *a, **k: (True, ["src/x.py"], 3, "green"))
        monkeypatch.setattr(gitops, "prove_regression", lambda *a, **k: (reg_status, "detail"))
        monkeypatch.setattr(gitops, "_open_pr", lambda *a, **k: ("https://x/pr/1", ""))
        monkeypatch.setattr(gitops, "_merge_to_main", lambda *a, **k: "enabled")
        monkeypatch.setattr("autotest.notify.notify", lambda *a, **k: None)
        return led, bug
    return _install


def _status(led):
    return json.loads(led.read_text())["bugs"]["deadbeefa6"]["status"]


# --- the gate blocks an uncorroborated subjective fix -----------------------
@pytest.mark.parametrize("reg_status", ["no-test", "hollow"])
def test_subjective_without_repro_is_blocked(bug_with_repro, reg_status):
    led, bug = bug_with_repro("semantic:user_brain", reg_status)
    res = fix_loop.fix_one(bug)
    assert "A6" in res["result"], res
    assert _status(led) == "open", "uncorroborated subjective finding stays open (not fixed)"
    assert not json.loads(led.read_text())["bugs"]["deadbeefa6"].get("fix_pr")


def test_subjective_with_proven_repro_proceeds(bug_with_repro):
    led, bug = bug_with_repro("semantic:user_brain", "proven")
    res = fix_loop.fix_one(bug)
    assert res["result"] == "fix-opened", res
    assert _status(led) == "fixing"


def test_subjective_unproven_fails_open(bug_with_repro):
    # "unproven" = the proof harness itself couldn't run (rare); don't block on it.
    led, bug = bug_with_repro("vision:review", "unproven")
    res = fix_loop.fix_one(bug)
    assert res["result"] == "fix-opened", res


# --- deterministic findings are NOT gated by A6 -----------------------------
def test_deterministic_without_repro_still_proceeds(bug_with_repro):
    led, bug = bug_with_repro("http_5xx", "no-test")
    res = fix_loop.fix_one(bug)
    assert res["result"] == "fix-opened", res
    assert _status(led) == "fixing"


def test_require_repro_flag_off_disables_the_gate(bug_with_repro):
    led, bug = bug_with_repro("semantic:functional", "no-test", require_repro="0")
    res = fix_loop.fix_one(bug)
    assert res["result"] == "fix-opened", res


# --- the coder prompt carries the corroboration instruction -----------------
def test_fix_prompt_demands_failing_first_test_for_subjective():
    p = fix_loop._fix_prompt({"category": "semantic:user_brain", "title": "t",
                              "route": "/r", "expected": "e", "actual": "a"})
    assert "CORROBORATION GATE" in p and "FAILS on the current code" in p


def test_fix_prompt_omits_corroboration_for_deterministic():
    p = fix_loop._fix_prompt({"category": "http_5xx", "title": "t", "route": "/r",
                              "expected": "e", "actual": "a"})
    assert "CORROBORATION GATE" not in p


# --- regressed findings are eligible for the fixer (A3 + A6) ----------------
def test_open_bugs_includes_regressed(tmp_path, monkeypatch):
    led = tmp_path / "ledger.json"
    led.write_text(json.dumps({"schema": report.SCHEMA_VERSION, "bugs": {
        "r1": {"fingerprint": "r1", "status": "regressed", "severity": "high",
               "category": "http_5xx", "route": "/x", "title": "came back",
               "fix_attempts": 0, "present_last_run": True},
        "p1": {"fingerprint": "p1", "status": "pending", "severity": "high",
               "category": "semantic:user_brain", "route": "/y", "title": "unconfirmed",
               "fix_attempts": 0, "present_last_run": True},
    }, "skipped": {}}))
    monkeypatch.setattr(report, "LEDGER_PATH", led)
    fps = [b["fingerprint"] for b in fix_loop._open_bugs(10)]
    assert "r1" in fps, "a regressed finding must be eligible for the fixer"
    assert "p1" not in fps, "a pending (unconfirmed) finding must be ignored by the fixer"
