"""tests/test_active_profile_memo.py — per-request active-profile memo.

Deep-review finding #16: the active org was re-read from disk 4-5× per
request (two ``before_request`` hooks + the handler, and ``_active_profile``
loaded it a second time itself), each an uncached JSON parse plus a
``secrets.json`` scrub. The fix memoises the loaded profile on ``flask.g``
for the request — mirroring ``_memberships_snapshot`` — and moves the legacy
secrets scrub to app startup.

The active profile drives tenant gating, so the memo MUST be per-request and
MUST invalidate the instant a profile is mutated mid-request. These tests
lock in both the perf win (one disk read) and — the security-critical part —
that a save or delete within a request is observed by the very next read.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest
from flask import g, session

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A fresh DATA_DIR, one unbound (anonymous-usable) profile, and an app."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    pid = "org-memo"
    cp.save_profile(cp.ClubProfile(profile_id=pid, display_name="Before Edit"))

    app = wm.create_app()
    app.config["TESTING"] = True
    return {"app": app, "pid": pid, "cp": cp, "wm": wm}


def _pin(pid):
    session["active_profile_id"] = pid


# ---------------------------------------------------------------------------
# Perf: one disk read per request, however many times it is resolved.
# ---------------------------------------------------------------------------

def test_active_profile_reads_disk_once_per_request(env, monkeypatch):
    app, pid, wm = env["app"], env["pid"], env["wm"]

    calls = []
    real = wm.load_profile
    monkeypatch.setattr(wm, "load_profile", lambda p: (calls.append(p), real(p))[1])

    with app.test_request_context("/"):
        _pin(pid)
        # Simulate the real per-request resolution volume: the two
        # before_request hooks + a handler, each hitting the active profile.
        assert app.active_profile_id() == pid          # hook 1 (governance)
        assert app.active_profile().display_name == "Before Edit"   # hook 2 (gate)
        assert app.active_profile().display_name == "Before Edit"   # handler

    assert calls == [pid], f"expected a single disk read, got {len(calls)}: {calls}"


def test_cache_is_populated_on_flask_g(env):
    app, pid = env["app"], env["pid"]
    with app.test_request_context("/"):
        _pin(pid)
        app.active_profile()
        assert isinstance(g._mh_profile_cache, dict)
        assert pid in g._mh_profile_cache


# ---------------------------------------------------------------------------
# Security-critical: a mid-request mutation MUST be observed by the next read.
# ---------------------------------------------------------------------------

def test_profile_save_within_request_is_observed(env):
    app, pid, cp = env["app"], env["pid"], env["cp"]
    with app.test_request_context("/"):
        _pin(pid)

        # First resolution caches the profile on flask.g.
        assert app.active_profile().display_name == "Before Edit"
        assert pid in g._mh_profile_cache

        # Persist a change mid-request. save_profile fires the invalidation
        # hook, so the cached copy must be dropped.
        prof = cp.load_profile(pid)
        prof.display_name = "After Edit"
        cp.save_profile(prof)
        assert pid not in g._mh_profile_cache, "save must invalidate the memo"

        # The very next read — the one tenant gating would rely on — sees it.
        assert app.active_profile().display_name == "After Edit"


def test_profile_delete_within_request_is_observed(env):
    """A profile deleted mid-request must not be resolvable afterwards — the
    delete route bypasses save_profile, so it invalidates the memo itself."""
    app, pid, cp = env["app"], env["pid"], env["cp"]
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["active_profile_id"] = pid

        # The active profile resolves before deletion.
        with app.test_request_context("/"):
            _pin(pid)
            assert app.active_profile() is not None

        r = c.post("/sign-in/delete", data={"profile_id": pid})
        assert r.status_code in (301, 302, 303)

        # File is gone and the stale pin was self-healed out of the session.
        assert not (cp._profiles_dir() / f"{pid}.json").exists()
        with c.session_transaction() as s:
            assert s.get("active_profile_id") is None


def test_cache_does_not_leak_across_requests(env):
    """flask.g is per-request, so the memo cannot carry a profile from one
    request into the next — the property that makes a cross-request stale
    read (a cross-tenant leak) impossible by construction."""
    app, pid = env["app"], env["pid"]
    with app.test_request_context("/"):
        _pin(pid)
        app.active_profile()
        assert pid in g._mh_profile_cache
    # A brand-new request starts with a fresh g — no carried-over cache.
    with app.test_request_context("/"):
        assert getattr(g, "_mh_profile_cache", None) is None


def test_disk_change_between_requests_is_seen(env):
    """Because nothing is cached across requests, a profile edited on disk
    between two requests is seen fresh by the second — no stale gating data."""
    app, pid, cp = env["app"], env["pid"], env["cp"]
    with app.test_request_context("/"):
        _pin(pid)
        assert app.active_profile().display_name == "Before Edit"

    prof = cp.load_profile(pid)
    prof.display_name = "Between Requests"
    cp.save_profile(prof)

    with app.test_request_context("/"):
        _pin(pid)
        assert app.active_profile().display_name == "Between Requests"


# ---------------------------------------------------------------------------
# The legacy-secrets scrub now runs once at startup, not per profile load.
# ---------------------------------------------------------------------------

def test_startup_scrubs_legacy_secrets_json(tmp_path, monkeypatch):
    import mediahub.web.secrets_store as ss
    import mediahub.web.web as wm

    secrets = tmp_path / "secrets.json"
    secrets.write_text(
        json.dumps(
            {
                "anthropic_api_key": "keep-me",
                "buffer_access_token": "tok-buf",
                "scheduler_access_token": "tok-sched",
            }
        )
    )
    monkeypatch.setattr(ss, "_SECRETS_PATH", secrets)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    # Building the app is the startup path that scrubs the legacy file.
    wm.create_app()

    on_disk = json.loads(secrets.read_text())
    assert "buffer_access_token" not in on_disk
    assert "scheduler_access_token" not in on_disk
    assert on_disk["anthropic_api_key"] == "keep-me"  # unrelated keys survive
