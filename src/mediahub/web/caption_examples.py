"""
caption_examples.py — Per-club few-shot caption example store.

Approved captions are persisted under DATA_DIR/caption_examples/<profile_id>.json
so they can be injected into future generation prompts as voice examples.

Public API:
  load_examples(profile_id) -> list[str]   # up to 5 most-recent examples
  append_example(profile_id, caption)      # add an approved caption; capped at 50
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_MAX_STORED = 50
_MAX_RETURNED = 5
_PROFILE_ID_RE = re.compile(r"\A[a-zA-Z0-9\-_]{1,80}\Z")


def _examples_dir() -> Path:
    """Resolve the caption-examples storage directory. DATA_DIR-aware."""
    data_dir = os.environ.get("DATA_DIR", "").strip()
    if data_dir:
        p = Path(data_dir) / "caption_examples"
    else:
        p = Path(__file__).resolve().parents[1] / "data" / "caption_examples"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _validate_profile_id(profile_id: str) -> None:
    if not isinstance(profile_id, str) or not _PROFILE_ID_RE.match(profile_id):
        raise ValueError(
            f"Invalid profile_id {profile_id!r} — must match [a-zA-Z0-9_-]{{1,80}}"
        )


def load_examples(profile_id: str) -> list[str]:
    """Return up to 5 of the most-recently approved captions for this club."""
    _validate_profile_id(profile_id)
    path = _examples_dir() / f"{profile_id}.json"
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        raw = data if isinstance(data, list) else []
        cleaned = [str(e) for e in raw if isinstance(e, str) and e.strip()]
        return cleaned[-_MAX_RETURNED:]
    except Exception:
        return []


def append_example(profile_id: str, caption: str) -> None:
    """Append an approved caption to the store. Total stored entries capped at 50.

    Idempotent for an already-stored caption — the approval seam runs on every
    content-pack build, so re-approving (or re-viewing) the same card must not
    fill the store with duplicates of one caption.
    """
    _validate_profile_id(profile_id)
    caption = caption.strip()
    if not caption:
        return
    path = _examples_dir() / f"{profile_id}.json"
    existing: list[str] = []
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            existing = [str(e) for e in data if isinstance(e, str) and e.strip()] \
                if isinstance(data, list) else []
        except Exception:
            existing = []
    if caption in existing:
        return
    existing.append(caption)
    existing = existing[-_MAX_STORED:]
    with path.open("w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


__all__ = ["load_examples", "append_example"]
