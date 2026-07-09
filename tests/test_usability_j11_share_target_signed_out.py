"""J-11 — a photo shared to MediaHub while signed out must not vanish silently.

The PWA share-target receiver bounced a signed-out share to /sign-in and dropped
the photo with no message, so the volunteer believed the shot was in the library
when it was gone. It now flashes an honest "sign in first, then re-share" notice
via the sign-in picker's existing error channel.
"""

from __future__ import annotations

import importlib
import io

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    c = app.test_client()
    if not wm._v8_ok:
        pytest.skip("V8 media engine not enabled")
    return c


def test_signed_out_share_flashes_and_does_not_500(client):
    r = client.post(
        "/share-target",
        data={"photos": (io.BytesIO(b"\xff\xd8\xff"), "poolside.jpg")},
        content_type="multipart/form-data",
    )
    assert r.status_code in (302, 303)
    assert r.headers["Location"].endswith("/sign-in")


def test_flash_reason_shown_on_sign_in(client):
    client.post(
        "/share-target",
        data={"photos": (io.BytesIO(b"\xff\xd8\xff"), "poolside.jpg")},
        content_type="multipart/form-data",
    )
    html = client.get("/sign-in").get_data(as_text=True)
    # (the apostrophe in "wasn't" is HTML-escaped, so match escape-free fragments)
    assert "then re-share the photo from your camera roll" in html
