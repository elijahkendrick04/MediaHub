"""documents.store — per-club persistence for saved documents (roadmap 1.15).

Documents are saved per profile under ``DATA_DIR/documents/<profile_id>/<doc_id>.json``
so they are **multi-tenant isolated** by construction — one club can only ever load
its own documents (the web layer scopes every call to the active profile). Each file
holds the spec plus a small header (title/format/updated_at) for cheap listing.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Optional

from .models import DocumentSpec

_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def _safe(component: str) -> str:
    return _SAFE.sub("_", str(component or "")).strip("_") or "default"


def _profile_dir(profile_id: str) -> Path:
    d = Path(os.environ.get("DATA_DIR", ".")).resolve() / "documents" / _safe(profile_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(profile_id: str, doc_id: str) -> Path:
    return _profile_dir(profile_id) / f"{_safe(doc_id)}.json"


def save_document(profile_id: str, spec: DocumentSpec) -> DocumentSpec:
    """Persist a document for a profile (atomic write)."""
    payload = {
        "updated_at": time.time(),
        "title": spec.title,
        "doc_format": spec.doc_format,
        "kind": spec.kind,
        "spec": spec.to_dict(),
    }
    p = _path(profile_id, spec.doc_id)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, p)
    return spec


def load_document(profile_id: str, doc_id: str) -> Optional[DocumentSpec]:
    """Load one document for a profile, or None if it doesn't exist / is unreadable."""
    p = _path(profile_id, doc_id)
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
        return DocumentSpec.from_dict(payload.get("spec") or {})
    except (OSError, ValueError, TypeError):
        return None


def list_documents(profile_id: str) -> list[dict]:
    """Summaries of a profile's documents, most-recently-updated first."""
    out: list[dict] = []
    for f in _profile_dir(profile_id).glob("*.json"):
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        spec = payload.get("spec") or {}
        out.append(
            {
                "doc_id": spec.get("doc_id") or f.stem,
                "title": payload.get("title") or spec.get("title") or "Untitled",
                "doc_format": payload.get("doc_format") or spec.get("doc_format") or "blank",
                "kind": payload.get("kind") or spec.get("kind") or "document",
                "updated_at": float(payload.get("updated_at") or 0.0),
            }
        )
    out.sort(key=lambda d: d["updated_at"], reverse=True)
    return out


def delete_document(profile_id: str, doc_id: str) -> bool:
    p = _path(profile_id, doc_id)
    try:
        p.unlink()
        return True
    except OSError:
        return False


__all__ = ["save_document", "load_document", "list_documents", "delete_document"]
