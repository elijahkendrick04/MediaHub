"""mediahub/web/secrets_store.py — operator credential resolution.

Post-rewrite: all credentials are **operator-controlled via env vars**
at deploy time. The settings page is gone. The user never sees a key.

This module remains as a thin facade with the same public API the rest
of the codebase imports, so callers don't break. Its job is now:

  • `get_*` / `get_secret(key)` reads from the relevant env var first;
    falls back to the on-disk `secrets.json` for ONE release so that
    self-hosted installs that pre-date this rewrite don't lose their
    keys overnight. A startup-time warning is logged when the disk
    fallback fires, telling the operator to migrate to env vars.

  • `set_*` / `set_secret(key, value)` are now no-ops that log a
    warning. They exist so that any stragglers in the codebase that
    still call them don't error out — but they never persist anything
    new. The settings page that used to call them is gone.

  • `save_secrets(...)` was the disk-writing back-compat shim and is
    DEPRECATED — kept only as a no-op stub to be deleted in the next
    release once we've confirmed no callers remain.

  • `_load_secrets_legacy()` (formerly `load_secrets`) is a private
    helper used internally by `get_secret` for the one-release disk-
    fallback path. Public callers should use `get_secret(key)`.

The on-disk fallback will be deleted in the next major release.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_LEGACY_SECRETS_PATH = _ROOT / "data" / "secrets.json"


def _resolve_secrets_path() -> Path:
    """Resolve the on-disk secrets fallback path. DATA_DIR-aware."""
    data_dir = os.environ.get("DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir) / "secrets.json"
    return _LEGACY_SECRETS_PATH


_SECRETS_PATH = _resolve_secrets_path()


def secrets_path() -> Path:
    """Return the legacy fallback path (still consulted for reads)."""
    return _SECRETS_PATH


# Env-var mapping for every credential the codebase currently reads via
# `get_secret(name)`. The disk-fallback path consults this table so that
# even a generic `get_secret("photoroom_api_key")` call hits the env
# first. The names match the existing on-disk JSON keys.
_SECRET_ENV_NAMES: dict[str, tuple[str, ...]] = {
    "anthropic_api_key":       ("ANTHROPIC_API_KEY",),
    "gemini_api_key":          ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "buffer_access_token":     ("BUFFER_ACCESS_TOKEN",),
    "photoroom_api_key":       ("PHOTOROOM_API_KEY",),
    "replicate_api_token":     ("REPLICATE_API_TOKEN",),
    "mediahub_cutout_provider": ("MEDIAHUB_CUTOUT_PROVIDER",),
    "mediahub_llm_provider":   ("MEDIAHUB_LLM_PROVIDER",),
}


def _load_secrets_legacy() -> dict:
    """Return the on-disk secrets dict (one-release fallback). May be empty.

    Private helper for `get_secret`'s disk-fallback path. Renamed from
    the public `load_secrets` name as part of the dead-code cleanup —
    there are no external callers, and the next major release will
    remove the disk-fallback entirely along with this function.
    """
    if not _SECRETS_PATH.exists():
        return {}
    try:
        with _SECRETS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_secrets(secrets: dict) -> None:
    """DEPRECATED no-op back-compat shim — scheduled for removal.

    Operator credentials are env-var-only now. This function previously
    persisted the settings-page form submissions to `secrets.json`; the
    settings page is gone, so this is a no-op. Logs a warning so any
    surviving caller surfaces in operator logs and can be removed.
    Will be deleted in the next major release.
    """
    log.warning(
        "secrets_store.save_secrets() is a deprecated no-op — operator "
        "credentials are env-var-only since the settings-page removal. "
        "The attempted save has been discarded. Configure credentials "
        "via env vars at deploy time. This shim will be removed in the "
        "next major release."
    )


# ---------------------------------------------------------------------------
# Public read API
# ---------------------------------------------------------------------------

_WARNED_FOR: set[str] = set()


def get_secret(key: str) -> Optional[str]:
    """Resolve a secret value, env-first.

    1. If an env var mapped to this key has a non-blank value, return it.
    2. Otherwise, read from the legacy on-disk `secrets.json` and emit a
       one-time-per-key warning telling the operator to migrate.
    3. Return None when neither path has a value.
    """
    env_names = _SECRET_ENV_NAMES.get(key, ())
    for env_name in env_names:
        v = os.environ.get(env_name, "")
        if v and v.strip():
            return v.strip()
    # Disk fallback — only fires when env is unset. One-release deprecation.
    val = _load_secrets_legacy().get(key)
    if isinstance(val, str) and val.strip():
        if key not in _WARNED_FOR:
            _WARNED_FOR.add(key)
            log.warning(
                "secrets_store: using legacy on-disk value for %r — set "
                "the equivalent env var (%s) on this deployment to "
                "silence this warning. Disk fallback will be removed "
                "in the next major release.",
                key, "/".join(env_names) or "?",
            )
        return val.strip()
    return None


def set_secret(key: str, value: Optional[str]) -> None:
    """NO-OP. See module docstring.

    Logs a one-time warning the first time it's called with a non-None
    value, pointing the operator at the env-var path.
    """
    if value is not None and str(value).strip():
        if key not in _WARNED_FOR:
            _WARNED_FOR.add(key)
            env_names = _SECRET_ENV_NAMES.get(key, ())
            log.warning(
                "secrets_store.set_secret(%r) is a no-op — operator "
                "credentials are env-var-only since the settings-page "
                "removal. Configure %s in the deployment environment "
                "instead.",
                key, "/".join(env_names) or "the relevant env var",
            )


# ---------------------------------------------------------------------------
# Typed helpers (back-compat — kept for callers across the codebase)
# ---------------------------------------------------------------------------

def get_anthropic_key() -> Optional[str]:
    return get_secret("anthropic_api_key")


def has_anthropic_key() -> bool:
    return bool(get_anthropic_key())


def get_buffer_access_token() -> Optional[str]:
    return get_secret("buffer_access_token")


def has_buffer_access_token() -> bool:
    return bool(get_buffer_access_token())


def set_buffer_access_token(token: Optional[str]) -> None:
    """NO-OP. See set_secret docstring."""
    set_secret("buffer_access_token", token)


__all__ = [
    "save_secrets",
    "get_secret", "set_secret",
    "get_anthropic_key", "has_anthropic_key",
    "get_buffer_access_token", "has_buffer_access_token",
    "set_buffer_access_token",
    "secrets_path",
]
