"""Roadmap 1.10 build 4 — mascot stickers, flagged AI seam, and web routes."""

from __future__ import annotations

import importlib

import pytest


# --------------------------------------------------------------------------- #
# stickers (cutout → org-custom sticker element)
# --------------------------------------------------------------------------- #
def _make_png(path, size=(64, 64), colour=(200, 30, 30, 255)):
    from PIL import Image

    Image.new("RGBA", size, colour).save(path)


def test_make_sticker_svg_embeds_image(tmp_path):
    from mediahub.elements import stickers

    p = tmp_path / "mascot.png"
    _make_png(p)
    svg = stickers.make_sticker_svg(p)
    assert svg is not None
    assert svg.startswith("<svg")
    assert "data:image/png;base64," in svg


def test_promote_image_to_sticker_registers_org_element(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.elements import catalog, stickers

    catalog.reload_bundled_cache()
    p = tmp_path / "crest.png"
    _make_png(p)
    el = stickers.promote_image_to_sticker(profile_id="club-1", image_path=p, name="Otters crest")
    assert el is not None
    assert el.kind == "sticker"
    assert el.source == "org_custom"
    assert el.slots == ()  # club imagery is not token-recoloured
    # now visible in that org's catalogue + loadable SVG
    assert catalog.get_element(el.id, "club-1") is not None
    svg = catalog.load_svg(el, "club-1")
    assert svg and "data:image/png;base64," in svg
    assert el in stickers.list_org_stickers("club-1")


def test_promote_missing_image_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.elements import stickers

    assert stickers.promote_image_to_sticker(
        profile_id="c", image_path=tmp_path / "nope.png", name="x"
    ) is None


# --------------------------------------------------------------------------- #
# flagged AI generation seam (honest-errors until 1.2)
# --------------------------------------------------------------------------- #
def test_generation_status_unavailable():
    from mediahub.elements import generate

    st = generate.status()
    assert st.available is False
    assert st.depends_on == "1.2"
    assert "1.2" in st.reason


def test_generate_functions_honest_error():
    from mediahub.elements import generate

    for fn in (generate.generate_shape, generate.generate_element, generate.generate_3d_element):
        with pytest.raises(generate.GenerativeElementsUnavailable):
            fn("a swimming pool")


# --------------------------------------------------------------------------- #
# web routes
# --------------------------------------------------------------------------- #
@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    for var in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    # The media-library store singleton uses a fixed package-local data.db; point
    # it at tmp so the app and the test share one DB (and the repo isn't touched).
    import mediahub.media_library.store as mls

    mls._default_store = mls.MediaLibraryStore(
        db_path=tmp_path / "data.db", uploads_dir=tmp_path / "uploads_v4" / "media_library"
    )
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, wm, tmp_path


def _signin(client, profile_id="alpha"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=profile_id, display_name="Alpha SC"))
    client.post("/api/organisation/active", data={"profile_id": profile_id})


def _seed_asset(tmp_path, profile_id="alpha"):
    from mediahub.media_library.models import MediaAsset
    from mediahub.media_library.store import get_store

    img = tmp_path / "uploads_v4" / "photo.png"
    img.parent.mkdir(parents=True, exist_ok=True)
    _make_png(img, size=(120, 80), colour=(20, 40, 60, 255))
    store = get_store()  # the tmp-pointed singleton the app also uses
    asset = store.save(
        MediaAsset(id="", filename="photo.png", path=str(img), type="other", profile_id=profile_id)
    )
    return asset


def test_annotate_save_and_serve(app_env, monkeypatch):
    app, _wm, tmp_path = app_env
    asset = _seed_asset(tmp_path)
    with app.test_client() as c:
        _signin(c)
        save = c.post(
            f"/api/media-library/{asset.id}/annotate",
            json={
                "symmetry": "none",
                "strokes": [
                    {"points": [[0.1, 0.5], [0.9, 0.5]], "kind": "arrow", "colour": "#FF0000", "width": 0.02}
                ],
            },
        )
        assert save.status_code == 200
        assert save.get_json()["strokes"] == 1
        # composited PNG is served
        served = c.get(f"/api/media-library/{asset.id}/annotated")
        assert served.status_code == 200
        assert served.mimetype == "image/png"
        assert served.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_annotate_persists_on_asset(app_env):
    app, _wm, tmp_path = app_env
    asset = _seed_asset(tmp_path)
    with app.test_client() as c:
        _signin(c)
        c.post(
            f"/api/media-library/{asset.id}/annotate",
            json={"strokes": [{"points": [[0.1, 0.1], [0.2, 0.2]], "kind": "line"}]},
        )
    from mediahub.media_library.store import MediaLibraryStore

    store = MediaLibraryStore(db_path=tmp_path / "data.db", uploads_dir=tmp_path / "uploads_v4")
    reloaded = store.get(asset.id)
    assert reloaded.annotation.get("strokes")


def test_annotate_page_renders(app_env):
    app, _wm, tmp_path = app_env
    asset = _seed_asset(tmp_path)
    with app.test_client() as c:
        _signin(c)
        resp = c.get(f"/annotate/{asset.id}")
    assert resp.status_code == 200
    assert b"Annotate" in resp.data
    assert b"an-canvas" in resp.data


def test_make_sticker_route(app_env):
    app, _wm, tmp_path = app_env
    asset = _seed_asset(tmp_path)
    with app.test_client() as c:
        _signin(c)
        resp = c.post(f"/api/media-library/{asset.id}/make-sticker", json={"name": "Club crest"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["element"]["id"].startswith("sticker.")
    # the new sticker is in the org catalogue
    from mediahub.elements import catalog

    assert catalog.get_element(data["element"]["id"], "alpha") is not None


def test_generate_route_honest_error(app_env):
    app, _wm, _ = app_env
    with app.test_client() as c:
        status = c.get("/api/elements/generate")
        assert status.status_code == 200
        assert status.get_json()["available"] is False
        gen = c.post("/api/elements/generate", json={"prompt": "a trophy"})
        assert gen.status_code == 501
        assert gen.get_json()["error"] == "generation_unavailable"
