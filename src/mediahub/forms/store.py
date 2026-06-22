"""forms.store — per-club persistence for form definitions (roadmap 1.16).

Forms are saved per profile under ``DATA_DIR/forms/<profile_id>/<form_id>.json`` so
they are **multi-tenant isolated** by construction — one club can only ever load its
own forms. The *responses* do not live here: they go into the 1.13 data hub as typed
rows (:mod:`forms.submit`), which is the single, exportable, GDPR-deletable home for
submitted data. This file holds only the form's shape (its fields) plus the id of the
data-hub table its responses land in.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Optional

from .models import FormSpec

_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def _safe(component: str) -> str:
    return _SAFE.sub("_", str(component or "")).strip("_") or "default"


def _profile_dir(profile_id: str) -> Path:
    d = Path(os.environ.get("DATA_DIR", ".")).resolve() / "forms" / _safe(profile_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(profile_id: str, form_id: str) -> Path:
    return _profile_dir(profile_id) / f"{_safe(form_id)}.json"


def save_form(profile_id: str, spec: FormSpec) -> FormSpec:
    """Persist a form definition (atomic write)."""
    payload = {
        "updated_at": time.time(),
        "title": spec.title,
        "form_id": spec.form_id,
        "spec": spec.to_dict(),
    }
    p = _path(profile_id, spec.form_id)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, p)
    return spec


def load_form(profile_id: str, form_id: str) -> Optional[FormSpec]:
    """Load one form for a profile, or None if missing / unreadable."""
    p = _path(profile_id, form_id)
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
        return FormSpec.from_dict(payload.get("spec") or {})
    except (OSError, ValueError, TypeError):
        return None


def list_forms(profile_id: str) -> list[dict]:
    """Summaries of a profile's forms, most-recently-updated first."""
    out: list[dict] = []
    for f in _profile_dir(profile_id).glob("*.json"):
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        spec = payload.get("spec") or {}
        out.append(
            {
                "form_id": spec.get("form_id") or f.stem,
                "title": payload.get("title") or spec.get("title") or "Form",
                "n_fields": len(spec.get("fields") or []),
                "table_id": spec.get("table_id") or "",
                "collects_minor_data": bool(spec.get("collects_minor_data")),
                "updated_at": float(payload.get("updated_at") or 0.0),
            }
        )
    out.sort(key=lambda d: d["updated_at"], reverse=True)
    return out


def delete_form(profile_id: str, form_id: str) -> bool:
    """Delete a form definition. (Its data-hub response table is left intact so
    already-collected responses are never lost by removing the form.)"""
    try:
        _path(profile_id, form_id).unlink()
        return True
    except OSError:
        return False


__all__ = ["save_form", "load_form", "list_forms", "delete_form"]
