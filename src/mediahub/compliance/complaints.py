"""Data-protection complaints intake — s.164A DPA 2018 (in force 19 June 2026).

The duty: a controller must *facilitate* data-protection complaints (provide
an electronic complaints form), *acknowledge* each complaint within 30 days
of receipt, and respond without undue delay. This module is the engine; the
public form and the operator admin view live in web.py.

A complaint is identified by a random reference token the complainant can
quote. State transitions append superseding records (see store.JsonlLedger):

    received -> acknowledged -> responded -> closed
"""

from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from .store import JsonlLedger

ACK_WINDOW_DAYS = 30  # statutory acknowledgement window, s.164A(3)

_STATUSES = ("received", "acknowledged", "responded", "closed")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


@dataclass
class Complaint:
    id: str
    received_at: str
    ack_due_at: str
    name: str = ""
    contact: str = ""
    relationship: str = ""  # athlete | parent/guardian | club member | other
    club: str = ""
    details: str = ""
    status: str = "received"
    acknowledged_at: str = ""
    acknowledged_via: str = ""
    response_note: str = ""
    updated_at: str = ""
    profile_id: str = ""

    def to_record(self) -> dict:
        return asdict(self)


class ComplaintsStore:
    def __init__(self) -> None:
        self._ledger = JsonlLedger("complaints.jsonl", key_field="id")

    def submit(
        self,
        *,
        name: str,
        contact: str,
        details: str,
        relationship: str = "",
        club: str = "",
        profile_id: str = "",
    ) -> Complaint:
        now = _now()
        complaint = Complaint(
            id=secrets.token_hex(6),
            received_at=_iso(now),
            ack_due_at=_iso(now + timedelta(days=ACK_WINDOW_DAYS)),
            name=(name or "").strip()[:200],
            contact=(contact or "").strip()[:300],
            relationship=(relationship or "").strip()[:60],
            club=(club or "").strip()[:120],
            details=(details or "").strip()[:8000],
            updated_at=_iso(now),
            profile_id=(profile_id or "").strip()[:80],
        )
        self._ledger.append(complaint.to_record())
        return complaint

    def get(self, complaint_id: str) -> Optional[Complaint]:
        rec = self._ledger.get(complaint_id)
        return Complaint(**rec) if rec else None

    def all(self) -> list[Complaint]:
        items = [Complaint(**rec) for rec in self._ledger.all()]
        items.sort(key=lambda c: c.received_at, reverse=True)
        return items

    def _transition(self, complaint_id: str, **changes: str) -> Optional[Complaint]:
        current = self.get(complaint_id)
        if current is None:
            return None
        rec = current.to_record()
        rec.update(changes)
        rec["updated_at"] = _iso(_now())
        self._ledger.append(rec)
        return Complaint(**rec)

    def acknowledge(self, complaint_id: str, via: str = "") -> Optional[Complaint]:
        return self._transition(
            complaint_id,
            status="acknowledged",
            acknowledged_at=_iso(_now()),
            acknowledged_via=(via or "").strip()[:300],
        )

    def respond(self, complaint_id: str, note: str = "") -> Optional[Complaint]:
        return self._transition(
            complaint_id, status="responded", response_note=(note or "").strip()[:4000]
        )

    def close(self, complaint_id: str, note: str = "") -> Optional[Complaint]:
        changes = {"status": "closed"}
        if note:
            changes["response_note"] = note.strip()[:4000]
        return self._transition(complaint_id, **changes)

    def overdue(self) -> list[Complaint]:
        """Complaints past their 30-day window with no acknowledgement."""
        now = _iso(_now())
        return [c for c in self.all() if c.status == "received" and c.ack_due_at < now]

    def due_soon(self, days: int = 7) -> list[Complaint]:
        horizon = _iso(_now() + timedelta(days=days))
        now = _iso(_now())
        return [c for c in self.all() if c.status == "received" and now <= c.ack_due_at <= horizon]
