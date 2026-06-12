"""
PC.6 — the warm-first go-to-market pipeline ledger.

The diligence-decided funnel (ADR-0011 / SCALING_DILIGENCE cycle 4): win the
first ~3–5 clubs from the local-warm Swansea / South-East-Wales base, compound
5 → 10 through referrals (**2 named intros asked of every signed club**), use
meet presence to manufacture warmth, and treat cold outreach as a **capped
supplement** (~0.3–1.0% cold-to-paid — never the path to the gate). This
module records leads and computes the discipline readouts; it makes no
judgement calls — every number is arithmetic over what the founder typed.

Storage: ``DATA_DIR/commercial/pipeline.jsonl`` — append-only JSON lines,
last-write-wins per ``lead_id``.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

SOURCE_WARM_LOCAL = "warm_local"
SOURCE_REFERRAL = "referral"
SOURCE_MEET_PRESENCE = "meet_presence"
SOURCE_COLD = "cold"
VALID_SOURCES = frozenset({SOURCE_WARM_LOCAL, SOURCE_REFERRAL, SOURCE_MEET_PRESENCE, SOURCE_COLD})

STATUS_LEAD = "lead"
STATUS_CONTACTED = "contacted"
STATUS_MEETING = "meeting"
STATUS_QUOTED = "quoted"
STATUS_WON = "won"
STATUS_LOST = "lost"
VALID_STATUSES = frozenset(
    {STATUS_LEAD, STATUS_CONTACTED, STATUS_MEETING, STATUS_QUOTED, STATUS_WON, STATUS_LOST}
)

# Cold is a "capped supplement": flag when it dominates top-of-funnel. The
# threshold is a fixed, documented number — a readout, not an enforcement.
COLD_SHARE_WARN_THRESHOLD = 0.30
REFERRAL_INTROS_PER_WIN = 2  # "ask each signed club for 2 named intros"

_LEDGER_LOCK = threading.Lock()


class PipelineError(Exception):
    """Expected, operator-facing pipeline failures (clean error, not a 500)."""


def _coerce_source(source: object) -> str:
    s = str(source or "").strip().lower()
    return s if s in VALID_SOURCES else SOURCE_COLD


def _coerce_status(status: object) -> str:
    s = str(status or "").strip().lower()
    return s if s in VALID_STATUSES else STATUS_LEAD


@dataclass
class Lead:
    lead_id: str
    club_name: str
    region: str = ""
    source: str = SOURCE_WARM_LOCAL
    status: str = STATUS_LEAD
    referrer_club: str = ""  # which signed club opened this door (source=referral)
    contact_email: str = ""  # set by PC.9 code-tracked signups (quote matching)
    intros: list[str] = field(default_factory=list)  # named intros THIS club gave us
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_record(self) -> dict:
        return asdict(self)

    @classmethod
    def from_record(cls, d: dict) -> "Lead":
        intros_raw = d.get("intros")
        intros = (
            [str(x).strip() for x in intros_raw if str(x).strip()]
            if isinstance(intros_raw, list)
            else []
        )
        return cls(
            lead_id=str(d.get("lead_id", "") or "").strip(),
            club_name=str(d.get("club_name", "") or "").strip(),
            region=str(d.get("region", "") or "").strip(),
            source=_coerce_source(d.get("source")),
            status=_coerce_status(d.get("status")),
            referrer_club=str(d.get("referrer_club", "") or "").strip(),
            contact_email=str(d.get("contact_email", "") or "").strip().lower(),
            intros=intros,
            notes=str(d.get("notes", "") or ""),
            created_at=str(d.get("created_at", "") or ""),
            updated_at=str(d.get("updated_at", "") or ""),
        )


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _data_dir() -> Path:
    src_root = Path(__file__).resolve().parents[2]
    return Path(os.environ.get("DATA_DIR", str(src_root)))


def _pipeline_path() -> Path:
    return _data_dir() / "commercial" / "pipeline.jsonl"


class LeadStore:
    """Append-only JSONL lead ledger, last-write-wins per ``lead_id``."""

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path is not None else _pipeline_path()

    @property
    def path(self) -> Path:
        return self._path

    def _read_all(self) -> dict[str, Lead]:
        out: dict[str, Lead] = {}
        if not self._path.exists():
            return out
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            return out
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            lead = Lead.from_record(rec)
            if lead.lead_id:
                out[lead.lead_id] = lead
        return out

    def _append(self, lead: Lead) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(lead.to_record(), ensure_ascii=False) + "\n")
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass

    def get(self, lead_id: str) -> Optional[Lead]:
        return self._read_all().get((lead_id or "").strip())

    def list_all(self) -> list[Lead]:
        return sorted(self._read_all().values(), key=lambda x: x.created_at, reverse=True)

    def create(
        self,
        club_name: str,
        *,
        source: str,
        region: str = "",
        referrer_club: str = "",
        contact_email: str = "",
        notes: str = "",
    ) -> Lead:
        club = (club_name or "").strip()
        if not club:
            raise PipelineError("Enter the club's name.")
        src = (source or "").strip().lower()
        if src not in VALID_SOURCES:
            raise PipelineError("Pick a real source: warm_local, referral, meet_presence or cold.")
        if src == SOURCE_REFERRAL and not (referrer_club or "").strip():
            raise PipelineError("A referral lead needs the referring club's name.")
        with _LEDGER_LOCK:
            now = _utc_now_iso()
            lead = Lead(
                lead_id=secrets.token_hex(8),
                club_name=club,
                region=(region or "").strip(),
                source=src,
                status=STATUS_LEAD,
                referrer_club=(referrer_club or "").strip(),
                contact_email=(contact_email or "").strip().lower(),
                notes=(notes or "").strip(),
                created_at=now,
                updated_at=now,
            )
            self._append(lead)
        return lead

    def set_status(self, lead_id: str, status: str) -> Lead:
        status = (status or "").strip().lower()
        if status not in VALID_STATUSES:
            raise PipelineError("Unknown pipeline status.")
        with _LEDGER_LOCK:
            lead = self._read_all().get((lead_id or "").strip())
            if lead is None:
                raise PipelineError("No such lead.")
            lead.status = status
            lead.updated_at = _utc_now_iso()
            self._append(lead)
            return lead

    def set_intros(self, lead_id: str, intros: list[str]) -> Lead:
        """Record the named intros a (won) club has given us."""
        with _LEDGER_LOCK:
            lead = self._read_all().get((lead_id or "").strip())
            if lead is None:
                raise PipelineError("No such lead.")
            lead.intros = [str(x).strip() for x in (intros or []) if str(x).strip()]
            lead.updated_at = _utc_now_iso()
            self._append(lead)
            return lead


# ---- deterministic readouts ----------------------------------------------


def funnel_summary(leads: list[Lead]) -> dict:
    by_status = {s: 0 for s in sorted(VALID_STATUSES)}
    by_source = {s: 0 for s in sorted(VALID_SOURCES)}
    for lead in leads:
        by_status[lead.status] = by_status.get(lead.status, 0) + 1
        by_source[lead.source] = by_source.get(lead.source, 0) + 1
    return {"total": len(leads), "by_status": by_status, "by_source": by_source}


def warm_first_discipline(leads: list[Lead]) -> dict:
    """Is cold staying a capped supplement? Pure arithmetic + a fixed threshold."""
    total = len(leads)
    cold = sum(1 for lead in leads if lead.source == SOURCE_COLD)
    share = (cold / total) if total else 0.0
    return {
        "total": total,
        "cold": cold,
        "cold_share": round(share, 3),
        "threshold": COLD_SHARE_WARN_THRESHOLD,
        "warn": total >= 5 and share > COLD_SHARE_WARN_THRESHOLD,
    }


def referral_debt(leads: list[Lead]) -> list[dict]:
    """Won clubs still owing named intros (the 5 → 10 compounding mechanism).

    Live code-tracked state (PC.9): a referred signup attributed to a won
    club through its referral code IS a delivered intro, so it counts next
    to the operator-typed names — the readout stops depending on manual
    entries the moment clubs share their links.
    """
    code_tracked: dict[str, int] = {}
    for lead in leads:
        if lead.source == SOURCE_REFERRAL and lead.referrer_club.strip():
            key = lead.referrer_club.strip().lower()
            code_tracked[key] = code_tracked.get(key, 0) + 1
    out = []
    for lead in leads:
        if lead.status != STATUS_WON:
            continue
        tracked = code_tracked.get(lead.club_name.strip().lower(), 0)
        recorded = len(lead.intros) + tracked
        missing = REFERRAL_INTROS_PER_WIN - recorded
        if missing > 0:
            out.append(
                {
                    "lead_id": lead.lead_id,
                    "club_name": lead.club_name,
                    "intros_recorded": recorded,
                    "intros_code_tracked": tracked,
                    "intros_missing": missing,
                }
            )
    return sorted(out, key=lambda d: d["club_name"].lower())
