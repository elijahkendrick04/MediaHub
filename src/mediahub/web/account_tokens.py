"""Signed, expiring account tokens — password reset + email verification (PC.14).

Same itsdangerous machinery as the W.9 magic links, keyed off the app
SECRET_KEY with purpose-specific salts. The reset token additionally carries
a fingerprint of the account's *current* password hash, which makes every
outstanding reset link single-use: the moment the password changes, the
fingerprint stops matching and older links die — no server-side token table
needed.
"""

from __future__ import annotations

import hashlib

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_RESET_SALT = "mediahub-password-reset-v1"
_VERIFY_SALT = "mediahub-email-verify-v1"

RESET_MAX_AGE_HOURS = 2.0
VERIFY_MAX_AGE_HOURS = 72.0


class AccountTokenError(Exception):
    """Invalid token (signature, shape, or superseded password)."""


class AccountTokenExpired(AccountTokenError):
    """Token older than its max age."""


def _serializer(secret: str, salt: str) -> URLSafeTimedSerializer:
    if not secret:
        raise AccountTokenError("no signing secret configured")
    return URLSafeTimedSerializer(secret, salt=salt)


def _password_fingerprint(hashed_password: str) -> str:
    """A short, non-reversible marker of the current password hash."""
    return hashlib.sha256((hashed_password or "").encode("utf-8")).hexdigest()[:16]


# ---- password reset --------------------------------------------------------


def mint_reset_token(secret: str, email: str, hashed_password: str) -> str:
    if not (email or "").strip():
        raise AccountTokenError("email required")
    payload = {"e": email.strip().lower(), "f": _password_fingerprint(hashed_password)}
    return _serializer(secret, _RESET_SALT).dumps(payload)


def verify_reset_token(
    secret: str,
    token: str,
    *,
    current_hash_for_email,
    max_age_hours: float = RESET_MAX_AGE_HOURS,
) -> str:
    """Validate a reset token → the account email.

    ``current_hash_for_email`` is a callable ``email -> hashed_password or
    None`` (the UserStore lookup). A token minted before any later password
    change fails the fingerprint check — single-use by construction.
    """
    try:
        payload = _serializer(secret, _RESET_SALT).loads(
            token, max_age=int(max_age_hours * 3600)
        )
    except SignatureExpired as e:
        raise AccountTokenExpired("this reset link has expired") from e
    except BadSignature as e:
        raise AccountTokenError("invalid reset link") from e
    email = str(payload.get("e") or "") if isinstance(payload, dict) else ""
    if not email:
        raise AccountTokenError("invalid reset link")
    current = current_hash_for_email(email)
    if not current or _password_fingerprint(current) != payload.get("f"):
        raise AccountTokenError("this reset link has already been used")
    return email


# ---- email verification ----------------------------------------------------


def mint_verify_token(secret: str, email: str) -> str:
    if not (email or "").strip():
        raise AccountTokenError("email required")
    return _serializer(secret, _VERIFY_SALT).dumps({"e": email.strip().lower()})


def verify_verify_token(
    secret: str, token: str, *, max_age_hours: float = VERIFY_MAX_AGE_HOURS
) -> str:
    """Validate a verification token → the account email."""
    try:
        payload = _serializer(secret, _VERIFY_SALT).loads(
            token, max_age=int(max_age_hours * 3600)
        )
    except SignatureExpired as e:
        raise AccountTokenExpired("this verification link has expired") from e
    except BadSignature as e:
        raise AccountTokenError("invalid verification link") from e
    email = str(payload.get("e") or "") if isinstance(payload, dict) else ""
    if not email:
        raise AccountTokenError("invalid verification link")
    return email


__all__ = [
    "AccountTokenError",
    "AccountTokenExpired",
    "RESET_MAX_AGE_HOURS",
    "VERIFY_MAX_AGE_HOURS",
    "mint_reset_token",
    "mint_verify_token",
    "verify_reset_token",
    "verify_verify_token",
]
