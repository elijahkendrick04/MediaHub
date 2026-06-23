"""1.21 webhooks — the per-org endpoint registry."""

from __future__ import annotations

import pytest

from mediahub.webhooks import _db
from mediahub.webhooks.registry import EndpointStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _db._initialized.clear()
    return EndpointStore()


def test_create_generates_secret_and_filters_events(store):
    ep = store.create(
        "org-a",
        "https://example.com/hook",
        events=["card.approved", "bogus.event"],
        created_by="o@x.com",
    )
    assert ep.secret.startswith("whsec_")
    assert ep.events == ["card.approved"]  # unknown event dropped
    assert ep.active is True


def test_create_rejects_non_http_url(store):
    with pytest.raises(ValueError):
        store.create("org-a", "ftp://nope", events=["card.approved"])
    with pytest.raises(ValueError):
        store.create("org-a", "", events=[])


def test_list_is_tenant_scoped(store):
    store.create("org-a", "https://a.com/h", events=["run.finished"])
    store.create("org-b", "https://b.com/h", events=["run.finished"])
    assert len(store.list_for_profile("org-a")) == 1
    assert len(store.list_for_profile("org-b")) == 1


def test_list_filters_by_event(store):
    store.create("org-a", "https://a.com/h", events=["run.finished"])
    store.create("org-a", "https://b.com/h", events=["card.approved"])
    approved = store.list_for_profile("org-a", event="card.approved")
    assert [e.url for e in approved] == ["https://b.com/h"]


def test_delete_is_tenant_scoped(store):
    ep = store.create("org-a", "https://a.com/h", events=["run.finished"])
    assert store.delete(ep.id, "org-b") is False  # wrong tenant
    assert store.get(ep.id) is not None
    assert store.delete(ep.id, "org-a") is True
    assert store.get(ep.id) is None


def test_set_active_and_roll_secret(store):
    ep = store.create("org-a", "https://a.com/h", events=["run.finished"])
    assert store.set_active(ep.id, "org-a", False) is True
    assert store.get(ep.id).active is False
    old = ep.secret
    new = store.roll_secret(ep.id, "org-a")
    assert new and new != old
    assert store.get(ep.id).secret == new
    # tenant-scoped roll
    assert store.roll_secret(ep.id, "org-b") is None


def test_public_dict_hides_secret_by_default(store):
    ep = store.create("org-a", "https://a.com/h", events=["run.finished"])
    assert "secret" not in ep.to_public_dict()
    assert ep.to_public_dict(include_secret=True)["secret"] == ep.secret
