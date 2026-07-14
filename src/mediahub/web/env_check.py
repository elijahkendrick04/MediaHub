"""Fail-fast environment validation at boot (security/secrets-and-config).

A misconfigured production deployment should refuse to start with a clear
message, not run quietly in a degraded or unsafe shape and be discovered in
an incident. Called from ``create_app``.

Production detection: ``RENDER`` env (Render sets it), ``FLY_APP_NAME``,
or explicit ``MEDIAHUB_ENV=production``. Dev/test environments only get
warnings — local hacking must not require ceremony.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


class EnvConfigError(RuntimeError):
    """The deployment environment is unsafe/incomplete — refuse to boot."""


def is_production() -> bool:
    return bool(
        os.environ.get("RENDER")
        or os.environ.get("FLY_APP_NAME")
        or os.environ.get("MEDIAHUB_ENV", "").strip().lower() == "production"
    )


def _problems() -> tuple[list[str], list[str]]:
    """(hard errors in production, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    if not os.environ.get("DATA_DIR", "").strip():
        errors.append(
            "DATA_DIR is not set — runtime data (athlete personal data!) would "
            "land inside the source tree and vanish on redeploy. Point DATA_DIR "
            "at the persistent disk."
        )

    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        val = os.environ.get(var, "")
        if val != val.strip():
            errors.append(f"{var} has leading/trailing whitespace — fix the .env quoting.")
        if val and len(val.strip()) < 12:
            errors.append(f"{var} looks truncated ({len(val.strip())} chars).")

    if not (
        os.environ.get("GEMINI_API_KEY", "").strip()
        or os.environ.get("GOOGLE_API_KEY", "").strip()
        or os.environ.get("ANTHROPIC_API_KEY", "").strip()
        or os.environ.get("MEDIAHUB_LLM_ENDPOINTS", "").strip()
    ):
        warnings.append(
            "No LLM provider configured — AI surfaces will honest-error "
            "(ClaudeUnavailableError) until a key is set."
        )

    # Operator /developer credential (deep-review #26 / ADR-0022). The default
    # password hash is committed to a PUBLIC repo, so it is offline-crackable by
    # anyone with repo read; a crack yields an unrestricted operator session on
    # production. Hard enforcement (refusing to boot until the hash is rotated)
    # is DEFERRED to pre-launch — tracked as roadmap RP.5 — so the
    # in-development Render deploy still boots on the baked-in default while the
    # product is pre-customers. Until then we surface it as a production warning
    # so it is never silently forgotten; at go-live RP.5 rotates the hash and
    # flips this to a hard error (see ADR-0022).
    from mediahub.web.auth import dev_password_hash_overridden

    if is_production() and not dev_password_hash_overridden():
        warnings.append(
            "Operator /developer sign-in is running on the shipped default "
            "credential, whose argon2id hash is public and offline-crackable. "
            "Accepted during development; before go-live set "
            "MEDIAHUB_DEV_PASSWORD_HASH and enable enforcement "
            "(roadmap RP.5 / ADR-0022)."
        )
    return errors, warnings


def validate_environment() -> None:
    """Raise EnvConfigError in production for unsafe config; warn otherwise."""
    errors, warnings = _problems()
    for w in warnings:
        log.warning("env check: %s", w)
    if not errors:
        return
    if is_production():
        raise EnvConfigError(
            "Refusing to start with unsafe configuration:\n - " + "\n - ".join(errors)
        )
    for e in errors:
        log.warning("env check (non-production, not fatal): %s", e)
