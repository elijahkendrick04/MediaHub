"""D-7 — uploaded club audio must be confirmed, listed, previewable and
removable, not vanish silently.

After a successful upload the form used to redirect back with no message and no
UI ever listing the org's own uploads (the list showed only the deployment-global
catalogue), so the volunteer couldn't tell it worked and re-uploaded. This adds
a "Track added" banner, a "Your uploaded audio" list with preview + remove, and
tenant-scoped serve/delete routes.
"""

from __future__ import annotations

import io
import wave

import pytest


@pytest.fixture
def app_env(web_module, monkeypatch):
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    app = web_module.create_app()
    app.config["TESTING"] = True
    return app


def _tiny_wav(ms: int = 300, rate: int = 22050) -> bytes:
    n = int(rate * ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


def _signin(c, pid="alpha"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name="Alpha SC"))
    c.post("/api/organisation/active", data={"profile_id": pid})


def _upload(c):
    return c.post(
        "/api/audio/upload",
        data={
            "file": (io.BytesIO(_tiny_wav()), "clip.wav"),
            "licence_name": "Licensed",
            "commercial_ok": "1",
        },
        content_type="multipart/form-data",
        headers={"Accept": "application/json"},
    ).get_json()["asset"]["asset_id"]


def test_form_upload_confirms_with_banner(app_env):
    with app_env.test_client() as c:
        _signin(c)
        # A browser (non-JSON) form POST redirects back with a status marker.
        r = c.post(
            "/api/audio/upload",
            data={"file": (io.BytesIO(_tiny_wav()), "clip.wav"), "commercial_ok": "1"},
            content_type="multipart/form-data",
        )
        assert r.status_code == 302
        assert "status=audio_added" in r.headers["Location"]
        page = c.get("/settings/audio?status=audio_added").get_data(as_text=True)
        assert "Track added" in page


def test_uploaded_audio_is_listed_and_previewable(app_env):
    with app_env.test_client() as c:
        _signin(c)
        asset_id = _upload(c)
        page = c.get("/settings/audio").get_data(as_text=True)
        assert "Your uploaded audio" in page
        assert f"/api/audio/upload/{asset_id}" in page
        # The preview stream serves the file.
        assert c.get(f"/api/audio/upload/{asset_id}").status_code == 200


def test_uploaded_audio_is_tenant_scoped(app_env):
    with app_env.test_client() as c:
        _signin(c, "alpha")
        asset_id = _upload(c)
    # A different org can't stream or delete alpha's upload.
    with app_env.test_client() as other:
        _signin(other, "beta")
        assert other.get(f"/api/audio/upload/{asset_id}").status_code == 404
        assert (
            other.post(
                f"/api/audio/upload/{asset_id}/delete", headers={"Accept": "application/json"}
            ).status_code
            == 404
        )


def test_uploaded_audio_can_be_removed(app_env):
    with app_env.test_client() as c:
        _signin(c)
        asset_id = _upload(c)
        r = c.post(f"/api/audio/upload/{asset_id}/delete", headers={"Accept": "application/json"})
        assert r.status_code == 200
        # Gone from the list and no longer streamable.
        assert f"/api/audio/upload/{asset_id}" not in c.get("/settings/audio").get_data(
            as_text=True
        )
        assert c.get(f"/api/audio/upload/{asset_id}").status_code == 404
