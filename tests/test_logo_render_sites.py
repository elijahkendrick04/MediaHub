"""Stage F — integration tests for the three logo-render sites.

Verifies that the existing <img> sites in web.py have been migrated
through _logo_chip_html() and produce the expected chip wrappers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def app_client(client, web_module):
    import mediahub.web.club_profile as cp

    return client, web_module, cp


def _seed_profile(
    cp_module,
    *,
    brand_logo_url=None,
    primary="#06D6A0",
    brand_voice_summary="Concise, energetic.",
    with_brand_extracted=True,
):
    from mediahub.web.club_profile import ClubProfile

    pid = "logo-test"
    prof = ClubProfile(profile_id=pid, display_name="Logo Test Club")
    prof.brand_primary = primary
    prof.brand_voice_summary = brand_voice_summary
    prof.brand_keywords = ["club"]
    if with_brand_extracted:
        prof.brand_palette_extracted = {"primary": primary, "secondary": "#0E2A47"}
    if brand_logo_url:
        prof.brand_logo_url = brand_logo_url
    prof.brand_kit = {
        "profile_id": pid,
        "display_name": "Logo Test Club",
        "primary_colour": primary,
        "secondary_colour": "#0E2A47",
    }
    cp_module.save_profile(prof)
    return prof


class TestLogoChipCSSPresent:
    def test_chip_class_in_rendered_css(self, app_client):
        client, _, _ = app_client
        body = client.get("/status").get_data(as_text=True)
        assert ".mh-logo-chip" in body
        # Spot-check the chip background uses the neutral-0 primitive.
        assert "var(--mh-prim-neutral-0)" in body
        # And the elevation token.
        assert "var(--mh-elevation-1)" in body


class TestDetectedLogoSite:
    """The 'Detected logo' preview on the /organisation page brand-DNA
    capture card (web.py site ~10914)."""

    def test_detected_logo_wrapped_in_chip(self, app_client):
        client, wm, cp = app_client
        prof = _seed_profile(cp, brand_logo_url="https://example.com/logo.png", primary="#06D6A0")
        with client.session_transaction() as sess:
            sess["active_profile_id"] = prof.profile_id
        # The "Detected logo" preview lives on /organisation, not
        # /organisation/setup. The setup route shows the captured-brand
        # card with palette swatches; the org-summary route shows the
        # rendered logo via _logo_chip_html.
        body = client.get("/organisation").get_data(as_text=True)
        assert 'alt="Detected logo"' in body, "Detected logo img not in rendered /organisation page"
        # The img is served FIRST-PARTY via the mirror route, never the raw
        # external URL: the CSP pins img-src 'self', so a cross-origin <img>
        # renders as a broken image. (The external URL still appears in the
        # page's hidden brand_logo_url form input — so assert on the img src,
        # not bare presence.)
        assert "/organisation/logo-test/brand-logo" in body
        assert 'src="https://example.com/logo.png"' not in body

    def test_no_logo_no_chip(self, app_client):
        """When the profile has no brand_logo_url, no chip render is
        emitted for the detected logo (the field renders empty)."""
        client, wm, cp = app_client
        prof = _seed_profile(cp, brand_logo_url=None)
        with client.session_transaction() as sess:
            sess["active_profile_id"] = prof.profile_id
        body = client.get("/organisation").get_data(as_text=True)
        # No "Detected logo" alt-text since there's no img.
        assert 'alt="Detected logo"' not in body


class TestProfileCardSite:
    """Profile cards on /sign-in (web.py site ~11288). Stage F forces
    chip mode for visual grid consistency."""

    def test_profile_card_logo_uses_chip(self, app_client):
        client, wm, cp = app_client
        prof = _seed_profile(
            cp,
            brand_logo_url="https://example.com/club.png",
            primary="#A30D2D",
        )
        # No need to pin a session — /sign-in shows ALL profiles.
        body = client.get("/sign-in").get_data(as_text=True)
        # The logo renders as the unified elevated chip (fixed-size, framed) for
        # grid consistency.
        assert (
            "mh-logo-chip mh-logo-chip--lg" in body
        ), "profile-card logo not rendered as the elevated .mh-logo-chip"
        # A detected (external) logo is served FIRST-PARTY via the mirror route's
        # KEYED silhouette — never the raw cross-origin URL, which the CSP
        # img-src 'self' would block (broken image). The chip carries the keyed
        # ?bg=1&chip=1 source and a built-in initials fallback.
        assert "/organisation/logo-test/brand-logo" in body
        assert "bg=1" in body and "chip=1" in body
        assert "https://example.com/club.png" not in body
        assert "mh-logo-chip__initials" in body


class TestRenderHelper:
    """Direct tests of _logo_chip_html()."""

    def test_helper_produces_chip_by_default(self, app_client):
        client, wm, _ = app_client
        with wm.app_or_helper_ctx() if hasattr(wm, "app_or_helper_ctx") else _request_context(wm):
            html = wm._logo_chip_html("/test.png", "alt")
            assert "mh-logo-chip" in html
            assert 'src="/test.png"' in html
            assert 'alt="alt"' in html

    def test_force_bare(self, app_client):
        _, wm, _ = app_client
        with _request_context(wm):
            html = wm._logo_chip_html("/x.png", "alt", force_bare=True)
            assert "mh-logo-chip" not in html
            assert "<img" in html

    def test_force_chip_overrides_dominant(self, app_client):
        _, wm, _ = app_client
        # Even with a high-contrast dominant (would be bare), force_chip
        # wraps it in a chip.
        with _request_context(wm):
            html = wm._logo_chip_html(
                "/x.png",
                "alt",
                dominant_hex="#FFFFFF",
                surface_hex="#0A0B11",
                force_chip=True,
            )
            assert "mh-logo-chip" in html

    def test_alt_text_escaped(self, app_client):
        _, wm, _ = app_client
        with _request_context(wm):
            html = wm._logo_chip_html("/x.png", "<img onerror=alert(1)>")
            # The brackets should be escaped (cannot inject HTML
            # via alt text).
            assert "<img onerror=alert(1)>" not in html or "&lt;" in html


def _request_context(wm_module):
    """Helper to create a Flask request context for testing the
    chip helper in isolation."""
    import os, tempfile

    os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
    app = wm_module.create_app()
    return app.test_request_context()
