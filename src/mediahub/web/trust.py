"""
Trust report — per-claim verification metadata for the V4 verification UI.

For each card we surface:
  - source name + URL (where the claim is grounded)
  - confidence (high|medium|low) with a plain-English reason
  - safe-to-post recommendation (post | review | hold)
  - "why this status" sentence

This module does NOT change the underlying detection logic; it inspects
existing claims/evidence and decides what to display. That keeps the
trust layer a pure read on top of the V3 pipeline.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict


SAFE_POST = "post"
SAFE_REVIEW = "review"
SAFE_HOLD = "hold"


@dataclass
class ClaimTrust:
    card_id: str
    card_type: str
    headline: str
    confidence: str  # high | medium | low
    safe_to_post: str  # post | review | hold
    reason: str  # plain-English why-this-status
    sources: list[dict] = field(default_factory=list)  # [{name,url,note,confidence}]
    flags: list[str] = field(default_factory=list)


@dataclass
class TrustReport:
    cards: list[ClaimTrust] = field(default_factory=list)
    overall_confidence: str = "medium"
    overall_summary: str = ""

    def to_dict(self) -> dict:
        return {
            "cards": [asdict(c) for c in self.cards],
            "overall_confidence": self.overall_confidence,
            "overall_summary": self.overall_summary,
        }


def _pb_url_from_snap(snap) -> str | None:
    """Read the actual PB-lookup URL from the snapshot (no hardcoded provider)."""
    if snap is None:
        return None
    url = getattr(snap, "source_url", None)
    if url:
        return url
    pb_times = getattr(snap, "pb_times", {}) or {}
    for entries in pb_times.values():
        for e in entries:
            u = e.get("source_url") if isinstance(e, dict) else None
            if u:
                return u
    return None


def _pb_source_label(snap) -> str:
    """Return the source label learned at runtime from the snapshot."""
    if snap is None:
        return "PB lookup"
    domain = getattr(snap, "source_domain", None)
    if domain:
        return f"{domain} PB lookup"
    url = _pb_url_from_snap(snap)
    if url:
        try:
            from urllib.parse import urlparse

            host = (urlparse(url).hostname or "").lower()
            if host.startswith("www."):
                host = host[4:]
            if host:
                return f"{host} PB lookup"
        except Exception:
            pass
    return "PB lookup"


def _evaluate_card(card, pb_snapshots: dict) -> ClaimTrust:
    sources = []
    flags = []

    # Always: meet results file is one source.
    sources.append(
        {
            "name": "Meet results file",
            "url": None,
            "note": "Imported from uploaded HY3 file",
            "confidence": "high",
        }
    )

    # Per-claim signals: confirmed PB references the PB snapshot from
    # whichever provider pb_discovery selected at runtime.
    has_confirmed_pb = any(c.kind == "pb_confirmed" for c in card.claims)
    has_likely_pb = any(c.kind == "pb_likely" for c in card.claims)
    has_unverified_pb = any(c.kind == "pb_unverified" for c in card.claims)
    has_qual = any(c.kind == "qual_hit" for c in card.claims)
    has_medal = any(c.kind in {"gold", "silver", "bronze"} for c in card.claims)

    referenced_tirefs = {c.swimmer_tiref for c in card.claims if c.swimmer_tiref}
    for tiref in sorted(referenced_tirefs):
        snap = pb_snapshots.get(tiref) if pb_snapshots else None
        if snap and snap.fetch_ok:
            sources.append(
                {
                    "name": _pb_source_label(snap),
                    "url": _pb_url_from_snap(snap),
                    "note": "Pre-meet PB snapshot",
                    "confidence": "high",
                }
            )

    if has_qual:
        sources.append(
            {
                "name": "Qualification standards registry",
                "url": "https://www.bucs.org.uk/competitions/swimming.html",
                "note": "Active standards including BUCS LC 2026-27",
                "confidence": "high",
            }
        )

    # Decide overall card confidence and safe-to-post
    confidence = "medium"
    safe = SAFE_REVIEW
    reasons = []

    if has_confirmed_pb and has_medal:
        confidence = "high"
        safe = SAFE_POST
        reasons.append("Confirmed PB and a medal — both verifiable.")
    elif has_confirmed_pb:
        confidence = "high"
        safe = SAFE_POST
        reasons.append("Confirmed PB against pre-meet snapshot.")
    elif has_likely_pb:
        confidence = "medium"
        safe = SAFE_REVIEW
        reasons.append(
            "Same-day PB without a pre-meet snapshot — likely but not proven. "
            "Confirm before posting."
        )
        flags.append("likely_pb_only")
    elif has_unverified_pb:
        confidence = "low"
        safe = SAFE_HOLD
        reasons.append("PB cannot be verified against any prior data. Hold.")
        flags.append("unverified_pb")
    elif has_qual:
        confidence = "high"
        safe = SAFE_POST
        reasons.append("Qualification standard hit — checked against registry.")
    elif has_medal:
        confidence = "high"
        safe = SAFE_POST
        reasons.append("Medal placement is read directly from results.")
    else:
        confidence = "medium"
        safe = SAFE_REVIEW
        reasons.append("Verifiable but no headline-strength claim.")

    if card.bucket == "needs_confirmation":
        safe = SAFE_HOLD
        confidence = "low"
        reasons.append("Card is queued in 'needs confirmation' bucket.")
    elif card.bucket == "archive":
        safe = SAFE_HOLD
        reasons.append("Card was archived by the ranker — not strong enough to post.")

    return ClaimTrust(
        card_id=card.card_id,
        card_type=card.card_type,
        headline=card.headline,
        confidence=confidence,
        safe_to_post=safe,
        reason=" ".join(reasons),
        sources=sources,
        flags=flags,
    )


def build_trust_report(*, meet, profile, cards, pb_snapshots, standards_meta) -> TrustReport:
    rep = TrustReport()
    for card in cards:
        rep.cards.append(_evaluate_card(card, pb_snapshots or {}))

    if rep.cards:
        n_post = sum(1 for c in rep.cards if c.safe_to_post == SAFE_POST)
        n_review = sum(1 for c in rep.cards if c.safe_to_post == SAFE_REVIEW)
        n_hold = sum(1 for c in rep.cards if c.safe_to_post == SAFE_HOLD)
        rep.overall_confidence = "high" if n_post >= n_review + n_hold else "medium"
        rep.overall_summary = (
            f"{n_post} ready to post, {n_review} need a quick review, "
            f"{n_hold} should be held back."
        )
    else:
        rep.overall_confidence = "low"
        rep.overall_summary = "No content cards were generated."
    return rep
