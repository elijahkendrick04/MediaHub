"""PC.4 quote-checkout billing tests: the webhook records revealed-WTP
evidence with the Council-mandated hardening — idempotent per quote/event and
amount-verified server-side — and quote recording works even when the payer
has no MediaHub account yet."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

FAKE_SECRET_KEY = "sk_test_placeholder_not_a_real_key"
FAKE_WEBHOOK_SECRET = "whsec_test_placeholder"
PASSWORD = "twelve-chars-long"


def _make_app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STRIPE_SECRET_KEY", FAKE_SECRET_KEY)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", FAKE_WEBHOOK_SECRET)
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    return app


def _signed_headers(payload: bytes, secret: str = FAKE_WEBHOOK_SECRET) -> dict:
    ts = int(time.time())
    signed_payload = f"{ts}.".encode() + payload
    sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={ts},v1={sig}", "Content-Type": "application/json"}


def _checkout_completed_event(
    quote_id: str, amount_total: int, *, email: str = "chair@club.org", event_id: str = "evt_q1"
) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "object": "event",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "object": "checkout.session",
                    "customer": "cus_123",
                    "customer_email": email,
                    "amount_total": amount_total,
                    "currency": "gbp",
                    "metadata": {
                        "plan": "club",
                        "mediahub_email": email,
                        "mediahub_quote_id": quote_id,
                    },
                }
            },
        }
    ).encode()


def _seed_quote(tmp_path, amount_pence: int = 58800, club: str = "Swansea Aquatics"):
    from mediahub.commercial.wtp import QuoteStore

    return QuoteStore().create(club, amount_pence, contact_email="chair@club.org")


def test_interpret_event_extracts_quote_fields(monkeypatch, tmp_path):
    _make_app(monkeypatch, tmp_path)
    from mediahub.web import billing

    payload = _checkout_completed_event("q-abc", 58800)
    update = billing._interpret_event(json.loads(payload))
    assert update.quote_id == "q-abc"
    assert update.amount_total_pence == 58800
    assert update.currency == "gbp"
    assert update.event_id == "evt_q1"
    assert update.plan == "club"


def test_webhook_records_verified_quote_payment_without_an_account(monkeypatch, tmp_path):
    """The prospect pays BEFORE signing up: no matching user, but the quote
    ledger must still capture the revealed-WTP payment."""
    app = _make_app(monkeypatch, tmp_path)
    q = _seed_quote(tmp_path)
    c = app.test_client()
    payload = _checkout_completed_event(q.quote_id, 58800)
    r = c.post("/webhooks/stripe", data=payload, headers=_signed_headers(payload))
    assert r.status_code == 200
    assert r.get_json()["reason"] == "no_matching_user"  # account flow unchanged

    from mediahub.commercial.wtp import QuoteStore

    out = QuoteStore().get(q.quote_id)
    assert out.status == "paid"
    assert out.method == "stripe"
    assert out.paid_amount_pence == 58800
    assert out.paid_event_id == "evt_q1"


def test_webhook_quote_payment_also_updates_plan_when_account_exists(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    q = _seed_quote(tmp_path)
    c = app.test_client()
    c.post("/signup", data={"email": "chair@club.org", "password": PASSWORD})
    payload = _checkout_completed_event(q.quote_id, 58800)
    r = c.post("/webhooks/stripe", data=payload, headers=_signed_headers(payload))
    assert r.status_code == 200
    assert r.get_json()["handled"] is True

    from mediahub.commercial.wtp import QuoteStore
    from mediahub.web.auth import UserStore

    assert QuoteStore().get(q.quote_id).status == "paid"
    assert UserStore().get("chair@club.org").plan == "club"


def test_webhook_amount_mismatch_recorded_never_counted(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    q = _seed_quote(tmp_path, amount_pence=58800)
    c = app.test_client()
    payload = _checkout_completed_event(q.quote_id, 12345)
    c.post("/webhooks/stripe", data=payload, headers=_signed_headers(payload))

    from mediahub.commercial.wtp import QuoteStore, pc4_pricing_gate

    out = QuoteStore().get(q.quote_id)
    assert out.status == "payment_mismatch"
    assert pc4_pricing_gate(QuoteStore().list_all())["paid_clubs"] == 0


def test_webhook_retry_is_idempotent(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    q = _seed_quote(tmp_path)
    c = app.test_client()
    payload = _checkout_completed_event(q.quote_id, 58800)
    c.post("/webhooks/stripe", data=payload, headers=_signed_headers(payload))

    from mediahub.commercial.wtp import QuoteStore

    lines_before = QuoteStore().path.read_text().count("\n")
    c.post("/webhooks/stripe", data=payload, headers=_signed_headers(payload))  # Stripe retry
    lines_after = QuoteStore().path.read_text().count("\n")
    assert lines_after == lines_before
    assert QuoteStore().get(q.quote_id).status == "paid"


def test_webhook_unknown_quote_id_is_acknowledged_not_500(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    c = app.test_client()
    payload = _checkout_completed_event("no-such-quote", 58800)
    r = c.post("/webhooks/stripe", data=payload, headers=_signed_headers(payload))
    assert r.status_code == 200


def test_forged_signature_still_rejected_and_records_nothing(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    q = _seed_quote(tmp_path)
    c = app.test_client()
    payload = _checkout_completed_event(q.quote_id, 58800)
    r = c.post(
        "/webhooks/stripe",
        data=payload,
        headers={"Stripe-Signature": "t=1,v1=forged", "Content-Type": "application/json"},
    )
    assert r.status_code == 400

    from mediahub.commercial.wtp import QuoteStore

    assert QuoteStore().get(q.quote_id).status == "quoted"


def test_quote_checkout_session_requires_valid_amount(monkeypatch, tmp_path):
    _make_app(monkeypatch, tmp_path)
    from mediahub.web import billing

    with pytest.raises(billing.BillingError):
        billing.create_quote_checkout_session(
            quote_id="q1",
            club_name="Club",
            amount_pence=0,
            currency="gbp",
            customer_email="a@b.org",
            success_url="https://x/s",
            cancel_url="https://x/c",
        )
    with pytest.raises(billing.BillingError):
        billing.create_quote_checkout_session(
            quote_id="",
            club_name="Club",
            amount_pence=58800,
            currency="gbp",
            customer_email="a@b.org",
            success_url="https://x/s",
            cancel_url="https://x/c",
        )
