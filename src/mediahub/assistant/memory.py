"""Org assistant memory (P6.2) — the copilot's preference book.

The Memory-Library analogue: short, org-scoped preferences the copilot should
respect ("we never show times for 8-and-unders", "lead with the swimmer's first
name"). This is the *preference* sibling to the semantic caption memory in
``mediahub.memory`` (which remembers winning captions); preferences are short,
human-authored policy lines, so a deterministic keyword recall is enough and —
crucially — needs **no embedding provider**, so the copilot's memory keeps
working even on a deployment with no AI key (honest-degrade rule).

Contract the spec calls for: writes are **gated behind an explicit "remember
this"** (the caller only writes on an explicit user action), and the org sees an
**inspectable, deletable list**. Stored as one JSON file per org under
``DATA_DIR/assistant_memory/<profile_id>.json`` — multi-tenant isolated by
construction.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_MAX_ITEMS = 200  # a preference book, not a database — bounded per org
_MAX_LEN = 280


@dataclass
class MemoryItem:
    id: str
    text: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "created_at": self.created_at}

    @classmethod
    def from_dict(cls, d: dict) -> Optional["MemoryItem"]:
        if not isinstance(d, dict) or not d.get("text"):
            return None
        return cls(
            id=str(d.get("id") or uuid.uuid4().hex[:12]),
            text=str(d["text"]),
            created_at=str(d.get("created_at") or datetime.now(timezone.utc).isoformat()),
        )


def _base_dir() -> Path:
    env = os.environ.get("DATA_DIR")
    root = Path(env) if env else Path(__file__).resolve().parents[1]
    return root / "assistant_memory"


def _slug(profile_id: str) -> str:
    s = re.sub(r"[^a-z0-9_-]", "-", str(profile_id or "").lower()).strip("-")
    return s or "_default"


def _path(profile_id: str) -> Path:
    return _base_dir() / f"{_slug(profile_id)}.json"


def list_items(profile_id: str) -> list[MemoryItem]:
    """Every remembered preference for one org, newest first."""
    p = _path(profile_id)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = [MemoryItem.from_dict(d) for d in (raw if isinstance(raw, list) else [])]
    out = [it for it in items if it is not None]
    out.sort(key=lambda it: it.created_at, reverse=True)
    return out


def _write(profile_id: str, items: list[MemoryItem]) -> None:
    p = _path(profile_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([it.to_dict() for it in items], indent=2), encoding="utf-8")


def remember(profile_id: str, text: str) -> Optional[MemoryItem]:
    """Store one preference (the explicit "remember this" action).

    Returns the new item, or ``None`` when the text is empty. De-dupes on exact
    (case-insensitive) text so repeated "remember this" doesn't pile up. Caps the
    book at ``_MAX_ITEMS`` (oldest dropped).
    """
    text = " ".join(str(text or "").split())[:_MAX_LEN].strip()
    if not text:
        return None
    items = list_items(profile_id)
    low = text.lower()
    items = [it for it in items if it.text.lower() != low]
    item = MemoryItem(id=uuid.uuid4().hex[:12], text=text)
    items.insert(0, item)
    _write(profile_id, items[:_MAX_ITEMS])
    return item


def forget(profile_id: str, item_id: str) -> bool:
    """Delete one preference by id. Returns True when something was removed."""
    items = list_items(profile_id)
    kept = [it for it in items if it.id != item_id]
    if len(kept) == len(items):
        return False
    _write(profile_id, kept)
    return True


def clear(profile_id: str) -> int:
    """Delete every preference for one org. Returns the count removed."""
    n = len(list_items(profile_id))
    p = _path(profile_id)
    if p.exists():
        try:
            p.unlink()
        except OSError:  # pragma: no cover
            pass
    return n


_WORD_RX = re.compile(r"[a-z0-9]+")
# Common words that would create false overlaps between a query and a
# preference; dropped so recall keys on the meaningful terms.
_STOPWORDS = frozenset(
    "the and for you can please our with this that than from into not but "
    "always never show make set use are was were has have had its his her "
    "them they when what why how who get got let".split()
)


def _keywords(text: str) -> set[str]:
    return {
        w for w in _WORD_RX.findall(str(text or "").lower()) if len(w) > 2 and w not in _STOPWORDS
    }


def recall(profile_id: str, context: str = "", *, k: int = 6) -> list[MemoryItem]:
    """The preferences most relevant to ``context`` (newest-first if no context).

    Deterministic keyword-overlap recall — no embedding provider needed. With no
    context (or no overlap) it returns the most recent preferences, so the
    copilot always sees the org's standing rules.
    """
    items = list_items(profile_id)
    if not items:
        return []
    ctx_words = _keywords(context)
    if not ctx_words:
        return items[:k]
    scored = sorted(
        items,
        key=lambda it: (len(_keywords(it.text) & ctx_words), it.created_at),
        reverse=True,
    )
    return scored[:k]


def as_prompt_block(profile_id: str, context: str = "", *, k: int = 6) -> str:
    """Render the relevant preferences as a system-prompt block (or "")."""
    items = recall(profile_id, context, k=k)
    if not items:
        return ""
    lines = "\n".join(f"- {it.text}" for it in items)
    return "The club has asked you to always respect these standing preferences:\n" + lines


__all__ = [
    "MemoryItem",
    "list_items",
    "remember",
    "forget",
    "clear",
    "recall",
    "as_prompt_block",
]
