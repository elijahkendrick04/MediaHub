"""tests/test_newsletter_renderer.py — Phase 1.2 newsletter output.

Pins three properties of the email-export pipeline:

  1. The renderer produces a standalone, sender-safe HTML body — full
     <!DOCTYPE>, inline styles, table-based outer scaffold — so the
     output is usable in real email clients (Gmail / Outlook / Apple
     Mail), not just inside the MediaHub UI.
  2. Org branding (display name, primary colour, logo) reaches the
     rendered email — without requiring an extra config step.
  3. ZIP packaging contains both formats + a README so the user can
     download once and pick the format they need.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.brand.newsletter_renderer import (  # noqa: E402
    render_email_html,
    render_plaintext,
    render_zip,
    safe_filename_for,
)
from mediahub.web.club_profile import ClubProfile  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def artefact():
    """A Turn-Into `parent_newsletter` artefact shape."""
    return {
        "type": "parent_newsletter",
        "title": "Winter Champs — meet update",
        "captions": {
            "default": (
                "Dear parents and supporters,\n\n"
                "A quick update from Winter Champs. Standout moments "
                "included Emma's first sub-60 in the 100 free and "
                "three personal bests from our junior squad. Thank "
                "you to everyone who travelled and cheered.\n\n"
                "Please reach out if you'd like more detail on any "
                "individual swim."
            ),
            "plain_text": (
                "Dear parents and supporters,\n\n"
                "A quick update from Winter Champs. Standout moments "
                "included Emma's first sub-60 in the 100 free and "
                "three personal bests from our junior squad. Thank "
                "you to everyone who travelled and cheered.\n\n"
                "Please reach out if you'd like more detail on any "
                "individual swim."
            ),
        },
        "cards": [{"headline": "Winter Champs — meet update", "body": "..."}],
    }


@pytest.fixture
def branded_profile():
    return ClubProfile(
        profile_id="city-aquatics",
        display_name="City Aquatics",
        brand_primary="#0066CC",
        brand_logo_url="https://city-aquatics.example/logo.png",
    )


@pytest.fixture
def meet_summary():
    return {
        "name": "Winter Championships",
        "start_date": "2026-01-20",
        "venue": "Manchester Aquatics Centre",
    }


# ---------------------------------------------------------------------------
# 1. Sender-safe HTML body
# ---------------------------------------------------------------------------

class TestSenderSafeHtml:
    def test_full_html_doctype(self, artefact, branded_profile, meet_summary):
        html = render_email_html(artefact, profile=branded_profile, meet_summary=meet_summary)
        assert html.lstrip().startswith("<!DOCTYPE html>")
        assert "<html" in html
        assert "</html>" in html
        assert "<head>" in html
        assert "<body" in html

    def test_meta_viewport_present(self, artefact, branded_profile, meet_summary):
        """Required for responsive email clients."""
        html = render_email_html(artefact, profile=branded_profile, meet_summary=meet_summary)
        assert 'name="viewport"' in html

    def test_styles_are_inline(self, artefact, branded_profile, meet_summary):
        """Email clients aggressively strip <style> blocks — guard
        against accidentally regressing to class-based styling."""
        html = render_email_html(artefact, profile=branded_profile, meet_summary=meet_summary)
        # No <style> blocks
        assert "<style" not in html
        # Multiple style="..." attributes present
        assert html.count('style="') >= 5

    def test_table_based_outer_scaffold(self, artefact, branded_profile, meet_summary):
        """Outlook in particular needs a table wrapper, not a div."""
        html = render_email_html(artefact, profile=branded_profile, meet_summary=meet_summary)
        assert "<table" in html
        assert 'role="presentation"' in html

    def test_body_paragraphs_rendered(self, artefact, branded_profile, meet_summary):
        html = render_email_html(artefact, profile=branded_profile, meet_summary=meet_summary)
        assert "first sub-60" in html
        # Each paragraph wrapped in <p>
        assert html.count("<p ") >= 2

    def test_html_escapes_user_content(self):
        """Anything that came from the artefact must be HTML-escaped —
        the artefact text is partly LLM-generated, and an injected
        <script> would otherwise render in the preview."""
        dangerous = {
            "captions": {
                "plain_text": "Hi <script>alert(1)</script> and & here.",
            },
        }
        html = render_email_html(dangerous)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "&amp;" in html


# ---------------------------------------------------------------------------
# 2. Branding flows through
# ---------------------------------------------------------------------------

class TestBrandingReachesEmail:
    def test_display_name_in_header(self, artefact, branded_profile, meet_summary):
        html = render_email_html(artefact, profile=branded_profile, meet_summary=meet_summary)
        assert "City Aquatics" in html

    def test_meet_title_in_header(self, artefact, branded_profile, meet_summary):
        html = render_email_html(artefact, profile=branded_profile, meet_summary=meet_summary)
        assert "Winter Championships" in html
        assert "Manchester Aquatics Centre" in html

    def test_primary_colour_in_header_band(self, artefact, branded_profile, meet_summary):
        html = render_email_html(artefact, profile=branded_profile, meet_summary=meet_summary)
        assert "#0066cc" in html.lower()

    def test_logo_img_when_present(self, artefact, branded_profile, meet_summary):
        html = render_email_html(artefact, profile=branded_profile, meet_summary=meet_summary)
        assert "https://city-aquatics.example/logo.png" in html
        assert "<img " in html

    def test_no_logo_no_img(self, artefact, meet_summary):
        unbranded = ClubProfile(
            profile_id="x", display_name="No-Logo Club", brand_primary="#444444",
        )
        html = render_email_html(artefact, profile=unbranded, meet_summary=meet_summary)
        assert "<img " not in html
        assert "No-Logo Club" in html

    def test_invalid_brand_colour_falls_back_to_default(self, artefact, meet_summary):
        broken = ClubProfile(
            profile_id="x", display_name="Broken Hex Club",
            brand_primary="not-a-colour",
        )
        html = render_email_html(artefact, profile=broken, meet_summary=meet_summary)
        # Default fallback is the dark navy
        assert "#0a2540" in html.lower()


# ---------------------------------------------------------------------------
# 3. Plaintext
# ---------------------------------------------------------------------------

class TestPlaintext:
    def test_returns_clean_body(self, artefact):
        text = render_plaintext(artefact)
        assert "Dear parents" in text
        assert "first sub-60" in text
        # No HTML in plaintext output
        assert "<" not in text

    def test_collapses_excess_blank_lines(self):
        artefact = {"captions": {"plain_text": "Para 1.\n\n\n\nPara 2."}}
        text = render_plaintext(artefact)
        assert "\n\n\n" not in text
        assert "Para 1." in text and "Para 2." in text

    def test_handles_missing_caption(self):
        assert render_plaintext({}) == ""
        assert render_plaintext({"captions": {}}) == ""


# ---------------------------------------------------------------------------
# 4. ZIP packaging
# ---------------------------------------------------------------------------

class TestZipExport:
    def test_zip_contains_both_formats(self, artefact, branded_profile, meet_summary):
        data = render_zip(artefact, profile=branded_profile, meet_summary=meet_summary)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            assert any(n.endswith(".html") for n in names)
            assert any(n.endswith(".txt") for n in names)
            assert "README.txt" in names
            # Spot-check the contents
            html = zf.read([n for n in names if n.endswith(".html")][0]).decode("utf-8")
            assert "City Aquatics" in html

    def test_zip_filename_slug_is_clean(self, artefact, branded_profile, meet_summary):
        data = render_zip(
            artefact, profile=branded_profile, meet_summary=meet_summary,
            base_name="winter-champs-newsletter",
        )
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            assert "winter-champs-newsletter.html" in names
            assert "winter-champs-newsletter.txt" in names


class TestSafeFilenameFor:
    def test_normal(self):
        assert safe_filename_for("Winter Championships 2026") == "winter-championships-2026"

    def test_special_chars(self):
        assert safe_filename_for("Spring/Summer Champs (2026)!") == "spring-summer-champs-2026"

    def test_empty_falls_back(self):
        assert safe_filename_for("") == "newsletter"
        assert safe_filename_for(None) == "newsletter"
