"""Internal incident / personal-data-breach register (Art 33(5) UK GDPR).

Art 33(5): a controller must document *every* personal data breach — the
facts, its effects, and the remedial action taken — whether or not it was
notifiable to the ICO. This register is that document. The decision process
(72-hour ICO clock, risk assessment, data-subject notification) is the
playbook in docs/compliance/BREACH_PLAYBOOK.md; this module is the record.

Incidents are never deleted (accountability record). Updates append
superseding lines.
"""

from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

from .store import JsonlLedger

_SEVERITIES = ("low", "medium", "high", "critical")


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Incident:
    id: str
    opened_at: str
    title: str = ""
    description: str = ""
    severity: str = "medium"
    personal_data_involved: bool = False
    detected_at: str = ""  # when the operator became *aware* — starts the 72h clock
    ico_notified_at: str = ""
    subjects_notified_at: str = ""
    remedial_action: str = ""
    status: str = "open"  # open | mitigated | closed
    updated_at: str = ""

    def to_record(self) -> dict:
        return asdict(self)


class IncidentRegister:
    def __init__(self) -> None:
        self._ledger = JsonlLedger("incidents.jsonl", key_field="id")

    def open(
        self,
        *,
        title: str,
        description: str = "",
        severity: str = "medium",
        personal_data_involved: bool = False,
        detected_at: str = "",
    ) -> Incident:
        incident = Incident(
            id=secrets.token_hex(6),
            opened_at=_iso_now(),
            title=(title or "").strip()[:300],
            description=(description or "").strip()[:8000],
            severity=severity if severity in _SEVERITIES else "medium",
            personal_data_involved=bool(personal_data_involved),
            detected_at=(detected_at or _iso_now()),
            updated_at=_iso_now(),
        )
        self._ledger.append(incident.to_record())
        return incident

    def get(self, incident_id: str) -> Optional[Incident]:
        rec = self._ledger.get(incident_id)
        return Incident(**rec) if rec else None

    def all(self) -> list[Incident]:
        items = [Incident(**rec) for rec in self._ledger.all()]
        items.sort(key=lambda i: i.opened_at, reverse=True)
        return items

    def update(self, incident_id: str, **changes) -> Optional[Incident]:
        current = self.get(incident_id)
        if current is None:
            return None
        rec = current.to_record()
        allowed = set(rec.keys()) - {"id", "opened_at"}
        rec.update({k: v for k, v in changes.items() if k in allowed})
        rec["updated_at"] = _iso_now()
        self._ledger.append(rec)
        return Incident(**rec)
