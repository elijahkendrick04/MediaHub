"""H-4 — a photo's metadata must be editable after upload.

Description, athlete link, venue, event and tags could only be set at upload
time, yet three pieces of UI copy told users they could "review and edit
anytime". When AI vision tagged the wrong swimmer the only fix was delete +
re-upload. There's now a POST /api/media-library/<id>/meta endpoint (a full
replace, so a wrong tag can be removed) and an in-place editor opened from an
"Info" button and the "auto" badge.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
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


def _seed(store_mod, pid="alpha", **kw):
    from mediahub.media_library.models import MediaAsset

    store = store_mod._default_store
    a = MediaAsset(
        id="",
        filename="pic.jpg",
        path="/tmp/pic.jpg",
        type="athlete_action",
        profile_id=pid,
        description_raw=kw.get("description", "old desc"),
        linked_athlete_names=kw.get("athletes", ["Wrong Name"]),
        linked_venue=kw.get("venue"),
        linked_event=kw.get("event"),
        tags=kw.get("tags", []),
    )
    return store.save(a).id


def test_meta_edit_replaces_fields(client):
    c, store_mod = client
    aid = _seed(store_mod, athletes=["Wrong Name"])
    r = c.post(
        f"/api/media-library/{aid}/meta",
        json={
            "description": "Eira Hughes wins the 100 free",
            "athletes": "Eira Hughes",
            "venue": "Cardiff",
            "event": "Welsh Open",
            "tags": "podium, freestyle",
        },
    )
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] is True
    assert j["asset"]["athletes"] == "Eira Hughes"  # replaced, not appended
    assert j["asset"]["venue"] == "Cardiff"
    assert j["asset"]["tags"] == "podium, freestyle"

    store = store_mod._default_store
    a = store.get(aid)
    assert a.linked_athlete_names == ["Eira Hughes"]
    assert a.linked_venue == "Cardiff"
    assert a.tags == ["podium", "freestyle"]


def test_meta_edit_can_clear_a_wrong_tag(client):
    c, store_mod = client
    aid = _seed(store_mod, athletes=["Wrong Name", "Also Wrong"])
    r = c.post(f"/api/media-library/{aid}/meta", json={"athletes": ""})
    assert r.status_code == 200
    assert store_mod._default_store.get(aid).linked_athlete_names == []


def test_meta_edit_tenant_isolation(client):
    c, store_mod = client
    other = _seed(store_mod, pid="beta")
    r = c.post(f"/api/media-library/{other}/meta", json={"venue": "sneaky"})
    assert r.status_code == 403
    # unchanged
    assert store_mod._default_store.get(other).linked_venue is None


def test_meta_edit_missing_asset_404(client):
    c, _ = client
    r = c.post("/api/media-library/does-not-exist/meta", json={"venue": "x"})
    assert r.status_code == 404


def test_library_page_has_editor_affordance(client):
    c, store_mod = client
    _seed(store_mod)
    html = c.get("/media-library").get_data(as_text=True)
    assert "mh-meta-modal" in html  # the editor modal is on the page
    assert "data-mh-meta-open" in html  # a trigger exists
    assert "Edit photo details" in html


def test_save_preserves_athlete_badges():
    # Pre-merge review: saving must update only the leading names text node, not
    # overwrite the whole Athlete cell (which would wipe the clickable "auto" and
    # "untagged" badge spans until reload).
    import pathlib

    src = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")
    assert "ac.textContent = a.athletes" not in src
    assert "tn.nodeValue=a.athletes" in src
