"""H-3 — photo consent/permission must be viewable and changeable.

Every photo defaulted to permission "unknown", the table showed the raw
snake_case enum read-only, and bulk Approve silently skipped anything with a
consent block or safe_for_minors=False — yet the only permission editor rejected
anything that wasn't footage, so a volunteer holding a signed consent form hit a
hard dead end (fixable only by delete + re-upload). There's now a photo consent
writer, a plain-English per-row dropdown, and the bulk "skipped (safeguarding)"
result flags the blocked rows.
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


def _seed(store_mod, pid="alpha", perm="needs_parental_consent", atype="athlete_action"):
    from mediahub.media_library.models import MediaAsset

    a = MediaAsset(
        id="", filename="p.jpg", path="/tmp/p.jpg", type=atype,
        profile_id=pid, permission_status=perm,
    )
    return store_mod._default_store.save(a).id


def test_permission_writer_records_consent(client):
    c, store_mod = client
    aid = _seed(store_mod, perm="needs_parental_consent")
    r = c.post(
        f"/api/media-library/{aid}/permission",
        json={"permission_status": "approved_by_club"},
    )
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] is True
    assert j["usable"] is True  # no longer blocked
    assert store_mod._default_store.get(aid).permission_status == "approved_by_club"


def test_blocked_status_reports_not_usable(client):
    c, store_mod = client
    aid = _seed(store_mod, perm="approved_by_club")
    r = c.post(
        f"/api/media-library/{aid}/permission", json={"permission_status": "do_not_use"}
    )
    assert r.get_json()["usable"] is False


def test_permission_bad_value_400(client):
    c, store_mod = client
    aid = _seed(store_mod)
    r = c.post(f"/api/media-library/{aid}/permission", json={"permission_status": "banana"})
    assert r.status_code == 400


def test_permission_tenant_isolation(client):
    c, store_mod = client
    other = _seed(store_mod, pid="beta")
    r = c.post(
        f"/api/media-library/{other}/permission", json={"permission_status": "approved_public"}
    )
    assert r.status_code == 403


def test_consent_then_bulk_approve_succeeds(client):
    """The end-to-end unblock: set consent inline, then bulk-approve works."""
    c, store_mod = client
    aid = _seed(store_mod, perm="needs_parental_consent")
    # Before consent: bulk approve skips it as a safeguarding block.
    r1 = c.post("/api/media-library/bulk-approve", json={"asset_ids": [aid]})
    j1 = r1.get_json()
    assert j1["n_skipped"] == 1
    assert any(x.get("error") == "safeguarding_block" for x in j1["results"])
    # Record consent, then bulk approve succeeds.
    c.post(f"/api/media-library/{aid}/permission", json={"permission_status": "approved_by_club"})
    r2 = c.post("/api/media-library/bulk-approve", json={"asset_ids": [aid]})
    assert r2.get_json()["n_ok"] == 1
    assert store_mod._default_store.get(aid).approval_status == "approved"


def test_library_page_renders_consent_dropdown(client):
    c, store_mod = client
    _seed(store_mod, perm="needs_parental_consent", atype="athlete_action")
    html = c.get("/media-library").get_data(as_text=True)
    assert "mh-ml-perm" in html  # the per-row consent select
    assert "Needs parental consent" in html  # plain-English label, not raw enum
    assert "Consent on file — club approved" in html


def test_logo_row_has_no_consent_dropdown(client):
    c, store_mod = client
    _seed(store_mod, atype="logo", perm="approved_public")
    html = c.get("/media-library").get_data(as_text=True)
    # A logo isn't a person — it gets a read-only label, not the consent select.
    # (Only assert when this is the sole asset so the select can't come from another row.)
    assert 'class="mh-ml-perm"' not in html
