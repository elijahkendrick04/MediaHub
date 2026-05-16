"""swim_content_v4/secrets_store.py — User-supplied secrets persistence.

Stores user-provided API keys in `data/secrets.json` with file-mode 0600.
Currently used for:
    - anthropic_api_key  (for live AI captions, set via /settings)

This module DOES NOT read environment variables. It is the dedicated
on-disk fallback that the LLM layer consults when no env key is present.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Legacy in-package path (kept ONLY so we can migrate old saves forward).
_LEGACY_SECRETS_PATH = _ROOT / "data" / "secrets.json"


def _resolve_secrets_path() -> Path:
    """Resolve the on-disk path for `secrets.json`.

    Honour DATA_DIR (same env var the rest of the app uses for runs, uploads,
    cache, etc. — see web.py:238). On Render / Docker / any deployment with a
    persistent disk mounted at DATA_DIR, saved API keys must land there so
    they survive container restarts and re-deploys. The old hardcoded
    in-package path got wiped every deploy, which is why users reported
    "I saved my Gemini key but the LLM keeps falling back to heuristic".
    """
    data_dir = os.environ.get("DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir) / "secrets.json"
    return _LEGACY_SECRETS_PATH


# Resolved at import time; deliberate — tests that mutate DATA_DIR per call
# should call `_resolve_secrets_path()` directly. Web routes import this
# module once at startup, by which time DATA_DIR is fixed for the process.
_SECRETS_PATH = _resolve_secrets_path()


def secrets_path() -> Path:
    """Public accessor for the active secrets path (used by /settings diag)."""
    return _SECRETS_PATH


def _ensure_dir() -> None:
    _SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)


def _migrate_legacy_secrets() -> None:
    """One-shot copy of the in-package secrets file to the DATA_DIR path.

    Runs lazily inside load_secrets() when the new path is empty but a legacy
    file exists. Idempotent: skips if the destination already has a file.
    """
    if _SECRETS_PATH == _LEGACY_SECRETS_PATH:
        return
    if _SECRETS_PATH.exists():
        return
    if not _LEGACY_SECRETS_PATH.exists():
        return
    try:
        _ensure_dir()
        with _LEGACY_SECRETS_PATH.open("r", encoding="utf-8") as src:
            payload = src.read()
        tmp = _SECRETS_PATH.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as dst:
            dst.write(payload)
        tmp.replace(_SECRETS_PATH)
        try:
            os.chmod(_SECRETS_PATH, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            pass
    except Exception:
        # Migration is best-effort. If it fails, fall through to a fresh store.
        return


def load_secrets() -> dict:
    """Return the secrets dict, or {} if absent / unreadable."""
    if not _SECRETS_PATH.exists():
        _migrate_legacy_secrets()
    if not _SECRETS_PATH.exists():
        return {}
    try:
        with _SECRETS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_secrets(secrets: dict) -> None:
    """Persist the secrets dict to disk with 0600 permissions."""
    _ensure_dir()
    tmp = _SECRETS_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(secrets, f, indent=2, sort_keys=True)
    tmp.replace(_SECRETS_PATH)
    try:
        os.chmod(_SECRETS_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        # On some platforms (e.g. Windows) chmod is best-effort.
        pass


def get_secret(key: str) -> Optional[str]:
    """Return a single secret value, or None if missing/blank."""
    val = load_secrets().get(key)
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


def set_secret(key: str, value: Optional[str]) -> None:
    """Set/clear a single secret. Empty/None deletes the key."""
    s = load_secrets()
    if value is None or not str(value).strip():
        s.pop(key, None)
    else:
        s[key] = str(value).strip()
    save_secrets(s)


def get_anthropic_key() -> Optional[str]:
    """Return the live Anthropic API key from env or on-disk store.

    Precedence: ANTHROPIC_API_KEY env > data/secrets.json key.
    """
    env = os.environ.get("ANTHROPIC_API_KEY")
    if env and env.strip():
        return env.strip()
    return get_secret("anthropic_api_key")


def has_anthropic_key() -> bool:
    return bool(get_anthropic_key())


def get_buffer_access_token() -> Optional[str]:
    """Return the user's Buffer access token, from env or on-disk store.

    Precedence: BUFFER_ACCESS_TOKEN env > data/secrets.json key.
    Used by the publishing layer (src/mediahub/publishing/buffer.py) to
    schedule approved content cards to the user's connected social channels.
    """
    env = os.environ.get("BUFFER_ACCESS_TOKEN")
    if env and env.strip():
        return env.strip()
    return get_secret("buffer_access_token")


def has_buffer_access_token() -> bool:
    return bool(get_buffer_access_token())


def set_buffer_access_token(token: Optional[str]) -> None:
    """Store the Buffer access token. Empty/None clears it."""
    set_secret("buffer_access_token", token)


def mask_key(key: Optional[str]) -> str:
    """Render a partially-masked key for UI display."""
    if not key:
        return ""
    k = key.strip()
    if len(k) <= 12:
        return "•" * len(k)
    return f"{k[:6]}…{k[-4:]} ({len(k)} chars)"


__all__ = [
    "load_secrets", "save_secrets",
    "get_secret", "set_secret",
    "get_anthropic_key", "has_anthropic_key",
    "get_buffer_access_token", "has_buffer_access_token",
    "set_buffer_access_token",
    "mask_key",
]
