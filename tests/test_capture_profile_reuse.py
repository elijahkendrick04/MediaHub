"""tests/test_capture_profile_reuse.py

Two follow-ups to the "signed-out by default" change:

1. /organisation/setup/capture must UPDATE the user's real profile when
   re-run, not orphan a "<slug>-<uuid>" clone. Making the default session
   signed-out (no auto-adopted org) exposed a latent bug: the capture
   route only reused an existing profile id when a session was pinned;
   otherwise it slugged the org name and, finding a profile already at
   that slug, appended a uuid suffix and created a CLONE. The freshly
   extracted colours + uploaded logos landed on the orphan while the
   user's real profile stayed empty — so after signing back in, "the
   logos aren't saved" and "the colours aren't identified".

2. The org logo is surfaced in the signed-in chrome (the active-org
   chip) the same way the brand colours are.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

# A tiny valid 1x1 PNG.
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f1f0000000049454e44ae426082"
)


@pytest.fixture(autouse=True)
def _no_llm_keys(monkeypatch):
    # No LLM keys: capture short-circuits (no network) but the profile
    # resolution + logo persistence we're testing still run. Provider keys are
    # read live at call time (not at web.py import), so pinning them empty here
    # is all this file needs on top of the canonical DATA_DIR-isolated ``app``
    # fixture from tests/conftest.py.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")


def _seed(display_name="City of Chester SC", profile_id="city-of-chester-sc"):
    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(
        profile_id=profile_id,
        display_name=display_name,
        brand_voice_summary="Friendly competitive club.",
    ))


def _capture(client, display_name, *, pin=None, with_logo=True):
    if pin:
        with client.session_transaction() as s:
            s["active_profile_id"] = pin
    data = {"display_name": display_name, "country": "United Kingdom"}
    if with_logo:
        data["brand_logos"] = (io.BytesIO(_PNG), "crest.png")
    return client.post(
        "/organisation/setup/capture",
        data=data,
        content_type="multipart/form-data",
        follow_redirects=False,
    )


class TestCaptureReusesProfile:
    def test_signed_out_recapture_updates_original_not_a_clone(self, app):
        """The regression: re-running capture while signed OUT (now the
        default) must update the same-named profile, not clone it."""
        _seed()
        from mediahub.web.club_profile import list_profiles, load_profile
        with app.test_client() as c:
            _capture(c, "City of Chester SC", pin=None, with_logo=True)
        ids = sorted(p.profile_id for p in list_profiles())
        assert ids == ["city-of-chester-sc"], f"expected no clone, got {ids}"
        assert len(load_profile("city-of-chester-sc").brand_logos or []) == 1

    def test_signed_in_recapture_still_updates_original(self, app):
        _seed()
        from mediahub.web.club_profile import list_profiles, load_profile
        with app.test_client() as c:
            _capture(c, "City of Chester SC", pin="city-of-chester-sc",
                     with_logo=True)
        ids = sorted(p.profile_id for p in list_profiles())
        assert ids == ["city-of-chester-sc"]
        assert len(load_profile("city-of-chester-sc").brand_logos or []) == 1

    def test_capture_pins_the_reused_profile(self, app):
        """After capture the user is signed in to the profile that was
        updated — not left signed out or pinned to a clone."""
        _seed()
        with app.test_client() as c:
            _capture(c, "City of Chester SC", pin=None, with_logo=False)
            with c.session_transaction() as s:
                assert s.get("active_profile_id") == "city-of-chester-sc"

    def test_different_org_same_slug_is_not_clobbered(self, app):
        """A genuinely different org whose name slugs to an existing id
        must NOT overwrite it — it gets a suffixed id instead."""
        _seed(display_name="Manchester Swimming",
              profile_id="manchester-swimming")
        from mediahub.web.club_profile import list_profiles, load_profile
        with app.test_client() as c:
            # Slugs to "manchester-swimming" but is a different name.
            _capture(c, "Manchester, Swimming!", pin=None, with_logo=False)
        ids = sorted(p.profile_id for p in list_profiles())
        # Original is untouched...
        assert load_profile("manchester-swimming").display_name == "Manchester Swimming"
        # ...and the new org got a distinct, suffixed id.
        assert any(i.startswith("manchester-swimming-") for i in ids), ids


class TestSignedInNavShowsLogo:
    def test_nav_renders_uploaded_logo_when_signed_in(self, app):
        from mediahub.web.club_profile import ClubProfile, save_profile
        save_profile(ClubProfile(
            profile_id="alpha", display_name="Alpha SC",
            brand_voice_summary="Friendly.",
            brand_logos=[{"logo_id": "abc123def456",
                          "original_filename": "crest.png"}],
        ))
        with app.test_client() as c:
            with c.session_transaction() as s:
                s["active_profile_id"] = "alpha"
            body = c.get("/").get_data(as_text=True)
        # The active-org chip carries the per-profile logo serve URL.
        assert "active-org-chip" in body
        assert "/organisation/setup/logo/abc123def456" in body

    def test_nav_falls_back_to_captured_logo_url(self, app):
        from mediahub.web.club_profile import ClubProfile, save_profile
        save_profile(ClubProfile(
            profile_id="beta", display_name="Beta AC",
            brand_voice_summary="Sharp.",
            brand_logo_url="https://example.com/logo.png",
        ))
        with app.test_client() as c:
            with c.session_transaction() as s:
                s["active_profile_id"] = "beta"
            body = c.get("/").get_data(as_text=True)
        # The detected website logo is served FIRST-PARTY via the mirror
        # route, never the raw external URL: the CSP pins img-src 'self', so a
        # cross-origin <img> would render as a broken image in the chrome.
        assert "/organisation/beta/brand-logo" in body
        assert "https://example.com/logo.png" not in body

    def test_no_logo_chip_when_signed_out(self, app):
        _seed()
        with app.test_client() as c:
            body = c.get("/").get_data(as_text=True)
        # The chip ELEMENT is absent when signed out (the CSS rule for
        # #active-org-chip always ships in the stylesheet, so assert on
        # the rendered element, not the bare class name).
        assert 'id="active-org-chip"' not in body
