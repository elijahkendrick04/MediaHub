"""Stage G3 — newsletter renderer reads from the theme store.

render_email_html() should pick the LIGHT scheme's primary role
when a theme is on disk for the profile. The light scheme is used
because emails are viewed on white email-body backgrounds.

Falls back to profile.brand_primary when no theme on disk; falls
back to the Stage A default (#0A2540) when neither source exists.
"""
from __future__ import annotations

import pytest

from mediahub.brand.newsletter_renderer import (
    _resolve_email_primary,
    render_email_html,
)


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.theming.theme_store import _read_cached
    _read_cached.cache_clear()
    return tmp_path


def _seed_theme(pid, primary):
    from mediahub.brand.kit import BrandKit
    kit = BrandKit(profile_id=pid, display_name=f"Test {pid}",
                   primary_colour=primary)
    return kit.ensure_derived_palette()


class FakeProfile:
    def __init__(self, profile_id="", brand_primary="",
                 display_name="", brand_logo_url=""):
        self.profile_id = profile_id
        self.brand_primary = brand_primary
        self.display_name = display_name
        self.brand_logo_url = brand_logo_url


class TestResolveEmailPrimary:
    def test_uses_light_scheme_when_theme_on_disk(self, isolated_data_dir):
        theme = _seed_theme("email-test", "#A30D2D")
        prof = FakeProfile(profile_id="email-test", brand_primary="#A30D2D")
        result = _resolve_email_primary(prof)
        # The light-scheme primary, not the raw brand hex.
        assert result.upper() == theme["roles"]["light"]["primary"].upper()

    def test_falls_back_to_brand_primary_without_theme(self, isolated_data_dir):
        prof = FakeProfile(profile_id="no-theme", brand_primary="#FF1234")
        # No theme on disk for this pid
        result = _resolve_email_primary(prof)
        assert result == "#ff1234"  # _safe_hex lowercases

    def test_falls_back_to_default_without_anything(self, isolated_data_dir):
        prof = FakeProfile()  # no profile_id, no brand_primary
        result = _resolve_email_primary(prof)
        # _safe_hex returns the fallback as-is; the canonical Stage A
        # default is upper-case.
        assert result.lower() == "#0a2540"

    def test_dict_profile_input(self, isolated_data_dir):
        theme = _seed_theme("dict-test", "#06D6A0")
        # Profile passed as a dict instead of an object
        result = _resolve_email_primary({
            "profile_id": "dict-test",
            "brand_primary": "#06D6A0",
        })
        assert result.upper() == theme["roles"]["light"]["primary"].upper()


class FakeProfileWithPalette(FakeProfile):
    """Profile that also carries confirmed palette dicts."""
    def __init__(self, *, brand_palette_manual=None,
                 brand_palette_extracted=None, **kw):
        super().__init__(**kw)
        self.brand_palette_manual = brand_palette_manual or {}
        self.brand_palette_extracted = brand_palette_extracted or {}


class TestConfirmedPrimaryBeatsTheme:
    """Regression for the off-brand email-header bug: a club's CONFIRMED
    primary must win over the MD3 theme-store derivation, which
    tone-shifts a navy #003C71 seed into a washed-out #426089."""

    def test_manual_primary_wins_over_theme(self, isolated_data_dir):
        theme = _seed_theme("manual-win", "#003C71")
        prof = FakeProfileWithPalette(
            profile_id="manual-win", brand_primary="#003C71",
            brand_palette_manual={"primary": "#003C71"},
        )
        result = _resolve_email_primary(prof)
        assert result == "#003c71"  # _safe_hex lowercases
        # Specifically NOT the tone-shifted theme primary.
        assert result.upper() != theme["roles"]["light"]["primary"].upper()

    def test_extracted_primary_wins_over_theme(self, isolated_data_dir):
        _seed_theme("extracted-win", "#003C71")
        prof = FakeProfileWithPalette(
            profile_id="extracted-win", brand_primary="#003C71",
            brand_palette_extracted={"primary": "#003C71"},
        )
        assert _resolve_email_primary(prof) == "#003c71"

    def test_theme_still_used_without_confirmed_palette(self, isolated_data_dir):
        # No manual/extracted → theme store remains the source (the
        # zero-drift fallback for clubs that never confirmed colours).
        theme = _seed_theme("no-confirm", "#003C71")
        prof = FakeProfile(profile_id="no-confirm", brand_primary="#003C71")
        assert _resolve_email_primary(prof).upper() == \
            theme["roles"]["light"]["primary"].upper()


class TestRenderEmailHTML:
    """End-to-end: the rendered HTML should carry the light primary
    in the header band's inline background style."""

    def _minimal_artefact(self):
        return {
            "captions": {"plain_text": "Hello swimmers.\n\nGreat meet!"},
            "title": "Saturday meet",
        }

    def test_header_band_uses_theme_primary(self, isolated_data_dir):
        theme = _seed_theme("e2e", "#A30D2D")
        prof = FakeProfile(profile_id="e2e", brand_primary="#A30D2D",
                           display_name="Test Club")
        html = render_email_html(self._minimal_artefact(), profile=prof)
        # The light primary should appear in the header band's
        # background. _safe_hex lowercases.
        expected = theme["roles"]["light"]["primary"].lower()
        assert f"background:{expected}" in html, (
            f"expected light primary {expected} in rendered email"
        )

    def test_header_falls_back_when_no_theme(self, isolated_data_dir):
        prof = FakeProfile(brand_primary="#FF8800",
                           display_name="No Theme Club")
        html = render_email_html(self._minimal_artefact(), profile=prof)
        assert "background:#ff8800" in html

    def test_render_doesnt_crash_with_no_profile(self, isolated_data_dir):
        html = render_email_html(self._minimal_artefact(), profile=None)
        assert "<!DOCTYPE html>" in html
        # Default primary in header — fallback is the Stage A default
        # (case may vary depending on _safe_hex internals).
        assert "background:#0a2540" in html.lower()


class TestPremailerInlining:
    """Emails must inline hex values into style="" attributes — the
    rendered HTML carries the resolved hex literally, not a CSS
    custom property reference."""

    def test_no_css_variables_in_output(self, isolated_data_dir):
        _seed_theme("inline-test", "#06D6A0")
        prof = FakeProfile(profile_id="inline-test", brand_primary="#06D6A0")
        html = render_email_html({"captions": {"plain_text": "Hi"}},
                                 profile=prof)
        # No var(--…) references in the email — email clients don't
        # support them. Stage G's Premailer-style inlining contract.
        assert "var(--" not in html, "email leaks CSS custom property"
