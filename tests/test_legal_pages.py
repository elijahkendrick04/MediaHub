"""UK legal baseline — the legal documents and the acceptance ledger.

Covers: /terms, /privacy, /cookies, /dpa render and are publicly reachable
(before sign-in / org setup, with the gate enforced); the Privacy Notice
accurately names the real third-party flows and no longer carries the old
false "no data is sent to third parties" claim; the footer links every legal
page and shows the provider-identity block; and the AcceptanceStore ledger
records versioned, timestamped acceptances.
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


# ---- pages render ---------------------------------------------------------


@pytest.mark.parametrize("path", ["/terms", "/privacy", "/cookies", "/dpa"])
def test_legal_page_renders(client, path):
    r = client.get(path)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "DRAFT" in html and "solicitor review" in html


@pytest.mark.parametrize("path", ["/terms", "/privacy", "/cookies", "/dpa"])
def test_legal_pages_public_even_with_org_gate_enforced(app, path):
    # Art. 13 / CCR: the documents must be readable BEFORE signup/org setup.
    app.config["ENFORCE_ORG_GATE"] = True
    r = app.test_client().get(path)
    assert r.status_code == 200


def test_privacy_notice_describes_real_third_party_flows(client):
    html = client.get("/privacy").get_data(as_text=True)
    # The old notice falsely claimed nothing left the box. The rewritten
    # notice must name the actual recipients found in the data-flow audit.
    assert "No data is sent to third parties" not in html
    for recipient in ("Gemini", "Anthropic", "Photoroom", "Replicate", "Stripe", "Buffer"):
        assert recipient in html, f"privacy notice must disclose {recipient}"
    # Children's-data section and ICO complaint info are mandatory content.
    assert "under 18" in html or "under-18" in html
    assert "ico.org.uk" in html


def test_privacy_notice_hides_deployment_inventory_when_signed_out(client):
    html = client.get("/privacy").get_data(as_text=True)
    assert "Your data on this deployment" not in html


def test_terms_cover_consumer_law_essentials(client):
    html = client.get("/terms").get_data(as_text=True)
    # CCR 2013 cooling-off + digital-content waiver wording.
    assert "14 days" in html
    assert "cancel" in html.lower()
    # DMCCA: renewal disclosure + cancellation parity.
    assert "renew automatically" in html
    # CRA 2015 quality duty.
    assert "reasonable care and skill" in html


def test_cookie_policy_describes_essential_only_cookie(client):
    html = client.get("/cookies").get_data(as_text=True)
    assert "session" in html
    assert "Strictly necessary" in html
    assert "no analytics" in html.lower() or "No analytics" in html


def test_dpa_lists_subprocessors_and_breach_duty(client):
    html = client.get("/dpa").get_data(as_text=True)
    for sub in ("Gemini", "Anthropic", "Photoroom", "Replicate", "Buffer"):
        assert sub in html
    assert "without undue delay" in html
    assert "sub-processor" in html.lower()


def test_footer_links_all_legal_pages_and_identity(client):
    html = client.get("/terms").get_data(as_text=True)
    for path in ("/privacy", "/terms", "/cookies", "/dpa"):
        assert f'href="{path}"' in html
    # E-Commerce Regs identity block (placeholders until filled in).
    assert "[COMPANY_NAME]" in html
    assert "[CONTACT_EMAIL]" in html


# ---- acceptance ledger ------------------------------------------------------


def test_acceptance_store_records_and_reads_back(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web import legal

    store = legal.AcceptanceStore()
    acc = store.record("Officer@Club.org", legal.DOC_TERMS, legal.TERMS_VERSION)
    assert acc.email == "officer@club.org"
    assert acc.accepted_at  # timestamped
    assert store.has_accepted("officer@club.org", legal.DOC_TERMS, legal.TERMS_VERSION)
    latest = store.latest("officer@club.org", legal.DOC_TERMS)
    assert latest is not None and latest.version == legal.TERMS_VERSION


def test_acceptance_store_versioning_drives_reacceptance(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web import legal

    store = legal.AcceptanceStore()
    # No record at all → needs acceptance.
    assert store.needs_terms_reacceptance("a@club.org") is True
    store.record("a@club.org", legal.DOC_TERMS, "2020-01-01")  # an old version
    assert store.needs_terms_reacceptance("a@club.org") is True
    store.record("a@club.org", legal.DOC_TERMS, legal.TERMS_VERSION)
    assert store.needs_terms_reacceptance("a@club.org") is False


def test_acceptance_store_org_scoping_and_erasure(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web import legal

    store = legal.AcceptanceStore()
    store.record("a@club.org", legal.DOC_DPA, legal.DPA_VERSION, org_id="sharks")
    assert store.has_accepted("a@club.org", legal.DOC_DPA, legal.DPA_VERSION, org_id="sharks")
    assert not store.has_accepted("a@club.org", legal.DOC_DPA, legal.DPA_VERSION, org_id="orcas")
    removed = store.erase_email("a@club.org")
    assert removed == 1
    assert store.latest("a@club.org", legal.DOC_DPA, org_id="sharks") is None


def test_acceptance_ledger_file_permissions(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web import legal

    store = legal.AcceptanceStore()
    store.record("a@club.org", legal.DOC_TERMS, legal.TERMS_VERSION)
    mode = store.path.stat().st_mode & 0o777
    assert mode == 0o600
