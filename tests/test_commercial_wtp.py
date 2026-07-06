"""Unit tests for the PC.4 revealed-WTP quote ledger (`mediahub.commercial.wtp`)."""

from __future__ import annotations

import pytest

from mediahub.commercial.wtp import (
    METHOD_MANUAL,
    METHOD_STRIPE,
    STATUS_ACCEPTED,
    STATUS_DECLINED,
    STATUS_MISMATCH,
    STATUS_PAID,
    STATUS_QUOTED,
    QuoteError,
    QuoteStore,
    pc4_pricing_gate,
    public_list_price,
    traction_gate,
)


@pytest.fixture
def store(tmp_path):
    return QuoteStore(path=tmp_path / "wtp_quotes.jsonl")


def test_create_quote_defaults(store):
    q = store.create("Swansea Aquatics", 58800, contact_email="Chair@SwanseaAq.org")
    assert q.status == STATUS_QUOTED
    assert q.amount_pence == 58800
    assert q.currency == "gbp"
    assert q.billing_interval == "year"
    assert q.contact_email == "chair@swanseaaq.org"
    assert store.get(q.quote_id).club_name == "Swansea Aquatics"


def test_create_rejects_bad_input(store):
    with pytest.raises(QuoteError):
        store.create("", 58800)
    with pytest.raises(QuoteError):
        store.create("Club", 0)
    with pytest.raises(QuoteError):
        store.create("Club", -5)


def test_set_status_accept_decline_only(store):
    q = store.create("Club A", 58800)
    assert store.set_status(q.quote_id, STATUS_ACCEPTED).status == STATUS_ACCEPTED
    assert store.set_status(q.quote_id, STATUS_DECLINED).status == STATUS_DECLINED
    with pytest.raises(QuoteError):
        store.set_status(q.quote_id, STATUS_PAID)  # paid needs payment evidence


def test_stripe_payment_verified_amount_marks_paid(store):
    q = store.create("Club A", 58800)
    out = store.record_stripe_payment(
        q.quote_id, amount_total_pence=58800, currency="gbp", event_id="evt_1"
    )
    assert out.status == STATUS_PAID
    assert out.method == METHOD_STRIPE
    assert out.paid_amount_pence == 58800
    assert out.paid_event_id == "evt_1"
    assert out.paid_at != ""


def test_stripe_payment_wrong_amount_is_a_mismatch_not_paid(store):
    q = store.create("Club A", 58800)
    out = store.record_stripe_payment(
        q.quote_id, amount_total_pence=10000, currency="gbp", event_id="evt_1"
    )
    assert out.status == STATUS_MISMATCH
    # Mismatches never count toward either gate.
    quotes = store.list_all()
    assert pc4_pricing_gate(quotes)["paid_clubs"] == 0
    assert traction_gate(quotes)["paying_clubs"] == 0


def test_stripe_payment_wrong_currency_is_a_mismatch(store):
    q = store.create("Club A", 58800)
    out = store.record_stripe_payment(
        q.quote_id, amount_total_pence=58800, currency="usd", event_id="evt_1"
    )
    assert out.status == STATUS_MISMATCH


def test_stripe_payment_is_idempotent_per_event(store):
    q = store.create("Club A", 58800)
    store.record_stripe_payment(
        q.quote_id, amount_total_pence=58800, currency="gbp", event_id="evt_1"
    )
    before = store.path.read_text().count("\n")
    store.record_stripe_payment(
        q.quote_id, amount_total_pence=58800, currency="gbp", event_id="evt_1"
    )
    after = store.path.read_text().count("\n")
    assert after == before  # exact retry appended nothing
    assert store.get(q.quote_id).status == STATUS_PAID


def test_stripe_payment_unknown_quote_returns_none(store):
    assert (
        store.record_stripe_payment("nope", amount_total_pence=1, currency="gbp", event_id="e")
        is None
    )


def test_manual_payment_verified_and_mismatch(store):
    q1 = store.create("Club A", 58800)
    out1 = store.record_manual_payment(q1.quote_id, amount_pence=58800)
    assert out1.status == STATUS_PAID and out1.method == METHOD_MANUAL
    q2 = store.create("Club B", 58800)
    out2 = store.record_manual_payment(q2.quote_id, amount_pence=30000)
    assert out2.status == STATUS_MISMATCH


def test_pc4_gate_counts_distinct_clubs_paid_annual(store):
    # Four distinct clubs paid at tested prices + a duplicate + a mismatch.
    for i, (club, price) in enumerate(
        [("Club A", 58800), ("Club B", 58800), ("Club C", 82800), ("Club D", 118800)]
    ):
        q = store.create(club, price)
        store.record_stripe_payment(
            q.quote_id, amount_total_pence=price, currency="gbp", event_id=f"evt_{i}"
        )
    dup = store.create("club a", 58800)  # same club, case-insensitive
    store.record_manual_payment(dup.quote_id, amount_pence=58800)
    bad = store.create("Club E", 58800)
    store.record_stripe_payment(
        bad.quote_id, amount_total_pence=100, currency="gbp", event_id="evt_x"
    )

    gate = pc4_pricing_gate(store.list_all())
    assert gate["paid_clubs"] == 4
    assert gate["met"] is False
    assert gate["tested_prices_pence"] == [58800, 82800, 118800]

    q5 = store.create("Club F", 82800)
    store.record_manual_payment(q5.quote_id, amount_pence=82800)
    gate = pc4_pricing_gate(store.list_all())
    assert gate["paid_clubs"] == 5
    assert gate["met"] is True


def test_traction_gate_requires_ten_paying_clubs(store):
    for i in range(9):
        q = store.create(f"Club {i}", 58800)
        store.record_manual_payment(q.quote_id, amount_pence=58800)
    gate = traction_gate(store.list_all())
    assert gate["paying_clubs"] == 9 and gate["met"] is False
    q = store.create("Club Ten", 58800)
    store.record_manual_payment(q.quote_id, amount_pence=58800)
    gate = traction_gate(store.list_all())
    assert gate["paying_clubs"] == 10 and gate["met"] is True


def test_public_list_price_none_until_gate_met(store):
    # Four paid clubs: gate unmet, no committed price — /pricing stays TBC.
    for i, price in enumerate([58800, 58800, 82800, 118800]):
        q = store.create(f"Club {i}", price)
        store.record_manual_payment(q.quote_id, amount_pence=price)
    assert public_list_price(store.list_all()) is None


def test_public_list_price_is_highest_tested_price_that_cleared(store):
    prices = [58800, 58800, 82800, 118800, 70800]
    for i, price in enumerate(prices):
        q = store.create(f"Club {i}", price)
        store.record_manual_payment(q.quote_id, amount_pence=price)
    # A mismatch at a higher figure never sets the list price.
    bad = store.create("Mismatch Club", 200000)
    store.record_manual_payment(bad.quote_id, amount_pence=150000)
    out = public_list_price(store.list_all())
    assert out == {"amount_pence": 118800, "currency": "gbp"}


def test_ledger_is_append_only_and_owner_readable(store):
    q = store.create("Club A", 58800)
    store.set_status(q.quote_id, STATUS_ACCEPTED)
    lines = store.path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert (store.path.stat().st_mode & 0o777) == 0o600


def test_malformed_amount_pence_row_never_crashes_the_ledger_read(store):
    """A non-numeric amount_pence in one line must not 500 the whole console."""
    import json

    q = store.create("Club A", 58800)
    with store.path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"quote_id": "bad1", "club_name": "Club B", "amount_pence": "abc"}) + "\n")
    quotes = {r.quote_id: r for r in store.list_all()}
    assert quotes[q.quote_id].amount_pence == 58800
    assert quotes["bad1"].amount_pence == 0  # coerced, not crashed
