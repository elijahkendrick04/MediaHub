"""Tests for audio/consent.py — voice-feature consent gate + audit (1.8)."""

from __future__ import annotations

import pytest

from mediahub.audio.consent import ConsentRequired, ConsentStore, require_consent


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))


def test_features_off_by_default():
    store = ConsentStore()
    assert store.is_enabled("club-a", "clone") is False
    assert store.is_enabled("club-a", "changer") is False


def test_grant_enables_then_revoke_disables():
    store = ConsentStore()
    rec = store.grant(
        "club-a", "clone", voice_owner="Coach Jo", consent_ref="form-2026-01", granted_by="admin"
    )
    assert rec.active is True
    assert store.is_enabled("club-a", "clone") is True
    # Other feature stays off — grants are per-feature.
    assert store.is_enabled("club-a", "changer") is False
    n = store.revoke("club-a", "clone", by="admin")
    assert n == 1
    assert store.is_enabled("club-a", "clone") is False


def test_history_keeps_grant_and_revocation():
    store = ConsentStore()
    store.grant("club-a", "changer", granted_by="admin")
    store.revoke("club-a", "changer")
    hist = store.history("club-a")
    assert len(hist) == 1  # one row, now revoked
    assert hist[0].revoked_at  # audit trail keeps the revocation
    assert hist[0].active is False
    assert store.active("club-a") == []


def test_require_consent_guard():
    store = ConsentStore()
    with pytest.raises(ConsentRequired):
        require_consent("club-a", "clone", store=store)
    store.grant("club-a", "clone", granted_by="admin")
    require_consent("club-a", "clone", store=store)  # no raise now


def test_unknown_feature_rejected():
    store = ConsentStore()
    with pytest.raises(ValueError):
        store.grant("club-a", "deepfake", granted_by="admin")
    # is_enabled is defensive: unknown feature is simply not enabled.
    assert store.is_enabled("club-a", "deepfake") is False


def test_isolation_between_orgs():
    store = ConsentStore()
    store.grant("club-a", "clone", granted_by="admin")
    assert store.is_enabled("club-a", "clone") is True
    assert store.is_enabled("club-b", "clone") is False
