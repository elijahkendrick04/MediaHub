"""Live full-lifecycle safety: the sweep must never upload a test meet into a
REAL customer org. Live mode signs into a real org first (ensure_signed_in_live
prefers non-autotest orgs); if the sign-up step fails or is skipped, the active
profile is that real org — run_full_lifecycle must abort BEFORE the upload,
mirroring the 'autotest*'-only guard the delete step already has."""
from __future__ import annotations

from autotest.run import Collector, Tester


def _tester(monkeypatch, pid: str):
    t = Tester(None, "http://x", None, Collector("http://x"), 10)
    calls = {"primary_flow": 0, "delete": []}
    monkeypatch.setattr(t, "run_signup_flow", lambda: "signup-failed")
    monkeypatch.setattr(t, "_active_profile_id_live", lambda: pid)
    monkeypatch.setattr(
        t, "run_primary_flow",
        lambda timeout: calls.__setitem__("primary_flow", calls["primary_flow"] + 1) or "ok",
    )
    monkeypatch.setattr(
        t, "_delete_test_profile",
        lambda p: calls["delete"].append(p) or "deleted",
    )
    return t, calls


def test_lifecycle_aborts_before_upload_when_active_profile_is_a_real_org(monkeypatch):
    t, calls = _tester(monkeypatch, "swansea-aquatics")
    result = t.run_full_lifecycle(flow_timeout=1.0)
    assert calls["primary_flow"] == 0, "uploaded a test meet into a real customer org"
    assert calls["delete"] == []       # nothing created, nothing to delete
    assert "aborted: active profile is not a test org" in result


def test_lifecycle_runs_upload_and_delete_for_a_test_org(monkeypatch):
    t, calls = _tester(monkeypatch, "autotest-lifecycle-123")
    result = t.run_full_lifecycle(flow_timeout=1.0)
    assert calls["primary_flow"] == 1
    assert calls["delete"] == ["autotest-lifecycle-123"]
    assert "aborted" not in result
