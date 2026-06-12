"""UK legal baseline — acceptance wiring.

Covers: signup requires and records a versioned ToS acceptance; login routes
stale/legacy accounts through /legal/accept (re-acceptance when
TERMS_VERSION changes); the terms gate blocks signed-in navigation until
re-acceptance; and workspace setup requires + records the DPA and
lawful-basis/parental-consent attestation (per-workspace, versioned,
timestamped).
"""

from __future__ import annotations

import pytest


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _signup(client, email="officer@club.org", password="twelvechars1", accept="1"):
    data = {"email": email, "password": password}
    if accept:
        data["accept_terms"] = accept
    return client.post("/signup", data=data)


# ---- signup ---------------------------------------------------------------


def test_signup_without_acceptance_is_rejected(client, tmp_path):
    r = _signup(client, accept="")
    assert r.status_code == 400
    assert "accept the Terms" in r.get_data(as_text=True)
    # No account, no acceptance record.
    assert not (tmp_path / "users.jsonl").exists()
    assert not (tmp_path / "legal_acceptances.jsonl").exists()


def test_signup_records_versioned_timestamped_acceptance(client, tmp_path):
    from mediahub.web import legal

    r = _signup(client)
    assert r.status_code == 302
    store = legal.AcceptanceStore()
    acc = store.latest("officer@club.org", legal.DOC_TERMS)
    assert acc is not None
    assert acc.version == legal.TERMS_VERSION
    assert acc.accepted_at.startswith("20")  # ISO timestamp


def test_signup_form_links_terms_and_privacy(client):
    html = client.get("/signup").get_data(as_text=True)
    assert 'name="accept_terms"' in html
    assert 'href="/terms"' in html and 'href="/privacy"' in html


# ---- re-acceptance on version change ---------------------------------------


def test_login_routes_stale_acceptance_through_reaccept(client, monkeypatch):
    from mediahub.web import legal

    _signup(client)
    client.get("/logout")
    # Simulate a Terms revision after this account accepted.
    monkeypatch.setattr(legal, "TERMS_VERSION", "2099-01-01")
    r = client.post("/login", data={"email": "officer@club.org", "password": "twelvechars1"})
    assert r.status_code == 302
    assert "/legal/accept" in r.headers["Location"]


def test_reaccept_page_and_post_record_new_version(client, monkeypatch):
    from mediahub.web import legal

    _signup(client)
    client.get("/logout")
    monkeypatch.setattr(legal, "TERMS_VERSION", "2099-01-01")
    client.post("/login", data={"email": "officer@club.org", "password": "twelvechars1"})
    page = client.get("/legal/accept")
    assert page.status_code == 200
    assert "2099-01-01" in page.get_data(as_text=True)
    r = client.post("/legal/accept", data={"accept_terms": "1"})
    assert r.status_code == 302
    assert legal.AcceptanceStore().has_accepted("officer@club.org", legal.DOC_TERMS, "2099-01-01")


def test_terms_gate_blocks_navigation_until_reaccepted(app, monkeypatch):
    from mediahub.web import legal

    client = app.test_client()
    _signup(client)
    monkeypatch.setattr(legal, "TERMS_VERSION", "2099-01-01")
    app.config["ENFORCE_TERMS_GATE"] = True
    r = client.get("/billing")
    assert r.status_code == 302
    assert "/legal/accept" in r.headers["Location"]
    # Legal pages themselves stay reachable (the user must be able to READ
    # what they're accepting), as does logout.
    assert client.get("/terms").status_code == 200
    # API calls answer JSON 403, not a redirect.
    r = client.get("/api/organisation")
    assert r.status_code == 403
    assert r.get_json()["error"] == "terms_reacceptance_required"
    # Accept → gate opens.
    client.post("/legal/accept", data={"accept_terms": "1"})
    r = client.get("/billing")
    assert "/legal/accept" not in (r.headers.get("Location") or "")


# ---- workspace DPA + lawful-basis attestation ------------------------------


def test_org_setup_requires_attestation_when_enforced(app, tmp_path):
    from mediahub.web import legal

    app.config["ENFORCE_ATTESTATION_GATE"] = True
    client = app.test_client()
    # Manual setup without the checkboxes → bounced back to the form,
    # no profile created, nothing recorded.
    r = client.post("/organisation/setup/manual", data={"display_name": "Sharks SC"})
    assert r.status_code == 302
    assert "/organisation/setup" in r.headers["Location"]
    store = legal.AcceptanceStore()
    assert not store.org_has_acceptance("sharks-sc", legal.DOC_DPA, legal.DPA_VERSION)

    # With both attestations → recorded against the workspace.
    r = client.post(
        "/organisation/setup/manual",
        data={
            "display_name": "Sharks SC",
            "accept_dpa": "1",
            "confirm_lawful_basis": "1",
        },
    )
    assert r.status_code in (200, 302)
    assert store.org_has_acceptance("sharks-sc", legal.DOC_DPA, legal.DPA_VERSION)
    assert store.org_has_acceptance("sharks-sc", legal.DOC_DATA_ATTESTATION, legal.DPA_VERSION)


def test_org_setup_attestation_not_required_twice(app):
    from mediahub.web import legal

    app.config["ENFORCE_ATTESTATION_GATE"] = True
    client = app.test_client()
    client.post(
        "/organisation/setup/manual",
        data={
            "display_name": "Orcas SC",
            "accept_dpa": "1",
            "confirm_lawful_basis": "1",
        },
    )
    assert legal.AcceptanceStore().org_has_acceptance("orcas-sc", legal.DOC_DPA, legal.DPA_VERSION)
    # Re-running setup for the same workspace doesn't demand the boxes again:
    # the update (org_type change) goes through without the checkboxes.
    r = client.post(
        "/organisation/setup/manual",
        data={"display_name": "Orcas SC", "org_type": "university_society"},
    )
    assert r.status_code in (200, 302)
    from mediahub.web.club_profile import load_profile

    prof = load_profile("orcas-sc")
    assert prof is not None and prof.org_type == "university_society"


def test_setup_form_shows_attestation_block(client):
    html = client.get("/organisation/setup").get_data(as_text=True)
    assert 'name="accept_dpa"' in html
    assert 'name="confirm_lawful_basis"' in html
    assert "parental consent" in html
