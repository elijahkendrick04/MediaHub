"""tests/test_login_idle_timeout.py — logins must not linger across visits.

Opening the app must always start signed-out unless the visitor has an
*actively-used* login. The active org is pinned into the Flask session,
but Flask's session cookie is non-persistent only in theory: Chrome/Edge
"continue where you left off" and most mobile browsers restore session
cookies on relaunch, so without a server-side guard a returning visitor
silently resumes whichever org was used last (the "it opens straight to
<org>" bug).

The guard is an idle window: a pin that hasn't been touched within
MEDIAHUB_LOGIN_IDLE_MINUTES — or that carries no activity stamp at all
(every login written before this mechanism existed) — is dropped and the
visitor reported signed-out. Active navigation rolls the window forward.

This file pins that behaviour.
"""
from __future__ import annotations

import time

import pytest


def _prepare_app(app):
    """Layer this suite's opt-in enforcement flags onto the canonical ``app``
    fixture and seed the club the tests sign into.

    The app object and its isolated ``DATA_DIR`` come from the shared
    ``app`` fixture (``tests/conftest.py``); this helper only adds what these
    idle-timeout tests need. ``MEDIAHUB_LOGIN_IDLE_MINUTES`` is *not* set here
    — it is read live from ``os.environ`` inside ``web.py`` at request time, so
    a test tunes it with ``monkeypatch.setenv`` before the request instead.
    """
    app.config["ENFORCE_ORG_GATE"] = True
    # Idle-timeout enforcement mirrors the org gate: off under TESTING
    # unless explicitly opted in. These tests are the opt-in.
    app.config["ENFORCE_LOGIN_IDLE"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(
        profile_id="wycombe",
        display_name="Wycombe District Swimming Club",
        brand_voice_summary="Friendly competitive club.",
        brand_capture_status="ok_heuristic",
    ))
    return app


@pytest.fixture
def client(app):
    _prepare_app(app)
    with app.test_client() as c:
        yield c


class TestLoginIdleTimeout:
    def test_fresh_signin_stays_signed_in(self, client):
        """A login that was just used resolves normally — the timeout
        must not log an active session out."""
        client.post("/sign-in", data={"profile_id": "wycombe"})
        body = client.get("/").get_data(as_text=True)
        assert "Wycombe District Swimming Club" in body
        # Signed-in-only CTA present.
        assert "Create new content" in body
        # The API agrees we're signed in.
        api = client.get("/api/organisation/active").get_json()
        assert api.get("profile_id") == "wycombe"

    def test_idle_beyond_window_signs_out(self, client):
        """Once the pin has been idle past the window, opening the home
        page must show the signed-out state, not resume the org."""
        client.post("/sign-in", data={"profile_id": "wycombe"})
        # Backdate the activity stamp well beyond the default 30-min window.
        with client.session_transaction() as sess:
            assert sess.get("active_profile_id") == "wycombe"
            sess["login_seen_at"] = int(time.time()) - 10_000_000

        body = client.get("/").get_data(as_text=True)
        # Neutral signed-out hero — Sign up primary, Sign in secondary.
        assert "Sign up" in body
        assert "Create new content" not in body
        # API reports signed-out, and the stale pin has been cleared.
        api = client.get("/api/organisation/active").get_json()
        assert not api.get("profile_id")
        with client.session_transaction() as sess:
            assert sess.get("active_profile_id") is None

    def test_legacy_pin_without_stamp_signs_out(self, client):
        """A cookie written before the idle-timeout existed carries an
        active_profile_id but no login_seen_at. That is exactly the
        lingering-login case reported in the field — it must resolve as
        signed-out so the historical pins are invalidated on next visit."""
        with client.session_transaction() as sess:
            sess["active_profile_id"] = "wycombe"  # note: no login_seen_at

        api = client.get("/api/organisation/active").get_json()
        assert not api.get("profile_id")
        with client.session_transaction() as sess:
            assert sess.get("active_profile_id") is None

    def test_active_use_rolls_window_forward(self, client):
        """A login used within the window stays alive AND its activity
        stamp is rolled forward, so continued use never expires."""
        client.post("/sign-in", data={"profile_id": "wycombe"})
        # Age the stamp past the 30s coalesce threshold but inside the
        # 30-min window, then make a request: it should still resolve and
        # advance the stamp.
        stale = int(time.time()) - 120
        with client.session_transaction() as sess:
            sess["login_seen_at"] = stale

        api = client.get("/api/organisation/active").get_json()
        assert api.get("profile_id") == "wycombe"
        with client.session_transaction() as sess:
            assert sess.get("login_seen_at") > stale

    def test_idle_window_is_tunable(self, app, monkeypatch):
        """A very short MEDIAHUB_LOGIN_IDLE_MINUTES is honoured (clamped
        to the 1-minute floor): a pin idle past it signs out."""
        # Read live at request time inside web.py, so setting it before the
        # request suffices — no reload needed.
        monkeypatch.setenv("MEDIAHUB_LOGIN_IDLE_MINUTES", "1")
        _prepare_app(app)
        with app.test_client() as c:
            c.post("/sign-in", data={"profile_id": "wycombe"})
            # 90s of idle exceeds the 1-minute window.
            with c.session_transaction() as sess:
                sess["login_seen_at"] = int(time.time()) - 90
            api = c.get("/api/organisation/active").get_json()
            assert not api.get("profile_id")
