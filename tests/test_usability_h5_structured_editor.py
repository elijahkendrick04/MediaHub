"""H-5 — editing a newsletter or document no longer requires raw spec JSON.

The newsletter/document editors render a structured "Edit content" card (per-block
title / text / link fields) that POSTs to /api/<surface>/<id>/content-edit; the raw
JSON textarea is kept, relabelled "Advanced". A content-edit applies only the
whitelisted props by id and preserves everything else (advanced blocks, ids).
"""

from __future__ import annotations

import pytest


@pytest.fixture
def app_env(web_module, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    app = web_module.create_app()
    app.config["TESTING"] = True
    return app, web_module


def _login(client, pid="club-a"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name=pid.title()))
    with client.session_transaction() as s:
        s["active_profile_id"] = pid


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
