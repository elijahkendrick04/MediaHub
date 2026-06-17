"""tests/test_scheduler_per_profile.py — multi-tenant-safe the scheduler model.

Pins the architectural fix for the the scheduler-multi-tenancy problem:

  • Each ClubProfile carries its OWN scheduler_access_token.
  • /api/organisation/connect-scheduler saves the token onto the active
    profile after validating it against the scheduler.
  • /api/scheduler/channels and /api/runs/<id>/card/<id>/schedule resolve
    the token PER PROFILE first, then fall back to the env var
    SCHEDULER_ACCESS_TOKEN for single-tenant self-hosted use.
  • /api/runs/<id>/card/<id>/download offers the the scheduler-free path —
    a ZIP with caption + visual for manual posting.

The invariant under test: content from Club A NEVER flows through
Club B's the scheduler account, even when both share the same MediaHub
deployment. This is the TOS-safe multi-tenant model.
"""
from __future__ import annotations

import importlib
import io
import json
import sys
import zipfile
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def two_club_app(tmp_path, monkeypatch):
    """Fresh deployment with two seeded clubs + one fake run per club."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    # Clear env SCHEDULER_ACCESS_TOKEN — these tests are about the
    # per-profile path. The env-fallback test sets it explicitly.
    monkeypatch.delenv("SCHEDULER_ACCESS_TOKEN", raising=False)
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    import mediahub.web.secrets_store as ss
    importlib.reload(cp)
    importlib.reload(ss)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(
        profile_id="club-a", display_name="Club A",
        brand_voice_summary="Friendly.",
    ))
    save_profile(ClubProfile(
        profile_id="club-b", display_name="Club B",
        brand_voice_summary="Serious.",
    ))

    for cid in ("club-a", "club-b"):
        run_id = f"{cid}-run-1"
        (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps({
            "run_id": run_id, "profile_id": cid,
            "meet": {"name": f"{cid} meet"},
            "recognition_report": {
                "ranked_achievements": [{
                    "rank": 1, "priority": 0.95,
                    "achievement": {
                        "swim_id": f"{cid}-swim-1",
                        "swimmer_name": "Emma Davies",
                        "event": "100 Free",
                        "time": "58.21",
                        "type": "pb_confirmed",
                        "headline": "First sub-60",
                    },
                    "factors": [],
                }],
            },
        }))

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True
    with app.test_client() as c:
        yield c


def _pin(client, profile_id: str):
    r = client.post("/api/organisation/active", data={"profile_id": profile_id})
    assert r.status_code == 200, r.get_json()


# ---------------------------------------------------------------------------
# 1. /api/organisation/connect-scheduler — validate + persist per-profile
# ---------------------------------------------------------------------------

class TestConnectScheduler:
    def test_token_validated_against_scheduler_before_save(self, two_club_app, monkeypatch):
        """A token that the scheduler rejects must NOT be persisted — the user
        gets immediate feedback, not a silent fail at schedule time."""
        c = two_club_app
        _pin(c, "club-a")
        from mediahub.publishing.scheduler import SchedulerAuthError
        monkeypatch.setattr(
            "mediahub.publishing.scheduler.list_channels",
            lambda t: (_ for _ in ()).throw(SchedulerAuthError("rejected")),
        )
        r = c.post(
            "/api/organisation/connect-scheduler",
            json={"scheduler_access_token": "1/bad-token-9999"},
        )
        assert r.status_code == 401
        assert r.get_json()["error"] == "auth"
        # Profile was NOT updated.
        from mediahub.web.club_profile import load_profile
        assert load_profile("club-a").scheduler_access_token == ""

    def test_valid_token_persists_on_profile(self, two_club_app, monkeypatch):
        c = two_club_app
        _pin(c, "club-a")
        monkeypatch.setattr(
            "mediahub.publishing.scheduler.list_channels",
            lambda t: [
                {"id": "p1", "service": "instagram",
                 "service_username": "@cluba", "formatted_username": "Club A",
                 "avatar": None, "default": True},
            ],
        )
        r = c.post(
            "/api/organisation/connect-scheduler",
            json={"scheduler_access_token": "1/valid-token-12345"},
        )
        assert r.status_code == 200, r.get_json()
        j = r.get_json()
        assert j["ok"] is True
        assert j["channel_count"] == 1
        # Profile NOW has the token.
        from mediahub.web.club_profile import load_profile
        assert load_profile("club-a").scheduler_access_token == "1/valid-token-12345"
        # And club-b is UNAFFECTED — content scoping invariant.
        assert load_profile("club-b").scheduler_access_token == ""

    def test_short_token_rejected_without_scheduler_call(self, two_club_app, monkeypatch):
        c = two_club_app
        _pin(c, "club-a")
        called = {"n": 0}
        def _spy(t):
            called["n"] += 1
            return []
        monkeypatch.setattr("mediahub.publishing.scheduler.list_channels", _spy)
        r = c.post(
            "/api/organisation/connect-scheduler",
            json={"scheduler_access_token": "x"},
        )
        assert r.status_code == 400
        assert r.get_json()["error"] == "short_token"
        # We never hit the scheduler for an obviously-invalid token.
        assert called["n"] == 0

    def test_missing_token_400(self, two_club_app):
        c = two_club_app
        _pin(c, "club-a")
        r = c.post("/api/organisation/connect-scheduler", json={})
        assert r.status_code == 400
        assert r.get_json()["error"] == "missing_token"

    def test_no_active_profile_409(self, tmp_path, monkeypatch):
        """Without a pinned profile we can't connect the scheduler because
        there's no profile to attach the token to."""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "p"))
        (tmp_path / "p").mkdir(parents=True, exist_ok=True)
        import mediahub.web.club_profile as cp
        import mediahub.web.web as wm
        importlib.reload(cp); importlib.reload(wm)
        app = wm.create_app()
        app.config["TESTING"] = True
        app.config["ENFORCE_ORG_GATE"] = False  # let the route handler decide
        with app.test_client() as c:
            r = c.post(
                "/api/organisation/connect-scheduler",
                json={"scheduler_access_token": "1/abc-xyz-9999"},
            )
            assert r.status_code == 409
            assert r.get_json()["error"] == "no_active_profile"


# ---------------------------------------------------------------------------
# 2. Per-profile token resolution (the multi-tenant invariant)
# ---------------------------------------------------------------------------

class TestPerProfileResolution:
    def test_club_b_token_NEVER_used_for_club_a(self, two_club_app, monkeypatch):
        """The multi-tenant safety invariant: content from Club A
        must NEVER flow through Club B's the scheduler account, even when
        both clubs share one MediaHub deployment."""
        c = two_club_app
        # Seed both clubs with their OWN distinct tokens.
        from mediahub.web.club_profile import load_profile, save_profile
        pa = load_profile("club-a")
        pa.scheduler_access_token = "1/CLUB-A-TOKEN"
        save_profile(pa)
        pb = load_profile("club-b")
        pb.scheduler_access_token = "1/CLUB-B-TOKEN"
        save_profile(pb)

        # Spy: which token does each call use?
        seen_tokens: list[str] = []
        def _spy(token, **kwargs):
            seen_tokens.append(token)
            return [{"id": "p1", "service": "instagram",
                     "service_username": "@x", "formatted_username": "X",
                     "avatar": None, "default": True}]
        monkeypatch.setattr("mediahub.publishing.scheduler.list_channels", _spy)

        # Club A's request uses Club A's token.
        _pin(c, "club-a")
        r = c.get("/api/scheduler/channels")
        assert r.status_code == 200
        # Club B's request uses Club B's token.
        _pin(c, "club-b")
        r = c.get("/api/scheduler/channels")
        assert r.status_code == 200

        # The invariant: each club's request used ITS OWN token, not the
        # other's.
        assert seen_tokens == ["1/CLUB-A-TOKEN", "1/CLUB-B-TOKEN"], seen_tokens

    def test_no_token_401_with_connect_url_for_inline_form(self, two_club_app):
        c = two_club_app
        _pin(c, "club-a")
        r = c.get("/api/scheduler/channels")
        assert r.status_code == 401
        j = r.get_json()
        assert j["error"] == "no_token"
        # The 401 carries the connect endpoint so the modal can render
        # the inline "Connect the scheduler" form.
        assert j["connect_url"].endswith("/api/organisation/connect-scheduler")

    def test_env_fallback_for_single_tenant(self, two_club_app, monkeypatch):
        """Single-tenant self-hosted: env SCHEDULER_ACCESS_TOKEN is used
        when the active profile has no token of its own."""
        c = two_club_app
        _pin(c, "club-a")
        # Set the env-var fallback. Profile still has no token.
        monkeypatch.setenv("SCHEDULER_ACCESS_TOKEN", "1/ENV-FALLBACK")
        seen: list[str] = []
        monkeypatch.setattr(
            "mediahub.publishing.scheduler.list_channels",
            lambda t: seen.append(t) or [],
        )
        r = c.get("/api/scheduler/channels")
        assert r.status_code == 200
        assert seen == ["1/ENV-FALLBACK"]

    def test_profile_token_wins_over_env(self, two_club_app, monkeypatch):
        """If both are set, the profile-level token MUST win — env is
        only a fallback, not an override."""
        c = two_club_app
        from mediahub.web.club_profile import load_profile, save_profile
        p = load_profile("club-a")
        p.scheduler_access_token = "1/PROFILE-WINS"
        save_profile(p)
        _pin(c, "club-a")
        monkeypatch.setenv("SCHEDULER_ACCESS_TOKEN", "1/ENV-LOSES")
        seen: list[str] = []
        monkeypatch.setattr(
            "mediahub.publishing.scheduler.list_channels",
            lambda t: seen.append(t) or [],
        )
        r = c.get("/api/scheduler/channels")
        assert r.status_code == 200
        assert seen == ["1/PROFILE-WINS"]


# ---------------------------------------------------------------------------
# 3. /api/runs/<id>/card/<id>/download — the the scheduler-free path
# ---------------------------------------------------------------------------

class TestNoSchedulerDownloadPath:
    def test_zip_contains_caption_text(self, two_club_app):
        c = two_club_app
        _pin(c, "club-a")
        r = c.get(
            "/api/runs/club-a-run-1/card/club-a-swim-1/download"
            "?caption=My%20final%20caption%20copy"
        )
        assert r.status_code == 200
        assert r.mimetype == "application/zip"
        assert "attachment" in r.headers.get("Content-Disposition", "")
        with zipfile.ZipFile(io.BytesIO(r.data)) as zf:
            names = zf.namelist()
            assert any(n.endswith("-caption.txt") for n in names)
            cap = zf.read(
                [n for n in names if n.endswith("-caption.txt")][0]
            ).decode("utf-8")
            assert cap == "My final caption copy"
            assert "README.txt" in names

    def test_unknown_run_404(self, two_club_app):
        c = two_club_app
        _pin(c, "club-a")
        r = c.get("/api/runs/no-such-run/card/x/download")
        assert r.status_code == 404

    def test_unknown_card_404(self, two_club_app):
        c = two_club_app
        _pin(c, "club-a")
        r = c.get("/api/runs/club-a-run-1/card/no-such-card/download")
        assert r.status_code == 404

    def test_works_without_scheduler_token(self, two_club_app):
        """The point of the download path: it works for clubs that
        have NEVER connected the scheduler."""
        c = two_club_app
        _pin(c, "club-a")
        # Confirm club-a has no the scheduler token.
        from mediahub.web.club_profile import load_profile
        assert load_profile("club-a").scheduler_access_token == ""
        r = c.get(
            "/api/runs/club-a-run-1/card/club-a-swim-1/download"
            "?caption=Manual%20post%20copy"
        )
        # Still 200 — download doesn't depend on the scheduler at all.
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# 4. Disconnect — clearing the token on a profile
# ---------------------------------------------------------------------------

class TestDisconnect:
    def test_disconnect_clears_token(self, two_club_app):
        c = two_club_app
        from mediahub.web.club_profile import load_profile, save_profile
        p = load_profile("club-a")
        p.scheduler_access_token = "1/will-be-cleared"
        save_profile(p)
        _pin(c, "club-a")
        r = c.post("/api/organisation/disconnect-scheduler")
        assert r.status_code == 200
        assert r.get_json()["ok"] is True
        assert load_profile("club-a").scheduler_access_token == ""
