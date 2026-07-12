"""Web surface for the typography system (roadmap 1.9).

The settings page (catalogue browse, AI pairing, custom-font upload with licence
attestation, remove) and the renderer's custom-font injection. Org-scoped to the
active profile (no caller-supplied profile_id ⇒ no IDOR); the woff2 subsetting
paths skip cleanly where fontTools/brotli are absent.
"""
from __future__ import annotations

import importlib
import io

import pytest

from mediahub.typography import font_intake as fi


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, tmp_path


def _signin(client, profile_id="alpha", name="Alpha SC"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=profile_id, display_name=name))
    client.post("/api/organisation/active", data={"profile_id": profile_id})


needs_woff2 = pytest.mark.skipif(
    not fi.is_font_tooling_available(), reason="fontTools + brotli (woff2) not installed"
)


def _ttf(family="Club Brand", weight=700, **kw):
    from tests.test_font_intake import build_ttf

    return build_ttf(family, weight=weight, **kw)


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #
class TestPage:
    def test_settings_tile_present(self, app_env):
        app, _ = app_env
        with app.test_client() as c:
            _signin(c)
            body = c.get("/settings").get_data(as_text=True)
        assert "Typography &amp; fonts" in body or "Typography & fonts" in body

    def test_section_without_profile_prompts_signin(self, app_env):
        app, _ = app_env
        with app.test_client() as c:
            body = c.get("/settings/typography").get_data(as_text=True)
        # The empty state is directive: it names the missing club and offers a
        # one-click path to set one up.
        assert "No club yet" in body
        assert "/organisation/setup" in body

    def test_section_with_profile_shows_catalogue_and_upload(self, app_env):
        app, _ = app_env
        with app.test_client() as c:
            _signin(c)
            resp = c.get("/settings/typography")
            body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "Font catalogue" in body and "Anton" in body and "JetBrains Mono" in body
        assert "Upload font" in body and "licensed to embed this font" in body
        assert "AI font pairing" in body and "Text effects" in body
        # never a CDN reference on the page
        assert "fonts.googleapis.com" not in body and "fonts.gstatic.com" not in body


# --------------------------------------------------------------------------- #
# Upload / remove
# --------------------------------------------------------------------------- #
class TestUploadFlow:
    def test_upload_without_profile_redirects(self, app_env):
        app, _ = app_env
        with app.test_client() as c:
            resp = c.post("/settings/typography/font/upload")
        assert resp.status_code == 302

    def test_upload_requires_attestation(self, app_env):
        app, _ = app_env
        with app.test_client() as c:
            _signin(c)
            resp = c.post(
                "/settings/typography/font/upload",
                data={"role": "display", "font_file": (io.BytesIO(b"x" * 64), "f.ttf")},
            )
        assert resp.status_code == 302 and "status=no-attest" in resp.headers["Location"]

    def test_upload_rejects_garbage_with_attestation(self, app_env):
        app, _ = app_env
        with app.test_client() as c:
            _signin(c)
            resp = c.post(
                "/settings/typography/font/upload",
                data={"role": "display", "attest": "1",
                      "font_file": (io.BytesIO(b"not a font"), "f.ttf")},
            )
        assert resp.status_code == 302 and "status=bad-font" in resp.headers["Location"]

    @needs_woff2
    def test_upload_happy_path_and_appears_in_list(self, app_env):
        app, _ = app_env
        with app.test_client() as c:
            _signin(c, profile_id="club-x")
            resp = c.post(
                "/settings/typography/font/upload",
                data={"role": "display", "attest": "1",
                      "font_file": (io.BytesIO(_ttf("Manchester Sans")), "brand.ttf")},
            )
            assert "status=font-added" in resp.headers["Location"]
            body = c.get("/settings/typography").get_data(as_text=True)
        assert "Manchester Sans" in body and "Remove" in body
        # stored under this org only
        assert [r.family for r in fi.list_fonts("club-x")] == ["Manchester Sans"]
        assert fi.list_fonts("other") == []

    @needs_woff2
    def test_uploaded_family_name_is_escaped_in_list(self, app_env):
        app, _ = app_env
        with app.test_client() as c:
            _signin(c, profile_id="club-x")
            c.post(
                "/settings/typography/font/upload",
                data={"role": "display", "attest": "1",
                      "font_file": (io.BytesIO(_ttf("<script>evil")), "x.ttf")},
            )
            body = c.get("/settings/typography").get_data(as_text=True)
        assert "<script>evil" not in body  # escaped, never raw

    @needs_woff2
    def test_remove_font(self, app_env):
        app, _ = app_env
        with app.test_client() as c:
            _signin(c, profile_id="club-x")
            c.post(
                "/settings/typography/font/upload",
                data={"role": "display", "attest": "1",
                      "font_file": (io.BytesIO(_ttf("Temp Face")), "x.ttf")},
            )
            slug = fi.list_fonts("club-x")[0].slug
            resp = c.post(f"/settings/typography/font/{slug}/remove")
        assert "status=font-removed" in resp.headers["Location"]
        assert fi.list_fonts("club-x") == []


# --------------------------------------------------------------------------- #
# AI pairing (honest error, no provider configured)
# --------------------------------------------------------------------------- #
class TestPairing:
    def test_pair_without_provider_is_honest(self, app_env):
        # H-16: the honest no-provider error is the standard plain wording —
        # raw exception text goes to the server log only, never the page.
        app, _ = app_env
        with app.test_client() as c:
            _signin(c)
            resp = c.post("/settings/typography/pair", data={"mood": "bold"})
            body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "AI suggestions are unavailable on this deployment." in body

    def test_pair_renders_suggestion_when_provider_present(self, app_env, monkeypatch):
        app, _ = app_env
        # Stub the AI layer so the route's success branch is exercised offline.
        from mediahub.brand import design_tokens as dt

        monkeypatch.setattr(
            dt, "ai_type_pairing",
            lambda ctx: {"pairing": "anton-inter", "headline_family": "Anton",
                         "body_family": "Inter", "numeral_family": "JetBrains Mono",
                         "reason": "Bold and clean.", "corrected": False, "source": "ai"},
        )
        with app.test_client() as c:
            _signin(c)
            body = c.post("/settings/typography/pair", data={"mood": "bold"}).get_data(as_text=True)
        assert "Suggested pairing" in body and "Anton" in body and "Bold and clean." in body


# --------------------------------------------------------------------------- #
# Renderer custom-font injection
# --------------------------------------------------------------------------- #
class TestRenderInjection:
    def _brief(self, profile_id):
        from mediahub.creative_brief.generator import CreativeBrief

        return CreativeBrief(
            id="c", content_item_id="ci", profile_id=profile_id, achievement_summary="",
            objective="", primary_hook="", confidence_label="", tone="",
            layout_template="big_number_dominant", inspiration_pattern_id="", image_treatment="",
            text_hierarchy=[], brand_instructions="", sponsor_instructions=None,
            sourced_asset_ids=[], safety_notes=[], why_this_design="",
            text_layers={"athlete_surname": "SMITH", "result_value": "1:42"},
            palette={"primary": "#0A1A3F", "secondary": "#F5C518"}, format_priority=[],
        )

    def _base_css(self, brief):
        from mediahub.brand.kit import BrandKit
        from mediahub.graphic_renderer import render as r

        repl = r._common_replacements(
            brief, 1080, 1350, BrandKit.generic_default(),
            athlete_data_uri=None, logo_block="", result_chip="", sponsor_block="",
        )
        return repl["BASE_CSS"]

    @needs_woff2
    def test_uploaded_font_inlined_into_base_css(self, app_env):
        app, _ = app_env  # noqa: F841 (DATA_DIR env is what matters)
        fi.intake_font(_ttf("Inline Face", weight=600), profile_id="club-r", role="display")
        css = self._base_css(self._brief("club-r"))
        assert "org custom fonts (1.9)" in css and "club-club-r-inline-face" in css
        assert "file://" in css and "googleapis" not in css

    def test_no_uploads_render_is_byte_identical(self, app_env):
        # A profile with no uploads gets NO custom @font-face block, so its font
        # CSS is identical to before 1.9 (cache keys unaffected).
        app, _ = app_env  # noqa: F841
        assert "org custom fonts (1.9)" not in self._base_css(self._brief("club-empty"))
        assert fi.font_face_css(fi.list_fonts("club-empty"), file_uri=True) == ""
