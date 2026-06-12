"""UK legal baseline — post-publication correction/takedown workflow.

A wrong published result about a named child needs a recorded, auditable
correction path: open → wall exclusion → honest manual checklist → resolve.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def test_correction_store_roundtrip(data_dir):
    from mediahub.privacy import corrections as c

    cid = c.open_correction(
        profile_id="sharks", run_id="run1", card_id="c-jane", reason="wrong time"
    )
    assert cid > 0
    rows = c.list_corrections("sharks", status="open")
    assert len(rows) == 1 and rows[0]["reason"] == "wrong time"
    # Tenant-scoped: another org sees nothing and cannot resolve.
    assert c.list_corrections("orcas") == []
    assert c.resolve_correction(profile_id="orcas", correction_id=cid) is False
    assert c.resolve_correction(
        profile_id="sharks", correction_id=cid, resolution="reposted fixed card"
    )
    assert c.list_corrections("sharks", status="open") == []
    resolved = c.list_corrections("sharks")[0]
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"]


def test_open_correction_validates_input(data_dir):
    from mediahub.privacy import corrections as c

    assert c.open_correction(profile_id="", run_id="r", card_id="c", reason="x") == 0
    assert c.open_correction(profile_id="p", run_id="r", card_id="c", reason="") == 0


@pytest.fixture
def app(data_dir, monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    return application


def _pin_org(client, profile_id="sharks"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=profile_id, display_name="Sharks"))
    with client.session_transaction() as sess:
        sess["active_profile_id"] = profile_id
        sess["login_seen_at"] = 2**62  # never idle out during the test


def test_correction_route_records_and_excludes_from_wall(app, data_dir):
    client = app.test_client()
    _pin_org(client)
    r = client.post(
        "/privacy/correction",
        data={"run_id": "run1", "card_id": "c-jane", "reason": "misidentified athlete"},
    )
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    # Honest checklist: MediaHub cannot delete the platform post itself.
    assert "cannot edit or remove a post" in html
    from mediahub.privacy import list_corrections
    from mediahub.web.club_profile import load_profile

    assert list_corrections("sharks", status="open")
    prof = load_profile("sharks")
    assert "run1::c-jane" in (prof.public_wall_excluded_cards or [])


def test_correction_resolve_route(app, data_dir):
    client = app.test_client()
    _pin_org(client)
    client.post(
        "/privacy/correction",
        data={"run_id": "run1", "card_id": "c-1", "reason": "wrong club"},
    )
    from mediahub.privacy import list_corrections

    cid = list_corrections("sharks", status="open")[0]["id"]
    r = client.post(f"/privacy/correction/{cid}/resolve", data={"resolution": "done"})
    assert r.status_code == 302
    assert list_corrections("sharks", status="open") == []


def test_privacy_page_shows_correction_panel(app, data_dir):
    client = app.test_client()
    _pin_org(client)
    html = client.get("/privacy").get_data(as_text=True)
    assert "Correct a published card" in html
    assert 'action="/privacy/correction"' in html
