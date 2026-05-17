"""tests/test_org_setup_gate.py — first-run organisation gate.

Asserts that:
  1. Browser routes that produce content (add-input, upload, etc.) are
     redirected to /organisation/setup until an organisation profile
     exists AND is "ready" (has a captured brand voice or pasted voice
     examples).
  2. JSON API routes return 409 with an explanatory body, not a redirect.
  3. /, /organisation*, /settings, /healthz, /static remain reachable.
  4. After a successful capture the session is pinned and the gate lifts
     for the same browser session.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def isolated_profiles(tmp_path, monkeypatch):
    """Redirect the profile store + DATA_DIR under tmp_path so the gate
    sees a clean slate. The web module is reloaded so its module-level
    DB_PATH / RUNS_DIR globals re-resolve against the fresh tmp dir
    (they're cached at first import)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    import importlib
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)
    yield tmp_path


@pytest.fixture
def gated_client(isolated_profiles, monkeypatch):
    """A test client with TESTING=True but ENFORCE_ORG_GATE=True so the
    gate is actually active (the gate is bypassed under plain TESTING
    mode by default so the existing test suite isn't disturbed)."""
    import mediahub.web.web as wm
    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True
    with app.test_client() as c:
        yield c, app


# ---------------------------------------------------------------------------
# 1. Browser routes are redirected when no org is set up
# ---------------------------------------------------------------------------

class TestBrowserRoutesGated:
    def test_add_input_redirects_to_setup(self, gated_client):
        c, _ = gated_client
        resp = c.get("/add-input", follow_redirects=False)
        assert resp.status_code in (301, 302, 303, 307, 308)
        assert "/organisation/setup" in resp.headers.get("Location", "")

    def test_upload_get_redirects_to_setup(self, gated_client):
        c, _ = gated_client
        resp = c.get("/upload", follow_redirects=False)
        assert resp.status_code in (301, 302, 303, 307, 308)
        assert "/organisation/setup" in resp.headers.get("Location", "")


# ---------------------------------------------------------------------------
# 2. JSON routes return 409
# ---------------------------------------------------------------------------

class TestApiRoutesReturn409:
    def test_caption_api_returns_409(self, gated_client):
        c, _ = gated_client
        resp = c.post("/api/runs/anything/swim/anything/caption?tone=ai")
        assert resp.status_code == 409
        body = resp.get_json() or {}
        assert body.get("error") == "organisation_not_ready"
        assert "/organisation/setup" in (body.get("setup_url") or "")


# ---------------------------------------------------------------------------
# 3. Exempt routes remain reachable
# ---------------------------------------------------------------------------

class TestExemptRoutesReachable:
    def test_home_loads(self, gated_client):
        c, _ = gated_client
        resp = c.get("/")
        assert resp.status_code == 200

    def test_setup_page_loads(self, gated_client):
        c, _ = gated_client
        resp = c.get("/organisation/setup")
        assert resp.status_code == 200
        assert b"organisation" in resp.data.lower()

    def test_organisation_editor_loads(self, gated_client):
        c, _ = gated_client
        resp = c.get("/organisation")
        assert resp.status_code == 200

    def test_settings_loads(self, gated_client):
        c, _ = gated_client
        resp = c.get("/settings")
        assert resp.status_code == 200

    def test_healthz_loads(self, gated_client):
        c, _ = gated_client
        resp = c.get("/healthz")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 4. After capture, the gate lifts within the same session
# ---------------------------------------------------------------------------

class TestGateLiftsAfterSetup:
    def test_capture_pins_session_and_unlocks(
        self, gated_client, monkeypatch,
    ):
        # Stub the social_dna capture to return a complete brand profile
        # without hitting the network or an LLM.
        from mediahub.brand import social_dna

        def fake_capture(social_links, website_url, *, force=False):
            return {
                "brand_voice_summary": "A friendly local swimming club.",
                "brand_keywords": ["community", "swimming"],
                "brand_palette_extracted": {"primary": "#0066cc"},
                "brand_logo_url": "",
                "brand_typography_hint": "sans",
                "brand_phrases_to_avoid": [],
                "brand_phrases_to_use": ["Big PB"],
                "brand_source_url": website_url or "",
                "brand_captured_at": "2026-05-17T12:00:00+00:00",
                "brand_capture_status": "ok",
                "voice_profile": {
                    "preferred_swimmer_address": "first_name",
                    "common_hashtags": ["#ClubLife"],
                },
                "social_links_status": {"website": "ok"},
                "captions_captured": 4,
            }

        monkeypatch.setattr(social_dna, "capture_from_socials", fake_capture)

        c, _ = gated_client

        # Before setup: blocked
        before = c.get("/add-input", follow_redirects=False)
        assert before.status_code in (301, 302, 303, 307, 308)

        # Run the setup capture
        resp = c.post(
            "/organisation/setup/capture",
            data={
                "display_name": "City Aquatics Club",
                "org_type": "swimming_club",
                "country": "United Kingdom",
                "governing_body": "Swim England",
                "website_url": "https://city-aquatics.example",
                "social_instagram": "",
                "social_facebook": "",
                "social_twitter": "",
                "social_tiktok": "",
                "social_linkedin": "",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (301, 302, 303, 307, 308)
        assert "/organisation/setup" in resp.headers.get("Location", "")

        # After setup: same session can hit content-production routes
        after = c.get("/add-input", follow_redirects=False)
        assert after.status_code == 200, (
            f"gate should have lifted after setup; got {after.status_code} "
            f"{after.headers.get('Location','')}"
        )

    def test_active_org_api_reports_pinned_profile(
        self, gated_client, monkeypatch,
    ):
        """/api/organisation/active should reflect the session pin."""
        from mediahub.brand import social_dna

        def fake_capture(social_links, website_url, *, force=False):
            return {
                "brand_voice_summary": "x",
                "brand_keywords": ["a"],
                "brand_palette_extracted": {},
                "brand_logo_url": "",
                "brand_typography_hint": "",
                "brand_phrases_to_avoid": [],
                "brand_phrases_to_use": [],
                "brand_source_url": website_url,
                "brand_captured_at": "2026-05-17T12:00:00+00:00",
                "brand_capture_status": "ok",
                "voice_profile": {},
                "social_links_status": {"website": "ok"},
                "captions_captured": 0,
            }

        monkeypatch.setattr(social_dna, "capture_from_socials", fake_capture)

        c, _ = gated_client
        c.post(
            "/organisation/setup/capture",
            data={
                "display_name": "Memory Club",
                "website_url": "https://memory-club.example",
            },
        )
        resp = c.get("/api/organisation/active")
        assert resp.status_code == 200
        body = resp.get_json() or {}
        assert body.get("ok") is True
        assert body.get("display_name") == "Memory Club"
        assert body.get("is_ready") is True


# ---------------------------------------------------------------------------
# 5. ClubProfile.is_ready() rules
# ---------------------------------------------------------------------------

class TestIsReady:
    def test_blank_profile_not_ready(self):
        from mediahub.web.club_profile import ClubProfile
        p = ClubProfile(profile_id="x", display_name="")
        assert p.is_ready() is False

    def test_name_only_not_ready(self):
        from mediahub.web.club_profile import ClubProfile
        p = ClubProfile(profile_id="x", display_name="Some Club")
        assert p.is_ready() is False

    def test_brand_voice_summary_makes_ready(self):
        from mediahub.web.club_profile import ClubProfile
        p = ClubProfile(
            profile_id="x", display_name="Some Club",
            brand_voice_summary="A community club that celebrates effort.",
        )
        assert p.is_ready() is True

    def test_voice_examples_make_ready(self):
        from mediahub.web.club_profile import ClubProfile
        p = ClubProfile(
            profile_id="x", display_name="Some Club",
            voice_examples=["a", "b", "c"],
        )
        assert p.is_ready() is True

    def test_voice_profile_makes_ready(self):
        from mediahub.web.club_profile import ClubProfile
        p = ClubProfile(
            profile_id="x", display_name="Some Club",
            voice_profile={"preferred_swimmer_address": "first_name"},
        )
        assert p.is_ready() is True
