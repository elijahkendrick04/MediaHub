"""Roadmap 1.22 — PWA share-target capture + mobile camera/quick-upload.

Covers the first build of the Mobile PWA:

  * the web manifest advertises a Web Share Target so the installed app shows
    up in the phone's OS share sheet;
  * POST /share-target drops the shared photo(s) into the *active* org's media
    library, skips non-image attachments, and is tenant-scoped;
  * the media-library page exposes the camera-capture affordance + on-device
    downscale script, and shows a success banner after a drop.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _tiny_jpeg() -> bytes:
    """A real, decodable JPEG — ingest verifies uploads actually decode."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (10, 20, 30)).save(buf, format="JPEG")
    return buf.getvalue()


_JPEG = _tiny_jpeg()


@pytest.fixture
def app(web_module):
    """Fresh app with one saved, active-able org, mirroring the media-library
    isolation tests."""
    import mediahub.media_library.store as mls

    # The media store is a process-level singleton keyed at first construction;
    # reset it so each test gets a fresh DB at its own tmp_path (otherwise asset
    # counts leak between tests).
    mls._default_store = None

    application = web_module.create_app()
    application.config["TESTING"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    save_profile(ClubProfile(profile_id="beta", display_name="Beta SC"))
    return application


def _pin(client, pid="alpha"):
    client.post("/api/organisation/active", data={"profile_id": pid})


def _library_count(pid="alpha"):
    from mediahub.media_library.store import get_store

    return len(get_store().list(profile_id=pid))


# ---------------------------------------------------------------------------
# Manifest advertises the share target
# ---------------------------------------------------------------------------


def test_manifest_declares_share_target(app):
    c = app.test_client()
    m = c.get("/manifest.webmanifest").get_json(force=True)
    st = m.get("share_target")
    assert st, "manifest must declare a share_target for the OS share sheet"
    assert st["action"].endswith("/share-target")
    assert st["method"].upper() == "POST"
    assert st["enctype"] == "multipart/form-data"
    files = st["params"]["files"]
    assert files and files[0]["name"] == "photos"
    assert any("image/" in a for a in files[0]["accept"])


# ---------------------------------------------------------------------------
# /share-target receiver
# ---------------------------------------------------------------------------


def test_share_target_saves_photo_to_active_library(app):
    c = app.test_client()
    _pin(c)
    assert _library_count() == 0
    resp = c.post(
        "/share-target",
        data={"photos": (io.BytesIO(_JPEG), "poolside.jpg")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/media-library" in resp.headers["Location"]
    assert "shared=1" in resp.headers["Location"]
    assert _library_count() == 1, "shared photo must land in the active library"


def test_share_target_handles_multiple_photos(app):
    c = app.test_client()
    _pin(c)
    resp = c.post(
        "/share-target",
        data={
            "photos": [
                (io.BytesIO(_JPEG), "a.jpg"),
                (io.BytesIO(_JPEG), "b.jpg"),
                (io.BytesIO(_JPEG), "c.jpg"),
            ]
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert "shared=3" in resp.headers["Location"]
    assert _library_count() == 3


def test_share_target_skips_non_image_attachments(app):
    c = app.test_client()
    _pin(c)
    resp = c.post(
        "/share-target",
        data={
            "photos": [
                (io.BytesIO(_JPEG), "photo.jpg"),
                (io.BytesIO(b"just some notes"), "notes.txt", "text/plain"),
            ]
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    loc = resp.headers["Location"]
    assert "shared=1" in loc and "skipped=1" in loc
    assert _library_count() == 1, "only the image should be stored"


def test_share_target_is_tenant_scoped(app):
    """A shared photo only ever reaches the session's active org — never the
    other tenant's library."""
    c = app.test_client()
    _pin(c, "alpha")
    c.post(
        "/share-target",
        data={"photos": (io.BytesIO(_JPEG), "x.jpg")},
        content_type="multipart/form-data",
    )
    assert _library_count("alpha") == 1
    assert _library_count("beta") == 0


def test_share_target_signed_out_redirects_to_sign_in(app):
    c = app.test_client()  # no active profile pinned
    resp = c.post(
        "/share-target",
        data={"photos": (io.BytesIO(_JPEG), "x.jpg")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/sign-in" in resp.headers["Location"]
    assert _library_count("alpha") == 0


def test_share_target_path_is_csrf_exempt(app):
    """The OS share sheet can't carry a CSRF token, so the path must be exempt
    even when CSRF enforcement is on."""
    c = app.test_client()
    _pin(c)  # pin first (the pin POST itself isn't CSRF-exempt)
    app.config["ENFORCE_CSRF"] = True
    resp = c.post(
        "/share-target",
        data={"photos": (io.BytesIO(_JPEG), "x.jpg")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302  # not a 403 CSRF block
    assert _library_count() == 1


# ---------------------------------------------------------------------------
# Media-library page: capture affordance + banner
# ---------------------------------------------------------------------------


def test_library_page_exposes_camera_capture_and_downscale(app):
    c = app.test_client()
    _pin(c)
    html = c.get("/media-library").get_data(as_text=True)
    assert "data-mh-capture-form" in html
    assert 'id="ml-capture"' in html and 'capture="environment"' in html
    assert 'id="ml-capture-btn"' in html
    assert "js/mobile-capture.js" in html


def test_library_page_shows_shared_success_banner(app):
    c = app.test_client()
    _pin(c)
    html = c.get("/media-library?shared=2").get_data(as_text=True)
    assert "2 photos added" in html
    html1 = c.get("/media-library?shared=1&skipped=1").get_data(as_text=True)
    assert "1 photo added" in html1
    assert "1 item skipped" in html1
