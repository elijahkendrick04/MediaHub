"""Finding lifecycle (Tier A: trust) — pending/confirm (A1), decay/auto-close
(A2), regression-reopen (A3), and the schema-v2 migration.

The report's core finding: subjective AI findings opened on a single sighting and
NEVER aged out, so the ledger filled with non-reproducing "bugs". These tests pin
the new lifecycle that fixes it. They assert on ground truth (the ledger record
after a real merge_findings call), never on a model verdict.
"""
from __future__ import annotations

import json

import pytest

from autotest import report
from autotest.report import Finding


@pytest.fixture
def temp_ledger(tmp_path, monkeypatch):
    led = tmp_path / "ledger.json"
    led.write_text(json.dumps({"schema": report.SCHEMA_VERSION, "bugs": {}, "skipped": {}}))
    monkeypatch.setattr(report, "LEDGER_PATH", led)
    # Deterministic, fast gates by default; individual tests override.
    monkeypatch.setenv("AUTOTEST_CONFIRM_SWEEPS", "2")
    monkeypatch.setenv("AUTOTEST_DECAY_SWEEPS_SUBJECTIVE", "3")
    monkeypatch.setenv("AUTOTEST_DECAY_SWEEPS_DETERMINISTIC", "6")
    # No precision file → council_precision() returns None → base gate unscaled.
    monkeypatch.setattr(report, "council_precision", lambda: None)
    return led


def _subjective(title="jargon label", route="/dash"):
    return Finding(category="semantic:user_brain", severity="high", title=title,
                   route=route, expected="clear", actual="confusing")


def _deterministic(title="HTTP 500 at /x", route="/x"):
    return Finding(category="http_5xx", severity="high", title=title, route=route,
                   expected="2xx", actual="500", evidence="boom")


def _status(led, fp):
    return json.loads(led.read_text())["bugs"][fp]["status"]


# --- A1: confirm-on-repeat ---------------------------------------------------
def test_subjective_finding_starts_pending(temp_ledger):
    f = _subjective()
    report.merge_findings([f], "run-1")
    assert _status(temp_ledger, f.fingerprint()) == "pending"


def test_deterministic_finding_starts_open(temp_ledger):
    f = _deterministic()
    report.merge_findings([f], "run-1")
    assert _status(temp_ledger, f.fingerprint()) == "open"


def test_pending_promotes_to_open_after_confirm_sweeps(temp_ledger):
    f = _subjective()
    fp = f.fingerprint()
    report.merge_findings([f], "run-1")          # pending, confirmations=0
    assert _status(temp_ledger, fp) == "pending"
    report.merge_findings([f], "run-2")          # confirmations=1, still pending
    assert _status(temp_ledger, fp) == "pending"
    report.merge_findings([f], "run-3")          # confirmations=2 >= 2 → open
    assert _status(temp_ledger, fp) == "open"


def test_two_runs_do_not_grow_open_count_from_oneshot_subjective(temp_ledger):
    """Acceptance criterion: re-running twice against a stable target does not grow
    the open-bug count from one-shot subjective findings (they sit in pending)."""
    findings = [_subjective(title=f"nit {i}", route=f"/p{i}") for i in range(5)]
    s1 = report.merge_findings(findings, "run-1")
    s2 = report.merge_findings(findings, "run-2")
    assert s1["open"] == 0 and s2["open"] == 0
    assert s1["pending"] == 5 and s2["pending"] == 5


def test_confirm_gate_disabled_opens_immediately(temp_ledger, monkeypatch):
    monkeypatch.setenv("AUTOTEST_CONFIRM_SWEEPS", "0")
    f = _subjective()
    report.merge_findings([f], "run-1")
    assert _status(temp_ledger, f.fingerprint()) == "open"


def test_first_pending_metadata_recorded(temp_ledger):
    f = _subjective()
    report.merge_findings([f], "run-7")
    entry = json.loads(temp_ledger.read_text())["bugs"][f.fingerprint()]
    assert entry["first_pending_run_id"] == "run-7" and entry["first_pending_at"]
    assert entry["confirmations"] == 0


# --- A2: decay / auto-close --------------------------------------------------
def test_subjective_decays_after_absent_streak(temp_ledger):
    f = _subjective()
    fp = f.fingerprint()
    report.merge_findings([f], "run-1")               # pending
    for r in ("run-2", "run-3", "run-4"):             # 3 absent sweeps
        report.merge_findings([], r)
    entry = json.loads(temp_ledger.read_text())["bugs"][fp]
    assert entry["status"] == "auto-closed"
    assert entry["auto_closed_at"] and "decayed" in entry["archived_reason"]


def test_decayed_record_is_kept_not_deleted(temp_ledger):
    f = _subjective()
    report.merge_findings([f], "run-1")
    for r in ("run-2", "run-3", "run-4"):
        report.merge_findings([], r)
    assert f.fingerprint() in json.loads(temp_ledger.read_text())["bugs"]


def test_deterministic_decays_slower_than_subjective(temp_ledger):
    f = _deterministic()
    fp = f.fingerprint()
    report.merge_findings([f], "run-1")               # open immediately
    for r in ("a", "b", "c"):                          # 3 absent: subjective would close
        report.merge_findings([], r)
    assert _status(temp_ledger, fp) == "open"          # deterministic threshold is 6
    for r in ("d", "e", "f"):                          # 6 absent total
        report.merge_findings([], r)
    assert _status(temp_ledger, fp) == "auto-closed"


def test_recurrence_resets_absent_streak(temp_ledger):
    f = _subjective()
    fp = f.fingerprint()
    report.merge_findings([f], "run-1")
    report.merge_findings([], "run-2")                 # absent_streak=1
    report.merge_findings([], "run-3")                 # absent_streak=2
    report.merge_findings([f], "run-4")                # seen again → streak reset, confirms
    entry = json.loads(temp_ledger.read_text())["bugs"][fp]
    assert entry["absent_streak"] == 0
    report.merge_findings([], "x")
    report.merge_findings([], "y")
    assert _status(temp_ledger, fp) != "auto-closed"   # only 2 absent since reset


def test_terminal_verified_fixed_is_exempt_from_decay(temp_ledger):
    f = _subjective()
    fp = f.fingerprint()
    report.merge_findings([f], "run-1")
    report.retire_verified_fixed(fp, commit="c", tests="t", note="n", verified_by="v")
    for r in ("a", "b", "c", "d", "e", "f", "g"):
        report.merge_findings([], r)
    assert _status(temp_ledger, fp) == "verified-fixed"


# --- A3: regression-aware reopening ------------------------------------------
def test_fixed_finding_that_recurs_is_regressed(temp_ledger):
    f = _deterministic()
    fp = f.fingerprint()
    report.merge_findings([f], "run-1")
    led = json.loads(temp_ledger.read_text())
    led["bugs"][fp]["status"] = "fixed"
    led["bugs"][fp]["fix_pr"] = "https://x/pr/1"
    temp_ledger.write_text(json.dumps(led))
    report.merge_findings([f], "run-2")                # recurs
    entry = json.loads(temp_ledger.read_text())["bugs"][fp]
    assert entry["status"] == "regressed" and entry["regressed_at"]


def test_auto_closed_finding_that_recurs_reopens_as_regressed(temp_ledger):
    f = _subjective()
    fp = f.fingerprint()
    report.merge_findings([f], "run-1")
    for r in ("run-2", "run-3", "run-4"):
        report.merge_findings([], r)
    assert _status(temp_ledger, fp) == "auto-closed"
    report.merge_findings([f], "run-5")                # comes back
    assert _status(temp_ledger, fp) == "regressed"


def test_verified_fixed_does_not_regress_on_recurrence(temp_ledger):
    # The terminal/evidence-backed invariant: the noisy finder must never resurrect
    # a verified-fixed finding (often a confirmed false-positive).
    f = _subjective()
    fp = f.fingerprint()
    report.merge_findings([f], "run-1")
    report.retire_verified_fixed(fp, commit="c", tests="t", note="n", verified_by="v")
    report.merge_findings([f], "run-2")
    assert _status(temp_ledger, fp) == "verified-fixed"


# --- migration ---------------------------------------------------------------
def test_pre_v2_ledger_loads_and_backfills(tmp_path, monkeypatch):
    led = tmp_path / "ledger.json"
    led.write_text(json.dumps({"schema": 1, "bugs": {
        "old01": {"fingerprint": "old01", "category": "semantic:functional",
                  "severity": "high", "title": "old", "route": "/r", "status": "open",
                  "seen_count": 9},   # NO v2 fields
    }, "skipped": {}}))
    monkeypatch.setattr(report, "LEDGER_PATH", led)
    ledger = report.load_ledger()
    assert ledger["schema"] == report.SCHEMA_VERSION
    e = ledger["bugs"]["old01"]
    for k in ("confirmations", "first_pending_run_id", "absent_streak", "auto_closed_at"):
        assert k in e
    assert e["status"] == "open"   # migration never changes status


def test_migration_does_not_regate_existing_open_subjective(tmp_path, monkeypatch):
    # An existing OPEN subjective finding (seen many times pre-A1) must stay open,
    # not be retroactively demoted to pending.
    led = tmp_path / "ledger.json"
    led.write_text(json.dumps({"schema": 1, "bugs": {
        "x": {"fingerprint": "x", "category": "semantic:user_brain", "status": "open",
              "severity": "high", "title": "t", "route": "/r", "seen_count": 12},
    }, "skipped": {}}))
    monkeypatch.setattr(report, "LEDGER_PATH", led)
    assert report.load_ledger()["bugs"]["x"]["status"] == "open"


# --- A5: confidence scaling (precision → confirm gate) -----------------------
def test_effective_confirm_sweeps_scales_with_precision():
    assert report.effective_confirm_sweeps(2, None) == 2     # unknown → unchanged
    assert report.effective_confirm_sweeps(2, 0.95) == 2     # high precision → trust
    assert report.effective_confirm_sweeps(2, 0.7) == 3      # mediocre → +1
    assert report.effective_confirm_sweeps(2, 0.4) == 4      # poor → +2
    assert report.effective_confirm_sweeps(0, 0.4) == 0      # disabled stays disabled
