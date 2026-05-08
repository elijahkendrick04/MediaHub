"""
Evidence model.

Every fact-bearing claim on a content card carries one or more Evidence rows.
This is what powers the "evidence drawer" in the UI and the source-log export.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# Confidence buckets used uniformly across the system.
CONF_HIGH = "high"
CONF_MEDIUM = "medium"
CONF_LOW = "low"
CONF_NONE = "none"


@dataclass
class Evidence:
    """One piece of evidence backing a single claim."""
    claim: str             # what is being claimed, e.g. "Confirmed LC PB in 100m Backstroke"
    source: str            # short source name, e.g. "swimmingresults.org" or "HY3 file"
    source_url: Optional[str] = None
    retrieved_at: Optional[str] = None  # ISO 8601 UTC; None for claims derived from the upload itself
    confidence: str = CONF_MEDIUM
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "claim": self.claim,
            "source": self.source,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at,
            "confidence": self.confidence,
            "note": self.note,
        }


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def evidence_from_meet(claim: str, meet_name: str) -> Evidence:
    """Evidence whose only source is the uploaded meet file itself."""
    return Evidence(
        claim=claim,
        source=f"Meet results file ({meet_name})",
        confidence=CONF_HIGH,
        note="Derived directly from the uploaded HY3 file.",
    )


def aggregate_confidence(evidence: list[Evidence]) -> str:
    """
    Card-level confidence is the WORST confidence among its claims, with
    common-sense rules:
      - any 'none' -> 'low'
      - all 'high' -> 'high'
      - else 'medium'
    """
    if not evidence:
        return CONF_LOW
    levels = {e.confidence for e in evidence}
    if CONF_NONE in levels:
        return CONF_LOW
    if levels == {CONF_HIGH}:
        return CONF_HIGH
    if CONF_LOW in levels:
        return CONF_LOW
    return CONF_MEDIUM
