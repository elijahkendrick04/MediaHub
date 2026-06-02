"""Stop the coder-no-op bleed: clean no-edit runs quarantine, not retry forever.

Council 2026-06-01 (autotest/reports/council/): 5 real CI runs showed 3/5 fix
attempts mislabeled "coder-failed" when the Claude coder ran, COMPLETED cleanly,
and correctly made NO edits on non-bugs (a documented false-positive, a
council:blind_spot theory, a live-prod branding artifact). The harness discarded
the coder's reasoning (kept JSON metadata) and never-skip retried the SAME
non-bug forever, burning ~900s each time.

Fix (verdict): parse the stream-json result frame to surface the coder's
conclusion + clean/error status; a CLEAN no-edit completion → quarantine to
``needs_disproof`` (out of the fix loop, NOT closed — the accused coder does not
self-acquit; a deterministic ground-truth repro must reopen or confirm it). An
error/timeout no-edit still retries (never-skip), as before.

These tests assert on ground truth (the parsed frame, the tag string, the ledger
status), never on a live coder.
"""
from __future__ import annotations

import json

import pytest

from autotest import gitops, coder, report


# --- coder.py: parse the stream-json result frame ---------------------------
def _stream(events: list[dict]) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


def test_parse_stream_json_result_extracts_the_final_result_frame():
    raw = _stream([
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": "looking..."}},
        {"type": "result", "subtype": "success", "is_error": False,
         "num_turns": 7, "result": "This is not a bug: the empty state is correct."},
    ])
    res = coder._parse_stream_json_result(raw)
    assert res is not None
    assert res["result"].startswith("This is not a bug")
    assert res["is_error"] is False and res["subtype"] == "success"


def test_parse_stream_json_result_none_on_non_stream_json():
    assert coder._parse_stream_json_result("not json at all\n{broken") is None
    assert coder._parse_stream_json_result("") is None


def test_run_coder_surfaces_conclusion_and_marker_not_metadata(monkeypatch):
    # The OLD failure mode: out was stdout[-2000:] = CLI metadata
    # (service_tier/terminal_reason). Now it must surface the assistant's
    # conclusion plus a truncation-proof <<CODER_RESULT ...>> marker.
    stream = _stream([
        {"type": "result", "subtype": "success", "is_error": False, "num_turns": 5,
         "result": "Investigated /review; 0 cards is the correct club-mismatch empty state. No change."},
    ])

    class _P:
        returncode = 1  # claude -p often exits non-zero even on a clean completion
        stdout = stream
        stderr = ""

    monkeypatch.setattr(coder.shutil, "which", lambda _x: "/usr/bin/claude")
    monkeypatch.setattr(coder.subprocess, "run", lambda *a, **k: _P())
    ok, out = coder.run_coder("fix it", timeout=5)
    assert "correct club-mismatch empty state" in out         # the conclusion, surfaced
    assert "<<CODER_RESULT is_error=false" in out             # the marker, for the fixer
    assert "service_tier" not in out                          # not the metadata tail
    assert ok is True                                         # clean completion counts as ok


# --- gitops.py: tag a clean no-edit run distinctly from a failure ----------
def test_implement_until_green_tags_clean_noedit(monkeypatch):
    monkeypatch.setattr(coder, "write_code",
                        lambda *a, **k: (True, "No change needed.\n<<CODER_RESULT is_error=false subtype=success turns=4>>"))
    monkeypatch.setattr(gitops, "_changed_files", lambda: ([], 0))
    ok, files, ins, info = gitops.implement_until_green("task", label="bug x")
    assert ok is False and files == []
    assert info.startswith("coder-noedit-complete"), info


def test_implement_until_green_tags_error_noedit_as_failed(monkeypatch):
    # An ERROR/timeout no-edit (is_error=true) must stay "coder-failed" → retried.
    monkeypatch.setattr(coder, "write_code",
                        lambda *a, **k: (False, "timed out\n<<CODER_RESULT is_error=true subtype=error turns=1>>"))
    monkeypatch.setattr(gitops, "_changed_files", lambda: ([], 0))
    ok, files, ins, info = gitops.implement_until_green("task", label="bug x")
    assert ok is False
    assert info.startswith("coder-failed"), info


# --- report.py: the needs_disproof quarantine state -------------------------
@pytest.fixture
def temp_ledger(tmp_path, monkeypatch):
    led = tmp_path / "ledger.json"
    monkeypatch.setattr(report, "LEDGER_PATH", led)
    led.write_text(json.dumps({"schema": report.SCHEMA_VERSION, "bugs": {
        "fp0001": {"fingerprint": "fp0001", "category": "semantic:user_brain",
                   "severity": "high", "title": "AQUATICA highlights on a Swansea page",
                   "route": "/review", "status": "open", "seen_count": 1},
    }, "skipped": {}}), encoding="utf-8")
    return led


def test_quarantine_sets_status_and_records_conclusion(temp_ledger):
    ok = report.quarantine_needs_disproof(
        "fp0001", conclusion="coder-noedit-complete (iter 1): not a bug, prod artifact",
        coder_attempts=1)
    assert ok is True
    entry = report.load_ledger()["bugs"]["fp0001"]
    assert entry["status"] == "needs_disproof"
    nd = entry["needs_disproof"]
    assert nd["coder_attempts"] == 1 and nd["at"] and "not a bug" in nd["coder_conclusion"]


def test_quarantine_unknown_fingerprint_is_noop(temp_ledger):
    assert report.quarantine_needs_disproof("nope", conclusion="x", coder_attempts=1) is False


def test_needs_disproof_is_fix_owned_so_the_live_finder_cannot_reopen_it():
    assert "needs_disproof" in report.FIX_OWNED_STATUSES


def test_needs_disproof_is_excluded_from_the_fix_loop(temp_ledger):
    # The whole point: a quarantined finding is no longer picked up for a coder
    # retry (the fix loop only selects status == "open").
    from autotest import fix_loop
    report.quarantine_needs_disproof("fp0001", conclusion="not a bug", coder_attempts=1)
    open_fps = [b["fingerprint"] for b in fix_loop._open_bugs(limit=10)]
    assert "fp0001" not in open_fps
