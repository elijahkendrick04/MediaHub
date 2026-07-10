"""H-17 — the /privacy correction and erase forms must fail loudly, not silently.

The correction form validated run/card ids with re.fullmatch and, on a
mismatch, redirected back to /privacy with NO message and the typed reason
discarded; the empty-name erase submit did the same. Both now re-render
/privacy with a styled inline error next to the failing form and every
submitted value preserved (escaped). Success paths keep their old behaviour.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


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
        sess["login_seen_at"] = 2**62


def test_correction_bad_ids_rerenders_with_error_and_preserved_values(app, data_dir):
    client = app.test_client()
    _pin_org(client)
    r = client.post(
        "/privacy/correction",
        data={
            "run_id": "not a valid id!!",
            "card_id": "c-jane",
            "reason": "wrong time recorded",
        },
    )
    assert r.status_code == 400
    html = r.get_data(as_text=True)
    # A styled inline error, next to the form on the re-rendered page.
    assert 'class="tag bad"' in html
    assert "look right" in html  # "That meet or card id doesn't look right…"
    # Every typed value survives the round-trip (escaped).
    assert 'value="not a valid id!!"' in html
    assert 'value="c-jane"' in html
    assert 'value="wrong time recorded"' in html
    # And nothing was recorded.
    from mediahub.privacy import list_corrections

    assert list_corrections("sharks", status="open") == []


def test_correction_missing_reason_rerenders_with_error(app, data_dir):
    client = app.test_client()
    _pin_org(client)
    r = client.post(
        "/privacy/correction",
        data={"run_id": "run1", "card_id": "c-1", "reason": "   "},
    )
    assert r.status_code == 400
    html = r.get_data(as_text=True)
    assert 'class="tag bad"' in html
    # The ids were fine — the error talks about the missing reason instead.
    assert "reason is recorded" in html
    assert 'value="run1"' in html
    assert 'value="c-1"' in html


def test_correction_error_values_are_escaped(app, data_dir):
    client = app.test_client()
    _pin_org(client)
    r = client.post(
        "/privacy/correction",
        data={
            "run_id": "bad id",
            "card_id": "c-1",
            "reason": '<script>alert(1)</script>',
        },
    )
    assert r.status_code == 400
    html = r.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_correction_success_path_unchanged(app, data_dir):
    client = app.test_client()
    _pin_org(client)
    r = client.post(
        "/privacy/correction",
        data={"run_id": "run1", "card_id": "c-jane", "reason": "misidentified athlete"},
    )
    assert r.status_code == 200
    assert "Correction" in r.get_data(as_text=True)
    from mediahub.privacy import list_corrections

    assert list_corrections("sharks", status="open")


def test_erase_empty_name_rerenders_with_error_and_keeps_club(app, data_dir):
    client = app.test_client()
    _pin_org(client)
    r = client.post(
        "/privacy/athlete/erase",
        data={"athlete_name": "   ", "athlete_club": "City Aquatics"},
    )
    assert r.status_code == 400
    html = r.get_data(as_text=True)
    assert 'class="tag bad"' in html
    assert "nothing was erased" in html
    # The optional club field the user typed survives.
    assert 'value="City Aquatics"' in html


def test_get_privacy_page_has_no_error_markup(app, data_dir):
    client = app.test_client()
    _pin_org(client)
    r = client.get("/privacy")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'role="alert"' not in html
    # Both forms are still there.
    assert 'action="/privacy/correction"' in html
    assert 'action="/privacy/athlete/erase"' in html
