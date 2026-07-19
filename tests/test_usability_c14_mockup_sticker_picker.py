"""C-14 — wire a real sticker/mockup picker; no raw-JSON dead-ends.

The make-sticker API had zero UI callers (unreachable), and the only mockup
affordance was a hardcoded anchor that opened the mockup API route in a NEW TAB
— so any failure dumped raw JSON with no way back. There's now an in-page
mockup + sticker picker (on the generated-images gallery and the cut-out page):
it lists templates, renders the mockup as an inline <img> with a styled error,
and gives the make-sticker API its first working caller.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def client(web_module, tmp_path, monkeypatch):
    wm = web_module
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")

    from mediahub.media_library import store as _mlstore

    _mlstore._default_store = _mlstore.MediaLibraryStore(
        db_path=tmp_path / "media.db",
        uploads_dir=tmp_path / "uploads_v4" / "media_library",
    )
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    save_profile(ClubProfile(profile_id="beta", display_name="Beta SC"))
    app = wm.create_app()
    app.config["TESTING"] = True
    if not wm._v8_ok:
        pytest.skip("V8 media engine not enabled in this environment")
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "alpha"
    return c, _mlstore


def _seed_generated(store_mod, pid="alpha"):
    from mediahub.media_library.models import MediaAsset

    a = MediaAsset(
        id="",
        filename="gen.png",
        path="/tmp/gen.png",
        type="ai_generated",
        profile_id=pid,
        description_raw="A poster",
        description_parsed={"imagine": {"prompt": "x"}},
    )
    return store_mod._default_store.save(a).id


def test_templates_endpoint_lists_mockups(client):
    c, _ = client
    j = c.get("/api/media-library/mockup-templates").get_json()
    assert "templates" in j
    ids = {t["id"] for t in j["templates"]}
    assert "poster_wall" in ids  # a known deterministic template


def test_generated_page_uses_in_page_picker_not_raw_json_anchor(client):
    c, store_mod = client
    _seed_generated(store_mod)
    html = c.get("/media-library/generated").get_data(as_text=True)
    # The picker button + modal are present…
    assert "data-mh-mockup-open" in html
    assert "mh-mockup-modal" in html
    assert "Product mockups" in html
    # …and the old raw-JSON new-tab anchor is gone.
    assert 'template="poster_wall"' not in html
    assert 'rel="noopener">Poster mockup' not in html


def test_make_sticker_reachable_and_tenant_scoped(client):
    c, store_mod = client
    aid = _seed_generated(store_mod)
    # The sticker endpoint (previously UI-orphaned) now backs the picker button.
    # It's tenant-scoped: a foreign asset is refused.
    other = _seed_generated(store_mod, pid="beta")
    r_forbidden = c.post(f"/api/media-library/{other}/make-sticker", json={})
    assert r_forbidden.status_code == 403
    # Own asset: reachable (may 500 if the on-disk source is absent in this
    # sandbox, but never 403/404 — it's wired and authorised).
    r_own = c.post(f"/api/media-library/{aid}/make-sticker", json={})
    assert r_own.status_code not in (403, 404)


def test_mockup_endpoint_tenant_scoped(client):
    c, store_mod = client
    other = _seed_generated(store_mod, pid="beta")
    r = c.get(f"/api/media-library/{other}/mockup/poster_wall")
    assert r.status_code == 403


def test_cutout_page_also_offers_the_picker(client):
    c, store_mod = client
    aid = _seed_generated(store_mod)
    html = c.get(f"/media-library/{aid}/cutout").get_data(as_text=True)
    assert "data-mh-mockup-open" in html
    assert "mh-mockup-modal" in html
