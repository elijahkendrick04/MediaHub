"""UI i18n wiring in _layout (1.24) — <html lang>, locale resolution, Welsh nav.

The catalogue itself is covered by test_ui_catalogue; this pins that the page
chrome actually resolves and renders the locale.
"""

from __future__ import annotations

import re

import pytest


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.web as wm
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="en-club", display_name="EN Club", language="en"))
    save_profile(ClubProfile(profile_id="cy-club", display_name="CY Club", language="cy"))

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"
    return app


def _lang(html: str) -> str:
    return re.search(r'<html lang="([^"]+)"', html).group(1)


class TestLocaleResolution:
    def test_default_is_english(self, app):
        html = app.test_client().get("/").get_data(as_text=True)
        assert _lang(html) == "en"
        assert ">Home</a>" in html
        assert "Hafan" not in html

    def test_lang_query_override_to_welsh(self, app):
        html = app.test_client().get("/?lang=cy").get_data(as_text=True)
        assert _lang(html) == "cy"
        assert ">Hafan</a>" in html

    def test_lang_override_is_sticky_for_the_session(self, app):
        client = app.test_client()
        client.get("/?lang=cy")  # pins ui_lang in the session
        html = client.get("/").get_data(as_text=True)  # no ?lang this time
        assert _lang(html) == "cy"
        assert "Hafan" in html

    def test_unknown_lang_falls_back_to_english(self, app):
        html = app.test_client().get("/?lang=klingon").get_data(as_text=True)
        assert _lang(html) == "en"

    def test_welsh_org_gets_welsh_ui(self, app):
        client = app.test_client()
        with client.session_transaction() as s:
            s["active_profile_id"] = "cy-club"
        html = client.get("/").get_data(as_text=True)
        assert _lang(html) == "cy"
        assert "Hafan" in html  # nav localised from the org's caption language

    def test_english_org_gets_english_ui(self, app):
        client = app.test_client()
        with client.session_transaction() as s:
            s["active_profile_id"] = "en-club"
        html = client.get("/").get_data(as_text=True)
        assert _lang(html) == "en"
        assert ">Home</a>" in html
