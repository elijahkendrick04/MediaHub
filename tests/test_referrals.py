"""PC.9 — the in-product referral engine.

Codes per org; signup-by-code lands a source=referral lead with zero
operator typing; an amount-verified annual payment auto-grants the
referrer's free month (Stripe coupon) idempotently — and every honest
fallback (no WTP evidence, no Stripe customer) records pending_manual
with the reason instead of inventing a figure.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

FAKE_WEBHOOK_SECRET = "whsec_test_placeholder"


@pytest.fixture
def commercial_world(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def _mint_code(profile_id="org-referrer", club="Swansea Aquatics"):
    from mediahub.commercial.referrals import ReferralCodeStore

    return ReferralCodeStore().get_or_create(profile_id, club)


# ---- codes ------------------------------------------------------------------


def test_code_is_stable_per_org(commercial_world):
    a = _mint_code()
    b = _mint_code()
    assert a.code == b.code
    from mediahub.commercial.referrals import ReferralCodeStore

    rc = ReferralCodeStore().resolve(a.code)
    assert rc.profile_id == "org-referrer"
    assert rc.club_name == "Swansea Aquatics"


def test_unknown_code_resolves_none(commercial_world):
    from mediahub.commercial.referrals import ReferralCodeStore

    assert ReferralCodeStore().resolve("nope") is None
    assert ReferralCodeStore().resolve("") is None


# ---- referred signups -------------------------------------------------------


def test_referred_signup_records_lead(commercial_world):
    from mediahub.commercial.pipeline import LeadStore
    from mediahub.commercial.referrals import record_referred_signup

    rc = _mint_code()
    lead = record_referred_signup(rc.code, "Chair@NewClub.org")
    assert lead is not None
    assert lead.source == "referral"
    assert lead.referrer_club == "Swansea Aquatics"
    assert lead.contact_email == "chair@newclub.org"
    assert LeadStore().get(lead.lead_id) is not None


def test_referred_signup_idempotent_per_email(commercial_world):
    from mediahub.commercial.pipeline import LeadStore
    from mediahub.commercial.referrals import record_referred_signup

    rc = _mint_code()
    first = record_referred_signup(rc.code, "chair@newclub.org")
    again = record_referred_signup(rc.code, "chair@newclub.org")
    assert again.lead_id == first.lead_id
    assert len([x for x in LeadStore().list_all() if x.source == "referral"]) == 1


def test_bad_code_records_nothing(commercial_world):
    from mediahub.commercial.pipeline import LeadStore
    from mediahub.commercial.referrals import record_referred_signup

    assert record_referred_signup("typo", "chair@newclub.org") is None
    assert LeadStore().list_all() == []


# ---- reward settlement ------------------------------------------------------


def _paid_quote(club="New Club SC", email="chair@newclub.org", amount=48000):
    """A quote that just hit verified-PAID."""
    from mediahub.commercial.wtp import QuoteStore

    q = QuoteStore().create(club, amount, contact_email=email)
    return QuoteStore().record_manual_payment(q.quote_id, amount_pence=amount)


def _referrer_paid_quote(amount=58800):
    from mediahub.commercial.wtp import QuoteStore

    q = QuoteStore().create("Swansea Aquatics", amount, contact_email="sec@swansea.org")
    QuoteStore().record_manual_payment(q.quote_id, amount_pence=amount)


def _bind_referrer_billing(profile_id="org-referrer"):
    from mediahub.web.auth import UserStore
    from mediahub.web.tenancy import MembershipStore, ROLE_OWNER, STATUS_ACTIVE

    store = UserStore()
    store.create("sec@swansea.org", "password-12345")
    store.set_plan("sec@swansea.org", "club", stripe_customer_id="cus_ref_1")
    MembershipStore().add(
        "sec@swansea.org", profile_id, role=ROLE_OWNER, status=STATUS_ACTIVE
    )


def test_verified_payment_grants_reward_and_advances_funnel(commercial_world):
    from mediahub.commercial.pipeline import LeadStore
    from mediahub.commercial.referrals import (
        REWARD_GRANTED,
        ReferralRewardStore,
        on_verified_quote_payment,
        record_referred_signup,
    )

    rc = _mint_code()
    record_referred_signup(rc.code, "chair@newclub.org")
    _referrer_paid_quote(amount=58800)  # referrer's own verified annual price
    _bind_referrer_billing()

    grants = []

    def fake_grant(customer_id, *, amount_off_pence, currency, referred_club):
        grants.append((customer_id, amount_off_pence, currency, referred_club))
        return "coupon_123"

    paid = _paid_quote()
    reward = on_verified_quote_payment(paid, grant_coupon=fake_grant)
    assert reward.status == REWARD_GRANTED
    assert reward.stripe_coupon_id == "coupon_123"
    assert reward.referrer_profile_id == "org-referrer"
    # One free month = the REFERRER's verified annual / 12.
    assert reward.amount_off_pence == round(58800 / 12)
    assert grants == [("cus_ref_1", round(58800 / 12), "gbp", "New Club SC")]

    # Funnel advanced itself: the referred lead is now WON.
    lead = [x for x in LeadStore().list_all() if x.source == "referral"][0]
    assert lead.status == "won"
    assert ReferralRewardStore().for_quote(paid.quote_id) is not None


def test_settlement_idempotent_per_quote(commercial_world):
    from mediahub.commercial.referrals import (
        ReferralRewardStore,
        on_verified_quote_payment,
        record_referred_signup,
    )

    rc = _mint_code()
    record_referred_signup(rc.code, "chair@newclub.org")
    _referrer_paid_quote()
    _bind_referrer_billing()
    calls = []

    def fake_grant(customer_id, **kw):
        calls.append(customer_id)
        return "coupon_123"

    paid = _paid_quote()
    first = on_verified_quote_payment(paid, grant_coupon=fake_grant)
    retry = on_verified_quote_payment(paid, grant_coupon=fake_grant)
    assert retry.reward_id == first.reward_id
    assert calls == ["cus_ref_1"]  # the coupon was granted exactly once
    assert len(ReferralRewardStore().list_all()) == 1


def test_club_name_match_fallback(commercial_world):
    """A quote typed by the operator without the email still settles when
    the club name matches the referred lead."""
    from mediahub.commercial.pipeline import LeadStore
    from mediahub.commercial.referrals import (
        on_verified_quote_payment,
        record_referred_signup,
    )

    rc = _mint_code()
    lead = record_referred_signup(rc.code, "chair@newclub.org")
    # Operator renames the lead to the real club name.
    store = LeadStore()
    lead.club_name = "New Club SC"
    store._append(lead)
    _referrer_paid_quote()
    _bind_referrer_billing()

    paid = _paid_quote(club="New Club SC", email="")  # no email on the quote
    reward = on_verified_quote_payment(paid, grant_coupon=lambda *a, **k: "c1")
    assert reward is not None
    assert reward.referred_club == "New Club SC"


def test_no_referrer_wtp_evidence_is_pending_manual(commercial_world):
    from mediahub.commercial.referrals import (
        REWARD_PENDING_MANUAL,
        on_verified_quote_payment,
        record_referred_signup,
    )

    rc = _mint_code()
    record_referred_signup(rc.code, "chair@newclub.org")
    _bind_referrer_billing()
    # No referrer paid quote → no honest value for "a free month".
    paid = _paid_quote()
    reward = on_verified_quote_payment(paid, grant_coupon=lambda *a, **k: "c1")
    assert reward.status == REWARD_PENDING_MANUAL
    assert "no verified paid annual quote" in reward.reason
    assert reward.stripe_coupon_id == ""


def test_no_stripe_customer_is_pending_manual(commercial_world):
    from mediahub.commercial.referrals import (
        REWARD_PENDING_MANUAL,
        on_verified_quote_payment,
        record_referred_signup,
    )

    rc = _mint_code()
    record_referred_signup(rc.code, "chair@newclub.org")
    _referrer_paid_quote()  # value known…
    # …but no member of the referrer org has a Stripe customer id.
    paid = _paid_quote()
    reward = on_verified_quote_payment(paid, grant_coupon=lambda *a, **k: "c1")
    assert reward.status == REWARD_PENDING_MANUAL
    assert "no Stripe customer" in reward.reason
    assert reward.amount_off_pence == round(58800 / 12)


def test_non_referral_payment_settles_nothing(commercial_world):
    from mediahub.commercial.referrals import (
        ReferralRewardStore,
        on_verified_quote_payment,
    )

    paid = _paid_quote(club="Walk-in Club", email="walkin@club.org")
    assert on_verified_quote_payment(paid, grant_coupon=lambda *a, **k: "c1") is None
    assert ReferralRewardStore().list_all() == []


def test_mismatched_payment_never_grants(commercial_world):
    from mediahub.commercial.referrals import (
        on_verified_quote_payment,
        record_referred_signup,
    )
    from mediahub.commercial.wtp import QuoteStore

    rc = _mint_code()
    record_referred_signup(rc.code, "chair@newclub.org")
    _referrer_paid_quote()
    _bind_referrer_billing()
    q = QuoteStore().create("New Club SC", 48000, contact_email="chair@newclub.org")
    mismatched = QuoteStore().record_manual_payment(q.quote_id, amount_pence=12345)
    assert on_verified_quote_payment(mismatched, grant_coupon=lambda *a, **k: "c1") is None


# ---- the debt readout goes live --------------------------------------------


def test_referral_debt_counts_code_tracked_intros(commercial_world):
    from mediahub.commercial.pipeline import LeadStore, referral_debt
    from mediahub.commercial.referrals import record_referred_signup

    store = LeadStore()
    won = store.create("Swansea Aquatics", source="warm_local")
    store.set_status(won.lead_id, "won")

    # Owing both intros before any code-tracked signup.
    debt = referral_debt(store.list_all())
    assert debt[0]["intros_recorded"] == 0
    assert debt[0]["intros_missing"] == 2

    rc = _mint_code()  # club name matches the won lead
    record_referred_signup(rc.code, "chair@newclub.org")
    debt = referral_debt(store.list_all())
    assert debt[0]["intros_recorded"] == 1
    assert debt[0]["intros_code_tracked"] == 1
    assert debt[0]["intros_missing"] == 1

    # A second tracked signup clears the debt entirely.
    record_referred_signup(rc.code, "sec@otherclub.org")
    assert referral_debt(store.list_all()) == []


# ---- billing: the coupon grant ----------------------------------------------


def test_grant_referral_reward_applies_coupon(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    from mediahub.web import billing

    calls = {}

    class FakeCoupon:
        @staticmethod
        def create(**kw):
            calls["coupon"] = kw
            return {"id": "co_1"}

    class FakeSubscription:
        @staticmethod
        def list(**kw):
            calls["sub_list"] = kw
            return {"data": [{"id": "sub_9"}]}

        @staticmethod
        def modify(sub_id, **kw):
            calls["sub_modify"] = (sub_id, kw)

    class FakeStripe:
        api_key = ""
        Coupon = FakeCoupon
        Subscription = FakeSubscription

    monkeypatch.setattr(billing, "_stripe", lambda: FakeStripe)
    coupon_id = billing.grant_referral_reward(
        "cus_1", amount_off_pence=4900, currency="gbp", referred_club="New Club SC"
    )
    assert coupon_id == "co_1"
    assert calls["coupon"]["amount_off"] == 4900
    assert calls["coupon"]["duration"] == "once"
    assert calls["sub_modify"] == ("sub_9", {"coupon": "co_1"})


def test_grant_referral_reward_customer_level_when_no_sub(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    from mediahub.web import billing

    calls = {}

    class FakeStripe:
        api_key = ""

        class Coupon:
            @staticmethod
            def create(**kw):
                return {"id": "co_2"}

        class Subscription:
            @staticmethod
            def list(**kw):
                return {"data": []}

        class Customer:
            @staticmethod
            def modify(cid, **kw):
                calls["customer_modify"] = (cid, kw)

    monkeypatch.setattr(billing, "_stripe", lambda: FakeStripe)
    assert billing.grant_referral_reward("cus_2", amount_off_pence=100) == "co_2"
    assert calls["customer_modify"] == ("cus_2", {"coupon": "co_2"})


def test_grant_referral_reward_rejects_bad_input(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    from mediahub.web import billing

    monkeypatch.setattr(billing, "_stripe", lambda: object())
    with pytest.raises(billing.BillingError):
        billing.grant_referral_reward("", amount_off_pence=100)
    with pytest.raises(billing.BillingError):
        billing.grant_referral_reward("cus_1", amount_off_pence=0)


# ---- end to end through the routes ------------------------------------------


def _signed_headers(payload: bytes, secret: str = FAKE_WEBHOOK_SECRET) -> dict:
    ts = int(time.time())
    signed_payload = f"{ts}.".encode() + payload
    sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={ts},v1={sig}", "Content-Type": "application/json"}


def test_signup_with_ref_code_then_webhook_grants_end_to_end(tmp_path, monkeypatch):
    """The PC.9 exit criterion, in one flow: shareable code → signup via
    link records the lead → verified annual payment on the webhook grants
    the reward and updates the funnel — zero operator typing."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_placeholder")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", FAKE_WEBHOOK_SECRET)

    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"

    # The signed club's code (their org page would mint this).
    rc = _mint_code()
    _referrer_paid_quote()
    _bind_referrer_billing()

    # 1. The referred club signs up through the shared link.
    c = app.test_client()
    r = c.post(
        "/signup",
        data={
            "email": "chair@newclub.org",
            "password": "twelve-chars-long",
            "accept_terms": "1",
            "ref": rc.code,
        },
    )
    assert r.status_code == 302

    from mediahub.commercial.pipeline import LeadStore

    leads = [x for x in LeadStore().list_all() if x.source == "referral"]
    assert len(leads) == 1
    assert leads[0].referrer_club == "Swansea Aquatics"

    # 2. The operator quotes them; the club pays through Stripe checkout.
    from mediahub.commercial.wtp import QuoteStore

    q = QuoteStore().create("New Club SC", 48000, contact_email="chair@newclub.org")

    granted = []
    import mediahub.web.billing as billing

    monkeypatch.setattr(
        billing,
        "grant_referral_reward",
        lambda cid, **kw: granted.append((cid, kw)) or "co_e2e",
    )

    payload = json.dumps(
        {
            "id": "evt_ref_1",
            "object": "event",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "object": "checkout.session",
                    "customer": "cus_new",
                    "customer_email": "chair@newclub.org",
                    "amount_total": 48000,
                    "currency": "gbp",
                    "metadata": {
                        "plan": "club",
                        "mediahub_email": "chair@newclub.org",
                        "mediahub_quote_id": q.quote_id,
                    },
                }
            },
        }
    ).encode()
    r = c.post("/webhooks/stripe", data=payload, headers=_signed_headers(payload))
    assert r.status_code == 200

    # The reward granted against the REFERRER's customer, at their annual/12.
    assert granted == [
        (
            "cus_ref_1",
            {
                "amount_off_pence": round(58800 / 12),
                "currency": "gbp",
                "referred_club": "New Club SC",
            },
        )
    ]
    from mediahub.commercial.referrals import ReferralRewardStore

    rewards = ReferralRewardStore().list_all()
    assert len(rewards) == 1 and rewards[0].status == "granted"
    # Funnel ledger updated with zero operator typing.
    assert [x for x in LeadStore().list_all() if x.source == "referral"][0].status == "won"

    # A Stripe webhook retry grants nothing twice.
    r = c.post("/webhooks/stripe", data=payload, headers=_signed_headers(payload))
    assert r.status_code == 200
    assert len(granted) == 1
    assert len(ReferralRewardStore().list_all()) == 1
