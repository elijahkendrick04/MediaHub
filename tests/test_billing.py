"""PC.2 — Stripe billing: Checkout, portal, signed webhook (Appendix B Step 7).

Stripe is mocked throughout (no network, no real keys). Coverage:

  - 503 honest-error on every billing route when STRIPE_SECRET_KEY is unset
    (self-host path stays open).
  - Webhook signature verification: a forged signature is rejected (400); a
    correctly-signed event drives the user's plan.
  - The subscription lifecycle: checkout-completed → club; subscription
    deleted/cancelled → free; updated-to-federation → federation; matching a
    user by Stripe customer id when the event carries no email.
  - Checkout session creation returns the Stripe URL and uses the env-driven
    price id (no hardcoded amount anywhere).

No real STRIPE_SECRET_KEY value is used; the tests set obviously-fake
``sk_test_…`` / ``whsec_…`` placeholders via monkeypatch (never committed
secrets).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest import mock

import pytest

# Obviously-fake placeholders. These are NOT secrets — they are test fixtures
# that exercise the "configured" code paths while Stripe itself is mocked.
FAKE_SECRET_KEY = "sk_test_placeholder_not_a_real_key"
FAKE_WEBHOOK_SECRET = "whsec_test_placeholder"
FAKE_PRICE_CLUB = "price_club_test"
FAKE_PRICE_FEDERATION = "price_federation_test"


def _make_app(monkeypatch, tmp_path, *, with_stripe: bool):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    if with_stripe:
        monkeypatch.setenv("STRIPE_SECRET_KEY", FAKE_SECRET_KEY)
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", FAKE_WEBHOOK_SECRET)
        monkeypatch.setenv("STRIPE_PRICE_CLUB", FAKE_PRICE_CLUB)
        monkeypatch.setenv("STRIPE_PRICE_FEDERATION", FAKE_PRICE_FEDERATION)
    else:
        for var in (
            "STRIPE_SECRET_KEY",
            "STRIPE_WEBHOOK_SECRET",
            "STRIPE_PRICE_CLUB",
            "STRIPE_PRICE_FEDERATION",
        ):
            monkeypatch.delenv(var, raising=False)
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    return app


def _signed_webhook_headers(payload: bytes, secret: str = FAKE_WEBHOOK_SECRET) -> dict:
    """Build a valid ``Stripe-Signature`` header for ``payload`` (scheme v1)."""
    ts = int(time.time())
    signed_payload = f"{ts}.".encode() + payload
    sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={ts},v1={sig}", "Content-Type": "application/json"}


def _event(event_type: str, obj: dict) -> bytes:
    return json.dumps(
        {"id": "evt_test", "object": "event", "type": event_type, "data": {"object": obj}}
    ).encode()


def _latest_plan(tmp_path) -> str:
    lines = (tmp_path / "users.jsonl").read_text().splitlines()
    return json.loads(lines[-1])["plan"]


# ---- unconfigured (self-host) path -------------------------------------


def test_billing_routes_503_when_unconfigured(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, with_stripe=False)
    from mediahub.web import billing

    assert billing.billing_configured() is False
    c = app.test_client()
    c.post("/signup", data={"email": "u@club.org", "password": "twelvechars1", "accept_terms": "1"})

    # Billing actions honest-error with 503 + the exact message.
    r = c.post("/billing/checkout", data={"plan": "club"})
    assert r.status_code == 503
    assert r.get_json()["message"] == billing.NOT_CONFIGURED_MESSAGE

    r = c.post("/billing/portal")
    assert r.status_code == 503

    # Webhook also 503s (so Stripe surfaces a clear delivery error).
    r = c.post("/webhooks/stripe", data=b"{}", headers={"Stripe-Signature": "x"})
    assert r.status_code == 503


def test_billing_page_shows_not_configured(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, with_stripe=False)
    c = app.test_client()
    c.post("/signup", data={"email": "u@club.org", "password": "twelvechars1", "accept_terms": "1"})
    r = c.get("/billing")
    assert r.status_code == 200
    assert b"not configured" in r.data.lower()


def test_pricing_page_renders_without_billing(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, with_stripe=False)
    c = app.test_client()
    r = c.get("/pricing")
    assert r.status_code == 200
    # The three tiers are present.
    for tier in (b"Free", b"Club", b"Federation"):
        assert tier in r.data


def test_pricing_bakes_in_no_committed_price(monkeypatch, tmp_path):
    """No hardcoded price amount appears, configured or not (ADR-0011/PC.4)."""
    for with_stripe in (False, True):
        app = _make_app(monkeypatch, tmp_path, with_stripe=with_stripe)
        c = app.test_client()
        html = c.get("/pricing").get_data(as_text=True)
        for amount in ("£30", "£250", "£49", "£99", "$625", "$3,000"):
            assert amount not in html, f"committed price {amount!r} leaked into /pricing"


def test_pricing_stays_tbc_until_pc4_gate_met(monkeypatch, tmp_path):
    """Even fully Stripe-configured, /pricing shows TBC while <5 clubs paid."""
    app = _make_app(monkeypatch, tmp_path, with_stripe=True)
    from mediahub.commercial.wtp import QuoteStore

    store = QuoteStore()
    for i, price in enumerate([58800, 82800, 118800, 70800]):  # only 4 clubs
        q = store.create(f"Club {i}", price)
        store.record_manual_payment(q.quote_id, amount_pence=price)

    html = app.test_client().get("/pricing").get_data(as_text=True)
    assert "Pricing TBC" in html
    assert "/year" not in html  # no committed annual figure anywhere


def test_pricing_commits_evidence_derived_price_once_gate_met(monkeypatch, tmp_path):
    """Gate met (≥5 paid clubs): the Club tier shows the highest cleared price."""
    app = _make_app(monkeypatch, tmp_path, with_stripe=False)
    from mediahub.commercial.wtp import QuoteStore

    store = QuoteStore()
    for i, price in enumerate([58800, 58800, 82800, 118800, 70800, 99000]):
        q = store.create(f"Club {i}", price)
        store.record_manual_payment(q.quote_id, amount_pence=price)
    # A mismatch at a higher figure must not move the list price.
    bad = store.create("Mismatch Club", 200000)
    store.record_manual_payment(bad.quote_id, amount_pence=150000)

    html = app.test_client().get("/pricing").get_data(as_text=True)
    # 118800p == £1188 — the highest tested price that actually cleared.
    assert "&pound;1188" in html and "/year" in html
    assert "Billed annually" in html


# ---- configured path: checkout + portal --------------------------------


def test_checkout_creates_session_with_env_price(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, with_stripe=True)
    c = app.test_client()
    c.post(
        "/signup", data={"email": "buyer@club.org", "password": "twelvechars1", "accept_terms": "1"}
    )

    fake_session = mock.MagicMock()
    fake_session.url = "https://checkout.stripe.test/sess_123"
    with mock.patch("stripe.checkout.Session.create", return_value=fake_session) as m:
        r = c.post("/billing/checkout", data={"plan": "club", "immediate_supply": "1"})

    assert r.status_code == 303
    assert r.headers["Location"] == "https://checkout.stripe.test/sess_123"
    # The price id is the env-configured one — never a literal amount.
    kwargs = m.call_args.kwargs
    assert kwargs["line_items"][0]["price"] == FAKE_PRICE_CLUB
    assert kwargs["mode"] == "subscription"
    assert kwargs["customer_email"] == "buyer@club.org"


def test_checkout_rejects_unknown_plan(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, with_stripe=True)
    c = app.test_client()
    c.post(
        "/signup", data={"email": "buyer@club.org", "password": "twelvechars1", "accept_terms": "1"}
    )
    r = c.post("/billing/checkout", data={"plan": "free"})
    assert r.status_code == 400


def test_checkout_requires_login(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, with_stripe=True)
    c = app.test_client()
    r = c.post("/billing/checkout", data={"plan": "club"})
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_portal_creates_session(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, with_stripe=True)
    from mediahub.web import auth

    c = app.test_client()
    c.post(
        "/signup",
        data={"email": "member@club.org", "password": "twelvechars1", "accept_terms": "1"},
    )
    # Give them a customer id so the portal has something to open.
    auth.UserStore().set_plan("member@club.org", "club", stripe_customer_id="cus_test9")

    fake_session = mock.MagicMock()
    fake_session.url = "https://portal.stripe.test/p_123"
    with mock.patch("stripe.billing_portal.Session.create", return_value=fake_session) as m:
        r = c.post("/billing/portal")

    assert r.status_code == 303
    assert r.headers["Location"] == "https://portal.stripe.test/p_123"
    assert m.call_args.kwargs["customer"] == "cus_test9"


def test_portal_without_customer_id_is_clean_error(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, with_stripe=True)
    c = app.test_client()
    c.post(
        "/signup",
        data={"email": "nocust@club.org", "password": "twelvechars1", "accept_terms": "1"},
    )
    r = c.post("/billing/portal")
    assert r.status_code == 400  # clean, not a 500


# ---- webhook signature verification + lifecycle ------------------------


def test_webhook_rejects_forged_signature(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, with_stripe=True)
    c = app.test_client()
    payload = _event(
        "checkout.session.completed",
        {"customer": "cus_x", "metadata": {"plan": "club", "mediahub_email": "x@club.org"}},
    )
    # Wrong signature → 400, never trusted.
    r = c.post("/webhooks/stripe", data=payload, headers={"Stripe-Signature": "t=1,v1=deadbeef"})
    assert r.status_code == 400
    assert r.get_json()["error"] == "invalid_webhook"


def test_webhook_completed_sets_plan_club(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, with_stripe=True)
    c = app.test_client()
    c.post(
        "/signup", data={"email": "w1@club.org", "password": "twelvechars1", "accept_terms": "1"}
    )

    payload = _event(
        "checkout.session.completed",
        {
            "object": "checkout.session",
            "customer": "cus_w1",
            "client_reference_id": "w1@club.org",
            "metadata": {"plan": "club", "mediahub_email": "w1@club.org"},
        },
    )
    r = c.post("/webhooks/stripe", data=payload, headers=_signed_webhook_headers(payload))
    assert r.status_code == 200
    body = r.get_json()
    assert body["handled"] is True and body["plan"] == "club"
    assert _latest_plan(tmp_path) == "club"
    # The customer id is captured for later portal use.
    from mediahub.web import auth

    assert auth.UserStore().get("w1@club.org").stripe_customer_id == "cus_w1"


def test_webhook_subscription_deleted_reverts_to_free(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, with_stripe=True)
    from mediahub.web import auth

    c = app.test_client()
    c.post(
        "/signup", data={"email": "w2@club.org", "password": "twelvechars1", "accept_terms": "1"}
    )
    auth.UserStore().set_plan("w2@club.org", "club", stripe_customer_id="cus_w2")

    payload = _event(
        "customer.subscription.deleted",
        {
            "object": "subscription",
            "customer": "cus_w2",
            "metadata": {"mediahub_email": "w2@club.org"},
        },
    )
    r = c.post("/webhooks/stripe", data=payload, headers=_signed_webhook_headers(payload))
    assert r.status_code == 200
    assert _latest_plan(tmp_path) == "free"


def test_webhook_updated_to_federation(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, with_stripe=True)
    c = app.test_client()
    c.post(
        "/signup", data={"email": "w3@club.org", "password": "twelvechars1", "accept_terms": "1"}
    )

    payload = _event(
        "customer.subscription.updated",
        {
            "object": "subscription",
            "status": "active",
            "customer": "cus_w3",
            "metadata": {"plan": "federation", "mediahub_email": "w3@club.org"},
        },
    )
    r = c.post("/webhooks/stripe", data=payload, headers=_signed_webhook_headers(payload))
    assert r.status_code == 200
    assert _latest_plan(tmp_path) == "federation"


def test_webhook_matches_user_by_customer_id(monkeypatch, tmp_path):
    """An event with no email but a known customer id still updates the plan."""
    app = _make_app(monkeypatch, tmp_path, with_stripe=True)
    from mediahub.web import auth

    c = app.test_client()
    c.post(
        "/signup", data={"email": "w4@club.org", "password": "twelvechars1", "accept_terms": "1"}
    )
    auth.UserStore().set_plan("w4@club.org", "club", stripe_customer_id="cus_w4")

    payload = _event(
        "customer.subscription.deleted",
        {"object": "subscription", "customer": "cus_w4"},  # no metadata email
    )
    r = c.post("/webhooks/stripe", data=payload, headers=_signed_webhook_headers(payload))
    assert r.status_code == 200
    assert _latest_plan(tmp_path) == "free"


def test_webhook_unknown_user_is_acknowledged_not_errored(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, with_stripe=True)
    c = app.test_client()
    # No matching account at all.
    payload = _event(
        "checkout.session.completed",
        {
            "object": "checkout.session",
            "customer": "cus_ghost",
            "metadata": {"plan": "club", "mediahub_email": "ghost@nowhere.org"},
        },
    )
    r = c.post("/webhooks/stripe", data=payload, headers=_signed_webhook_headers(payload))
    # Acknowledge (200) so Stripe stops retrying; nothing updated.
    assert r.status_code == 200
    assert r.get_json()["handled"] is False


def test_webhook_ignored_event_type_is_noop(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, with_stripe=True)
    c = app.test_client()
    payload = _event("invoice.paid", {"object": "invoice", "customer": "cus_x"})
    r = c.post("/webhooks/stripe", data=payload, headers=_signed_webhook_headers(payload))
    assert r.status_code == 200
    assert r.get_json()["handled"] is False


# ---- module-level helpers ----------------------------------------------


def test_price_id_for_plan_reads_env(monkeypatch, tmp_path):
    _make_app(monkeypatch, tmp_path, with_stripe=True)
    from mediahub.web import billing

    assert billing.price_id_for_plan("club") == FAKE_PRICE_CLUB
    assert billing.price_id_for_plan("federation") == FAKE_PRICE_FEDERATION
    assert billing.price_id_for_plan("free") == ""
    assert billing.plan_purchasable("club") is True


def test_create_checkout_raises_when_unconfigured(monkeypatch, tmp_path):
    _make_app(monkeypatch, tmp_path, with_stripe=False)
    from mediahub.web import billing

    with pytest.raises(billing.BillingNotConfigured):
        billing.create_checkout_session(
            plan="club",
            customer_email="x@club.org",
            success_url="https://x/ok",
            cancel_url="https://x/no",
        )
