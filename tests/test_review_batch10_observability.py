"""Regression tests for deep-review batch 10 (observability robustness).

#94 detectors.detect folds the lines AFTER a match into the evidence, so an
    unhandled_traceback finding carries its frames, not just the header.
#96 render_api._parse_epoch treats a naive timestamp as UTC (not host-local).
#98 github_issues.issue_state distinguishes a 404 ('gone' → refile) from a
    transient error (None → retry).
#100 llm_usage headroom is computed over a fixed trailing 24h, independent of
    the summary window.
"""

from __future__ import annotations

from datetime import datetime, timezone


# ── #94 traceback evidence carries frames ───────────────────────────────────


def test_traceback_evidence_includes_frames():
    from mediahub.log_sentinel.detectors import detect
    from mediahub.log_sentinel.render_api import LogLine

    lines = [
        LogLine(epoch=1.0, timestamp="t0", message="Traceback (most recent call last):"),
        LogLine(epoch=2.0, timestamp="t1", message='  File "app.py", line 10, in handler'),
        LogLine(epoch=3.0, timestamp="t2", message="    do_thing()"),
        LogLine(epoch=4.0, timestamp="t3", message="ValueError: boom"),
    ]
    tb = [f for f in detect(lines) if f.issue_id == "unhandled_traceback"]
    assert tb, "traceback should be detected"
    joined = " ".join(tb[0].evidence)
    # The frames + exception line come along, not just the repeated header.
    assert "app.py" in joined
    assert "ValueError: boom" in joined


# ── #96 naive timestamp is UTC ──────────────────────────────────────────────


def test_parse_epoch_treats_naive_as_utc():
    from mediahub.log_sentinel.render_api import _parse_epoch

    expected = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
    assert _parse_epoch("2025-01-01T00:00:00+00:00") == expected
    assert _parse_epoch("2025-01-01T00:00:00Z") == expected
    assert _parse_epoch("2025-01-01T00:00:00") == expected  # naive → UTC, not local
    assert _parse_epoch("not-a-timestamp") == 0.0


# ── #98 404 vs transient in issue_state ─────────────────────────────────────


class _Resp:
    def __init__(self, code):
        self.status_code = code

    def json(self):
        return {"state": "open"}


def test_issue_state_distinguishes_404_from_transient(monkeypatch):
    from mediahub.log_sentinel import github_issues as gh

    monkeypatch.setattr(gh, "_request", lambda m, p, **k: _Resp(404))
    assert gh.issue_state(1) == "gone"  # deleted → caller refiles
    monkeypatch.setattr(gh, "_request", lambda m, p, **k: _Resp(500))
    assert gh.issue_state(1) is None  # transient → retry next window
    monkeypatch.setattr(gh, "_request", lambda m, p, **k: _Resp(200))
    assert gh.issue_state(1) == "open"


# ── #100 headroom over a fixed trailing 24h ─────────────────────────────────


def test_gemini_headroom_uses_fixed_24h_not_summary_window(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import importlib

    from mediahub.observability import llm_usage

    llm_usage = importlib.reload(llm_usage)
    llm_usage.record_call(provider="gemini", model="g", ok=True)

    # A 30-day summary window must NOT subtract 30 days of calls from the daily
    # ceiling — headroom stays measured against the last 24h only.
    summary = llm_usage.usage_for_window(window_hours=720)
    assert summary["gemini_free_tier_headroom"] == llm_usage.GEMINI_FREE_TIER_DAILY_REQ - 1
