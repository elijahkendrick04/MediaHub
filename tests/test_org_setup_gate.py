"""tests/test_org_setup_gate.py — first-run organisation gate.

Asserts that:
  1. Browser routes that produce content (the Create tab, upload, etc.)
     are redirected to /organisation/setup until an organisation profile
     exists AND is "ready" (has a captured brand voice or pasted voice
     examples). /add-input is exercised here because it's a redirect
     alias to /make and the gate must fire before the alias resolves.
  2. JSON API routes return 409 with an explanatory body, not a redirect.
  3. /, /organisation*, /settings (consolidated Operations page),
     /healthz, /static remain reachable.
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
def gated_client(app):
    """A test client with TESTING=True but ENFORCE_ORG_GATE=True so the
    gate is actually active (the gate is bypassed under plain TESTING
    mode by default so the existing test suite isn't disturbed).

    Rides the canonical ``app`` fixture (fresh ``create_app()`` on an
    isolated per-test DATA_DIR — no ``importlib.reload``); only the
    gate-enforcement flag is layered on here."""
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

    def test_settings_renders_without_org(self, gated_client):
        """The Settings page is a card grid of headings (Activity, Auto
        scheduling, Privacy & data, System status, …), each opening its own
        detail page. It must render even when no organisation is pinned —
        the user needs to reach settings before completing first-run setup."""
        c, _ = gated_client
        resp = c.get("/settings", follow_redirects=False)
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Activity" in body
        assert "System status" in body
        assert "Privacy &amp; data" in body or "Privacy & data" in body
        assert "mh-template" in body

    def test_healthz_loads(self, gated_client):
        c, _ = gated_client
        resp = c.get("/healthz")
        assert resp.status_code == 200

    def test_research_page_loads_without_org(self, gated_client):
        """/research is a public informational page ("What files can I upload?");
        it must be reachable before sign-in, not redirected to setup. F-4 rewrote
        it from the parser/adapter research notes into customer-facing copy."""
        c, _ = gated_client
        resp = c.get("/research", follow_redirects=False)
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "What files can I upload?" in body
        assert "can_parse" not in body and "adapter" not in body.lower()


# ---------------------------------------------------------------------------
# 4. After capture, the gate lifts within the same session
# ---------------------------------------------------------------------------


class TestGateLiftsAfterSetup:
    def test_capture_pins_session_and_unlocks(
        self,
        gated_client,
        monkeypatch,
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

        # After setup: same session can hit content-production routes.
        # /add-input is preserved as a redirect alias to /make (the
        # "Add Input" tab was merged into "Create"), so we follow
        # redirects to confirm the page lands on a real 200, not on
        # the org-setup gate.
        after = c.get("/add-input", follow_redirects=True)
        assert after.status_code == 200, (
            f"gate should have lifted after setup; got {after.status_code} "
            f"{after.headers.get('Location','')}"
        )

    def test_setup_accepts_optional_brand_guidelines_file(
        self,
        gated_client,
        monkeypatch,
    ):
        """The setup form has an optional file upload. When a file IS
        provided, the AI ingestion fields land on the saved profile;
        when it's NOT, the rest of the form still works."""
        from mediahub.brand import social_dna, guidelines

        monkeypatch.setattr(
            social_dna,
            "capture_from_socials",
            lambda **kw: {
                "brand_voice_summary": "Captured.",
                "brand_keywords": ["x"],
                "brand_palette_extracted": {},
                "brand_logo_url": "",
                "brand_typography_hint": "",
                "brand_phrases_to_avoid": [],
                "brand_phrases_to_use": [],
                "brand_source_url": kw.get("website_url", ""),
                "brand_captured_at": "2026-05-17T12:00:00+00:00",
                "brand_capture_status": "ok",
                "voice_profile": {},
                "social_links_status": {"website": "ok"},
                "captions_captured": 0,
            },
        )
        # Mock the LLM so the guidelines interpretation is deterministic.
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        monkeypatch.setattr(
            "mediahub.media_ai.llm.generate_json",
            lambda *a, **kw: {
                "summary": "Warm and inclusive.",
                "voice_attributes": ["warm", "inclusive"],
                "tone_dos": ["Use first names"],
                "tone_donts": ["Never compare swimmers"],
                "prohibited_words": ["loser"],
                "preferred_terminology": {},
                "hashtag_rules": "",
                "sponsor_mention_rules": "",
                "audience": "",
                "key_messages": [],
                "palette_mentions": [],
            },
        )

        c, _ = gated_client
        import io

        file_bytes = b"Brand voice: warm, inclusive. Never compare swimmers."
        resp = c.post(
            "/organisation/setup/capture",
            data={
                "display_name": "Upload Club",
                "website_url": "https://upload-club.example",
                "brand_guidelines_file": (io.BytesIO(file_bytes), "guide.txt"),
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code in (301, 302, 303, 307, 308)

        # The profile must now carry the AI-interpreted guidelines.
        from mediahub.web.club_profile import list_profiles

        profs = [p for p in list_profiles() if p.display_name == "Upload Club"]
        assert len(profs) == 1, "profile not saved"
        p = profs[0]
        assert p.brand_guidelines_filename == "guide.txt"
        assert p.brand_guidelines_status == "ok"
        assert "warm" in p.brand_guidelines["voice_attributes"]
        assert "Use first names" in p.brand_guidelines["tone_dos"]
        assert "loser" in p.brand_guidelines["prohibited_words"]
        # Raw excerpt preserved
        assert "warm" in p.brand_guidelines_raw_excerpt.lower()

    def test_setup_without_file_still_works(self, gated_client, monkeypatch):
        """The file upload is genuinely optional — the form must
        succeed without it, leaving brand_guidelines fields empty."""
        from mediahub.brand import social_dna

        monkeypatch.setattr(
            social_dna,
            "capture_from_socials",
            lambda **kw: {
                "brand_voice_summary": "x",
                "brand_keywords": ["x"],
                "brand_palette_extracted": {},
                "brand_logo_url": "",
                "brand_typography_hint": "",
                "brand_phrases_to_avoid": [],
                "brand_phrases_to_use": [],
                "brand_source_url": kw.get("website_url", ""),
                "brand_captured_at": "2026-05-17T12:00:00+00:00",
                "brand_capture_status": "ok",
                "voice_profile": {},
                "social_links_status": {"website": "ok"},
                "captions_captured": 0,
            },
        )
        c, _ = gated_client
        resp = c.post(
            "/organisation/setup/capture",
            data={
                "display_name": "No-File Club",
                "website_url": "https://no-file-club.example",
            },
        )
        assert resp.status_code in (301, 302, 303, 307, 308)
        from mediahub.web.club_profile import list_profiles

        profs = [p for p in list_profiles() if p.display_name == "No-File Club"]
        assert len(profs) == 1
        assert profs[0].brand_guidelines == {}
        assert profs[0].brand_guidelines_filename == ""

    def test_setup_page_has_optional_upload_field(self, gated_client):
        """The setup page must render the upload card with no `required`
        attribute on the file input — the upload is additive, not a
        replacement for the existing identity/website/social inputs."""
        c, _ = gated_client
        resp = c.get("/organisation/setup")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'name="brand_guidelines_file"' in body
        assert 'enctype="multipart/form-data"' in body
        # Card label must say it's optional
        assert "Upload a document with your brand guidelines" in body
        assert "optional" in body.lower()
        # The file input itself must NOT be required
        upload_idx = body.find('name="brand_guidelines_file"')
        # Look at the entire <input ...> tag for that field
        tag_start = body.rfind("<input", 0, upload_idx)
        tag_end = body.find(">", upload_idx) + 1
        upload_tag = body[tag_start:tag_end]
        assert " required" not in upload_tag, "brand_guidelines_file must be optional, not required"

    def test_active_org_api_reports_pinned_profile(
        self,
        gated_client,
        monkeypatch,
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
            profile_id="x",
            display_name="Some Club",
            brand_voice_summary="A community club that celebrates effort.",
        )
        assert p.is_ready() is True

    def test_voice_examples_make_ready(self):
        from mediahub.web.club_profile import ClubProfile

        p = ClubProfile(
            profile_id="x",
            display_name="Some Club",
            voice_examples=["a", "b", "c"],
        )
        assert p.is_ready() is True

    def test_voice_profile_makes_ready(self):
        from mediahub.web.club_profile import ClubProfile

        p = ClubProfile(
            profile_id="x",
            display_name="Some Club",
            voice_profile={"preferred_swimmer_address": "first_name"},
        )
        assert p.is_ready() is True
