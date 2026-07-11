"""F-8 — the consent & athlete-rights UI must lead with plain English.

A club safeguarding officer is explicitly a non-lawyer, yet the forms led with
statute: "Consent (Art 6(1)(a))", "Restrict processing (Art 18)", "Access —
export everything we hold (SAR)", "stop-the-clock rules (Article 12A)". Each now
leads with the plain-English meaning; the legal citation is demoted to a muted
helper line or a hover tooltip.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.web import create_app

    save_profile(ClubProfile(profile_id="clubx", display_name="Club X"))
    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "x"
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "clubx"
    return c


def test_consent_lawful_basis_leads_with_plain_english(client):
    # G-9 moved the registry to /athletes?tab=records; the old URL redirects.
    html = client.get("/organisation/consent", follow_redirects=True).get_data(as_text=True)
    # Plain-English option labels lead; the bare statute label is gone.
    assert "They (or a parent) said yes" in html
    assert "We have a good reason to" in html
    assert ">Consent (Art 6(1)(a))<" not in html
    # The article is demoted to a muted helper line, still present for accuracy.
    assert "Art&nbsp;6(1)(a)" in html or "Art 6(1)(a)" in html


def test_consent_restrict_checkbox_is_plain_language(client):
    # G-9 moved the registry to /athletes?tab=records; the old URL redirects.
    html = client.get("/organisation/consent", follow_redirects=True).get_data(as_text=True)
    assert "Pause all use of their data" in html
    assert "Restrict processing (Art 18)" not in html


def test_athlete_rights_request_types_lead_with_plain_english(client):
    html = client.get("/organisation/athlete-rights").get_data(as_text=True)
    assert "See everything we hold about them" in html
    assert "Pause all use of their data" in html
    # The bare jargon option labels are gone…
    assert "Access — export everything we hold (SAR)" not in html
    assert "Restriction — pause processing (Art 18)" not in html
    # …and the lede no longer leads with the article citation.
    assert "stop-the-clock rules (Article 12A)" not in html
    # The form still posts the same request-type values (behaviour unchanged).
    assert 'value="access"' in html and 'value="restriction"' in html
