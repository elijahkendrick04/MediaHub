"""F-3 — operator env-var names must not leak into customer-facing copy.

A hosted-SaaS customer has no shell, yet the UI told them to set env vars: a
stalled crawl named MEDIAHUB_RESULTS_FETCH_TIMEOUT_S; the audio page embedded
MEDIAHUB_REEL_MUSIC_LIBRARY / MEDIAHUB_AUDIO_LIBRARY_DIR and tagged voices
"(local)"/"(online)"; the image panel named MEDIAHUB_IMAGINE_LOCAL_ENDPOINT.
Each is now customer-relevant copy; env-var remediation stays operator-side.
"""

from __future__ import annotations

import pathlib

import pytest

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


@pytest.fixture
def client(web_module, monkeypatch):
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    app = web_module.create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "club-a"
    return c


def test_customer_env_var_names_gone_from_source():
    for var in (
        "MEDIAHUB_RESULTS_FETCH_TIMEOUT_S",
        "MEDIAHUB_REEL_MUSIC_LIBRARY",
        "MEDIAHUB_AUDIO_LIBRARY_DIR",
        "MEDIAHUB_IMAGINE_LOCAL_ENDPOINT",
    ):
        assert var not in _SRC, f"{var} still referenced in web.py customer copy"


def test_audio_page_uses_customer_copy_and_built_in_labels(client):
    html = client.get("/settings/audio").get_data(as_text=True)
    assert "Upload your licensed tracks" in html
    # Voice tags read "built-in"/"premium", not deployment "(local)/(online)".
    assert "(built-in)" in html or "(premium)" in html
    assert "(local)" not in html
    assert "(online)" not in html
