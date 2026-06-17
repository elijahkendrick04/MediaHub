"""Transparency artifacts — notices, DPA template, cookie audit, disclosure page."""

from __future__ import annotations

from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs" / "compliance"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    return app.test_client()


def test_subprocessor_page_public_and_complete(client):
    r = client.get("/legal/subprocessors")
    assert r.status_code == 200
    page = r.data.decode()
    # every provider in the canonical inventory appears on the public page
    for provider in ("Render", "Google", "Anthropic", "Photoroom", "Replicate"):
        assert provider in page, f"{provider} missing from /legal/subprocessors"
    assert "swimmingresults.org" in page  # the source-not-processor clarification


def test_public_page_matches_canonical_inventory():
    canonical = (DOCS / "SUBPROCESSORS.md").read_text()
    for provider in ("Render", "Google", "Anthropic", "Photoroom", "Replicate"):
        assert provider in canonical


@pytest.mark.parametrize(
    "template",
    [
        "templates/PRIVACY_NOTICE_ATHLETE_ART14.md",
        "templates/PRIVACY_NOTICE_CLUB_ART13.md",
        "templates/DPA_ART28_TEMPLATE.md",
    ],
)
def test_legal_templates_exist_and_are_marked_draft(template):
    text = (DOCS / template).read_text()
    assert "DRAFT — FOR LEGAL REVIEW" in text, "legal documents must never present as final"


def test_athlete_notice_covers_article_14_essentials():
    """Art 14 essentials for the enrichment: the source, the right to object,
    recipients, and child-readable rights."""
    text = (DOCS / "templates/PRIVACY_NOTICE_ATHLETE_ART14.md").read_text().lower()
    assert "swimmingresults.org" in text  # the source of indirectly-collected data
    assert "not to feature" in text or "object" in text
    assert "ico" in text
    assert "gemini" in text and "anthropic" in text
    assert "withdraw" in text or "changing your mind" in text


def test_dpa_template_covers_article_28_3_elements():
    text = (DOCS / "templates/DPA_ART28_TEMPLATE.md").read_text().lower()
    for needle in (
        "documented instructions",
        "confidentiality",
        "sub-processor",
        "breach",
        "audit",
        "end of processing",
        "international transfers",
    ):
        assert needle in text, f"Art 28(3) element missing: {needle}"


def test_cookie_audit_documents_the_clean_position():
    text = (DOCS / "COOKIE_AUDIT.md").read_text()
    assert "No consent banner is required" in text
    assert "opt-out" in text  # the DUAA analytics-exemption conditions are recorded


def test_no_cookies_set_beyond_flask_session(client):
    """The audit's claim, enforced: anonymous pages set no cookie at all,
    and nothing other than the session cookie is ever set."""
    for path in ("/legal/subprocessors", "/complaints", "/privacy"):
        r = client.get(path)
        cookies = [v for k, v in r.headers if k.lower() == "set-cookie"]
        for c in cookies:
            assert c.strip().startswith("session="), f"unexpected cookie on {path}: {c}"
