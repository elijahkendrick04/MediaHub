"""1.21 public API — the org-scoped token store (auth security posture)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from mediahub.api_public import _db
from mediahub.api_public.tokens import ApiTokenStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _db._initialized.clear()  # force schema bootstrap against the temp db
    return ApiTokenStore()


def test_create_returns_usable_secret(store):
    tok, secret = store.create("org-a", name="t", scopes=["runs:read"], created_by="a@b.com")
    assert secret.startswith("mhk_")
    assert tok.profile_id == "org-a"
    assert tok.scopes == ["runs:read"]
    got = store.verify(secret)
    assert got is not None and got.id == tok.id


def test_secret_is_never_stored_in_plaintext(store, tmp_path):
    _tok, secret = store.create("org-a", name="t", scopes=["runs:read"], created_by="a@b.com")
    raw = (tmp_path / "data.db").read_bytes()
    assert secret.encode() not in raw  # only the sha256 hash is persisted


def test_verify_rejects_unknown_and_malformed(store):
    assert store.verify("") is None
    assert store.verify("not-a-token") is None
    assert store.verify("mhk_deadbeef") is None


def test_revoke_is_tenant_scoped(store):
    tok, secret = store.create("org-a", scopes=["runs:read"], created_by="a@b.com")
    # Another org cannot revoke this token.
    assert store.revoke(tok.id, "org-b") is False
    assert store.verify(secret) is not None
    # Its own org can.
    assert store.revoke(tok.id, "org-a") is True
    assert store.verify(secret) is None


def test_expired_token_does_not_verify(store):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _tok, secret = store.create("org-a", scopes=["runs:read"], created_by="a@b.com", expires_at=past)
    assert store.verify(secret) is None


def test_future_expiry_still_verifies(store):
    future = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _tok, secret = store.create("org-a", scopes=["runs:read"], created_by="a@b.com", expires_at=future)
    assert store.verify(secret) is not None


def test_list_excludes_revoked_by_default(store):
    a, _ = store.create("org-a", name="keep", scopes=["runs:read"], created_by="x")
    b, _ = store.create("org-a", name="drop", scopes=["runs:read"], created_by="x")
    store.revoke(b.id, "org-a")
    active = store.list_for_profile("org-a")
    assert [t.id for t in active] == [a.id]
    assert len(store.list_for_profile("org-a", include_revoked=True)) == 2


def test_list_is_tenant_isolated(store):
    store.create("org-a", scopes=["runs:read"], created_by="x")
    store.create("org-b", scopes=["runs:read"], created_by="y")
    assert len(store.list_for_profile("org-a")) == 1
    assert len(store.list_for_profile("org-b")) == 1


def test_unknown_scopes_are_dropped_at_creation(store):
    tok, _ = store.create("org-a", scopes=["runs:read", "danger:all"], created_by="x")
    assert tok.scopes == ["runs:read"]


def test_verify_touches_last_used(store):
    tok, secret = store.create("org-a", scopes=["runs:read"], created_by="x")
    assert tok.last_used_at is None
    store.verify(secret)
    assert store.get(tok.id).last_used_at is not None


def test_public_dict_has_no_secret(store):
    tok, secret = store.create("org-a", scopes=["runs:read"], created_by="x")
    d = tok.to_public_dict()
    assert "token_hash" not in d and secret not in str(d)
