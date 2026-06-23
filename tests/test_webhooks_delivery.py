"""1.21 webhooks — delivery: fan-out, signing, retry/backoff, redelivery."""

from __future__ import annotations

import json

import pytest

from mediahub.webhooks import _db, delivery, signing
from mediahub.webhooks.events import card_approved
from mediahub.webhooks.registry import EndpointStore


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _db._initialized.clear()
    return EndpointStore()


def _capture(monkeypatch):
    sent = []

    def fake_post(url, body, headers):
        sent.append({"url": url, "body": body, "headers": headers})
        return 200, None

    monkeypatch.setattr(delivery, "_http_post", fake_post)
    return sent


def test_emit_delivers_to_subscribed_endpoint(env, monkeypatch):
    sent = _capture(monkeypatch)
    ep = env.create("org-a", "https://ex.com/h", events=["card.approved"])
    ids = delivery.emit("card.approved", "org-a", card_approved("org-a", "r1", "c1"), background=False)
    assert len(ids) == 1
    assert len(sent) == 1 and sent[0]["url"] == "https://ex.com/h"
    rows = delivery.DeliveryStore().list_for_endpoint(ep.id)
    assert rows[0]["status"] == "delivered" and rows[0]["attempts"] == 1


def test_delivery_is_signed_and_verifiable(env, monkeypatch):
    sent = _capture(monkeypatch)
    ep = env.create("org-a", "https://ex.com/h", events=["card.approved"])
    delivery.emit("card.approved", "org-a", card_approved("org-a", "r1", "c1"), background=False)
    req = sent[0]
    sig = req["headers"][signing.HEADER]
    assert signing.verify(ep.secret, sig, req["body"])
    assert req["headers"]["X-MediaHub-Event"] == "card.approved"


def test_only_subscribed_events_fan_out(env, monkeypatch):
    sent = _capture(monkeypatch)
    env.create("org-a", "https://ex.com/h", events=["run.finished"])
    ids = delivery.emit("card.approved", "org-a", card_approved("org-a", "r1", "c1"), background=False)
    assert ids == [] and sent == []


def test_failure_marks_pending_with_retry(env, monkeypatch):
    ep = env.create("org-a", "https://ex.com/h", events=["card.approved"])
    monkeypatch.setattr(delivery, "_http_post", lambda u, b, h: (500, "HTTP 500"))
    delivery.emit("card.approved", "org-a", card_approved("org-a", "r1", "c1"), background=False)
    row = delivery.DeliveryStore().list_for_endpoint(ep.id)[0]
    assert row["status"] == "pending" and row["attempts"] == 1
    # a next attempt is scheduled
    conn = _db.connect()
    try:
        nxt = conn.execute(
            "SELECT next_attempt_at FROM webhook_deliveries WHERE id=?", (row["id"],)
        ).fetchone()[0]
    finally:
        conn.close()
    assert nxt is not None


def test_exhausted_retries_mark_failed(env, monkeypatch):
    monkeypatch.setattr(delivery, "_BACKOFF", [])  # no retries → first failure is terminal
    ep = env.create("org-a", "https://ex.com/h", events=["card.approved"])
    monkeypatch.setattr(delivery, "_http_post", lambda u, b, h: (None, "boom"))
    delivery.emit("card.approved", "org-a", card_approved("org-a", "r1", "c1"), background=False)
    row = delivery.DeliveryStore().list_for_endpoint(ep.id)[0]
    assert row["status"] == "failed"


def test_deliver_pending_retries_due(env, monkeypatch):
    ep = env.create("org-a", "https://ex.com/h", events=["card.approved"])
    # First attempt fails → pending.
    monkeypatch.setattr(delivery, "_http_post", lambda u, b, h: (503, "HTTP 503"))
    delivery.emit("card.approved", "org-a", card_approved("org-a", "r1", "c1"), background=False)
    did = delivery.DeliveryStore().list_for_endpoint(ep.id)[0]["id"]
    # Make it due now, then let it succeed.
    conn = _db.connect()
    try:
        conn.execute(
            "UPDATE webhook_deliveries SET next_attempt_at=? WHERE id=?", ("2000-01-01T00:00:00Z", did)
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(delivery, "_http_post", lambda u, b, h: (200, None))
    n = delivery.deliver_pending()
    assert n == 1
    assert delivery.DeliveryStore().list_for_endpoint(ep.id)[0]["status"] == "delivered"


def test_redeliver_requeues(env, monkeypatch):
    monkeypatch.setattr(delivery, "_BACKOFF", [])
    ep = env.create("org-a", "https://ex.com/h", events=["card.approved"])
    monkeypatch.setattr(delivery, "_http_post", lambda u, b, h: (500, "HTTP 500"))
    delivery.emit("card.approved", "org-a", card_approved("org-a", "r1", "c1"), background=False)
    did = delivery.DeliveryStore().list_for_endpoint(ep.id)[0]["id"]
    assert delivery.DeliveryStore().list_for_endpoint(ep.id)[0]["status"] == "failed"
    # Now succeed on redeliver.
    monkeypatch.setattr(delivery, "_http_post", lambda u, b, h: (200, None))
    assert delivery.DeliveryStore().redeliver(did, "org-a") is True
    assert delivery.DeliveryStore().list_for_endpoint(ep.id)[0]["status"] == "delivered"
    # tenant-scoped
    assert delivery.DeliveryStore().redeliver(did, "org-b") is False


def test_emit_never_raises_on_bad_event(env):
    # Unknown event is a quiet no-op, never an exception.
    assert delivery.emit("not.an.event", "org-a", {}, background=False) == []


def test_payload_envelope_carries_delivery_id(env, monkeypatch):
    sent = _capture(monkeypatch)
    env.create("org-a", "https://ex.com/h", events=["card.approved"])
    ids = delivery.emit("card.approved", "org-a", card_approved("org-a", "r1", "c1"), background=False)
    body = json.loads(sent[0]["body"])
    assert body["id"] == ids[0] and body["type"] == "card.approved"
    assert body["data"]["card_id"] == "c1"
