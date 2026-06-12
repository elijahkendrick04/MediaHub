"""Route tests for the operator-only commercial console (/operator/commercial).

Pins the access posture (the page does not exist without MEDIAHUB_DEV_KEY;
non-operator sessions are redirected to the developer sign-in) and the main
PC.4/PC.6/PC.3 flows: quote add → manual payment → gate readout, lead add →
update, NGB state, and the operator pre-bind → signup → bound-workspace path.
"""

from __future__ import annotations

from unittest import mock

import pytest

DEV_KEY = "operator-key-for-commercial-tests"
PASSWORD = "twelve-chars-long"


def _make_app(monkeypatch, tmp_path, *, dev_key: str | None = DEV_KEY, stripe: bool = False):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    if dev_key is None:
        monkeypatch.delenv("MEDIAHUB_DEV_KEY", raising=False)
    else:
        monkeypatch.setenv("MEDIAHUB_DEV_KEY", dev_key)
    if stripe:
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_placeholder_not_a_real_key")
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_placeholder")
    else:
        monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
        monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    return app


def _login_operator(client, key: str = DEV_KEY):
    r = client.post("/developer", data={"dev_key": key})
    assert r.status_code in (302, 303)


def test_console_404s_without_dev_key(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, dev_key=None)
    c = app.test_client()
    assert c.get("/operator/commercial").status_code == 404
    assert c.post("/operator/commercial/quotes", data={}).status_code == 404
    assert c.post("/operator/commercial/bind", data={}).status_code == 404


def test_console_redirects_non_operator_to_developer_login(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    c = app.test_client()
    r = c.get("/operator/commercial")
    assert r.status_code in (302, 303)
    assert "/developer" in r.headers["Location"]
    # A signed-in regular USER is still not the operator.
    c.post("/signup", data={"email": "user@club.org", "password": PASSWORD, "accept_terms": "1"})
    r = c.get("/operator/commercial")
    assert r.status_code in (302, 303)
    assert "/developer" in r.headers["Location"]


def test_operator_quote_flow_and_gates(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    c = app.test_client()
    _login_operator(c)

    r = c.get("/operator/commercial")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "0<" in body and "/ 5" in body and "/ 10" in body  # both gates open

    # Add a quote (£588 → 58800p), then record the real payment manually.
    r = c.post(
        "/operator/commercial/quotes",
        data={"club_name": "Swansea Aquatics", "contact_email": "chair@sa.org", "pounds": "588"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "Swansea Aquatics" in r.get_data(as_text=True)

    from mediahub.commercial.wtp import QuoteStore

    quote = QuoteStore().list_all()[0]
    assert quote.amount_pence == 58800

    r = c.post(
        "/operator/commercial/quotes/update",
        data={"quote_id": quote.quote_id, "op": "paid_manual", "paid_pounds": "588"},
        follow_redirects=True,
    )
    body = r.get_data(as_text=True)
    assert "paid" in body
    assert QuoteStore().get(quote.quote_id).status == "paid"
    assert "1<" in body  # gate counters moved


def test_checkout_link_honest_error_without_stripe(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, stripe=False)
    c = app.test_client()
    _login_operator(c)
    c.post("/operator/commercial/quotes", data={"club_name": "Club A", "pounds": "588"})
    from mediahub.commercial.wtp import QuoteStore

    quote = QuoteStore().list_all()[0]
    r = c.post(
        "/operator/commercial/quotes/update",
        data={"quote_id": quote.quote_id, "op": "checkout"},
        follow_redirects=True,
    )
    assert "Billing is not configured" in r.get_data(as_text=True)
    assert QuoteStore().get(quote.quote_id).last_checkout_url == ""


def test_checkout_link_created_when_stripe_configured(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, stripe=True)
    c = app.test_client()
    _login_operator(c)
    c.post(
        "/operator/commercial/quotes",
        data={"club_name": "Club A", "contact_email": "chair@a.org", "pounds": "828"},
    )
    from mediahub.commercial.wtp import QuoteStore

    quote = QuoteStore().list_all()[0]

    captured: dict = {}

    def _fake_create(**kwargs):
        captured.update(kwargs)
        return {"url": "https://checkout.stripe.test/sess_123"}

    import stripe as stripe_pkg

    with mock.patch.object(stripe_pkg.checkout.Session, "create", side_effect=_fake_create):
        r = c.post(
            "/operator/commercial/quotes/update",
            data={"quote_id": quote.quote_id, "op": "checkout"},
            follow_redirects=True,
        )
    assert "Checkout link created" in r.get_data(as_text=True)
    assert QuoteStore().get(quote.quote_id).last_checkout_url == (
        "https://checkout.stripe.test/sess_123"
    )
    # The session charges exactly the quoted annual figure and carries the
    # quote id for webhook attribution.
    li = captured["line_items"][0]["price_data"]
    assert li["unit_amount"] == 82800
    assert li["recurring"] == {"interval": "year"}
    assert captured["metadata"]["mediahub_quote_id"] == quote.quote_id
    assert captured["mode"] == "subscription"


def test_lead_and_ngb_flows(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    c = app.test_client()
    _login_operator(c)

    r = c.post(
        "/operator/commercial/leads",
        data={"club_name": "Neath SC", "region": "Neath", "source": "warm_local"},
        follow_redirects=True,
    )
    assert "Neath SC" in r.get_data(as_text=True)
    from mediahub.commercial.pipeline import LeadStore

    lead = LeadStore().list_all()[0]
    r = c.post(
        "/operator/commercial/leads/update",
        data={"lead_id": lead.lead_id, "status": "won", "intros": "Cardiff SC, Bridgend SC"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    updated = LeadStore().get(lead.lead_id)
    assert updated.status == "won"
    assert updated.intros == ["Cardiff SC", "Bridgend SC"]

    r = c.post(
        "/operator/commercial/ngb",
        data={"status": "applied", "notes": "Submitted via the approved-systems form."},
        follow_redirects=True,
    )
    assert "applied" in r.get_data(as_text=True)
    from mediahub.commercial import ngb

    assert ngb.load_state()["status"] == "applied"


def test_bind_invite_then_signup_binds_workspace(monkeypatch, tmp_path):
    """The PC.3 founder tool end-to-end: pre-bind a pilot org's email from the
    console, pilot keeps working anonymously, then their signup binds it."""
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    app = _make_app(monkeypatch, tmp_path)

    import importlib

    import mediahub.web.club_profile as cp

    importlib.reload(cp)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="org-pilot",
            display_name="Pilot SC",
            brand_voice_summary="Bold, energetic.",
        )
    )

    c = app.test_client()
    _login_operator(c)
    r = c.post(
        "/operator/commercial/bind",
        data={"profile_id": "org-pilot", "email": "chair@pilot.org"},
        follow_redirects=True,
    )
    assert "invited as owner" in r.get_data(as_text=True)

    from mediahub.web.tenancy import MembershipStore

    ms = MembershipStore()
    assert ms.is_bound("org-pilot") is False  # invite must not lock the pilot out

    # Anonymous pilot session still works (open workspace).
    anon = app.test_client()
    assert anon.post("/api/organisation/active", data={"profile_id": "org-pilot"}).status_code == 200

    # The pilot signs up — org binds, anonymous access ends.
    new = app.test_client()
    new.post("/signup", data={"email": "chair@pilot.org", "password": PASSWORD, "accept_terms": "1"})
    assert ms.is_bound("org-pilot") is True
    assert ms.is_active_owner("chair@pilot.org", "org-pilot") is True
    anon2 = app.test_client()
    assert (
        anon2.post("/api/organisation/active", data={"profile_id": "org-pilot"}).status_code == 404
    )


def test_bind_unknown_profile_is_a_clean_error(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    c = app.test_client()
    _login_operator(c)
    r = c.post(
        "/operator/commercial/bind",
        data={"profile_id": "ghost", "email": "x@y.org"},
        follow_redirects=True,
    )
    assert "No profile with id" in r.get_data(as_text=True)
