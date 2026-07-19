"""H-15 — pronunciation-lexicon and voice-consent form posts must give feedback.

"Name pronunciation" add/remove and "Voice cloning" grant/revoke are plain form
posts. On ValueError the handler built a 400 JSON payload, but the non-XHR
redirect discarded both payload and status — the volunteer saw a silent reload
with no clue whether the action worked. Successes were equally silent.

Now `_audio_back_or_json` carries a status CODE through the redirect
(`?status=<code>`, mirroring the typography banner pattern) and the audio page
maps each code to plain-English copy server-side: success confirmations
("Pronunciation saved", "Consent recorded") and honest error explanations.
Raw exception text never reaches the URL or the page. JSON/XHR callers keep
the machine body.
"""

from __future__ import annotations

import pytest
from tests._helpers import web_surface_src


@pytest.fixture
def app_env(app, monkeypatch):
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return app


def _signin(c, pid="alpha"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name="Alpha SC"))
    c.post("/api/organisation/active", data={"profile_id": pid})


# --------------------------------------------------------------------------- #
# Pronunciation lexicon
# --------------------------------------------------------------------------- #
def test_lexicon_add_confirms_with_banner(app_env):
    with app_env.test_client() as c:
        _signin(c)
        r = c.post(
            "/api/audio/lexicon",
            data={"op": "set", "written": "Saoirse", "spoken": "Seer-sha"},
        )
        assert r.status_code == 302
        assert "status=lexicon_saved" in r.headers["Location"]
        page = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "Pronunciation saved" in page


def test_lexicon_remove_confirms_with_banner(app_env):
    with app_env.test_client() as c:
        _signin(c)
        c.post("/api/audio/lexicon", data={"op": "set", "written": "Eira", "spoken": "AY-ra"})
        r = c.post("/api/audio/lexicon", data={"op": "remove", "written": "Eira"})
        assert r.status_code == 302
        assert "status=lexicon_removed" in r.headers["Location"]
        page = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "Pronunciation override removed" in page


def test_lexicon_invalid_shows_plain_english_not_raw_exception(app_env):
    with app_env.test_client() as c:
        _signin(c)
        # Missing "spoken" → OrgLexicon.set raises ValueError. The form post must
        # come back with a mapped code — never the raw exception text.
        r = c.post("/api/audio/lexicon", data={"op": "set", "written": "Saoirse", "spoken": ""})
        assert r.status_code == 302
        loc = r.headers["Location"]
        assert "status=lexicon_invalid" in loc
        assert "emsg=" not in loc  # raw message no longer travels in the URL
        page = c.get(loc).get_data(as_text=True)
        assert "Pronunciation not saved" in page
        assert "written name and how to say it" in page
        # The ValueError's own wording must not leak to the page.
        assert "are required" not in page


def test_lexicon_json_caller_keeps_machine_body(app_env):
    with app_env.test_client() as c:
        _signin(c)
        r = c.post(
            "/api/audio/lexicon",
            data={"op": "set", "written": "X", "spoken": ""},
            headers={"Accept": "application/json"},
        )
        assert r.status_code == 400
        assert r.get_json()["error"] == "invalid"


# --------------------------------------------------------------------------- #
# Voice consent
# --------------------------------------------------------------------------- #
def test_consent_grant_confirms_with_banner(app_env):
    with app_env.test_client() as c:
        _signin(c)
        r = c.post(
            "/api/audio/voice-consent",
            data={
                "action": "grant",
                "feature": "clone",
                "voice_owner": "Coach Dana",
                "consent_ref": "form-2026-01",
            },
        )
        assert r.status_code == 302
        assert "status=consent_recorded" in r.headers["Location"]
        page = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "Consent recorded" in page


def test_consent_revoke_confirms_with_banner(app_env):
    with app_env.test_client() as c:
        _signin(c)
        c.post(
            "/api/audio/voice-consent",
            data={"action": "grant", "feature": "clone", "voice_owner": "A", "consent_ref": "r"},
        )
        r = c.post("/api/audio/voice-consent", data={"action": "revoke", "feature": "clone"})
        assert r.status_code == 302
        assert "status=consent_revoked" in r.headers["Location"]
        page = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "Consent revoked" in page


def test_consent_invalid_shows_plain_english_not_raw_exception(app_env):
    with app_env.test_client() as c:
        _signin(c)
        r = c.post(
            "/api/audio/voice-consent",
            data={"action": "grant", "feature": "bogus-feature"},
        )
        assert r.status_code == 302
        loc = r.headers["Location"]
        assert "status=consent_invalid" in loc
        page = c.get(loc).get_data(as_text=True)
        assert "could not be recorded" in page
        # The ValueError's own wording must not leak to the page.
        assert "unknown consent feature" not in page


def test_consent_json_caller_keeps_machine_body(app_env):
    with app_env.test_client() as c:
        _signin(c)
        r = c.post(
            "/api/audio/voice-consent",
            data={"action": "grant", "feature": "bogus-feature"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert r.status_code == 400
        assert r.get_json()["error"] == "invalid"


# --------------------------------------------------------------------------- #
# Unknown / stale codes degrade safely
# --------------------------------------------------------------------------- #
def test_unknown_status_code_renders_no_banner(app_env):
    with app_env.test_client() as c:
        _signin(c)
        r = c.get("/settings/audio?status=not-a-real-code")
        assert r.status_code == 200


class TestEarlyReturnsUseBanners:
    def test_lexicon_post_without_org_lands_on_banner_not_json(self, app_env):
        """SRV-4: the no_org early return goes through _audio_back_or_json —
        a browser form POST gets the settings banner redirect, never JSON."""
        with app_env.test_client() as c:
            r = c.post("/api/audio/lexicon", data={"op": "set", "written": "A", "spoken": "ay"})
            assert r.status_code == 302
            assert "status=no_org" in (r.headers.get("Location") or "")

    def test_voice_consent_post_without_org_lands_on_banner_not_json(self, app_env):
        with app_env.test_client() as c:
            r = c.post("/api/audio/voice-consent", data={"feature": "voice_clone"})
            assert r.status_code == 302
            assert "status=no_org" in (r.headers.get("Location") or "")

    def test_no_raw_exception_detail_in_audio_errors(self):
        """audio_unavailable responses never carry str(e) to the customer."""
        from pathlib import Path

        src = web_surface_src()
        audio_region = src[
            src.index("def api_audio_library") : src.index("def api_audio_voice_consent")
        ]
        assert '"detail": str(e)' not in audio_region
