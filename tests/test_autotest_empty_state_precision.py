"""Finder precision: legitimate empty states must not read as zero-card bugs.

The functional judge used to flag EVERY zero-card run ("a real meet file that
yielded ZERO cards") as a silent failure. But "0 cards" is the CORRECT result of
a club-name mismatch — the file parsed fine, none of its swims matched the
selected club, so recognition had nothing to rank (the honest "No swims matched
your club" review state, fixed product-side in #196). The judge could not tell
that legitimate empty state from a real pipeline failure because its only
content signal, ``content_summary``, omitted the swim-match counts — so it
false-positived on every mismatch run, and a re-sweep RE-CREATED the findings
rather than clearing them.

Fix (council "AI judgement surface, non-suppressive"): enrich the judge's INPUT
with the swim-match counts (already on the export) and state two verbatim rules
in the rubric so it distinguishes legit-empty from broken-empty WITHOUT a
hardcoded suppression rule. These tests assert on ground truth — the summary
string and the rubric text the judge receives — never on a model verdict (the
repo convention; the LLM verdict is non-deterministic). The live-judge flip
(LEGIT-empty HIGH→clean, REAL-bug stays HIGH) is recorded in the PR as the
council's one-time gate.
"""
from __future__ import annotations

from autotest import semantic


def _functional_rubric() -> str:
    fn = next(c for c in semantic.CHARTERS if c.name == "functional")
    return fn.rubric


# --- The enrichment: the counts the judge needs are now in content_summary ---
def test_content_summary_exposes_swim_match_counts():
    s = semantic._content_summary({
        "meet": {"name": "West Wales Regional LC 2025"}, "cards": [],
        "parsed_swim_count": 1217, "our_swim_count": 0,
        "club_filter": "Swansea Uni", "parse_warnings": [],
    })
    # Without these, cards=0 is indistinguishable from a bug.
    assert "parsed_swim_count=1217" in s
    assert "our_swim_count=0" in s
    assert "club_filter=Swansea Uni" in s
    assert "parse_warnings=none" in s


def test_absent_counts_render_as_unknown_never_zero():
    # Council rule 1's enabling data: an absent count must read "unknown" (escalate),
    # NOT be coerced to 0 (which would masquerade as a clean matched=0 exoneration).
    s = semantic._content_summary({"meet": {"name": "?"}, "cards": []})
    assert "parsed_swim_count=unknown" in s
    assert "our_swim_count=unknown" in s
    # a real zero is still shown as 0, distinct from unknown:
    s0 = semantic._content_summary({"cards": [], "parsed_swim_count": 0, "our_swim_count": 0})
    assert "parsed_swim_count=0" in s0 and "our_swim_count=0" in s0


def test_parse_warning_codes_surface_for_the_broken_filter_guard():
    # The council blind-spot: matched=0 can mean club mismatch OR a broken filter.
    # The warning codes must reach the judge so it escalates the broken-filter case.
    s = semantic._content_summary({
        "cards": [], "parsed_swim_count": 1217, "our_swim_count": 0,
        "parse_warnings": [{"code": "filter_error", "message": "club filter failed"}],
    })
    assert "parse_warnings=filter_error" in s


# --- The two verbatim rules the council mandated, in the rubric the judge reads -
def test_rubric_states_the_unknown_escalation_rule():
    r = _functional_rubric()
    # Rule 1: null/absent counts OR a parse error => escalate, do not exonerate.
    assert "unknown" in r.lower() and "escalate" in r.lower()
    assert "do not exonerate" in r.lower()


def test_rubric_states_the_matched_but_zero_cards_invariant_verbatim():
    r = _functional_rubric()
    # Rule 2 (the invariant that must never erode): swims matched but no cards = HIGH.
    assert "our_swim_count > 0 AND cards = 0" in r
    assert "HIGH" in r
    assert "No exceptions" in r


def test_rubric_keeps_the_legit_empty_exoneration_path():
    r = _functional_rubric().lower()
    # parsed>0 AND matched=0 AND no error => legitimate explained empty state, not a bug.
    assert "parsed_swim_count > 0" in r
    assert "our_swim_count = 0" in r
    assert "not a bug" in r or "this is not a bug" in r


def test_rubric_preserves_the_no_ai_key_caption_carveout():
    # Regression guard: the pre-existing "don't flag missing AI captions" carve-out
    # must survive the rubric rewrite.
    assert "missing AI captions" in _functional_rubric()


# --- End-to-end (stubbed LLM): the enriched counts actually reach the prompt ---
def test_enriched_counts_reach_the_functional_prompt_body(monkeypatch):
    captured = {}

    def fake_ask(system, user, max_tokens=0):
        captured["system"], captured["user"] = system, user
        return '{"issues":[]}'

    import autotest.cli_llm as cli
    monkeypatch.setattr(cli, "ask", fake_ask)
    arts = semantic._build_artifacts({
        "flow_result": "passed-empty",
        "export_json": {"meet": {"name": "West Wales LC"}, "cards": [],
                        "parsed_swim_count": 1217, "our_swim_count": 0},
        "pages": [],
    })
    fn = next(c for c in semantic.CHARTERS if c.name == "functional")
    semantic._run_charter(fn, arts)
    # The judge's prompt now carries the swim-match counts AND the two rules.
    assert "parsed_swim_count=1217" in captured["user"]
    assert "our_swim_count=0" in captured["user"]
    assert "our_swim_count > 0 AND cards = 0" in captured["system"]


# --- The verified-fixed retirement lifecycle (council Q3) --------------------
import json

import pytest

from autotest import report


@pytest.fixture
def temp_ledger(tmp_path, monkeypatch):
    led = tmp_path / "ledger.json"
    monkeypatch.setattr(report, "LEDGER_PATH", led)
    base = {"schema": report.SCHEMA_VERSION, "bugs": {
        "deadbeef0001": {"fingerprint": "deadbeef0001", "category": "semantic:functional",
                         "severity": "high", "title": "13 /review 200 but 0 cards",
                         "route": "/review/:id", "status": "open", "seen_count": 1},
    }, "skipped": {}}
    led.write_text(json.dumps(base), encoding="utf-8")
    return led


def test_retire_sets_terminal_status_and_evidence(temp_ledger):
    ok = report.retire_verified_fixed("deadbeef0001", commit="5c86706 (#196) + this PR",
        tests="test_autotest_empty_state_precision.py (8 passed)",
        note="false-positive: legitimate club-mismatch empty state", verified_by="council + human merge")
    assert ok is True
    entry = report.load_ledger()["bugs"]["deadbeef0001"]
    assert entry["status"] == "verified-fixed"
    vf = entry["verified_fixed"]
    # Council's required fields are all recorded as a permanent audit trail.
    assert vf["commit"] and vf["tests"] and vf["note"] and vf["verified_by"] and vf["at"]


def test_retire_unknown_fingerprint_is_a_noop(temp_ledger):
    assert report.retire_verified_fixed("nope", commit="x", tests="x", note="x", verified_by="x") is False


def test_verified_fixed_is_fix_owned_so_the_finder_cannot_reopen_it():
    # The terminal state must be fix-owned, else a re-detection downgrades it to open.
    assert "verified-fixed" in report.FIX_OWNED_STATUSES


def test_redetection_does_not_reopen_a_retired_finding(tmp_path, monkeypatch):
    # Exercise the REAL merge path: a finding retired as verified-fixed, then
    # re-emitted by the finder (same fingerprint, e.g. before the finder fix ships),
    # must keep its terminal status — merge_findings bumps seen_count but never
    # downgrades a fix-owned status back to open.
    led = tmp_path / "ledger.json"
    monkeypatch.setattr(report, "LEDGER_PATH", led)
    led.write_text(json.dumps({"schema": report.SCHEMA_VERSION, "bugs": {}, "skipped": {}}),
                   encoding="utf-8")
    f = report.Finding(category="semantic:functional", severity="high",
                       title="13 /review 200 but 0 cards", route="/review/:id",
                       expected="cards", actual="0 cards")
    report.merge_findings([f], "run-1")                       # first detection -> open
    fp = f.fingerprint()
    assert report.load_ledger()["bugs"][fp]["status"] == "open"
    report.retire_verified_fixed(fp, commit="c", tests="t", note="n", verified_by="v")
    report.merge_findings([f], "run-2")                       # re-detection
    entry = report.load_ledger()["bugs"][fp]
    assert entry["status"] == "verified-fixed", "re-detection must not reopen a retired finding"
    assert entry["seen_count"] == 2 and entry["present_last_run"] is True
