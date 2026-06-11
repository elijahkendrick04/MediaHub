"""
PC.6(a) — Swim England approved-systems API application state.

ADR-0012's reality check: official **data-API access is real — apply** (the
concrete first NGB action; it grants data + credibility, not promotion).
This tiny module tracks where that application stands so the operator page
can show it next to the funnel. The application document itself lives at
``docs/commercial/SWIM_ENGLAND_API_APPLICATION.md``.

Storage: ``DATA_DIR/commercial/ngb_application.json`` (a single state file).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

STATUS_NOT_APPLIED = "not_applied"
STATUS_APPLIED = "applied"
STATUS_APPROVED = "approved"
STATUS_DECLINED = "declined"
VALID_STATUSES = (STATUS_NOT_APPLIED, STATUS_APPLIED, STATUS_APPROVED, STATUS_DECLINED)

APPLICATION_DOC = "docs/commercial/SWIM_ENGLAND_API_APPLICATION.md"


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _data_dir() -> Path:
    src_root = Path(__file__).resolve().parents[2]
    return Path(os.environ.get("DATA_DIR", str(src_root)))


def _state_path() -> Path:
    return _data_dir() / "commercial" / "ngb_application.json"


def load_state() -> dict:
    p = _state_path()
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                status = str(d.get("status", "") or "").strip().lower()
                return {
                    "status": status if status in VALID_STATUSES else STATUS_NOT_APPLIED,
                    "applied_at": str(d.get("applied_at", "") or ""),
                    "notes": str(d.get("notes", "") or ""),
                    "updated_at": str(d.get("updated_at", "") or ""),
                }
        except (OSError, json.JSONDecodeError):
            pass
    return {"status": STATUS_NOT_APPLIED, "applied_at": "", "notes": "", "updated_at": ""}


def save_state(status: str, *, notes: str = "") -> dict:
    status = (status or "").strip().lower()
    if status not in VALID_STATUSES:
        raise ValueError(f"Unknown NGB application status: {status!r}")
    prior = load_state()
    state = {
        "status": status,
        "applied_at": (
            prior["applied_at"]
            if prior["applied_at"]
            else (_utc_now_iso() if status != STATUS_NOT_APPLIED else "")
        ),
        "notes": (notes or "").strip(),
        "updated_at": _utc_now_iso(),
    }
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return state
