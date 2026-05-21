"""On-disk theme store — Phase 1.6 Stage G.

The single source of truth for brand-derived palettes consumed by
the four content surfaces (web, motion, email, static graphics).

Storage layout:
    DATA_DIR/themes/<profile_id>.json

The file is a DTCG-format dict matching the ``ThemeJSON`` TypedDict
in ``mediahub.theming.__init__``. It mirrors
``ClubProfile.brand_kit.derived_palette`` so consumers don't have
to load the full ClubProfile to pluck the palette.

Public API
----------
- ``themes_dir()``       — directory path, created on demand
- ``theme_path(pid)``    — absolute path for a profile's theme JSON
- ``write_theme(pid, dict)`` — atomic write (tmp + rename)
- ``read_theme(pid)``    — cached read; returns None for missing/malformed
- ``delete_theme(pid)``  — idempotent deletion
- ``palette_for_motion(theme_json)`` — dark-scheme {primary,secondary,accent}
- ``palette_for_email(theme_json)``  — light-scheme {primary,secondary,accent}
- ``palette_for_static(theme_json)`` — light-scheme {primary,secondary,accent}

Each ``palette_for_*`` helper encodes the role-mapping convention
documented in ``docs/THEMING.md`` §7.
The dark/light split is intentional: motion (video-grade output)
needs higher saturation; email + static graphics live on white
backgrounds so they need higher contrast.

Safety
------
- ``profile_id`` is regex-validated before becoming a filesystem
  path — no `../etc/passwd` shenanigans.
- Writes are atomic via ``tempfile.NamedTemporaryFile`` + ``Path.replace``.
- Reads are cached by ``(path, mtime)`` so a fresh write invalidates
  the cached read on the next call.
- Read errors return ``None`` rather than raising — every consumer
  has a legacy fallback path.

References:
    - W3C Design Tokens Format Module (DTCG)
    - docs/THEMING.md
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Optional


__all__ = [
    "themes_dir",
    "theme_path",
    "write_theme",
    "read_theme",
    "delete_theme",
    "palette_for_motion",
    "palette_for_email",
    "palette_for_static",
    "ProfileIdError",
]


# Strict slug pattern — matches what ClubProfile profile_ids look
# like (lowercase, digits, hyphens, underscores). Defends against
# path traversal even if upstream profile-id validation is bypassed.
_PROFILE_ID_RE = re.compile(r"\A[a-z0-9\-_]{1,80}\Z")


class ProfileIdError(ValueError):
    """Raised when a profile_id fails the safety regex."""


def _data_dir() -> Path:
    """Resolve DATA_DIR at call time so tests can monkeypatch the env."""
    src_root = Path(__file__).resolve().parents[2]
    return Path(os.environ.get("DATA_DIR", str(src_root)))


def themes_dir() -> Path:
    """Return ``DATA_DIR/themes/``, creating it if necessary."""
    d = _data_dir() / "themes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _validate_pid(profile_id: str) -> str:
    if not isinstance(profile_id, str) or not _PROFILE_ID_RE.fullmatch(profile_id):
        raise ProfileIdError(
            f"profile_id must match {_PROFILE_ID_RE.pattern}, got {profile_id!r}"
        )
    return profile_id


def theme_path(profile_id: str) -> Path:
    """Return the absolute path for a profile's theme JSON.

    Raises ``ProfileIdError`` for unsafe profile ids.
    """
    pid = _validate_pid(profile_id)
    return themes_dir() / f"{pid}.json"


def write_theme(profile_id: str, theme_json: dict) -> Path:
    """Write the DTCG JSON atomically. Returns the absolute path.

    Atomicity: writes to a temp file in the same directory as the
    target, then ``Path.replace()``s into place. On POSIX this is
    a single ``rename(2)``; on Windows ``Path.replace`` is also
    atomic per spec.
    """
    if not isinstance(theme_json, dict):
        raise TypeError(f"theme_json must be a dict, got {type(theme_json).__name__}")
    dest = theme_path(profile_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{profile_id}-",
        suffix=".json.tmp",
        dir=str(dest.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(theme_json, f, ensure_ascii=False, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        Path(tmp_name).replace(dest)
        # Invalidate the read cache for this path so subsequent reads
        # pick up the new content.
        _read_cached.cache_clear()
    except Exception:
        # Clean up tmp on failure.
        try:
            Path(tmp_name).unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return dest


@lru_cache(maxsize=128)
def _read_cached(path_str: str, mtime_ns: int) -> Optional[dict]:
    """Cache key includes mtime_ns so a fresh write invalidates."""
    try:
        with open(path_str, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def read_theme(profile_id: str) -> Optional[dict]:
    """Read a profile's theme JSON, or None if missing / malformed.

    Never raises (the consumers all have legacy fallback paths).
    Cached by mtime so repeat reads in the same request are free.
    """
    try:
        path = theme_path(profile_id)
    except ProfileIdError:
        return None
    if not path.is_file():
        return None
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return None
    return _read_cached(str(path), mtime_ns)


def delete_theme(profile_id: str) -> bool:
    """Remove a profile's theme file. Idempotent — returns True if
    a file was deleted, False if nothing was there."""
    try:
        path = theme_path(profile_id)
    except ProfileIdError:
        return False
    try:
        path.unlink()
        _read_cached.cache_clear()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Role-mapping convention (docs/THEMING.md §7)
# ---------------------------------------------------------------------------
# Each helper maps Stage B's ~30 MD3 role tokens onto the legacy
# {primary, secondary, accent} shape that the three consumers
# (motion, email, static graphics) historically used. The dark/light
# split tracks the output medium:
#
#   Motion (Remotion):  dark scheme — video-grade saturation
#   Email:              light scheme — viewed on white email body
#   Static (Playwright): light scheme — viewed on white social feed
#
# All three return the SAME shape so downstream renderers can swap
# the helper call without code change.


_FALLBACK_PRIMARY = "#0A2540"
_FALLBACK_SECONDARY = "#000000"
_FALLBACK_ACCENT = "#FFFFFF"


def _role(theme_json: dict, scheme: str, role_name: str, fallback: str) -> str:
    """Pluck a role from the theme JSON's roles map, with fallback."""
    roles_map = (theme_json or {}).get("roles") or {}
    scheme_roles = roles_map.get(scheme) or {}
    value = scheme_roles.get(role_name)
    if isinstance(value, str) and value.startswith("#"):
        return value
    return fallback


def palette_for_motion(theme_json: dict) -> dict:
    """Map the theme JSON onto the Remotion compositions' shape.

    Uses the DARK scheme — video output's higher dynamic range
    handles saturated primaries cleanly, and MD3's dark.primary is
    the lighter / more saturated tone of the brand."""
    return {
        "primary":   _role(theme_json, "dark", "primary",              _FALLBACK_PRIMARY),
        "secondary": _role(theme_json, "dark", "secondary_container", _FALLBACK_SECONDARY),
        "accent":    _role(theme_json, "dark", "tertiary",             _FALLBACK_ACCENT),
        "scheme":    "dark",
        "source":    "theme-store",
    }


def palette_for_email(theme_json: dict) -> dict:
    """Map the theme JSON onto the newsletter renderer's shape.

    Uses the LIGHT scheme — emails are viewed against a white email
    body, and MD3's light.primary is the darker/more contrasting
    brand tone."""
    return {
        "primary":   _role(theme_json, "light", "primary",              _FALLBACK_PRIMARY),
        "secondary": _role(theme_json, "light", "secondary_container", _FALLBACK_SECONDARY),
        "accent":    _role(theme_json, "light", "tertiary",             _FALLBACK_ACCENT),
        "scheme":    "light",
        "source":    "theme-store",
    }


def palette_for_static(theme_json: dict) -> dict:
    """Map the theme JSON onto the graphic_renderer's brief.palette
    shape.

    Uses the LIGHT scheme — static graphics are posted to social
    feeds, which default to white backgrounds on mobile."""
    return {
        "primary":   _role(theme_json, "light", "primary",              _FALLBACK_PRIMARY),
        "secondary": _role(theme_json, "light", "secondary_container", _FALLBACK_SECONDARY),
        "accent":    _role(theme_json, "light", "tertiary",             _FALLBACK_ACCENT),
        "scheme":    "light",
        "source":    "theme-store",
    }
