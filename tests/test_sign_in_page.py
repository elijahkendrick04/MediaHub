"""tests/test_sign_in_page.py — Phase 1.5 profile picker.

Pins the new /sign-in page:

  * Renders a card per saved ClubProfile with display_name + a Sign in CTA.
  * POST /sign-in pins the chosen profile into session and redirects home.
  * POST /sign-in/delete removes the profile JSON; orphans runs but
    doesn't crash.
  * The picker is reachable without an active org (it's how the user
    picks one in the first place).
  * When no profiles exist the page renders an honest empty state with
    a Create CTA — previously it 302'd to /organisation/setup, which
    made the home page "Sign in" button look broken.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def app_no_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True
    with app.test_client() as c:
        yield c, app, tmp_path


@pytest.fixture
def app_two_profiles(app_no_profiles):
    c, app, tmp_path = app_no_profiles
    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(
        profile_id="wycombe",
        display_name="Wycombe District Swimming Club",
        brand_voice_summary="Friendly competitive club.",
        brand_capture_status="ok_heuristic",
    ))
    save_profile(ClubProfile(
        profile_id="other",
        display_name="Other Club",
    ))
    return c, app, tmp_path


class TestSignInPage:
    def test_no_profiles_renders_empty_state(self, app_no_profiles):
        """When no organisation profiles exist, the sign-in page must
        render an honest empty state — NOT a redirect to /organisation/
        setup. The redirect-to-setup behaviour made the home page
        "Sign in to my organisation profile" button look broken, since
        clicking it landed the user on the same setup page as "Create
        your first organisation"."""
        c, _, _ = app_no_profiles
        resp = c.get("/sign-in", follow_redirects=False)
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # The empty state announces "no profiles" and offers a clear
        # path forward (create one) and a way back home.
        assert "No organisation profiles" in body
        assert "Create your first organisation" in body
        # The sign-in page is in the topnav as active.
        assert "Sign in" in body

    def test_renders_card_per_profile(self, app_two_profiles):
        c, _, _ = app_two_profiles
        resp = c.get("/sign-in")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Wycombe District Swimming Club" in body
        assert "Other Club" in body
        # Both have a sign-in button.
        assert body.count("btn-sign-in") >= 2
        # And both have a delete button.
        assert body.count("btn-delete") >= 2
        # And a "Create new organisation" tile.
        assert "mh-new-profile" in body

    def test_pinning_a_profile_redirects_home(self, app_two_profiles):
        c, _, _ = app_two_profiles
        resp = c.post(
            "/sign-in",
            data={"profile_id": "wycombe"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"

    def test_pinning_unknown_profile_redirects_to_picker(self, app_two_profiles):
        c, _, _ = app_two_profiles
        resp = c.post(
            "/sign-in",
            data={"profile_id": "does-not-exist"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/sign-in" in resp.headers.get("Location", "")

    def test_pinned_profile_appears_pinned_on_home(self, app_two_profiles):
        c, _, _ = app_two_profiles
        c.post("/sign-in", data={"profile_id": "wycombe"})
        resp = c.get("/")
        body = resp.get_data(as_text=True)
        assert "Wycombe District Swimming Club" in body
        # The pinned-state CTA wording.
        assert "Switch organisation" in body

    def test_delete_removes_profile_json(self, app_two_profiles):
        c, _, tmp_path = app_two_profiles
        json_path = tmp_path / "club_profiles" / "other.json"
        assert json_path.exists()
        resp = c.post(
            "/sign-in/delete",
            data={"profile_id": "other"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert not json_path.exists()
        # Sign-in page no longer lists it.
        body = c.get("/sign-in").get_data(as_text=True)
        assert "Other Club" not in body

    def test_delete_clears_active_pin_when_deleting_active(self, app_two_profiles):
        """If the user deletes the currently-active profile, the
        session pin must clear; otherwise subsequent gates would refer
        to a profile that no longer exists on disk and crash.

        After clearing, `_active_profile_id` may fall back to the
        most-recent-mtime remaining profile via the existing helper —
        what matters is that the *deleted* profile's id is no longer
        the active one.
        """
        c, _, _ = app_two_profiles
        c.post("/sign-in", data={"profile_id": "wycombe"})
        c.post("/sign-in/delete", data={"profile_id": "wycombe"})
        resp = c.get("/api/organisation/active")
        body = resp.get_json() or {}
        # The deleted profile must NOT remain pinned.
        assert body.get("profile_id") != "wycombe"


class TestHomeHeroSwitching:
    def test_unpinned_home_shows_two_ctas_when_profiles_exist(self, app_two_profiles):
        c, _, _ = app_two_profiles
        resp = c.get("/")
        body = resp.get_data(as_text=True)
        # Hero copy + both CTAs.
        assert "Sign in" in body
        assert "Create new organisation" in body
        assert 'class="mh-cta-primary"' in body
        assert 'class="mh-cta-secondary"' in body

    def test_unpinned_home_shows_create_first_when_no_profiles(self, app_no_profiles):
        c, _, _ = app_no_profiles
        resp = c.get("/")
        body = resp.get_data(as_text=True)
        # Primary CTA leads to setup ("Create your first organisation").
        assert "Create your first organisation" in body
        # AND the secondary CTA offers the sign-in path — the user
        # must see both options even on a fresh deployment so the
        # "Sign in" button never looks broken.
        assert "Sign in to my organisation profile" in body
        assert 'class="mh-cta-primary"' in body
        assert 'class="mh-cta-secondary"' in body

    def test_pinned_home_shows_continue_cta(self, app_two_profiles):
        c, _, _ = app_two_profiles
        c.post("/sign-in", data={"profile_id": "wycombe"})
        body = c.get("/").get_data(as_text=True)
        assert "Create new content" in body
        assert "Wycombe District Swimming Club" in body
