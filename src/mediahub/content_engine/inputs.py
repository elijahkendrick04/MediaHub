"""Direct planner inputs — the operator-entered third signal source (P1.3).

The cross-source planner fuses three sources (docs/ARCHITECTURE_TARGET.md §1):
*own* (runs, packs, posting history), *external* (discovered context,
calendar), and *direct* — what the operator tells us. This module stores the
direct inputs, one JSON file per organisation under
``DATA_DIR/planner_inputs/<org_id>.json``:

  upcoming_events: [{"name": str, "date": "YYYY-MM-DD", "venue": str}]
  goals:           [{"post_type": canonical slug, "note": str}]
  blackout_dates:  ["YYYY-MM-DD", ...]

Goals are **structured** — the operator picks the target post type from the
sport profile's enabled list. That keeps the planner deterministic: no
free-text interpretation happens outside ``media_ai.llm``, and a goal can
never be silently mis-routed by a keyword heuristic.

Storage uses a sanitised org filename, one file per org, never mixed, with
honest I/O errors on save.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import date
from pathlib import Path
from typing import Optional

from mediahub.club_platform.post_types import canonical_slug

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")
_LOCK = threading.Lock()
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MAX_EVENTS = 24
MAX_GOALS = 12
MAX_BLACKOUTS = 24


def _sanitise_org(org_id: str) -> str:
    s = _SAFE.sub("_", (org_id or "unknown").strip()) or "unknown"
    return s[:120]


def _inputs_dir(data_dir: Optional[Path] = None) -> Path:
    base = Path(data_dir) if data_dir is not None else Path(os.environ.get("DATA_DIR", "."))
    d = base / "planner_inputs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _inputs_path(org_id: str, data_dir: Optional[Path] = None) -> Path:
    return _inputs_dir(data_dir) / f"{_sanitise_org(org_id)}.json"


def _clean_date(value: object) -> Optional[str]:
    s = str(value or "").strip()
    if not _ISO_DATE.match(s):
        return None
    try:
        date.fromisoformat(s)
    except ValueError:
        return None
    return s


def _clean_event(raw: object) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()[:160]
    when = _clean_date(raw.get("date"))
    if not name or not when:
        return None
    return {"name": name, "date": when, "venue": str(raw.get("venue") or "").strip()[:160]}


def _clean_goal(raw: object) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    slug = canonical_slug(raw.get("post_type"))
    if not slug:
        return None
    return {"post_type": slug, "note": str(raw.get("note") or "").strip()[:240]}


def empty_inputs() -> dict:
    return {"upcoming_events": [], "goals": [], "blackout_dates": []}


def load_planner_inputs(org_id: str, *, data_dir: Optional[Path] = None) -> dict:
    """Load the org's direct inputs; missing/corrupt files load as empty."""
    path = _inputs_path(org_id, data_dir)
    if not path.exists():
        return empty_inputs()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # "missing/corrupt files load as empty" (per the module docstring): any
        # unreadable/undecodable file degrades gracefully. ValueError covers both
        # json.JSONDecodeError (malformed JSON) and UnicodeDecodeError (a non-UTF-8
        # file on the durable disk) — both are ValueError subclasses, neither is an
        # OSError, so the narrower (OSError, JSONDecodeError) used to let a non-UTF-8
        # inputs file escape and 500 the loader (QA-016).
        return empty_inputs()
    if not isinstance(raw, dict):
        return empty_inputs()
    events = [e for e in map(_clean_event, raw.get("upcoming_events") or []) if e]
    goals = [g for g in map(_clean_goal, raw.get("goals") or []) if g]
    blackouts = [d for d in map(_clean_date, raw.get("blackout_dates") or []) if d]
    return {
        "upcoming_events": sorted(events, key=lambda e: e["date"])[:MAX_EVENTS],
        "goals": goals[:MAX_GOALS],
        "blackout_dates": sorted(set(blackouts))[:MAX_BLACKOUTS],
    }


def save_planner_inputs(org_id: str, inputs: dict, *, data_dir: Optional[Path] = None) -> dict:
    """Validate, persist and return the org's direct inputs."""
    raw = inputs if isinstance(inputs, dict) else {}
    clean = {
        "upcoming_events": sorted(
            (e for e in map(_clean_event, raw.get("upcoming_events") or []) if e),
            key=lambda e: e["date"],
        )[:MAX_EVENTS],
        "goals": [g for g in map(_clean_goal, raw.get("goals") or []) if g][:MAX_GOALS],
        "blackout_dates": sorted(
            {d for d in map(_clean_date, raw.get("blackout_dates") or []) if d}
        )[:MAX_BLACKOUTS],
    }
    path = _inputs_path(org_id, data_dir)
    with _LOCK:
        path.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
    return clean


__all__ = [
    "empty_inputs",
    "load_planner_inputs",
    "save_planner_inputs",
    "MAX_EVENTS",
    "MAX_GOALS",
    "MAX_BLACKOUTS",
]
