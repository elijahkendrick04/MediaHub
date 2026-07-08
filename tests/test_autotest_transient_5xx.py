"""The fixer must not open PRs for gateway/infra 5xx (502/503/504).

A 502/503/504 against the live Render free-tier deployment is a cold-start /
overload of the hosting layer — the app never received the request, so there is
no product-code fix and the coder could only write a throwaway "document the
502" note (the pattern that produced the four low-value July fix PRs). A genuine
500 (the app itself raised) is a real defect and MUST stay eligible. The finding
is still recorded in the ledger for human visibility — it is de-queued from
auto-fixing, not hidden.
"""
from __future__ import annotations

import json

import pytest

from autotest import fix_loop, report


def _bug(fp, **kw):
    b = {"fingerprint": fp, "status": "open", "severity": "high",
         "category": "http_5xx", "route": f"/{fp}", "title": fp,
         "actual": "", "fix_attempts": 0, "present_last_run": True}
    b.update(kw)
    return b


@pytest.fixture
def ledger_of(tmp_path, monkeypatch):
    def _install(bugs):
        led = tmp_path / "ledger.json"
        led.write_text(json.dumps({"schema": 1, "bugs": {b["fingerprint"]: b for b in bugs}}))
        monkeypatch.setattr(report, "LEDGER_PATH", led)
    return _install


def test_gateway_5xx_predicate_matches_502_503_504():
    for code in (502, 503, 504):
        assert fix_loop._is_transient_5xx(
            _bug("g", category="http_5xx", title=f"HTTP {code} at /health",
                 actual=f"HTTP {code}")), code
    # network_error sub-request gateway failures are excluded too
    assert fix_loop._is_transient_5xx(
        _bug("n", category="network_error", title="script 503 on /", actual="script → 503: /x.js"))


def test_real_500_stays_eligible():
    # A 500 is the app itself raising — a real, fixable defect. Not excluded.
    assert not fix_loop._is_transient_5xx(
        _bug("real", category="http_5xx", title="HTTP 500 at /free-text", actual="HTTP 500"))


def test_predicate_is_scoped_to_status_categories():
    # A finding in another category that merely mentions a gateway number in
    # passing must NOT be swept up.
    assert not fix_loop._is_transient_5xx(
        _bug("copy", category="user_brain", title="the 502 area code looks odd",
             actual="tone nit"))
    assert not fix_loop._is_transient_5xx(
        _bug("a11y", category="a11y", title="contrast 5.02:1 below AA on /x", actual="axe"))


def test_502_is_dequeued_but_500_and_others_remain(ledger_of):
    ledger_of([
        _bug("cold502", category="http_5xx", title="HTTP 502 at /drafts", actual="HTTP 502"),
        _bug("real500", category="http_5xx", title="HTTP 500 at /free-text", actual="HTTP 500"),
        _bug("a11y1", category="a11y", severity="medium", title="missing label on /x",
             actual="axe: label"),
    ])
    fps = {b["fingerprint"] for b in fix_loop._open_bugs(10)}
    assert "cold502" not in fps, "gateway 502 must not enter the fix queue"
    assert {"real500", "a11y1"} <= fps, "a real 500 and other defects stay eligible"
