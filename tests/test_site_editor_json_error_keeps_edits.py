"""tests/test_site_editor_json_error_keeps_edits.py — a JSON typo in the site
editor no longer throws away the user's edits (audit finding H-6).

On an invalid-JSON save the route redirected to the editor, which re-rendered
from the STORED spec — so every edit was gone — and the "nothing saved" flash
rendered with the success border colour, so the failure looked like a
confirmation. Twenty minutes of editing destroyed by one trailing comma.

The fix re-renders the editor in place with the submitted text preserved and an
error-styled message (and adds client-side JSON validation before submit).
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    for sub in ("runs_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app


def _login(client, pid="club-a"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name="Club A"))
    with client.session_transaction() as s:
        s["active_profile_id"] = pid


def _seed_site(pid="club-a", title="Otters"):
    from mediahub.sites.models import SitePage, SiteSection, SiteSpec, hero
    from mediahub.sites.store import save_site

    spec = SiteSpec(
        title=title,
        archetype="club_home",
        pages=[SitePage(title="Home", slug="", sections=[SiteSection(blocks=[hero("Hi")])])],
    )
    save_site(pid, spec)
    return spec.site_id


def test_invalid_json_save_preserves_text_and_shows_error(app_env):
    c = app_env.test_client()
    _login(c)
    site_id = _seed_site()

    bad = '{ "title": "My New Title", oops not json ,,'
    r = c.post(f"/api/sites/{site_id}/save", data={"spec": bad})

    # Re-rendered in place (400), not a 302 redirect that reloads the stored spec.
    assert r.status_code == 400, r.status_code
    body = r.data.decode()
    # The user's submitted text is kept in the textarea...
    assert "oops not json" in body, "the submitted text must be preserved"
    # ...an honest error message is shown...
    assert "wasn't valid JSON" in body or "wasn&#39;t valid JSON" in body
    # ...styled as an error, not the success colour.
    assert "var(--mh-bad" in body

    # And the stored spec is untouched — nothing was saved.
    from mediahub.sites.store import load_site

    assert load_site("club-a", site_id).title == "Otters"


def test_valid_json_save_persists_and_redirects(app_env):
    c = app_env.test_client()
    _login(c)
    site_id = _seed_site()

    good = '{"title": "Renamed Club", "archetype": "club_home", "pages": []}'
    r = c.post(f"/api/sites/{site_id}/save", data={"spec": good})
    assert r.status_code in (301, 302)

    from mediahub.sites.store import load_site

    assert load_site("club-a", site_id).title == "Renamed Club"


def test_editor_has_client_side_json_guard(app_env):
    c = app_env.test_client()
    _login(c)
    site_id = _seed_site()
    body = c.get(f"/sites/{site_id}").data.decode()
    assert "mhSiteSpecValid" in body
