"""RANK hardening (council severity-floor): a genuine security/data-loss bug is
attempted ahead of cosmetic ones — but bounded, so an unfixable critical can't
starve the never-skip queue.

Council rule: a bug jumps the queue iff severity=="critical" AND a structural
security/data marker is present AND fix_attempts < CRITICAL_ATTEMPT_CAP. Past the
cap it falls back into normal rotation (still eligible forever).
"""
from __future__ import annotations

import json

import pytest

from autotest import fix_loop, report


def _bug(fp, **kw):
    b = {"fingerprint": fp, "status": "open", "severity": "low",
         "category": "ui", "route": f"/{fp}", "title": fp, "fix_attempts": 0,
         "present_last_run": True}
    b.update(kw)
    return b


@pytest.fixture
def ledger_of(tmp_path, monkeypatch):
    def _install(bugs):
        led = tmp_path / "ledger.json"
        led.write_text(json.dumps({"schema": 1, "bugs": {b["fingerprint"]: b for b in bugs}}))
        monkeypatch.setattr(report, "LEDGER_PATH", led)
    return _install


def test_verified_critical_jumps_the_queue(ledger_of):
    ledger_of([
        _bug("high_old", severity="high", category="semantic:flow", route="/review", fix_attempts=0),
        _bug("crit_sec", severity="critical", category="security:auth", route="/login",
             title="auth bypass lets any org read another tenant data"),
        _bug("low_new", severity="low", category="ui:css", route="/dash"),
    ])
    out = fix_loop._open_bugs(10)
    assert out[0]["fingerprint"] == "crit_sec", "verified-critical must be attempted first"
    assert len(out) == 3, "never-skip: every open bug still returned"


def test_critical_without_security_marker_does_not_jump(ledger_of):
    # severity alone (LLM-judge label) must NOT be enough — needs a real marker.
    ledger_of([
        _bug("crit_cosmetic", severity="critical", category="ui:layout", route="/dash",
             title="critical visual glitch in the header"),
        _bug("high_real", severity="high", category="semantic:flow", route="/review",
             fix_attempts=0),
    ])
    out = fix_loop._open_bugs(10)
    # both are attempts=0, tier-1; ordered by severity → critical(cosmetic) still
    # sorts above high, BUT it did not enter the verified tier (proven below).
    assert not fix_loop._is_verified_critical({"severity": "critical", "category": "ui:layout",
                                               "route": "/dash", "title": "critical visual glitch",
                                               "fix_attempts": 0})


def test_unfixable_critical_falls_back_after_cap(ledger_of):
    # A critical+security bug that has already failed CRITICAL_ATTEMPT_CAP times
    # must stop jumping the queue so it can't starve everything else.
    cap = fix_loop.CRITICAL_ATTEMPT_CAP
    ledger_of([
        _bug("crit_stuck", severity="critical", category="security:leak", route="/api/secret",
             title="secret leak", fix_attempts=cap),
        _bug("fresh_high", severity="high", category="semantic:flow", route="/review",
             fix_attempts=0),
    ])
    out = fix_loop._open_bugs(10)
    assert out[0]["fingerprint"] == "fresh_high", "capped critical must fall back below fresh work"
    assert len(out) == 2, "never-skip: the capped critical is still returned, not dropped"


def test_verified_critical_helper_bounds():
    base = {"severity": "critical", "category": "security:idor", "route": "/x", "title": "idor"}
    assert fix_loop._is_verified_critical({**base, "fix_attempts": 0}) is True
    assert fix_loop._is_verified_critical({**base, "fix_attempts": fix_loop.CRITICAL_ATTEMPT_CAP}) is False
    assert fix_loop._is_verified_critical({**base, "severity": "high", "fix_attempts": 0}) is False
    assert fix_loop._is_verified_critical(
        {"severity": "critical", "category": "ui", "route": "/x", "title": "ugly", "fix_attempts": 0}
    ) is False
