"""Production boot warns (does not yet refuse) on the shipped operator credential.

Deep-review 2026-07 finding #26 / ADR-0022: the operator ``/developer``
password hash is committed to a *public* repository, so it is offline-crackable
by anyone with repo read — and a crack grants an unrestricted operator session
on production.

Hard enforcement (refusing to boot until ``MEDIAHUB_DEV_PASSWORD_HASH`` is
rotated) is **deferred to pre-launch** (roadmap RP.5) so the in-development
Render deploy keeps booting on the baked-in default while the product is
pre-customers. Until then ``env_check`` emits a **production warning** — never a
hard stop — so the risk is not silently forgotten. At go-live RP.5 rotates the
hash and flips this to a hard error; this test pins the current (warn-only)
behaviour.
"""

from __future__ import annotations

import logging

import pytest

from mediahub.web import env_check
from mediahub.web.auth import _DEV_PASSWORD_HASH_DEFAULT, dev_password_hash_overridden

_ROTATED = "$argon2id$v=19$m=65536,t=3,p=4$rotated-test-value$rotated-test-digest"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for var in ("RENDER", "FLY_APP_NAME", "MEDIAHUB_ENV",
                "MEDIAHUB_DEV_PASSWORD_HASH", "MEDIAHUB_DEV_USER"):
        monkeypatch.delenv(var, raising=False)
    yield


# ---- the predicate (reused by the launch-time hard error) --------------


def test_predicate_false_when_unset():
    assert dev_password_hash_overridden() is False


def test_predicate_false_when_set_to_shipped_default(monkeypatch):
    # Copy-pasting the committed default into the env is NOT a rotation.
    monkeypatch.setenv("MEDIAHUB_DEV_PASSWORD_HASH", _DEV_PASSWORD_HASH_DEFAULT)
    assert dev_password_hash_overridden() is False


def test_predicate_true_when_rotated(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_DEV_PASSWORD_HASH", _ROTATED)
    assert dev_password_hash_overridden() is True


# ---- production: WARN, never hard-stop (enforcement deferred, RP.5) -----


def test_production_warns_but_boots_on_default_credential(monkeypatch, caplog):
    monkeypatch.setenv("MEDIAHUB_ENV", "production")
    with caplog.at_level(logging.WARNING):
        env_check.validate_environment()  # must NOT raise while enforcement is deferred
    assert any("MEDIAHUB_DEV_PASSWORD_HASH" in r.message for r in caplog.records)


def test_production_quiet_when_rotated(monkeypatch, caplog):
    monkeypatch.setenv("MEDIAHUB_ENV", "production")
    monkeypatch.setenv("MEDIAHUB_DEV_PASSWORD_HASH", _ROTATED)
    with caplog.at_level(logging.WARNING):
        env_check.validate_environment()
    assert not any("MEDIAHUB_DEV_PASSWORD_HASH" in r.message for r in caplog.records)


# ---- dev / test: not even a warning (production-scoped) -----------------


def test_non_production_has_no_credential_warning(monkeypatch, caplog):
    # No production signal set (autouse fixture cleared them).
    with caplog.at_level(logging.WARNING):
        env_check.validate_environment()  # no exception
    assert not any("MEDIAHUB_DEV_PASSWORD_HASH" in r.message for r in caplog.records)
