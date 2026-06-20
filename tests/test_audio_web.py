"""Web-surface tests for the 1.8 audio engine routes + settings section."""

from __future__ import annotations

import importlib
import io
import wave

import pytest


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    # Keep AI + library-bed off so honest-error / byte-parity paths are exercised.
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "MEDIAHUB_REEL_MUSIC_LIBRARY"):
        monkeypatch.delenv(var, raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, wm, tmp_path


def _tiny_wav(ms: int = 400, rate: int = 22050) -> bytes:
    n = int(rate * ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


def _signin(client, profile_id="alpha", name="Alpha SC"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=profile_id, display_name=name))
    client.post("/api/organisation/active", data={"profile_id": profile_id})


# ---- public catalogue routes ---------------------------------------------


def test_library_lists_bundled_tracks(app_env):
    app, _wm, _ = app_env
    with app.test_client() as c:
        resp = c.get("/api/audio/library")
    assert resp.status_code == 200
    tracks = resp.get_json()["tracks"]
    assert len(tracks) >= 8
    assert any(t["kind"] == "music" for t in tracks)


def test_track_preview_serves_audio_and_404s(app_env):
    app, _wm, _ = app_env
    with app.test_client() as c:
        tid = c.get("/api/audio/library").get_json()["tracks"][0]["id"]
        ok = c.get(f"/api/audio/track/{tid}")
        missing = c.get("/api/audio/track/does-not-exist")
    assert ok.status_code == 200
    assert ok.mimetype.startswith("audio/")
    assert missing.status_code == 404


def test_voices_route(app_env):
    app, _wm, _ = app_env
    with app.test_client() as c:
        resp = c.get("/api/audio/voices")
    assert resp.status_code == 200
    body = resp.get_json()
    assert any(v["local"] for v in body["voices"])


def test_suggest_honest_errors_without_ai(app_env):
    app, _wm, _ = app_env
    with app.test_client() as c:
        resp = c.get("/api/audio/suggest?mood=triumphant")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "ai_unavailable"


def test_settings_audio_section_renders(app_env):
    app, _wm, _ = app_env
    with app.test_client() as c:
        resp = c.get("/settings/audio")
    assert resp.status_code == 200
    assert b"Music" in resp.data and b"Voices" in resp.data


# ---- org-scoped routes ----------------------------------------------------


def test_lexicon_requires_org(app_env):
    app, _wm, _ = app_env
    with app.test_client() as c:
        resp = c.post(
            "/api/audio/lexicon",
            data={"op": "set", "written": "Saoirse", "spoken": "Seer-sha"},
            headers={"Accept": "application/json"},
        )
    assert resp.status_code == 403


def test_lexicon_crud_when_signed_in(app_env):
    app, _wm, _ = app_env
    with app.test_client() as c:
        _signin(c)
        c.post(
            "/api/audio/lexicon",
            data={"op": "set", "written": "Saoirse", "spoken": "Seer-sha"},
            headers={"Accept": "application/json"},
        )
        got = c.get("/api/audio/lexicon").get_json()
        assert got["entries"]["Saoirse"] == "Seer-sha"
        c.post(
            "/api/audio/lexicon",
            data={"op": "remove", "written": "Saoirse"},
            headers={"Accept": "application/json"},
        )
        after = c.get("/api/audio/lexicon").get_json()
        assert "Saoirse" not in after["entries"]


def test_upload_records_rights(app_env):
    app, _wm, _ = app_env
    with app.test_client() as c:
        _signin(c)
        resp = c.post(
            "/api/audio/upload",
            data={
                "file": (io.BytesIO(_tiny_wav()), "clip.wav"),
                "licence_name": "Licensed",
                "commercial_ok": "1",
                "platforms": "instagram,tiktok",
            },
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["asset"]["licence"]["name"] == "Licensed"
    assert body["fingerprint_method"] in {"chromaprint", "pcm", "filebytes"}


def test_upload_rejects_bad_type(app_env):
    app, _wm, _ = app_env
    with app.test_client() as c:
        _signin(c)
        resp = c.post(
            "/api/audio/upload",
            data={"file": (io.BytesIO(b"hello"), "notes.txt")},
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
    assert resp.status_code == 415


def test_voice_consent_grant_revoke(app_env):
    app, _wm, _ = app_env
    with app.test_client() as c:
        _signin(c)
        # off by default
        assert c.get("/api/audio/voice-consent").get_json()["active"] == []
        c.post(
            "/api/audio/voice-consent",
            data={"action": "grant", "feature": "clone", "voice_owner": "Coach"},
            headers={"Accept": "application/json"},
        )
        active = c.get("/api/audio/voice-consent").get_json()["active"]
        assert any(r["feature"] == "clone" for r in active)
        c.post(
            "/api/audio/voice-consent",
            data={"action": "revoke", "feature": "clone"},
            headers={"Accept": "application/json"},
        )
        assert c.get("/api/audio/voice-consent").get_json()["active"] == []
