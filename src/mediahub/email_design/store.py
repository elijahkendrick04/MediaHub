"""email_design.store — per-club newsletter persistence + the public token index.

Newsletters are saved per profile under
``DATA_DIR/newsletters/<profile_id>/<newsletter_id>.json`` so they are
**multi-tenant isolated** by construction — one club can only ever load its own
newsletters (the web layer scopes every call to the active profile). Each file
holds the editable *draft* spec plus a small publish record for the **hosted web
version** (roadmap 1.17 export #3): whether it is live, a frozen published
snapshot (so editing a draft never changes the live page until re-published —
the human-approval gate), and an unguessable public token.

The public surface resolves a token → (profile_id, newsletter_id) through a
small index file (``DATA_DIR/newsletters/_tokens.json``) with a **constant-time**
compare, exactly like :mod:`sites.store` and :mod:`web.public_wall`. Revocation
is structural: unpublishing removes the token from the index *and* the record,
so the old URL resolves to nothing.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Optional

from .models import NewsletterSpec

_SAFE = re.compile(r"[^A-Za-z0-9_-]")
_LOCK = threading.Lock()


def _safe(component: str) -> str:
    return _SAFE.sub("_", str(component or "")).strip("_") or "default"


def _root() -> Path:
    d = Path(os.environ.get("DATA_DIR", ".")).resolve() / "newsletters"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _profile_dir(profile_id: str) -> Path:
    d = _root() / _safe(profile_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(profile_id: str, newsletter_id: str) -> Path:
    return _profile_dir(profile_id) / f"{_safe(newsletter_id)}.json"


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
# Token index (token → {profile_id, newsletter_id})
# ---------------------------------------------------------------------------


def _tokens_path() -> Path:
    return _root() / "_tokens.json"


def _load_tokens() -> dict:
    return _read(_tokens_path()) or {}


def _save_tokens(tokens: dict) -> None:
    _atomic_write(_tokens_path(), tokens)


# ---------------------------------------------------------------------------
# Draft CRUD
# ---------------------------------------------------------------------------


def save_newsletter(profile_id: str, spec: NewsletterSpec) -> NewsletterSpec:
    """Persist a newsletter's editable draft (atomic). Preserves publish state.

    The read-modify-write runs under ``_LOCK`` like publish/unpublish/delete —
    otherwise a save racing a publish can clobber the record's publish fields
    while ``_tokens.json`` keeps the token, stranding a 404ing public URL."""
    p = _path(profile_id, spec.newsletter_id)
    with _LOCK:
        existing = _read(p) or {}
        payload = {
            "updated_at": time.time(),
            "title": spec.title,
            "newsletter_format": spec.newsletter_format,
            "spec": spec.to_dict(),
            # carry forward publish state untouched
            "published": bool(existing.get("published")),
            "public_token": existing.get("public_token", ""),
            "published_at": existing.get("published_at", 0.0),
            "published_spec": existing.get("published_spec"),
            "created_at": existing.get("created_at", time.time()),
        }
        _atomic_write(p, payload)
    return spec


def load_newsletter(profile_id: str, newsletter_id: str) -> Optional[NewsletterSpec]:
    """Load a newsletter's editable draft, or None if missing / unreadable."""
    payload = _read(_path(profile_id, newsletter_id))
    if payload is None:
        return None
    return NewsletterSpec.from_dict(payload.get("spec") or {})


def list_newsletters(profile_id: str) -> list[dict]:
    """Summaries of a profile's newsletters, most-recently-updated first."""
    out: list[dict] = []
    for f in _profile_dir(profile_id).glob("*.json"):
        payload = _read(f)
        if not payload:
            continue
        spec = payload.get("spec") or {}
        out.append(
            {
                "newsletter_id": spec.get("newsletter_id") or f.stem,
                "title": payload.get("title") or spec.get("title") or "Untitled newsletter",
                "newsletter_format": (
                    payload.get("newsletter_format") or spec.get("newsletter_format") or "blank"
                ),
                "updated_at": float(payload.get("updated_at") or 0.0),
                "published": bool(payload.get("published")),
                "public_token": payload.get("public_token", "") if payload.get("published") else "",
                "n_sections": len(spec.get("sections") or []),
            }
        )
    out.sort(key=lambda d: d["updated_at"], reverse=True)
    return out


def newsletter_record(profile_id: str, newsletter_id: str) -> Optional[dict]:
    """The full stored record (header + publish state), or None."""
    payload = _read(_path(profile_id, newsletter_id))
    if payload is None:
        return None
    return {
        "newsletter_id": newsletter_id,
        "title": payload.get("title", ""),
        "newsletter_format": payload.get("newsletter_format", ""),
        "updated_at": float(payload.get("updated_at") or 0.0),
        "published": bool(payload.get("published")),
        "public_token": payload.get("public_token", "") if payload.get("published") else "",
        "published_at": float(payload.get("published_at") or 0.0),
    }


def delete_newsletter(profile_id: str, newsletter_id: str) -> bool:
    """Delete a newsletter and remove its public token from the index."""
    with _LOCK:
        payload = _read(_path(profile_id, newsletter_id))
        token = (payload or {}).get("public_token", "")
        if token:
            tokens = _load_tokens()
            tokens.pop(token, None)
            _save_tokens(tokens)
        try:
            _path(profile_id, newsletter_id).unlink()
            return True
        except OSError:
            return False


# ---------------------------------------------------------------------------
# Publish / unpublish (the human-approval gate for the hosted web version)
# ---------------------------------------------------------------------------


def publish_newsletter(profile_id: str, newsletter_id: str) -> Optional[str]:
    """Freeze the current draft as the live snapshot and make it publicly
    reachable as a hosted web page. Returns the public token, or None if the
    newsletter doesn't exist. Re-publishing refreshes the snapshot in place and
    keeps the token, so a shared link stays valid across edits."""
    with _LOCK:
        p = _path(profile_id, newsletter_id)
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
        tokens[token] = {"profile_id": profile_id, "newsletter_id": newsletter_id}
        _save_tokens(tokens)
        return token


def unpublish_newsletter(profile_id: str, newsletter_id: str) -> bool:
    """Take the hosted page offline: drop the token from the index and the
    record, so the public URL resolves to nothing (structural revocation)."""
    with _LOCK:
        p = _path(profile_id, newsletter_id)
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


def load_published(profile_id: str, newsletter_id: str) -> Optional[NewsletterSpec]:
    """The frozen *published* snapshot served to the public, or None if the
    newsletter isn't currently published."""
    payload = _read(_path(profile_id, newsletter_id))
    if not payload or not payload.get("published"):
        return None
    snap = payload.get("published_spec") or payload.get("spec") or {}
    return NewsletterSpec.from_dict(snap)


def resolve_token(token: str) -> Optional[tuple[str, str]]:
    """Resolve a public token to (profile_id, newsletter_id), or None.
    Constant-time compare against the index, then a defence-in-depth re-check
    that the newsletter is still published with the same token."""
    token = (token or "").strip()
    if not token:
        return None
    tokens = _load_tokens()
    for known, ref in tokens.items():
        if hmac.compare_digest(str(known), token):
            profile_id = str(ref.get("profile_id", ""))
            newsletter_id = str(ref.get("newsletter_id", ""))
            payload = _read(_path(profile_id, newsletter_id))
            if (
                payload
                and payload.get("published")
                and hmac.compare_digest(str(payload.get("public_token", "")), token)
            ):
                return profile_id, newsletter_id
            return None
    return None


__all__ = [
    "save_newsletter",
    "load_newsletter",
    "list_newsletters",
    "newsletter_record",
    "delete_newsletter",
    "publish_newsletter",
    "unpublish_newsletter",
    "load_published",
    "resolve_token",
]
