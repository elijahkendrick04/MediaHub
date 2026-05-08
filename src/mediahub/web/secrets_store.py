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

_SECRETS_PATH = _ROOT / "data" / "secrets.json"


def _ensure_dir() -> None:
    _SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_secrets() -> dict:
    """Return the secrets dict, or {} if absent / unreadable."""
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
    "mask_key",
]
