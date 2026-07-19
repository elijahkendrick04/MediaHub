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

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def app_no_profiles(client, app, tmp_path):
    app.config["ENFORCE_ORG_GATE"] = True
    yield client, app, tmp_path


@pytest.fixture
def app_two_profiles(app_no_profiles):
    c, app, tmp_path = app_no_profiles
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="wycombe",
            display_name="Wycombe District Swimming Club",
            brand_voice_summary="Friendly competitive club.",
            brand_capture_status="ok_heuristic",
        )
    )
    save_profile(
        ClubProfile(
            profile_id="other",
            display_name="Other Club",
        )
    )
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
        # The empty state is honest about the user's own access (A-4: not a
        # false "none exist on this deployment") and offers a clear path
        # forward (create one) and a way back home.
        assert "don't have access to any organisation" in body
        assert "Create your first organisation" in body
        # A-5: the org picker is titled with organisation vocabulary, not the
        # account "Sign in".
        assert "Choose your organisation" in body

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
        # The pinned-state hero renders its returning-user CTA.
        assert "Create new content" in body
        # Switching organisations is now a developer-operator-only affordance
        # (ADR-0029). An anonymous pilot session (no account, not the dev
        # operator) must not see it in the hero or the account menu.
        assert "Switch organisation" not in body

    def test_switch_organisation_is_dev_operator_only(self, app_two_profiles):
        """Only the authenticated dev operator keeps the cross-org switcher —
        it appears in both the account-menu dropdown and the pinned home hero
        for a dev session, and nowhere for a non-dev session."""
        c, _, _ = app_two_profiles
        # A dev-operator session (ADR-0019 grants the session flag).
        with c.session_transaction() as sess:
            sess["dev_operator"] = True
        c.post("/sign-in", data={"profile_id": "wycombe"})
        body = c.get("/").get_data(as_text=True)
        assert "Wycombe District Swimming Club" in body
        # The operator sees the switch affordance (nav dropdown + hero CTA).
        assert "Switch organisation" in body

    def test_header_dropdowns_are_mutually_exclusive(self, app_two_profiles):
        """The notifications and org-menu dropdowns each stopPropagation on their
        toggle, so opening one must actively close the other via the shared
        mh:dropdown-open event — otherwise both overlap on the same right edge."""
        c, _, _ = app_two_profiles
        c.post("/sign-in", data={"profile_id": "wycombe"})
        body = c.get("/").get_data(as_text=True)
        # Both panels announce their open and both listen to close the sibling.
        assert body.count("mh:dropdown-open") >= 4
        assert "detail:'notif'" in body and "detail:'orgmenu'" in body

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

        After clearing, the session is signed out — we no longer adopt
        any remaining profile automatically — so what matters is that
        the *deleted* profile's id is no longer the active one.
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
        # A fresh session is signed out — the home page must NOT resume
        # the last-used org. With profiles on disk but none pinned, the
        # signed-out hero surfaces Sign up (primary) and Log in (secondary)
        # — A-5: the account log-in, not the org picker.
        resp = c.get("/")
        body = resp.get_data(as_text=True)
        # Hero copy + both CTAs.
        assert "Log in" in body
        assert "Sign up" in body
        assert 'class="mh-cta-primary"' in body
        assert 'class="mh-cta-secondary"' in body
        # The signed-in-only CTA must be absent — we are signed out.
        assert "Create new content" not in body

    def test_unpinned_home_shows_create_first_when_no_profiles(self, app_no_profiles):
        c, _, _ = app_no_profiles
        resp = c.get("/")
        body = resp.get_data(as_text=True)
        # Primary CTA leads to sign up for new users.
        assert "Sign up" in body
        # AND the secondary CTA offers the account log-in path (A-5), so a
        # returning user always has an entry point even on a fresh deployment.
        assert "Log in" in body
        assert 'class="mh-cta-primary"' in body
        assert 'class="mh-cta-secondary"' in body

    def test_pinned_home_shows_continue_cta(self, app_two_profiles):
        c, _, _ = app_two_profiles
        c.post("/sign-in", data={"profile_id": "wycombe"})
        body = c.get("/").get_data(as_text=True)
        assert "Create new content" in body
        assert "Wycombe District Swimming Club" in body
