"""Tests for the 1.3 photo-editor web surface.

Two layers:
  1. The Flask-free body builder (``web.photo_editor.render_editor_body``) —
     control presence + XSS escaping, no request context needed.
  2. The routes, through the app test client — the editor page, the
     preview / apply / enhance / reset / edited endpoints, profile-picture +
     collage exports, profile-scope enforcement, and HEIC upload ingest.

Mirrors tests/test_media_library_profile_isolation.py for the app fixture.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# --------------------------------------------------------------------------- #
# Layer 1 — Flask-free body
# --------------------------------------------------------------------------- #


def _body(**over):
    from mediahub.web.photo_editor import render_editor_body

    kw = dict(
        asset_id="ma_x",
        asset_label="Eira Hughes",
        asset_type="athlete_action",
        asset_url="/file",
        edited_url="/edited",
        apply_url="/apply",
        preview_url="/preview",
        enhance_url="/enhance",
        reset_url="/reset",
        profile_pic_url="/profilepic",
        back_url="/library",
        width=1280,
        height=960,
    )
    kw.update(over)
    return render_editor_body(**kw)


def test_body_has_core_controls():
    b = _body()
    for token in (
        'id="pe-img"',
        'id="pe-overlay"',
        'id="pe-config"',
        'data-op="brightness"',
        'data-op="warmth"',
        'data-op="white_balance"',
        'data-op="vignette"',
        'data-filter="poolside"',
        'id="pe-shape"',
        'data-brush="blur_brush"',
        'data-brush="eraser"',
        'id="pe-persp-h"',
        'data-preset="avatar_circle"',
        'id="pe-enhance"',
        'id="pe-apply"',
    ):
        assert token in b, token


def test_body_escapes_label():
    b = _body(asset_label="<script>x</script>")
    assert "<script>x</script>" not in b
    assert "&lt;script&gt;" in b


def test_body_uses_brand_duotone_defaults():
    b = _body(brand_shadow="#123456", brand_highlight="#abcdef")
    assert "#123456" in b and "#abcdef" in b


def test_body_shows_edited_when_recipe_present():
    b = _body(has_edit=True, edited_url="/edited-xyz")
    assert 'src="/edited-xyz"' in b


# --------------------------------------------------------------------------- #
# Layer 2 — routes
# --------------------------------------------------------------------------- #


@pytest.fixture
def app_ctx(app, tmp_path):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    save_profile(ClubProfile(profile_id="beta", display_name="Beta SC"))
    return app, tmp_path


def _seed_png(tmp_path, profile_id, name="p.png", size=(80, 60), rgb=(120, 80, 40)):
    from mediahub.media_library.models import MediaAsset
    from mediahub.media_library.store import get_store

    p = tmp_path / f"{profile_id}_{name}"
    Image.new("RGB", size, rgb).save(p)
    store = get_store()
    a = MediaAsset(
        id="",
        filename=name,
        path=str(p),
        type="athlete_action",
        profile_id=profile_id,
        permission_status="approved_by_club",
        approval_status="approved",
    )
    return store.save(a).id


def _activate(c, pid):
    c.post("/api/organisation/active", data={"profile_id": pid})


def test_editor_page_renders_for_own_asset(app_ctx):
    app, tmp_path = app_ctx
    with app.test_client() as c:
        _activate(c, "alpha")
        aid = _seed_png(tmp_path, "alpha")
        r = c.get(f"/media-library/{aid}/edit")
    assert r.status_code == 200
    assert b"Photo editor" in r.data
    assert b"pe-config" in r.data


def test_editor_page_404_for_missing(app_ctx):
    app, _ = app_ctx
    with app.test_client() as c:
        _activate(c, "alpha")
        r = c.get("/media-library/ma_nope/edit")
    assert r.status_code == 404


def test_editor_page_403_for_foreign(app_ctx):
    app, tmp_path = app_ctx
    with app.test_client() as c:
        _activate(c, "alpha")
        beta_id = _seed_png(tmp_path, "beta")
        r = c.get(f"/media-library/{beta_id}/edit")
    assert r.status_code == 403


def test_preview_returns_png(app_ctx):
    app, tmp_path = app_ctx
    with app.test_client() as c:
        _activate(c, "alpha")
        aid = _seed_png(tmp_path, "alpha")
        r = c.post(
            f"/api/media-library/{aid}/edit/preview",
            json={"steps": [{"op": "grayscale", "params": {"amount": 1.0}}]},
        )
    assert r.status_code == 200
    assert r.mimetype == "image/png"
    with Image.open(io.BytesIO(r.data)) as im:
        im.load()
        assert im.size[0] > 0


def test_apply_persists_recipe_and_edits(app_ctx):
    app, tmp_path = app_ctx
    with app.test_client() as c:
        _activate(c, "alpha")
        aid = _seed_png(tmp_path, "alpha", rgb=(200, 40, 40))
        r = c.post(
            f"/api/media-library/{aid}/edit/apply",
            json={"steps": [{"op": "grayscale", "params": {"amount": 1.0}}]},
        )
        assert r.status_code == 200
        body = json.loads(r.data)
        assert body["ok"] and body["steps"] == 1 and body["edited_url"]

        # The recipe is persisted on the asset.
        from mediahub.media_library.store import get_store
        from mediahub.media_library import photo_edit as pe

        a = get_store().get(aid)
        assert pe.has_edit(a)

        # The edited serve differs from the original (greyscale removed colour).
        orig = c.get(f"/api/media-library/file/{aid}").data
        edited = c.get(f"/api/media-library/{aid}/edited").data
        assert edited != orig


def test_apply_foreign_is_forbidden(app_ctx):
    app, tmp_path = app_ctx
    with app.test_client() as c:
        _activate(c, "alpha")
        beta_id = _seed_png(tmp_path, "beta")
        r = c.post(
            f"/api/media-library/{beta_id}/edit/apply",
            json={"steps": [{"op": "grayscale", "params": {"amount": 1.0}}]},
        )
    assert r.status_code == 403


def test_enhance_returns_recipe(app_ctx):
    app, tmp_path = app_ctx
    with app.test_client() as c:
        _activate(c, "alpha")
        aid = _seed_png(tmp_path, "alpha", rgb=(30, 45, 70))
        r = c.post(f"/api/media-library/{aid}/edit/enhance", json={})
    assert r.status_code == 200
    body = json.loads(r.data)
    assert body["ok"] and "steps" in body["recipe"]


def test_reset_clears_recipe(app_ctx):
    app, tmp_path = app_ctx
    with app.test_client() as c:
        _activate(c, "alpha")
        aid = _seed_png(tmp_path, "alpha")
        c.post(
            f"/api/media-library/{aid}/edit/apply",
            json={"steps": [{"op": "vignette", "params": {"amount": 40}}]},
        )
        r = c.post(f"/api/media-library/{aid}/edit/reset", json={})
        assert r.status_code == 200
        from mediahub.media_library.store import get_store
        from mediahub.media_library import photo_edit as pe

        assert not pe.has_edit(get_store().get(aid))


def test_edited_serves_original_without_recipe(app_ctx):
    app, tmp_path = app_ctx
    with app.test_client() as c:
        _activate(c, "alpha")
        aid = _seed_png(tmp_path, "alpha")
        r = c.get(f"/api/media-library/{aid}/edited")
    assert r.status_code == 200
    assert len(r.data) > 0


def test_profile_picture_export_creates_asset(app_ctx):
    app, tmp_path = app_ctx
    with app.test_client() as c:
        _activate(c, "alpha")
        aid = _seed_png(tmp_path, "alpha", size=(400, 300))
        from mediahub.media_library.store import get_store

        before = len(get_store().list(profile_id="alpha"))
        r = c.post(f"/api/media-library/{aid}/profile-picture", json={"preset": "avatar_circle"})
        assert r.status_code == 200
        body = json.loads(r.data)
        assert body["ok"] and body["asset"]["width"] == 512
        after = len(get_store().list(profile_id="alpha"))
    assert after == before + 1


def test_collage_creates_asset_from_two(app_ctx):
    app, tmp_path = app_ctx
    with app.test_client() as c:
        _activate(c, "alpha")
        a1 = _seed_png(tmp_path, "alpha", name="a1.png", rgb=(200, 0, 0))
        a2 = _seed_png(tmp_path, "alpha", name="a2.png", rgb=(0, 200, 0))
        r = c.post(
            "/api/media-library/collage",
            json={"asset_ids": [a1, a2], "layout": "duo_v", "format": "collage_square"},
        )
    assert r.status_code == 200
    body = json.loads(r.data)
    assert body["ok"] and body["asset"]["width"] == 1080


def test_collage_needs_two(app_ctx):
    app, tmp_path = app_ctx
    with app.test_client() as c:
        _activate(c, "alpha")
        a1 = _seed_png(tmp_path, "alpha", name="solo.png")
        r = c.post("/api/media-library/collage", json={"asset_ids": [a1], "layout": "duo_v"})
    assert r.status_code == 400


def test_library_page_offers_collage_bulk_action(app_ctx):
    """The collage capability must be reachable from the UI: the media
    library's bulk bar carries a 'Make collage' action + layout picker
    posting to the collage endpoint."""
    app, tmp_path = app_ctx
    with app.test_client() as c:
        _activate(c, "alpha")
        _seed_png(tmp_path, "alpha", name="ui1.png")
        r = c.get("/media-library")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'data-mh-bulk="collage"' in body
    assert "/api/media-library/collage" in body
    assert 'id="mh-ml-collage-layout"' in body
    for slug in ("grid_2x2", "duo_v", "duo_h", "trio_strip", "trio_feature", "grid_3x3"):
        assert f'value="{slug}"' in body, slug


def test_collage_form_post_redirects_to_editor(app_ctx):
    """The no-JS form path: url-encoded asset_ids + layout → 302 to the new
    draft's photo editor."""
    app, tmp_path = app_ctx
    with app.test_client() as c:
        _activate(c, "alpha")
        a1 = _seed_png(tmp_path, "alpha", name="f1.png", rgb=(200, 0, 0))
        a2 = _seed_png(tmp_path, "alpha", name="f2.png", rgb=(0, 200, 0))
        r = c.post(
            "/api/media-library/collage",
            data={"asset_ids": [a1, a2], "layout": "grid_2x2"},
        )
    assert r.status_code == 302
    assert "/edit" in r.headers["Location"]


def _has_heif_writer() -> bool:
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
        b = io.BytesIO()
        Image.new("RGB", (8, 8), (1, 2, 3)).save(b, format="HEIF")
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _has_heif_writer(), reason="pillow_heif HEIF encode unavailable")
def test_heic_upload_is_normalised_to_jpeg(app_ctx):
    app, tmp_path = app_ctx
    buf = io.BytesIO()
    Image.new("RGB", (48, 36), (200, 120, 60)).save(buf, format="HEIF")
    buf.seek(0)
    with app.test_client() as c:
        _activate(c, "alpha")
        r = c.post(
            "/api/media-library",
            data={
                "file": (buf, "IMG_9999.heic"),
                "profile_id": "alpha",
                "asset_type": "athlete_action",
            },
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
    assert r.status_code == 200, r.data
    body = json.loads(r.data)
    assert body["ok"]
    assert body["asset"]["path"].endswith(".jpg")  # HEIC converted on ingest
    # And the stored file is a real, openable JPEG.
    with Image.open(body["asset"]["path"]) as im:
        im.load()
        assert (im.format or "").upper() == "JPEG"


def test_reset_button_posts_to_reset_endpoint():
    """Reset must persist: the handler POSTs cfg.resetUrl (clearing the saved
    recipe server-side), not just clear the local controls."""
    b = _body()
    assert "fetch(cfg.resetUrl,{method:'POST'" in b
