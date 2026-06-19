"""tests/test_activity_scoping.py — /activity shows runs for the active org only.

The home page used to show every run on the instance, regardless of
which organisation produced it. The /activity page (and the underlying
SQL filter) must instead surface only the runs whose ``profile_id``
matches the currently-pinned organisation.

This guards against the leak described in the spec:
  "say we have three people using the website. The recent runs should
   only show the recent runs of the specific organisation, full stop."
"""
from __future__ import annotations

import importlib
import sys
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def gated_client(tmp_path, monkeypatch):
    """Fresh DATA_DIR with the org gate enforced. Reloads the web module
    so module-level DB_PATH / RUNS_DIR re-resolve against tmp_path."""
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
    app.config["ENFORCE_ORG_GATE"] = True

    # Seed two organisations on disk so we have multi-tenant data.
    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(
        profile_id="club-a", display_name="Club A",
        brand_voice_summary="A friendly club.",
    ))
    save_profile(ClubProfile(
        profile_id="club-b", display_name="Club B",
        brand_voice_summary="A serious club.",
    ))

    # Seed five runs across the two clubs in the SQLite store.
    conn = wm._db()
    for run_id, profile_id, meet in [
        ("run-a1", "club-a", "Club A meet 1"),
        ("run-a2", "club-a", "Club A meet 2"),
        ("run-b1", "club-b", "Club B meet 1"),
        ("run-b2", "club-b", "Club B meet 2"),
        ("run-b3", "club-b", "Club B meet 3"),
    ]:
        conn.execute(
            "INSERT INTO runs (id, created_at, finished_at, status, profile_id, "
            "meet_name, file_name, our_swims, n_cards, n_queue, error) "
            "VALUES (?, datetime('now'), datetime('now'), 'done', ?, ?, ?, 1, 1, 0, NULL)",
            (run_id, profile_id, meet, f"{meet}.pdf"),
        )
    conn.commit()
    conn.close()

    with app.test_client() as c:
        yield c, app


# ---------------------------------------------------------------------------
# 1. /activity is scoped to the pinned org
# ---------------------------------------------------------------------------

class TestActivityScoping:
    def _pin(self, client, profile_id: str):
        """Pin a profile into the test session by hitting the active-org API."""
        resp = client.post(
            "/api/organisation/active",
            data={"profile_id": profile_id},
        )
        assert resp.status_code == 200, resp.get_json()

    def test_activity_for_club_a_only_shows_club_a_runs(self, gated_client):
        c, _ = gated_client
        self._pin(c, "club-a")
        resp = c.get("/activity")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Club A meet 1" in body
        assert "Club A meet 2" in body
        # Critical: NO Club B runs leak in
        assert "Club B meet 1" not in body
        assert "Club B meet 2" not in body
        assert "Club B meet 3" not in body

    def test_activity_for_club_b_only_shows_club_b_runs(self, gated_client):
        c, _ = gated_client
        self._pin(c, "club-b")
        resp = c.get("/activity")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Club B meet 1" in body
        assert "Club B meet 2" in body
        assert "Club B meet 3" in body
        assert "Club A meet 1" not in body
        assert "Club A meet 2" not in body

    def test_activity_empty_state_for_new_club(self, gated_client):
        """A club with no runs gets the empty-state message, not someone
        else's table."""
        c, _ = gated_client
        from mediahub.web.club_profile import ClubProfile, save_profile
        save_profile(ClubProfile(
            profile_id="club-c", display_name="Club C",
            brand_voice_summary="A new club.",
        ))
        self._pin(c, "club-c")
        resp = c.get("/activity")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "No runs yet for this organisation" in body
        # And critically — no other club's data appears
        assert "Club A meet" not in body
        assert "Club B meet" not in body


# ---------------------------------------------------------------------------
# 2. /home is stripped to banner + how-it-works only
# ---------------------------------------------------------------------------

class TestHomeIsStripped:
    def test_home_has_no_engine_live_badge(self, gated_client):
        c, _ = gated_client
        self._pin = lambda *_: c.post("/api/organisation/active", data={"profile_id": "club-a"})
        self._pin()
        resp = c.get("/")
        body = resp.get_data(as_text=True)
        # The provider-live badge is a developer detail and must not
        # appear on the front page.
        assert "Content engine live" not in body
        assert "Heuristic mode" not in body
        assert "powered by Google Gemini" not in body
        # The badge element itself must not render on the page — the CSS
        # class name still appears in <style>, which is harmless.
        assert 'class="mh-provider-badge' not in body

    def test_home_has_no_content_templates(self, gated_client):
        c, _ = gated_client
        c.post("/api/organisation/active", data={"profile_id": "club-a"})
        resp = c.get("/")
        body = resp.get_data(as_text=True)
        assert "Content templates" not in body
        assert "Pick a format" not in body

    def test_home_has_no_recent_runs_table(self, gated_client):
        """Runs are surfaced under /activity now, not on the home page."""
        c, _ = gated_client
        c.post("/api/organisation/active", data={"profile_id": "club-a"})
        resp = c.get("/")
        body = resp.get_data(as_text=True)
        assert "Recent runs" not in body
        assert "Club A meet 1" not in body  # would appear if the table leaked back

    def test_home_keeps_org_banner_and_how_it_works(self, gated_client):
        c, _ = gated_client
        c.post("/api/organisation/active", data={"profile_id": "club-a"})
        resp = c.get("/")
        body = resp.get_data(as_text=True)
        # Phase 1.5 redesigned home: pinned-state hero leads with the
        # org name + "Create new content" CTA + "Edit profile" link.
        assert "Club A" in body
        assert "Create new content" in body
        assert "Edit profile" in body
        # The "how it works" explainer (pipeline diagram) is still present.
        assert ("How it works" in body) or ("workflow" in body.lower())

    def test_home_banner_morphs_to_setup_when_no_org(self, gated_client):
        c, _ = gated_client
        # A fresh session is signed out: the home page must NOT resume
        # whichever org was used last. With organisations on disk but
        # none pinned, the signed-out hero surfaces Sign up (primary)
        # and Sign in (secondary) so new users have a clear entry point.
        resp = c.get("/")
        body = resp.get_data(as_text=True)
        assert "Sign in" in body
        assert "Sign up" in body
        # The signed-in-only CTA must be absent — we are signed out.
        assert "Create new content" not in body


# ---------------------------------------------------------------------------
# 3. Top nav consolidates Activity under Settings
# ---------------------------------------------------------------------------

class TestSettingsExposesActivityInNav:
    def test_settings_link_in_top_nav(self, gated_client):
        """The standalone Activity nav button was consolidated into the
        Settings page (which carries Activity / Status / Privacy /
        Deployment status sections). The topnav must surface Settings
        as the single entrypoint; the /activity deep-link route still
        exists for backwards compatibility, but is no longer a
        first-class nav item."""
        c, _ = gated_client
        c.post("/api/organisation/active", data={"profile_id": "club-a"})
        resp = c.get("/")
        body = resp.get_data(as_text=True)
        # Settings is the nav entrypoint.
        assert ">Settings<" in body
        assert "/settings" in body

    def test_activity_route_still_resolves(self, gated_client):
        """Backwards compatibility — the /activity URL still works
        even though the nav no longer surfaces it directly. Internal
        url_for('activity_page') calls and external bookmarks must
        continue to render the activity page."""
        c, _ = gated_client
        c.post("/api/organisation/active", data={"profile_id": "club-a"})
        resp = c.get("/activity")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Activity" in body
