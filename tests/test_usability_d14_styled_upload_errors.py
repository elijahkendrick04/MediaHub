"""D-14 — routes must not dump raw JSON into a full-page navigation.

The audio upload is a plain form POST: an unsupported type, a missing file, or an
over-limit file navigated the browser to a bare `{"error":"bad_type",...}` body
with no styling, no upfront limit, and typed licence fields lost. The billing
routes did the same with a 503 JSON body. Non-JSON callers now get a styled
message; JSON/AJAX callers keep the machine body.
"""

from __future__ import annotations

import importlib
import io
import wave

import pytest


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app


def _signin(c, pid="alpha"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name="Alpha SC"))
    c.post("/api/organisation/active", data={"profile_id": pid})


def _wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x00\x00" * 2000)
    return buf.getvalue()


def test_bad_audio_type_form_post_redirects_with_styled_error(app_env):
    with app_env.test_client() as c:
        _signin(c)
        # Browser form POST (no JSON Accept) → redirect back with a banner, not
        # a bare JSON page.
        r = c.post(
            "/api/audio/upload",
            data={"file": (io.BytesIO(b"hello"), "notes.txt")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 302
        # H-15: the redirect carries a status CODE (mapped to copy server-side),
        # not free-text — the banner intent of D-14 is unchanged.
        assert "status=bad_type" in r.headers["Location"]
        page = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "Upload failed" in page
        # The message is HTML-escaped in the banner; match its unescaped part.
        assert "supported" in page


def test_missing_file_form_post_is_styled(app_env):
    with app_env.test_client() as c:
        _signin(c)
        r = c.post("/api/audio/upload", data={}, content_type="multipart/form-data")
        assert r.status_code == 302
        # H-15: code-carrying redirect ("no_file"), mapped to copy server-side.
        assert "status=no_file" in r.headers["Location"]
        page = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "choose an audio file" in page.lower()


def test_audio_error_json_caller_still_gets_machine_body(app_env):
    with app_env.test_client() as c:
        _signin(c)
        r = c.post(
            "/api/audio/upload",
            data={"file": (io.BytesIO(b"hello"), "notes.txt")},
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
        assert r.status_code == 415
        assert r.get_json()["error"] == "bad_type"


def test_audio_form_shows_type_and_size_limits(app_env):
    with app_env.test_client() as c:
        _signin(c)
        page = c.get("/settings/audio").get_data(as_text=True)
        assert "up to 25 MB" in page
        assert "MP3" in page  # the allowed-types hint is present


def test_successful_upload_still_confirms(app_env):
    with app_env.test_client() as c:
        _signin(c)
        r = c.post(
            "/api/audio/upload",
            data={"file": (io.BytesIO(_wav()), "clip.wav"), "commercial_ok": "1"},
            content_type="multipart/form-data",
        )
        assert r.status_code == 302
        assert "status=audio_added" in r.headers["Location"]
