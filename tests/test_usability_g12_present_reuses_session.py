"""G-12 — reloading the presenter console must not desync the live audience.

document_present called create_session on every page load, so any reload
(accidental refresh, laptop lid-close/wake) minted a new session; the already-open
audience view kept polling the OLD session while the reloaded console drove the NEW
one, so Next/Prev silently stopped moving the projector. The console now resumes
the existing live session for the same deck+owner, keeping the session and audience
URL stable across reloads.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def app_env(web_module, monkeypatch):
    # MEDIAHUB_SCHEDULER is read fresh by mediahub.scheduler._enabled() each time
    # start_scheduler() runs inside create_app() — no reload needed for it to take
    # effect, so it's set here, before create_app() is called below.
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    app = web_module.create_app()
    app.config["TESTING"] = True
    return app


def _login(client, pid="club-a"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name="Club A"))
    with client.session_transaction() as s:
        s["active_profile_id"] = pid


def _save_deck(pid="club-a", title="AGM 2026"):
    from mediahub.documents import models as m
    from mediahub.documents.models import DocumentSpec, Section
    from mediahub.documents.store import save_document

    spec = DocumentSpec(
        title=title,
        kind="deck",
        doc_format="agm_deck",
        geometry="slide_16_9",
        brand_profile_id=pid,
        sections=[
            Section(layout="cover", blocks=[m.heading(title, 1)], notes="Welcome."),
            Section(blocks=[m.heading("The year", 2)], notes="Numbers."),
            Section(layout="closing", blocks=[m.heading("Thanks", 1)]),
        ],
    )
    save_document(pid, spec)
    return spec


def test_get_live_for_returns_the_active_session(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.documents import presenter

    importlib.reload(presenter)
    assert presenter.get_live_for("d1", "club-a") is None
    s = presenter.create_session("d1", 3, owner="club-a")
    got = presenter.get_live_for("d1", "club-a")
    assert got is not None and got.session_id == s.session_id
    # a different deck/owner does not match
    assert presenter.get_live_for("d2", "club-a") is None
    assert presenter.get_live_for("d1", "club-b") is None
    # an ended session is not resumable
    presenter.apply_action(s.session_id, "end")
    assert presenter.get_live_for("d1", "club-a") is None


def test_console_reload_keeps_the_same_code(app_env):
    c = app_env.test_client()
    _login(c)
    spec = _save_deck()
    from mediahub.documents import presenter as _pres

    r1 = c.get(f"/documents/{spec.doc_id}/present")
    assert r1.status_code == 200
    s1 = _pres.get_live_for(spec.doc_id, "club-a")
    assert s1 is not None

    r2 = c.get(f"/documents/{spec.doc_id}/present")
    assert r2.status_code == 200
    s2 = _pres.get_live_for(spec.doc_id, "club-a")

    # Same session across the reload — no remint.
    assert s2.session_id == s1.session_id
    # Exactly one live session for this deck (not one per reload).
    live = [s for s in _pres._iter_live() if s.doc_id == spec.doc_id]
    assert len(live) == 1


def test_present_after_end_starts_a_fresh_session(app_env):
    c = app_env.test_client()
    _login(c)
    spec = _save_deck()
    from mediahub.documents import presenter as _pres

    c.get(f"/documents/{spec.doc_id}/present")
    s1 = _pres.get_live_for(spec.doc_id, "club-a")
    _pres.apply_action(s1.session_id, "end")
    # A deliberately ended talk is not resumed — reopening mints a new session.
    c.get(f"/documents/{spec.doc_id}/present")
    s2 = _pres.get_live_for(spec.doc_id, "club-a")
    assert s2 is not None and s2.session_id != s1.session_id
