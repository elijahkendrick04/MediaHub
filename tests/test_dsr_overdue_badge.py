"""tests/test_dsr_overdue_badge.py — the athlete-rights (DSR) table flags
overdue requests so the statutory one-month deadline can't be silently blown
(audit finding D-9).

Each request's "Due" date was plain text with only open/clock-stopped/completed
tags — nothing turned red or said "overdue" when the deadline passed, the exact
failure GDPR penalises.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def env(app, monkeypatch):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="t", display_name="Test club", brand_voice_summary="Hi"))
    return app, monkeypatch


def _pin(client):
    with client.session_transaction() as s:
        s["active_profile_id"] = "t"


def test_overdue_request_is_flagged(env):
    app, monkeypatch = env
    from mediahub.compliance import dsr as _dsr

    # Open a request "in the past" so its due date is already blown.
    past = datetime.now(timezone.utc) - timedelta(days=90)
    monkeypatch.setattr(_dsr, "_now", lambda: past)
    _dsr.DsrRequestLog().open(profile_id="t", athlete_name="Late Kid", request_type="access")
    # And a fresh one that is comfortably within the window.
    monkeypatch.setattr(_dsr, "_now", lambda: datetime.now(timezone.utc))
    _dsr.DsrRequestLog().open(profile_id="t", athlete_name="On Time Kid", request_type="access")

    c = app.test_client()
    _pin(c)
    body = c.get("/organisation/athlete-rights").get_data(as_text=True)
    assert "OVERDUE" in body, "an overdue DSR request must be flagged (D-9)"
    assert "d late" in body
    # The in-window request shows a countdown, not an overdue flag.
    assert "due in" in body


def test_no_overdue_when_all_within_window(env):
    app, monkeypatch = env
    from mediahub.compliance import dsr as _dsr

    _dsr.DsrRequestLog().open(profile_id="t", athlete_name="Fresh", request_type="access")
    c = app.test_client()
    _pin(c)
    body = c.get("/organisation/athlete-rights").get_data(as_text=True)
    assert "OVERDUE" not in body
    assert "due in" in body
