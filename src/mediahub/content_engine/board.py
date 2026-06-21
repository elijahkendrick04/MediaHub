"""The planning board — a Kanban/whiteboard for committee brainstorms (1.14).

The ranked plan and the calendar are *structured*; a club committee also needs a
loose place to throw ideas around ("post about the new kit", "thank the
volunteers") and watch them move through the content lifecycle. This is that
surface: a per-org board of free-form **idea cards** in four columns that mirror
how content actually progresses —

    idea  →  drafted  →  approved  →  scheduled

An idea card can be **promoted** into a real free-text draft (a stub pack),
linking the board to the rest of the pipeline: the seed draft can then be
edited/regenerated, previewed per channel (1.14 build 2) and scheduled on the
calendar (build 1). Promotion seeds the draft from the idea text verbatim — no
AI in the loop, so it works with no provider configured and never fabricates.

Pure persistence, one JSON file per org under ``DATA_DIR/plan_board/<org>.json``,
tenant-isolated by construction (a board only ever holds its own org's cards).
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

COLUMNS = ("idea", "drafted", "approved", "scheduled")
COLUMN_LABELS = {
    "idea": "Ideas",
    "drafted": "Drafted",
    "approved": "Approved",
    "scheduled": "Scheduled",
}
MAX_CARDS = 200

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")
_LOCK = threading.Lock()


@dataclass
class IdeaCard:
    id: str
    title: str
    note: str = ""
    column: str = "idea"
    pack_id: str = ""  # linked draft once promoted
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "note": self.note,
            "column": self.column,
            "pack_id": self.pack_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sanitise_org(org_id: str) -> str:
    s = _SAFE.sub("_", (org_id or "unknown").strip()) or "unknown"
    return s[:120]


def _board_path(org_id: str, data_dir: Optional[Path] = None) -> Path:
    base = Path(data_dir) if data_dir is not None else Path(os.environ.get("DATA_DIR", "."))
    d = base / "plan_board"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{_sanitise_org(org_id)}.json"


def _clean_card(raw: object) -> Optional[IdeaCard]:
    if not isinstance(raw, dict):
        return None
    cid = str(raw.get("id") or "").strip()
    title = str(raw.get("title") or "").strip()[:160]
    if not cid or not title:
        return None
    column = str(raw.get("column") or "idea").strip()
    if column not in COLUMNS:
        column = "idea"
    return IdeaCard(
        id=cid,
        title=title,
        note=str(raw.get("note") or "").strip()[:600],
        column=column,
        pack_id=str(raw.get("pack_id") or "").strip()[:40],
        created_at=str(raw.get("created_at") or ""),
        updated_at=str(raw.get("updated_at") or ""),
    )


def load_board(org_id: str, *, data_dir: Optional[Path] = None) -> list[IdeaCard]:
    """The org's idea cards (missing/corrupt boards load empty)."""
    path = _board_path(org_id, data_dir)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    cards = raw.get("cards") if isinstance(raw, dict) else None
    if not isinstance(cards, list):
        return []
    return [c for c in map(_clean_card, cards) if c]


def _save(org_id: str, cards: list[IdeaCard], *, data_dir: Optional[Path] = None) -> None:
    path = _board_path(org_id, data_dir)
    payload = json.dumps({"cards": [c.to_dict() for c in cards]}, indent=2, ensure_ascii=False)
    with _LOCK:
        path.write_text(payload, encoding="utf-8")


def add_card(
    org_id: str, title: str, note: str = "", *, data_dir: Optional[Path] = None
) -> Optional[IdeaCard]:
    """Add an idea card to the 'idea' column. None when the title is empty or the
    board is full (honest cap, never silently drops)."""
    title = (title or "").strip()[:160]
    if not title:
        return None
    cards = load_board(org_id, data_dir=data_dir)
    if len(cards) >= MAX_CARDS:
        return None
    now = _now()
    card = IdeaCard(
        id=uuid.uuid4().hex[:12],
        title=title,
        note=(note or "").strip()[:600],
        column="idea",
        created_at=now,
        updated_at=now,
    )
    cards.append(card)
    _save(org_id, cards, data_dir=data_dir)
    return card


def _find(cards: list[IdeaCard], card_id: str) -> Optional[IdeaCard]:
    return next((c for c in cards if c.id == card_id), None)


def move_card(
    org_id: str, card_id: str, column: str, *, data_dir: Optional[Path] = None
) -> Optional[IdeaCard]:
    """Move a card to ``column`` (one of COLUMNS). None when unknown column/card."""
    if column not in COLUMNS:
        return None
    cards = load_board(org_id, data_dir=data_dir)
    card = _find(cards, card_id)
    if card is None:
        return None
    card.column = column
    card.updated_at = _now()
    _save(org_id, cards, data_dir=data_dir)
    return card


def delete_card(org_id: str, card_id: str, *, data_dir: Optional[Path] = None) -> bool:
    cards = load_board(org_id, data_dir=data_dir)
    kept = [c for c in cards if c.id != card_id]
    if len(kept) == len(cards):
        return False
    _save(org_id, kept, data_dir=data_dir)
    return True


def link_pack(
    org_id: str,
    card_id: str,
    pack_id: str,
    *,
    column: str = "drafted",
    data_dir: Optional[Path] = None,
) -> Optional[IdeaCard]:
    """Attach a draft pack to a card and advance it (used by 'promote to draft')."""
    cards = load_board(org_id, data_dir=data_dir)
    card = _find(cards, card_id)
    if card is None:
        return None
    card.pack_id = (pack_id or "").strip()[:40]
    if column in COLUMNS:
        card.column = column
    card.updated_at = _now()
    _save(org_id, cards, data_dir=data_dir)
    return card


def board_by_column(cards: list[IdeaCard]) -> dict[str, list[IdeaCard]]:
    """Group cards by column, in COLUMNS order, newest first within a column."""
    out: dict[str, list[IdeaCard]] = {c: [] for c in COLUMNS}
    for card in cards:
        out.setdefault(card.column, []).append(card)
    for col in out.values():
        col.sort(key=lambda c: c.updated_at or c.created_at, reverse=True)
    return out


__all__ = [
    "IdeaCard",
    "COLUMNS",
    "COLUMN_LABELS",
    "MAX_CARDS",
    "load_board",
    "add_card",
    "move_card",
    "delete_card",
    "link_pack",
    "board_by_column",
]
