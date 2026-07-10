"""Stage E — /api/organisation/finalise endpoint contract tests.

The endpoint that the "Looks right" button calls before navigating.
Idempotent: ensures the active profile's derived palette is computed
and persisted; returns the resolved seed_hex + repair flag.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """A clean Flask app with isolated DATA_DIR and a session pin
    helper. Pattern mirrors tests/test_responsive_meta.py."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, wm, cp


def _seed_profile(cp_module, primary="#06D6A0", display_name="Test Club"):
    """Create a minimal profile with a brand kit and persist it."""
    from mediahub.web.club_profile import ClubProfile
    pid = "swim-test"
    prof = ClubProfile(profile_id=pid, display_name=display_name)
    prof.brand_primary = primary
    prof.brand_kit = {
        "profile_id": pid,
        "display_name": display_name,
        "primary_colour": primary,
        "secondary_colour": "#0E2A47",
    }
    cp_module.save_profile(prof)
    return prof


class TestRouteRegistered:
    def test_finalise_route_exists(self, app_client):
        client, wm, _ = app_client
        routes = [r.rule for r in wm.create_app().url_map.iter_rules()]
        assert "/api/organisation/finalise" in routes

    def test_finalise_is_post_only(self, app_client):
        client, _, _ = app_client
        # GET should be rejected (POST-only endpoint)
        r = client.get("/api/organisation/finalise")
        assert r.status_code == 405, f"GET should be 405, got {r.status_code}"


class TestNoActiveProfile:
    def test_post_without_session_returns_400(self, app_client):
        client, _, _ = app_client
        r = client.post("/api/organisation/finalise")
        assert r.status_code == 400
        payload = r.get_json()
        assert payload is not None
        assert "error" in payload
        assert "no active" in payload["error"].lower()


class TestWithActiveProfile:
    def test_post_with_active_org_returns_200(self, app_client):
        client, wm, cp = app_client
        prof = _seed_profile(cp, primary="#06D6A0")
        with client.session_transaction() as sess:
            sess["active_profile_id"] = prof.profile_id
        r = client.post("/api/organisation/finalise")
        assert r.status_code == 200, f"expected 200, got {r.status_code} {r.get_data(as_text=True)}"
        payload = r.get_json()
        assert payload is not None
        assert "seed_hex" in payload
        # The seed should be a 6/8-digit hex.
        import re
        assert re.fullmatch(r"#[0-9A-Fa-f]{6,8}", payload["seed_hex"])

    def test_persistence_end_to_end(self, app_client):
        """After POST, the profile's brand_kit should contain a
        derived_palette dict — proof that the call wrote to disk."""
        client, wm, cp = app_client
        prof = _seed_profile(cp, primary="#0E2A47")
        with client.session_transaction() as sess:
            sess["active_profile_id"] = prof.profile_id

        # Pre-state: no derived palette
        before = cp.load_profile(prof.profile_id)
        assert "derived_palette" not in (before.brand_kit or {}) or \
               before.brand_kit.get("derived_palette") is None

        r = client.post("/api/organisation/finalise")
        assert r.status_code == 200

        # Post-state: derived palette present
        after = cp.load_profile(prof.profile_id)
        bk = after.brand_kit or {}
        assert bk.get("derived_palette") is not None, (
            f"profile not updated after finalise; brand_kit={bk!r}"
        )
        derived = bk["derived_palette"]
        # The derived dict carries the documented shape
        for key in ("seed_hex", "palettes", "roles", "schema_version"):
            assert key in derived, f"derived missing {key!r}"

    def test_idempotent(self, app_client):
        """Calling twice should return the same payload — no work the
        second time because the palette is cached."""
        client, wm, cp = app_client
        prof = _seed_profile(cp, primary="#A30D2D")
        with client.session_transaction() as sess:
            sess["active_profile_id"] = prof.profile_id

        a = client.post("/api/organisation/finalise").get_json()
        b = client.post("/api/organisation/finalise").get_json()
        assert a == b, f"non-idempotent: {a} != {b}"


class TestRepairFlag:
    """For a hostile seed (red brand vs locked status reds), Stage B
    triggers the repair loop and ``was_repaired`` is True. The
    finalise endpoint surfaces that flag for the Stage H UI."""

    def test_was_repaired_flag_propagates(self, app_client):
        client, wm, cp = app_client
        # Brand red seed → Stage B's repair loop fires per Stage B tests
        prof = _seed_profile(cp, primary="#A30D2D")
        with client.session_transaction() as sess:
            sess["active_profile_id"] = prof.profile_id

        payload = client.post("/api/organisation/finalise").get_json()
        # The Stage B engine deterministically repairs red seeds —
        # was_repaired must be True.
        assert payload["was_repaired"] is True


class TestNoInternalPathLeak:
    """On a save/derivation failure the 500 JSON must not echo the raw
    exception text — it can carry the absolute DATA_DIR path / errno.
    The detail belongs in the server log only."""

    def test_save_failure_does_not_leak_path_in_response(self, app_client, monkeypatch):
        client, wm, cp = app_client
        prof = _seed_profile(cp, primary="#06D6A0")
        with client.session_transaction() as sess:
            sess["active_profile_id"] = prof.profile_id

        leaky = "/var/data/mediahub/club_profiles/swim-test.json"

        def boom(_profile):
            raise OSError(f"[Errno 30] Read-only file system: '{leaky}'")

        # save_profile is imported into the web module's namespace at call time.
        monkeypatch.setattr(wm, "save_profile", boom)

        r = client.post("/api/organisation/finalise")
        assert r.status_code == 500
        body = r.get_data(as_text=True)
        assert leaky not in body, f"leaked internal path in response: {body!r}"
        assert "Errno" not in body
        assert "Read-only" not in body
        payload = r.get_json()
        assert payload is not None
        assert "detail" not in payload
        assert payload.get("error") == "profile save failed"
