"""PC.14 — signed account tokens: password reset (single-use) + verification."""

from __future__ import annotations

import pytest

from mediahub.web import account_tokens as at

SECRET = "test-secret-key"


def test_reset_token_round_trip():
    token = at.mint_reset_token(SECRET, "Coach@Club.org", "$2b$12$hashhashhash")
    email = at.verify_reset_token(
        SECRET, token, current_hash_for_email=lambda e: "$2b$12$hashhashhash"
    )
    assert email == "coach@club.org"


def test_reset_token_single_use_after_password_change():
    token = at.mint_reset_token(SECRET, "coach@club.org", "old-hash")
    # The password changed → the fingerprint no longer matches → token dead.
    with pytest.raises(at.AccountTokenError):
        at.verify_reset_token(SECRET, token, current_hash_for_email=lambda e: "new-hash")


def test_reset_token_dead_for_deleted_account():
    token = at.mint_reset_token(SECRET, "coach@club.org", "h")
    with pytest.raises(at.AccountTokenError):
        at.verify_reset_token(SECRET, token, current_hash_for_email=lambda e: None)


def test_reset_token_expiry():
    token = at.mint_reset_token(SECRET, "coach@club.org", "h")
    with pytest.raises(at.AccountTokenExpired):
        at.verify_reset_token(
            SECRET, token, current_hash_for_email=lambda e: "h", max_age_hours=-1
        )


def test_reset_token_wrong_secret_rejected():
    token = at.mint_reset_token(SECRET, "coach@club.org", "h")
    with pytest.raises(at.AccountTokenError):
        at.verify_reset_token(
            "other-secret", token, current_hash_for_email=lambda e: "h"
        )


def test_verify_token_round_trip():
    token = at.mint_verify_token(SECRET, "Coach@Club.org")
    assert at.verify_verify_token(SECRET, token) == "coach@club.org"


def test_verify_token_garbage_rejected():
    with pytest.raises(at.AccountTokenError):
        at.verify_verify_token(SECRET, "not-a-token")


def test_salts_are_not_interchangeable():
    # A verification token must never work as a reset token.
    token = at.mint_verify_token(SECRET, "coach@club.org")
    with pytest.raises(at.AccountTokenError):
        at.verify_reset_token(SECRET, token, current_hash_for_email=lambda e: "h")
