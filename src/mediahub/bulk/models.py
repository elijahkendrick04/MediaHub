"""bulk.models — a bulk-generation job and its items (roadmap 1.13).

"Certificates for all 47 PB swimmers" is one **bulk job** made of many **items**,
one per swimmer/achievement. Each item produces a single piece of content that
flows into the *normal review queue* — bulk never bypasses approval. These
dataclasses are the plain, serialisable record of a job: what it targeted, how
far it got, and what happened to each item.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Item lifecycle. An item is queued for review and (optionally) an artifact is
# rendered. Nothing is ever auto-approved or auto-posted.
ITEM_PENDING = "pending"
ITEM_QUEUED = "queued"  # the card is in the review queue (artifact may also exist)
ITEM_FAILED = "failed"  # generation/queueing failed (reason in .error)
ITEM_SKIPPED = "skipped"  # excluded (e.g. already decided by a human)

JOB_PLANNED = "planned"
JOB_RUNNING = "running"
JOB_DONE = "done"
JOB_FAILED = "failed"


@dataclass
class BulkItem:
    item_id: str
    card_id: str
    label: str = ""
    status: str = ITEM_PENDING
    post_angle: str = ""
    output_path: str = ""  # rendered artifact, if any
    error: str = ""
    # 1.24 localisation: the target language for this item's content ("" = the
    # workspace default). A per-language bulk job fans out one item per
    # (card × language), each carrying its language so the generator localises.
    language: str = ""

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "card_id": self.card_id,
            "label": self.label,
            "status": self.status,
            "post_angle": self.post_angle,
            "output_path": self.output_path,
            "error": self.error,
            "language": self.language,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BulkItem":
        return cls(
            item_id=str(d.get("item_id", "")),
            card_id=str(d.get("card_id", "")),
            label=str(d.get("label", "") or ""),
            status=str(d.get("status", ITEM_PENDING) or ITEM_PENDING),
            post_angle=str(d.get("post_angle", "") or ""),
            output_path=str(d.get("output_path", "") or ""),
            error=str(d.get("error", "") or ""),
            language=str(d.get("language", "") or ""),
        )


@dataclass
class BulkJob:
    job_id: str
    profile_id: str
    run_id: str
    format_slug: str
    title: str = ""
    status: str = JOB_PLANNED
    items: list[BulkItem] = field(default_factory=list)
    cap: int = 0  # max items this job was allowed to produce (0 = uncapped record)
    message: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    # ----- progress -----

    @property
    def n_total(self) -> int:
        return len(self.items)

    @property
    def n_queued(self) -> int:
        return sum(1 for i in self.items if i.status == ITEM_QUEUED)

    @property
    def n_failed(self) -> int:
        return sum(1 for i in self.items if i.status == ITEM_FAILED)

    @property
    def n_skipped(self) -> int:
        return sum(1 for i in self.items if i.status == ITEM_SKIPPED)

    @property
    def n_done(self) -> int:
        """Items that reached a terminal state (queued/failed/skipped)."""
        return self.n_queued + self.n_failed + self.n_skipped

    @property
    def pct(self) -> int:
        return int(round(100 * self.n_done / self.n_total)) if self.n_total else 0

    def progress(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "n_total": self.n_total,
            "n_queued": self.n_queued,
            "n_failed": self.n_failed,
            "n_skipped": self.n_skipped,
            "n_done": self.n_done,
            "pct": self.pct,
        }

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "profile_id": self.profile_id,
            "run_id": self.run_id,
            "format_slug": self.format_slug,
            "title": self.title,
            "status": self.status,
            "cap": self.cap,
            "message": self.message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "items": [i.to_dict() for i in self.items],
            "progress": self.progress(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BulkJob":
        return cls(
            job_id=str(d.get("job_id", "")),
            profile_id=str(d.get("profile_id", "")),
            run_id=str(d.get("run_id", "")),
            format_slug=str(d.get("format_slug", "")),
            title=str(d.get("title", "") or ""),
            status=str(d.get("status", JOB_PLANNED) or JOB_PLANNED),
            items=[BulkItem.from_dict(i) for i in d.get("items", []) if isinstance(i, dict)],
            cap=int(d.get("cap", 0) or 0),
            message=str(d.get("message", "") or ""),
            created_at=str(d.get("created_at", "") or _now()),
            updated_at=str(d.get("updated_at", "") or _now()),
        )

    def touch(self) -> None:
        self.updated_at = _now()


__all__ = [
    "BulkItem",
    "BulkJob",
    "ITEM_PENDING",
    "ITEM_QUEUED",
    "ITEM_FAILED",
    "ITEM_SKIPPED",
    "JOB_PLANNED",
    "JOB_RUNNING",
    "JOB_DONE",
    "JOB_FAILED",
]
