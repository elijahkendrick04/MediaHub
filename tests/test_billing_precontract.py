"""UK legal baseline — CCR 2013 / DMCCA pre-contract checkout flow.

The pricing CTA routes through /billing/confirm (pre-contract information:
what you get, price honesty, auto-renewal disclosure, cancellation parity,
14-day cooling-off). Checkout refuses to start without the recorded
immediate-supply acknowledgement, and the acknowledgement lands in the
acceptance ledger with version + timestamp.
"""

from __future__ import annotations

from unittest import mock

import pytest

FAKE_PRICE_CLUB = "price_club_test_123"


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.setenv("STRIPE_PRICE_CLUB", FAKE_PRICE_CLUB)
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    return application


def _signup(client, email="buyer@club.org"):
    client.post(
        "/signup",
        data={"email": email, "password": "twelvechars1", "accept_terms": "1"},
    )


def test_pricing_cta_routes_through_confirm(app):
    c = app.test_client()
    _signup(c)
    html = c.get("/pricing").get_data(as_text=True)
    assert "/billing/confirm?plan=club" in html
    # The old direct-POST form is gone from the pricing page.
    assert 'action="/billing/checkout"' not in html


def test_confirm_page_carries_required_precontract_information(app):
    c = app.test_client()
    _signup(c)
    r = c.get("/billing/confirm?plan=club")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "renews automatically" in html  # DMCCA renewal disclosure
    assert "14 days" in html  # CCR cooling-off
    assert "Manage billing" in html  # cancellation parity
    assert 'name="immediate_supply"' in html  # express request control
    assert "/terms" in html


def test_confirm_rejects_unknown_plan(app):
    c = app.test_client()
    _signup(c)
    r = c.get("/billing/confirm?plan=free")
    assert r.status_code == 302
    assert "/pricing" in r.headers["Location"]


def test_checkout_blocked_without_acknowledgement(app):
    c = app.test_client()
    _signup(c)
    with mock.patch("stripe.checkout.Session.create") as m:
        r = c.post("/billing/checkout", data={"plan": "club"})
    assert r.status_code == 302
    assert "/billing/confirm" in r.headers["Location"]
    m.assert_not_called()


def test_checkout_records_cooling_off_acknowledgement(app, tmp_path):
    c = app.test_client()
    _signup(c)
    fake_session = mock.MagicMock()
    fake_session.url = "https://checkout.stripe.test/sess_1"
    with mock.patch("stripe.checkout.Session.create", return_value=fake_session):
        r = c.post(
            "/billing/checkout", data={"plan": "club", "immediate_supply": "1"}
        )
    assert r.status_code == 303
    from mediahub.web import legal

    acc = legal.AcceptanceStore().latest(
        "buyer@club.org", legal.DOC_COOLING_OFF, org_id="club"
    )
    assert acc is not None and acc.accepted_at
