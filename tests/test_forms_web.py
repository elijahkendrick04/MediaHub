"""Forms engine (roadmap 1.16) — build 4: the web surface + public submit."""

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

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, wm, tmp_path


def _login(client, pid="club-a"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name="Otters"))
    with client.session_transaction() as s:
        s["active_profile_id"] = pid


def _published_site_with_form(pid="club-a"):
    """Create a form + a published site embedding it; return (form, token)."""
    from mediahub.forms.models import FormSpec, FormField
    from mediahub.forms.store import save_form
    from mediahub.sites.models import SitePage, SiteSection, SiteSpec, form_embed
    from mediahub.sites.store import publish_site, save_site, site_record

    form = FormSpec(
        title="RSVP",
        fields=[
            FormField(label="Name", required=True),
            FormField(label="Email", type="email", required=True),
        ],
    )
    save_form(pid, form)
    spec = SiteSpec(
        title="Event",
        pages=[
            SitePage(
                title="Home", slug="", sections=[SiteSection(blocks=[form_embed(form.form_id)])]
            )
        ],
    )
    save_site(pid, spec)
    publish_site(pid, spec.site_id)
    token = site_record(pid, spec.site_id)["public_token"]
    return form, token, spec.site_id


def test_create_form_from_template(app_env):
    app, _wm, _ = app_env
    c = app.test_client()
    _login(c)
    r = c.post("/api/forms", data={"title": "Trial sign-up", "template": "trial_signup"})
    assert r.status_code in (302, 303)
    from mediahub.forms.store import list_forms

    forms = list_forms("club-a")
    assert len(forms) == 1
    assert forms[0]["collects_minor_data"] is True


def test_public_form_submit_writes_row(app_env):
    app, _wm, _ = app_env
    _login(app.test_client())  # ensure profile exists
    form, token, _site_id = _published_site_with_form()

    pub = app.test_client()
    r = pub.post(
        f"/site/{token}/form/{form.form_id}",
        json={"name": "Sam", "email": "sam@club.example"},
    )
    assert r.status_code == 200 and r.get_json()["ok"]

    # the response landed in the data hub as a typed row
    from mediahub.data_hub import store as dh
    from mediahub.forms.store import load_form

    table_id = load_form("club-a", form.form_id).table_id
    assert table_id
    table = dh.get_org_table("club-a", table_id)
    assert len(table.rows) == 1
    assert table.rows[0]["name"].display == "Sam"


def test_public_form_submit_validation_errors(app_env):
    app, _wm, _ = app_env
    _login(app.test_client())
    form, token, _ = _published_site_with_form()
    pub = app.test_client()
    r = pub.post(f"/site/{token}/form/{form.form_id}", json={"name": "", "email": "bad"})
    assert r.status_code == 400
    errs = r.get_json()["errors"]
    assert "name" in errs and "email" in errs


def test_cannot_submit_form_not_embedded_in_site(app_env):
    app, _wm, _ = app_env
    _login(app.test_client())
    _form, token, _ = _published_site_with_form()
    pub = app.test_client()
    # a different, un-embedded form id must not accept submissions via this token
    r = pub.post(f"/site/{token}/form/form_doesnotexist", json={"name": "x"})
    assert r.status_code == 404


def test_form_delete(app_env):
    app, _wm, _ = app_env
    c = app.test_client()
    _login(c)
    from mediahub.forms.models import FormSpec
    from mediahub.forms.store import save_form

    spec = FormSpec(title="Old form")
    save_form("club-a", spec)
    c.post(f"/api/forms/{spec.form_id}/delete", data={})
    from mediahub.forms.store import load_form

    assert load_form("club-a", spec.form_id) is None
