"""Per-tenant athlete consent / opt-out registry.

In plain words: before a club posts a card about a swimmer — especially a
child — there must be a recorded answer to "are we allowed to?". This module
stores that answer per athlete, per club (tenant), and the gate
(``compliance.gate``) enforces it everywhere a card could become public:
approval, pack building, and publishing.

Two operating modes, chosen per tenant on the club profile
(``ClubProfile.consent_mode``):

- ``opt_out``  (the floor; also the legacy default when unset) — every
  athlete may appear UNLESS they are recorded as refused/revoked or
  restricted. This is the legitimate-interests footing: objections are
  honoured immediately, everywhere.
- ``opt_in`` — an athlete may appear ONLY with a recorded ``granted``
  consent. For under-18s (or unknown age, treated as under-18), the grant
  must be marked parental when the profile requires it (default yes).
  This is the consent footing and the recommended setting for clubs whose
  athletes are mostly children.

Which mode a club *should* use is a legal-judgment call — Q2 in
docs/compliance/OPEN_LEGAL_QUESTIONS.md. The registry also carries the
Art 18 ``restricted`` flag: a restricted athlete is blocked in BOTH modes.

Records are append-only (accountability); the latest record per athlete
wins. Ledger: ``DATA_DIR/compliance/consent/<profile_id>.jsonl``.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

from .store import JsonlLedger

VALID_STATUSES = ("granted", "refused", "revoked")


def athlete_key(name: str) -> str:
    """Canonical athlete identity: lowercased, whitespace-collapsed name.

    Deliberately conservative — two athletes sharing a normalised name in
    one club resolve to the same record, and any block applies to both.
    """
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class ConsentRecord:
    athlete_key: str
    athlete_name: str
    status: str  # granted | refused | revoked
    parental: bool = False  # grant given by a parent/guardian
    under_18: Optional[bool] = None  # as recorded by the club; None = unknown
    restricted: bool = False  # Art 18 restriction of processing
    note: str = ""
    recorded_by: str = ""
    recorded_at: str = ""

    def to_record(self) -> dict:
        return asdict(self)


class ConsentRegistry:
    """Consent ledger for one tenant (club profile)."""

    def __init__(self, profile_id: str) -> None:
        pid = re.sub(r"[^A-Za-z0-9_-]", "_", (profile_id or "default").strip()) or "default"
        self.profile_id = pid
        self._ledger = JsonlLedger(f"consent/{pid}.jsonl", key_field="athlete_key")

    def record(
        self,
        *,
        athlete_name: str,
        status: str,
        parental: bool = False,
        under_18: Optional[bool] = None,
        restricted: Optional[bool] = None,
        note: str = "",
        recorded_by: str = "",
    ) -> ConsentRecord:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid consent status: {status!r}")
        key = athlete_key(athlete_name)
        if not key:
            raise ValueError("athlete name required")
        previous = self.get(athlete_name)
        rec = ConsentRecord(
            athlete_key=key,
            athlete_name=re.sub(r"\s+", " ", athlete_name.strip())[:200],
            status=status,
            parental=bool(parental),
            under_18=under_18 if under_18 is not None else (previous.under_18 if previous else None),
            restricted=bool(restricted) if restricted is not None else (previous.restricted if previous else False),
            note=(note or "").strip()[:1000],
            recorded_by=(recorded_by or "").strip()[:200],
            recorded_at=_iso_now(),
        )
        self._ledger.append(rec.to_record())
        return rec

    def set_restricted(self, athlete_name: str, restricted: bool, recorded_by: str = "") -> ConsentRecord:
        """Art 18 restriction flag — blocks the athlete in every mode."""
        previous = self.get(athlete_name)
        rec = ConsentRecord(
            athlete_key=athlete_key(athlete_name),
            athlete_name=re.sub(r"\s+", " ", athlete_name.strip())[:200],
            status=previous.status if previous else "refused",
            parental=previous.parental if previous else False,
            under_18=previous.under_18 if previous else None,
            restricted=bool(restricted),
            note=previous.note if previous else "",
            recorded_by=(recorded_by or "").strip()[:200],
            recorded_at=_iso_now(),
        )
        self._ledger.append(rec.to_record())
        return rec

    def get(self, athlete_name: str) -> Optional[ConsentRecord]:
        rec = self._ledger.get(athlete_key(athlete_name))
        return ConsentRecord(**rec) if rec else None

    def all(self) -> list[ConsentRecord]:
        items = [ConsentRecord(**rec) for rec in self._ledger.all()]
        items.sort(key=lambda r: r.athlete_name.lower())
        return items
