"""1.21 webhooks — the event catalogue + payload builders."""

from __future__ import annotations

from mediahub.webhooks import events as ev


def test_catalogue_has_the_three_events():
    assert set(ev.ALL_EVENTS) == {
        "run.finished",
        "card.approved",
        "pack.exported",
    }


def test_validate_drops_unknown_and_orders():
    out = ev.validate_events(["card.approved", "nope", "run.finished", "run.finished"])
    assert out == [e for e in ev.ALL_EVENTS if e in {"card.approved", "run.finished"}]
    assert "nope" not in out


def test_envelope_shape():
    env = ev.card_approved("org-a", "r1", "c1", via="api")
    assert env["type"] == "card.approved"
    assert env["org"] == "org-a"
    assert env["created"]
    assert env["data"] == {"run_id": "r1", "card_id": "c1", "via": "api"}


def test_payload_builders_are_whitelisted():
    # No internal paths / secrets — just the documented fields.
    rf = ev.run_finished("org-a", "r1", card_count=3, meet_name="Gala")
    assert rf["data"] == {"run_id": "r1", "card_count": 3, "meet_name": "Gala"}
    pe = ev.pack_exported("org-a", "r1")
    assert pe["data"]["run_id"] == "r1"
