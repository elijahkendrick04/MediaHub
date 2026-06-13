"""
CardStatus enum and CardWorkflowState dataclass.

Workflow lifecycle:
  QUEUE    — default; waiting for review
  APPROVED — volunteer has approved this card for posting
  REJECTED — card rejected; will not appear in content pack
  POSTED   — card has been posted; marked with timestamp
  EDITED   — card has user edits (caption overrides) but not yet approved

ScheduleStatus tracks the external-publishing handoff (e.g. the scheduler):
  QUEUED    — default; not yet sent to an external scheduler
  SCHEDULED — accepted by the scheduler; awaiting its post-time
  PUBLISHED — scheduler has confirmed the post went live
  FAILED    — last schedule attempt failed (see notes / logs)
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional


class CardStatus(str, Enum):
    QUEUE = "queue"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTED = "posted"
    EDITED = "edited"


class ScheduleStatus(str, Enum):
    QUEUED = "queued"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"


@dataclass
class CardWorkflowState:
    card_id: str
    status: CardStatus = CardStatus.QUEUE
    edited_captions: Optional[dict[str, str]] = None  # tone_slot → user override
    notes: Optional[str] = None
    posted_at: Optional[str] = None
    last_changed_at: str = ""
    # External-scheduler state. Defaults keep the field optional so existing
    # workflow sidecars that pre-date publishing still load cleanly.
    schedule_status: ScheduleStatus = ScheduleStatus.QUEUED
    scheduler_update_id: Optional[str] = None
    scheduled_at: Optional[str] = None  # ISO8601 UTC, when set
    schedule_error: Optional[str] = None  # last failure reason

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["schedule_status"] = self.schedule_status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CardWorkflowState":
        status_str = d.get("status", "queue")
        try:
            status = CardStatus(status_str)
        except ValueError:
            status = CardStatus.QUEUE
        sched_str = d.get("schedule_status", "queued")
        try:
            sched = ScheduleStatus(sched_str)
        except ValueError:
            sched = ScheduleStatus.QUEUED
        return cls(
            card_id=d.get("card_id", ""),
            status=status,
            edited_captions=d.get("edited_captions"),
            notes=d.get("notes"),
            posted_at=d.get("posted_at"),
            last_changed_at=d.get("last_changed_at", ""),
            schedule_status=sched,
            # Back-compat: the id was historically persisted under "buffer_update_id".
            scheduler_update_id=d.get("scheduler_update_id") or d.get("buffer_update_id"),
            scheduled_at=d.get("scheduled_at"),
            schedule_error=d.get("schedule_error"),
        )
