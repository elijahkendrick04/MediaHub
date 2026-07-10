"""G-11 — setting "Caption language" must not silently flip the interface.

With no ?lang / session pin, `_ui_locale()` used to fall back to the org's
primary CAPTION language whenever that locale shipped a UI catalogue — so a
club choosing "Cymraeg (Welsh)" as its caption language got the whole app
chrome switched to Welsh without asking.

The fallback is removed: the interface language is driven only by the explicit
controls — a `?lang=` override or the `ui_lang` session pin set by the C-16
interface-language switcher — defaulting to English. The Caption-language
picker carries a muted note pointing at the Interface language control.
"""

from __future__ import annotations

import importlib
import re

import pytest


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="cy-club", display_name="CY Club", language="cy"))
    save_profile(
        ClubProfile(profile_id="ency-club", display_name="Bilingual Club", language="en+cy")
    )

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"
    return app


def _lang(html: str) -> str:
    return re.search(r'<html lang="([^"]+)"', html).group(1)


def test_welsh_caption_language_does_not_flip_interface(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s["active_profile_id"] = "cy-club"
    html = client.get("/").get_data(as_text=True)
    assert _lang(html) == "en"
    assert "Hafan" not in html  # nav stays English


def test_bilingual_caption_language_does_not_flip_interface(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s["active_profile_id"] = "ency-club"
    html = client.get("/").get_data(as_text=True)
    assert _lang(html) == "en"


def test_explicit_controls_still_work(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s["active_profile_id"] = "cy-club"
    # ?lang= override still wins and pins…
    html = client.get("/?lang=cy").get_data(as_text=True)
    assert _lang(html) == "cy"
    html = client.get("/").get_data(as_text=True)
    assert _lang(html) == "cy"
    # …and the C-16 switcher off-ramps back to English.
    client.post("/settings/interface-language", data={"ui_lang": "en"})
    html = client.get("/").get_data(as_text=True)
    assert _lang(html) == "en"


def test_caption_language_picker_carries_decoupling_note(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s["active_profile_id"] = "cy-club"
    html = client.get("/organisation").get_data(as_text=True)
    assert "This affects generated captions only" in html
    assert "Interface language control" in html
