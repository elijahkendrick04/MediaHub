"""Microsite engine (roadmap 1.16) — build 4: the web surface."""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "MEDIAHUB_LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, wm, tmp_path


def _login(client, pid="club-a"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name=pid.replace("-", " ").title()))
    with client.session_transaction() as s:
        s["active_profile_id"] = pid


def _save_site(pid="club-a", *, pages=None, title="Otters", archetype="club_home"):
    from mediahub.sites.models import SitePage, SiteSection, SiteSpec, hero
    from mediahub.sites.store import save_site

    pages = pages or [SitePage(title="Home", slug="", sections=[SiteSection(blocks=[hero("Hi")])])]
    spec = SiteSpec(title=title, archetype=archetype, pages=pages)
    save_site(pid, spec)
    return spec


# ---------------------------------------------------------------------------
# Operator surface
# ---------------------------------------------------------------------------


def test_home_requires_org(app_env):
    app, _wm, _ = app_env
    c = app.test_client()
    r = c.get("/sites")
    assert r.status_code == 200
    assert b"organisation" in r.data.lower()


def test_home_signed_in(app_env):
    app, _wm, _ = app_env
    c = app.test_client()
    _login(c)
    r = c.get("/sites")
    assert r.status_code == 200
    assert b"Sites" in r.data
    assert b"New site" in r.data


def test_generate_then_edit(app_env):
    app, _wm, _ = app_env
    c = app.test_client()
    _login(c)
    r = c.post("/api/sites/generate", json={"archetype": "link_in_bio"})
    j = r.get_json()
    assert j["ok"] and j["site_id"]
    v = c.get(f"/sites/{j['site_id']}")
    assert v.status_code == 200
    assert b"Preview" in v.data and b"Publish" in v.data


def test_save_spec(app_env):
    app, _wm, _ = app_env
    c = app.test_client()
    _login(c)
    spec = _save_site()
    new = spec.to_dict()
    new["title"] = "Renamed Club"
    r = c.post(f"/api/sites/{spec.site_id}/save", json={"spec": new})
    assert r.get_json()["ok"]
    from mediahub.sites.store import load_site

    assert load_site("club-a", spec.site_id).title == "Renamed Club"


def test_publish_then_public_then_unpublish(app_env):
    app, _wm, _ = app_env
    c = app.test_client()
    _login(c)
    spec = _save_site()
    r = c.post(f"/api/sites/{spec.site_id}/publish", json={})
    j = r.get_json()
    assert j["ok"] and j["token"]
    token = j["token"]

    # public page renders without a login (fresh client, no session)
    pub = app.test_client()
    pr = pub.get(f"/site/{token}")
    assert pr.status_code == 200
    assert b"Made with MediaHub" in pr.data

    # unpublish → the public URL resolves to nothing
    c.post(f"/api/sites/{spec.site_id}/unpublish", json={})
    assert app.test_client().get(f"/site/{token}").status_code == 404


def test_preview_allows_same_origin_framing(app_env):
    app, _wm, _ = app_env
    c = app.test_client()
    _login(c)
    spec = _save_site()
    r = c.get(f"/sites/{spec.site_id}/preview")
    assert r.status_code == 200
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in r.headers.get("Content-Security-Policy", "")


def test_public_bad_token_404(app_env):
    app, _wm, _ = app_env
    assert app.test_client().get("/site/not-a-real-token").status_code == 404


def test_qr_requires_publish_then_serves_png(app_env):
    app, _wm, _ = app_env
    c = app.test_client()
    _login(c)
    spec = _save_site()
    assert c.get(f"/sites/{spec.site_id}/qr.png").status_code == 409  # not published yet
    c.post(f"/api/sites/{spec.site_id}/publish", json={})
    r = c.get(f"/sites/{spec.site_id}/qr.png")
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "image/png"
    assert r.data[:4] == b"\x89PNG"


def test_org_isolation(app_env):
    app, _wm, _ = app_env
    spec = _save_site(pid="club-a")
    other = app.test_client()
    _login(other, pid="club-b")
    assert other.get(f"/sites/{spec.site_id}").status_code == 404
    assert other.post(f"/api/sites/{spec.site_id}/save", json={"spec": {}}).status_code == 404


def test_sitemap_and_robots(app_env):
    app, _wm, _ = app_env
    c = app.test_client()
    _login(c)
    spec = _save_site()
    c.post(f"/api/sites/{spec.site_id}/publish", json={})
    token = __import__("mediahub.sites.store", fromlist=["site_record"]).site_record(
        "club-a", spec.site_id
    )["public_token"]
    pub = app.test_client()
    sm = pub.get(f"/site/{token}/sitemap.xml")
    assert sm.status_code == 200 and b"<urlset" in sm.data
    rb = pub.get(f"/site/{token}/robots.txt")
    assert rb.status_code == 200 and b"Sitemap:" in rb.data


def test_password_gate(app_env):
    app, _wm, _ = app_env
    from mediahub.sites.models import SitePage, SiteSection, SiteSpec
    from mediahub.documents.models import text

    c = app.test_client()
    _login(c)
    spec = SiteSpec(
        title="Members",
        pages=[
            SitePage(
                title="Home",
                slug="",
                protected=True,
                sections=[SiteSection(blocks=[text("secret members content")])],
            )
        ],
    )
    from mediahub.sites.store import save_site

    save_site("club-a", spec)
    c.post(f"/api/sites/{spec.site_id}/password", data={"password": "letmein"})
    c.post(f"/api/sites/{spec.site_id}/publish", data={})
    from mediahub.sites.store import site_record

    token = site_record("club-a", spec.site_id)["public_token"]

    pub = app.test_client()
    locked = pub.get(f"/site/{token}")
    assert locked.status_code == 200
    assert b"protected" in locked.data.lower()
    assert b"secret members content" not in locked.data
    # unlock with the right password
    ok = pub.post(f"/site/{token}/unlock", data={"site_password": "letmein", "next": ""})
    assert ok.status_code in (302, 303)
    seen = pub.get(f"/site/{token}")
    assert b"secret members content" in seen.data


def test_delete_site(app_env):
    app, _wm, _ = app_env
    c = app.test_client()
    _login(c)
    spec = _save_site()
    c.post(f"/api/sites/{spec.site_id}/delete", json={})
    assert c.get(f"/sites/{spec.site_id}").status_code == 404


def test_poll_vote_flow(app_env):
    app, _wm, _ = app_env
    from mediahub.sites.models import SitePage, SiteSection, SiteSpec, widget_embed
    from mediahub.sites.store import save_site, site_record

    c = app.test_client()
    _login(c)
    poll = widget_embed(
        widget_id="poll1", widget_type="poll", config={"question": "Best?", "options": ["A", "B"]}
    )
    spec = SiteSpec(
        title="P", pages=[SitePage(title="Home", slug="", sections=[SiteSection(blocks=[poll])])]
    )
    save_site("club-a", spec)
    c.post(f"/api/sites/{spec.site_id}/publish", data={})
    token = site_record("club-a", spec.site_id)["public_token"]

    pub = app.test_client()
    r = pub.post(f"/site/{token}/widget/poll1/vote", json={"option": "A"})
    j = r.get_json()
    assert j["ok"] and j["counts"]["A"] == 1
    # a non-existent option is refused
    assert pub.post(f"/site/{token}/widget/poll1/vote", json={"option": "Z"}).status_code == 400
