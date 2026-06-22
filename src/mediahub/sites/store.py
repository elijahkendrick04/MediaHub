"""sites.store — per-club persistence, publish state & the public token index.

Sites are saved per profile under ``DATA_DIR/sites/<profile_id>/<site_id>.json`` so
they are **multi-tenant isolated** by construction — one club can only ever load its
own sites (the web layer scopes every call to the active profile). Each file holds
the editable *draft* spec plus a small publish record: whether it is live, its
**published snapshot** (frozen at publish time so editing a draft never changes the
live site until re-published — this is the human-approval gate), an unguessable
public token, and an optional access password.

The public surface resolves a token → (profile_id, site_id) through a small index
file (``DATA_DIR/sites/_tokens.json``) using a **constant-time** compare, exactly
like :mod:`web.public_wall`. Revocation is structural: unpublishing removes the
token from the index *and* the record, so the old URL resolves to nothing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Optional

from .models import SiteSpec

_SAFE = re.compile(r"[^A-Za-z0-9_-]")
_LOCK = threading.Lock()
_PBKDF2_ITERATIONS = 200_000


def _safe(component: str) -> str:
    return _SAFE.sub("_", str(component or "")).strip("_") or "default"


def _sites_root() -> Path:
    d = Path(os.environ.get("DATA_DIR", ".")).resolve() / "sites"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _profile_dir(profile_id: str) -> Path:
    d = _sites_root() / _safe(profile_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(profile_id: str, site_id: str) -> Path:
    return _profile_dir(profile_id) / f"{_safe(site_id)}.json"


def _atomic_write(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Token index (token → {profile_id, site_id})
# ---------------------------------------------------------------------------


def _tokens_path() -> Path:
    return _sites_root() / "_tokens.json"


def _load_tokens() -> dict:
    return _read(_tokens_path()) or {}


def _save_tokens(tokens: dict) -> None:
    _atomic_write(_tokens_path(), tokens)


# ---------------------------------------------------------------------------
# Password hashing (self-contained pbkdf2 — no Flask/Werkzeug dependency)
# ---------------------------------------------------------------------------


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    )
    return f"pbkdf2${_PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iters, salt, digest = str(stored).split("$", 3)
        if scheme != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iters)
        )
        return hmac.compare_digest(dk.hex(), digest)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Draft CRUD
# ---------------------------------------------------------------------------


def save_site(profile_id: str, spec: SiteSpec) -> SiteSpec:
    """Persist a site's editable draft (atomic). Preserves existing publish state."""
    p = _path(profile_id, spec.site_id)
    existing = _read(p) or {}
    payload = {
        "updated_at": time.time(),
        "title": spec.title,
        "archetype": spec.archetype,
        "spec": spec.to_dict(),
        # carry forward publish state untouched
        "published": bool(existing.get("published")),
        "public_token": existing.get("public_token", ""),
        "published_at": existing.get("published_at", 0.0),
        "published_spec": existing.get("published_spec"),
        "password": existing.get("password", ""),
        "created_at": existing.get("created_at", time.time()),
    }
    _atomic_write(p, payload)
    return spec


def load_site(profile_id: str, site_id: str) -> Optional[SiteSpec]:
    """Load a site's editable draft, or None if it doesn't exist / is unreadable."""
    payload = _read(_path(profile_id, site_id))
    if payload is None:
        return None
    return SiteSpec.from_dict(payload.get("spec") or {})


def list_sites(profile_id: str) -> list[dict]:
    """Summaries of a profile's sites, most-recently-updated first."""
    out: list[dict] = []
    for f in _profile_dir(profile_id).glob("*.json"):
        payload = _read(f)
        if not payload:
            continue
        spec = payload.get("spec") or {}
        out.append(
            {
                "site_id": spec.get("site_id") or f.stem,
                "title": payload.get("title") or spec.get("title") or "Untitled site",
                "archetype": payload.get("archetype") or spec.get("archetype") or "blank",
                "updated_at": float(payload.get("updated_at") or 0.0),
                "published": bool(payload.get("published")),
                "public_token": payload.get("public_token", "") if payload.get("published") else "",
                "n_pages": len(spec.get("pages") or []),
            }
        )
    out.sort(key=lambda d: d["updated_at"], reverse=True)
    return out


def site_record(profile_id: str, site_id: str) -> Optional[dict]:
    """The full stored record (header + publish state), or None. The ``password``
    hash is never returned — only a ``has_password`` boolean."""
    payload = _read(_path(profile_id, site_id))
    if payload is None:
        return None
    return {
        "site_id": site_id,
        "title": payload.get("title", ""),
        "archetype": payload.get("archetype", ""),
        "updated_at": float(payload.get("updated_at") or 0.0),
        "published": bool(payload.get("published")),
        "public_token": payload.get("public_token", "") if payload.get("published") else "",
        "published_at": float(payload.get("published_at") or 0.0),
        "has_password": bool(payload.get("password")),
    }


def delete_site(profile_id: str, site_id: str) -> bool:
    """Delete a site and remove its public token from the index."""
    with _LOCK:
        payload = _read(_path(profile_id, site_id))
        token = (payload or {}).get("public_token", "")
        if token:
            tokens = _load_tokens()
            tokens.pop(token, None)
            _save_tokens(tokens)
        try:
            _path(profile_id, site_id).unlink()
            return True
        except OSError:
            return False


# ---------------------------------------------------------------------------
# Publish / unpublish (the human-approval gate)
# ---------------------------------------------------------------------------


def publish_site(profile_id: str, site_id: str) -> Optional[str]:
    """Freeze the current draft as the live snapshot and make it publicly
    reachable. Returns the public token, or None if the site doesn't exist.

    Re-publishing refreshes the snapshot in place and keeps the existing token, so
    a printed QR code / shared link stays valid across edits."""
    with _LOCK:
        p = _path(profile_id, site_id)
        payload = _read(p)
        if payload is None:
            return None
        token = payload.get("public_token") or secrets.token_urlsafe(24)
        payload["public_token"] = token
        payload["published"] = True
        payload["published_at"] = time.time()
        payload["published_spec"] = payload.get("spec")  # freeze the snapshot
        _atomic_write(p, payload)
        tokens = _load_tokens()
        tokens[token] = {"profile_id": profile_id, "site_id": site_id}
        _save_tokens(tokens)
        return token


def unpublish_site(profile_id: str, site_id: str) -> bool:
    """Take a site offline: drop the token from the index and the record, so the
    public URL resolves to nothing (structural revocation, like the wall)."""
    with _LOCK:
        p = _path(profile_id, site_id)
        payload = _read(p)
        if payload is None:
            return False
        token = payload.get("public_token", "")
        if token:
            tokens = _load_tokens()
            tokens.pop(token, None)
            _save_tokens(tokens)
        payload["published"] = False
        payload["public_token"] = ""
        _atomic_write(p, payload)
        return True


def load_published(profile_id: str, site_id: str) -> Optional[SiteSpec]:
    """The frozen *published* snapshot served to the public, or None if the site
    isn't currently published."""
    payload = _read(_path(profile_id, site_id))
    if not payload or not payload.get("published"):
        return None
    snap = payload.get("published_spec") or payload.get("spec") or {}
    return SiteSpec.from_dict(snap)


# ---------------------------------------------------------------------------
# Public token resolution (constant-time, scoped to one org+site)
# ---------------------------------------------------------------------------


def resolve_token(token: str) -> Optional[tuple[str, str]]:
    """Resolve a public token to its (profile_id, site_id), or None. Constant-time
    compare against the index, then a defence-in-depth re-check that the site is
    still published with the same token."""
    token = (token or "").strip()
    if not token:
        return None
    tokens = _load_tokens()
    for known, ref in tokens.items():
        if hmac.compare_digest(str(known), token):
            profile_id = str(ref.get("profile_id", ""))
            site_id = str(ref.get("site_id", ""))
            payload = _read(_path(profile_id, site_id))
            if (
                payload
                and payload.get("published")
                and hmac.compare_digest(str(payload.get("public_token", "")), token)
            ):
                return profile_id, site_id
            return None
    return None


# ---------------------------------------------------------------------------
# Per-site access password (the password/SSO-protected-pages analog)
# ---------------------------------------------------------------------------


def set_site_password(profile_id: str, site_id: str, password: str) -> bool:
    """Set (non-empty) or clear (empty) the access password for a site's
    ``protected`` pages."""
    p = _path(profile_id, site_id)
    payload = _read(p)
    if payload is None:
        return False
    payload["password"] = _hash_password(password) if password else ""
    _atomic_write(p, payload)
    return True


def has_password(profile_id: str, site_id: str) -> bool:
    payload = _read(_path(profile_id, site_id))
    return bool(payload and payload.get("password"))


def check_site_password(profile_id: str, site_id: str, password: str) -> bool:
    payload = _read(_path(profile_id, site_id))
    stored = (payload or {}).get("password", "")
    if not stored:
        return True  # no password set → not gated
    return _verify_password(password, stored)


__all__ = [
    "save_site",
    "load_site",
    "list_sites",
    "site_record",
    "delete_site",
    "publish_site",
    "unpublish_site",
    "load_published",
    "resolve_token",
    "set_site_password",
    "has_password",
    "check_site_password",
]
