"""D-8 — setting a site password must not silently do nothing.

A site password only gates a page marked members-only (``protected``), a flag
that defaulted false, no archetype set, and that had no editor control (only raw
JSON). So a treasurer who set a password believing a page was now private had
changed nothing. This adds a real per-page "members-only" toggle and honest
feedback when a password and protected pages are out of step.
"""

from __future__ import annotations

import importlib
from urllib.parse import unquote_plus

import pytest


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app


def _login(c, pid="club-a"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name="Club A"))
    with c.session_transaction() as s:
        s["active_profile_id"] = pid


def _save_two_page_site(pid="club-a"):
    from mediahub.sites.models import SitePage, SiteSection, SiteSpec, hero
    from mediahub.sites.store import save_site

    pages = [
        SitePage(title="Home", slug="", sections=[SiteSection(blocks=[hero("Hi")])]),
        SitePage(title="Members", slug="members", sections=[SiteSection(blocks=[hero("Secret")])]),
    ]
    spec = SiteSpec(title="Otters", archetype="club_home", pages=pages)
    save_site(pid, spec)
    return spec.site_id


def test_password_without_protected_page_warns_honestly(app_env):
    c = app_env.test_client()
    _login(c)
    site_id = _save_two_page_site()
    r = c.post(f"/api/sites/{site_id}/password", data={"password": "secret123"})
    assert r.status_code == 302
    # The honest warning replaces "Password updated." when nothing is protected.
    assert "still fully public" in unquote_plus(r.headers["Location"])


def test_editor_exposes_per_page_members_only_toggle(app_env):
    c = app_env.test_client()
    _login(c)
    site_id = _save_two_page_site()
    html = c.get(f"/sites/{site_id}").get_data(as_text=True)
    assert "Members-only pages" in html
    assert "page-protection" in html
    # A checkbox per page, keyed by slug.
    assert 'name="protected" value="members"' in html


def test_marking_page_protected_actually_gates_it(app_env):
    from mediahub.sites.store import load_site

    c = app_env.test_client()
    _login(c)
    site_id = _save_two_page_site()
    # Set a password, then mark the members page members-only.
    c.post(f"/api/sites/{site_id}/password", data={"password": "secret123"})
    r = c.post(f"/api/sites/{site_id}/page-protection", data={"protected": "members"})
    assert r.status_code == 302
    spec = load_site("club-a", site_id)
    prot = {p.slug: p.protected for p in spec.pages}
    # The home page's blank slug normalises to "home"; only "members" is gated.
    assert prot == {"home": False, "members": True}


def test_protected_page_without_password_warns(app_env):
    c = app_env.test_client()
    _login(c)
    site_id = _save_two_page_site()
    # Protect a page but set no password — honest warning, not a false success.
    r = c.post(f"/api/sites/{site_id}/page-protection", data={"protected": "members"})
    assert r.status_code == 302
    assert "no password is set" in unquote_plus(r.headers["Location"])
