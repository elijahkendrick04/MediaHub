"""
CardStatus enum and CardWorkflowState dataclass.

Workflow lifecycle:
  QUEUE    — default; waiting for review
  APPROVED — volunteer has approved this card for posting
  REJECTED — card rejected; will not appear in content pack
  POSTED   — card has been posted; marked with timestamp
  EDITED   — card has user edits (caption overrides) but not yet approved
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class CardStatus(str, Enum):
    QUEUE = "queue"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTED = "posted"
    EDITED = "edited"


@dataclass
class CardWorkflowState:
    card_id: str
    status: CardStatus = CardStatus.QUEUE
    edited_captions: Optional[dict[str, str]] = None   # tone_slot → user override
    notes: Optional[str] = None
    posted_at: Optional[str] = None
    last_changed_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CardWorkflowState":
        status_str = d.get("status", "queue")
        try:
            status = CardStatus(status_str)
        except ValueError:
            status = CardStatus.QUEUE
        return cls(
            card_id=d.get("card_id", ""),
            status=status,
            edited_captions=d.get("edited_captions"),
            notes=d.get("notes"),
            posted_at=d.get("posted_at"),
            last_changed_at=d.get("last_changed_at", ""),
        )
