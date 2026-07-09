"""H-5 (site surface) — editing a microsite no longer requires raw spec JSON.

The site editor now renders a structured "Edit content" card (per-block title /
text / link fields) that POSTs to /api/sites/<id>/content-edit; the raw JSON
textarea is kept, relabelled "Advanced". A content-edit applies only the
whitelisted props by id and preserves everything else (advanced blocks, ids).
"""

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
    return app, wm


def _login(client, pid="club-a"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name=pid.title()))
    with client.session_transaction() as s:
        s["active_profile_id"] = pid


def _site(pid="club-a", *, advanced=False):
    from mediahub.documents.models import Block
    from mediahub.sites.models import SitePage, SiteSection, SiteSpec, hero
    from mediahub.sites.store import save_site

    blocks = [hero("Hi", subhead="welcome")]
    if advanced:
        blocks.append(Block("card_grid", {"cards": [{"src": "a.jpg"}], "columns": 3}))
    spec = SiteSpec(
        title="Otters",
        archetype="club_home",
        tagline="",
        pages=[SitePage(title="Home", slug="", sections=[SiteSection(blocks=blocks)])],
    )
    save_site(pid, spec)
    return spec


def test_editor_renders_structured_form(app_env):
    app, _wm = app_env
    with app.test_client() as c:
        _login(c)
        spec = _site()
        if not _wm._sites_ok:
            pytest.skip("sites feature not enabled")
        html = c.get(f"/sites/{spec.site_id}").get_data(as_text=True)
        # Structured card present; raw JSON hatch relabelled "Advanced".
        assert "Edit content" in html
        assert "Advanced — raw spec (JSON)" in html
        bid = spec.pages[0].sections[0].blocks[0].block_id
        assert f"block__{bid}__headline" in html
        assert f'action="/api/sites/{spec.site_id}/content-edit"' in html


def test_content_edit_applies_and_persists(app_env):
    app, _wm = app_env
    from mediahub.sites.store import load_site

    with app.test_client() as c:
        _login(c)
        spec = _site()
        if not _wm._sites_ok:
            pytest.skip("sites feature not enabled")
        bid = spec.pages[0].sections[0].blocks[0].block_id
        r = c.post(
            f"/api/sites/{spec.site_id}/content-edit",
            data={f"block__{bid}__headline": "Welcome Otters", "spec__tagline": "Fast fish"},
        )
        assert r.status_code in (302, 303), r.status_code
        saved = load_site("club-a", spec.site_id)
        assert saved.pages[0].sections[0].blocks[0].props["headline"] == "Welcome Otters"
        # untouched hero prop survives; spec chrome applied
        assert saved.pages[0].sections[0].blocks[0].props["subhead"] == "welcome"
        assert saved.tagline == "Fast fish"


def test_content_edit_preserves_advanced_blocks(app_env):
    app, _wm = app_env
    from mediahub.sites.store import load_site

    with app.test_client() as c:
        _login(c)
        spec = _site(advanced=True)
        if not _wm._sites_ok:
            pytest.skip("sites feature not enabled")
        bid = spec.pages[0].sections[0].blocks[0].block_id
        c.post(f"/api/sites/{spec.site_id}/content-edit", data={f"block__{bid}__headline": "Edited"})
        saved = load_site("club-a", spec.site_id)
        kinds = [b.kind for b in saved.pages[0].sections[0].blocks]
        assert kinds == ["hero", "card_grid"]
        # the advanced block is byte-for-byte intact
        assert saved.pages[0].sections[0].blocks[1].props == {
            "cards": [{"src": "a.jpg"}],
            "columns": 3,
        }


def test_content_edit_foreign_profile_404(app_env):
    app, _wm = app_env
    with app.test_client() as c:
        _login(c, "club-a")
        spec = _site("club-a")
        if not _wm._sites_ok:
            pytest.skip("sites feature not enabled")
    with app.test_client() as c2:
        _login(c2, "club-b")
        r = c2.post(f"/api/sites/{spec.site_id}/content-edit", data={"spec__title": "x"})
        assert r.status_code == 404


def test_json_hatch_still_works(app_env):
    """H-6 non-regression: the raw JSON save path is untouched."""
    app, _wm = app_env
    from mediahub.sites.store import load_site

    with app.test_client() as c:
        _login(c)
        spec = _site()
        if not _wm._sites_ok:
            pytest.skip("sites feature not enabled")
        good = '{"title": "Via JSON", "pages": []}'
        r = c.post(f"/api/sites/{spec.site_id}/save", data={"spec": good})
        assert r.status_code in (302, 303)
        assert load_site("club-a", spec.site_id).title == "Via JSON"


# --- newsletter surface ------------------------------------------------------


def _newsletter(pid="club-a"):
    from mediahub.email_design.models import EmailBlock, NewsletterSpec, Section
    from mediahub.email_design.store import save_newsletter

    spec = NewsletterSpec(
        title="March", sections=[Section(blocks=[EmailBlock("heading", {"text": "Hi"})])]
    )
    save_newsletter(pid, spec)
    return spec


def test_newsletter_editor_and_content_edit(app_env):
    app, _wm = app_env
    from mediahub.email_design.store import load_newsletter

    with app.test_client() as c:
        _login(c)
        if not _wm._email_design_ok:
            pytest.skip("email design not enabled")
        spec = _newsletter()
        html = c.get(f"/newsletters/{spec.newsletter_id}").get_data(as_text=True)
        assert "Edit content" in html
        assert "Advanced — raw spec (JSON)" in html
        bid = spec.sections[0].blocks[0].block_id
        assert f"block__{bid}__text" in html
        r = c.post(
            f"/api/newsletters/{spec.newsletter_id}/content-edit",
            data={f"block__{bid}__text": "Season review", "spec__subject": "News"},
        )
        assert r.status_code in (302, 303)
        saved = load_newsletter("club-a", spec.newsletter_id)
        assert saved.sections[0].blocks[0].props["text"] == "Season review"
        assert saved.subject == "News"


def test_newsletter_content_edit_foreign_404(app_env):
    app, _wm = app_env
    with app.test_client() as c:
        _login(c, "club-a")
        if not _wm._email_design_ok:
            pytest.skip("email design not enabled")
        spec = _newsletter("club-a")
    with app.test_client() as c2:
        _login(c2, "club-b")
        assert (
            c2.post(
                f"/api/newsletters/{spec.newsletter_id}/content-edit", data={"spec__title": "x"}
            ).status_code
            == 404
        )


# --- document surface --------------------------------------------------------


def _document(pid="club-a"):
    from mediahub.documents.models import DocumentSpec, Section, heading
    from mediahub.documents.store import save_document

    spec = DocumentSpec(title="Report", sections=[Section(blocks=[heading("Overview")])])
    save_document(pid, spec)
    return spec


def test_document_editor_and_content_edit(app_env):
    app, _wm = app_env
    from mediahub.documents.store import load_document

    with app.test_client() as c:
        _login(c)
        if not _wm._documents_ok:
            pytest.skip("documents not enabled")
        spec = _document()
        html = c.get(f"/documents/{spec.doc_id}").get_data(as_text=True)
        assert "Edit content" in html
        assert "Advanced — raw spec (JSON)" in html
        bid = spec.sections[0].blocks[0].block_id
        assert f"block__{bid}__text" in html
        r = c.post(
            f"/api/documents/{spec.doc_id}/content-edit",
            data={f"block__{bid}__text": "Year in review", "spec__title": "AGM 2026"},
        )
        assert r.status_code in (302, 303)
        saved = load_document("club-a", spec.doc_id)
        assert saved.sections[0].blocks[0].props["text"] == "Year in review"
        assert saved.title == "AGM 2026"
