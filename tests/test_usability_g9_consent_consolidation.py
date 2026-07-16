"""G-9 — the two consent surfaces are consolidated with /athletes as the truth.

/athletes now carries a two-tab strip: "Roster & permissions" (the levels
MediaHub enforces on content, via mediahub.safeguarding) and "Consent records"
(the compliance registry — grant/refuse/revoke decisions, lawful basis, child
controls, retention — moved verbatim from /organisation/consent). The
ConsentRegistry store and its records are untouched: only the page moved.
/organisation/consent keeps its endpoint (and its 404-without-organisation
gate) but redirects signed-in officers to /athletes?tab=records; every inbound
link (Settings → Privacy) is repointed. F-8's plain-English copy and I-3's
scroll wrapper ride along unchanged.
"""

from __future__ import annotations

import pytest

from mediahub.web.club_profile import ClubProfile, save_profile

ORG = "org-a"
FOREIGN_ORG = "org-b"


@pytest.fixture
def client(app):
    save_profile(ClubProfile(profile_id=ORG, display_name="Org A"))
    save_profile(ClubProfile(profile_id=FOREIGN_ORG, display_name="Org B"))
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = ORG
    return c


# ------------------------------------------------------------ the redirect


def test_old_url_redirects_to_the_records_tab(client):
    r = client.get("/organisation/consent")
    assert r.status_code == 302
    assert "/athletes?tab=records" in r.headers["Location"]


def test_old_url_still_404s_without_an_organisation(client):
    """The move must not weaken the tenant gate: an anonymous session gets
    the same 404 the old page gave, never a redirect into the registry."""
    with client.session_transaction() as s:
        s.clear()
    assert client.get("/organisation/consent").status_code == 404
    # And the registry tab itself renders only the sign-in prompt.
    page = client.get("/athletes?tab=records")
    assert page.status_code == 200
    assert b"Pick an organisation" in page.data
    assert b"Lawful basis" not in page.data


# ------------------------------------------------------- the records tab


def test_records_tab_renders_the_same_records_from_the_same_store(client):
    from mediahub.compliance.consent import ConsentRegistry

    ConsentRegistry(ORG).record(
        athlete_name="Eira Hughes",
        status="granted",
        parental=True,
        under_18=True,
        note="Form signed by parent 2026-06-01",
    )
    html = client.get("/athletes?tab=records").get_data(as_text=True)
    # The registry table, record form, lawful basis, child controls and
    # retention all render on the tab.
    assert "Eira Hughes" in html
    assert ">granted<" in html
    assert "Lawful basis" in html
    assert "Record a consent decision" in html
    assert "Under-18 content controls" in html
    assert "Retention" in html
    # I-3's phone scroll wrapper rides along.
    assert "mh-table-scroll" in html
    # F-8's plain-English labels are unchanged.
    assert "They (or a parent) said yes" in html
    assert "Pause all use of their data" in html
    assert "Restrict processing (Art 18)" not in html


def test_record_posted_via_old_route_lands_in_the_registry_and_new_tab(client):
    r = client.post(
        "/organisation/consent/record",
        data={"athlete_name": "Maya Patel", "status": "refused"},
    )
    assert r.status_code == 302
    assert "/athletes?tab=records" in r.headers["Location"]

    from mediahub.compliance.consent import ConsentRegistry

    assert ConsentRegistry(ORG).get("Maya Patel").status == "refused"
    assert b"Maya Patel" in client.get("/athletes?tab=records").data


def test_settings_posts_redirect_to_the_records_tab(client):
    for path, data in (
        ("/organisation/consent/settings", {"consent_mode": "opt_in"}),
        ("/organisation/consent/child-policy", {"child_surname_initial": "1"}),
        ("/organisation/consent/retention", {"runs": "30"}),
    ):
        r = client.post(path, data=data)
        assert r.status_code == 302, path
        assert "/athletes?tab=records" in r.headers["Location"], path


def test_foreign_org_never_sees_another_orgs_records(client):
    from mediahub.compliance.consent import ConsentRegistry

    ConsentRegistry(ORG).record(athlete_name="Athlete A", status="refused")
    with client.session_transaction() as s:
        s.clear()
        s["active_profile_id"] = FOREIGN_ORG
    page = client.get("/athletes?tab=records")
    assert page.status_code == 200
    assert b"Athlete A" not in page.data


# ------------------------------------------------------------- signposting


def test_both_tabs_carry_the_strip_and_framing(client):
    roster = client.get("/athletes").get_data(as_text=True)
    assert "Roster &amp; permissions" in roster
    assert "Consent records" in roster
    assert "/athletes?tab=records" in roster
    # Plain-English framing: permissions = enforced; records = the decisions.
    assert (
        "what\nMediaHub enforces on content" in roster
        or "what MediaHub enforces on content" in roster
    )

    records = client.get("/athletes?tab=records").get_data(as_text=True)
    assert "Roster &amp; permissions" in records
    assert "signed" in records and "decisions" in records
    # The records tab links back to the roster tab.
    assert 'href="/athletes"' in records


def test_settings_privacy_links_to_the_new_home(client):
    body = client.get("/settings/privacy").get_data(as_text=True)
    assert "/athletes?tab=records" in body
    # No Settings link points at the retired page location any more.
    assert 'href="/organisation/consent"' not in body
