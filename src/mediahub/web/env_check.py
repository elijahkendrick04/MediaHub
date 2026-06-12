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

    dev_key = os.environ.get("MEDIAHUB_DEV_KEY", "").strip()
    if dev_key and len(dev_key) < 24:
        errors.append(
            "MEDIAHUB_DEV_KEY is set but shorter than 24 characters — the "
            "operator override must be high-entropy (or unset)."
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
