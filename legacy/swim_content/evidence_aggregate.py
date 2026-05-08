"""
Aggregate evidence from a card's claims onto the card itself.

The grouper builds cards from claims, but it only attaches a single
'meet-derived' evidence line. Once the detector has set source URLs and
retrieved_at timestamps on PB and qualification claims, we push those into
the card's `evidence` list so the UI evidence drawer has something to show.
"""
from __future__ import annotations

from .cards import ContentCard
from .evidence import Evidence, CONF_HIGH, CONF_MEDIUM, CONF_LOW, aggregate_confidence


def _evidence_for_pb_claim(claim, swimmer_name: str) -> Evidence:
    if claim.kind == "pb_confirmed":
        delta = claim.extra.get("delta_sec")
        delta_str = f"{abs(delta):.2f}s improvement" if delta is not None else ""
        prior = claim.extra.get("prior_time_str")
        prior_date = claim.extra.get("prior_date_iso")
        note_parts = [delta_str]
        if prior:
            note_parts.append(f"prior PB {prior}")
        if prior_date:
            note_parts.append(f"set {prior_date}")
        note = " · ".join(p for p in note_parts if p)
        return Evidence(
            claim=f"Confirmed PB in {claim.event_label} for {swimmer_name}",
            source="swimmingresults.org",
            source_url=claim.extra.get("source_url"),
            retrieved_at=claim.extra.get("retrieved_at"),
            confidence=CONF_HIGH,
            note=note,
        )
    return Evidence(
        claim=f"Likely PB in {claim.event_label} for {swimmer_name}",
        source="swimmingresults.org",
        source_url=claim.extra.get("source_url"),
        retrieved_at=claim.extra.get("retrieved_at"),
        confidence=CONF_MEDIUM,
        note=claim.extra.get("note", "PB cannot be confirmed without a pre-meet snapshot."),
    )


def _evidence_for_qual_claim(claim, swimmer_name: str) -> Evidence:
    comp = claim.extra.get("competition", "qualifying standard")
    in_window = claim.extra.get("in_window", False)
    margin = claim.extra.get("margin_sec")
    margin_str = f"{abs(margin):.2f}s under threshold" if margin is not None else ""
    note_parts = [margin_str]
    note_parts.append("inside qualification window" if in_window else "OUTSIDE qualification window")
    return Evidence(
        claim=f"Hit the {comp} standard in {claim.event_label} for {swimmer_name}",
        source=claim.extra.get("body", "qualification standard"),
        source_url=claim.extra.get("source_url"),
        retrieved_at=claim.extra.get("retrieved_at"),
        confidence=CONF_HIGH if in_window else CONF_MEDIUM,
        note=" · ".join(note_parts),
    )


def attach_evidence_from_claims(cards: list[ContentCard]) -> list[ContentCard]:
    """Mutate cards: append evidence lines derived from PB and qual claims."""
    for card in cards:
        seen_keys = set()
        for claim in card.claims:
            ev = None
            if claim.kind in ("pb_confirmed", "pb_likely"):
                ev = _evidence_for_pb_claim(claim, claim.swimmer_name)
                key = ("pb", claim.swimmer_name, claim.distance, claim.stroke, claim.course, claim.kind)
            elif claim.kind == "qual_hit":
                ev = _evidence_for_qual_claim(claim, claim.swimmer_name)
                key = ("qual", claim.swimmer_name, claim.extra.get("standard_id"),
                       claim.distance, claim.stroke, claim.course)
            else:
                continue
            if key in seen_keys:
                continue
            seen_keys.add(key)
            card.evidence.append(ev)
        card.confidence = aggregate_confidence(card.evidence)
    return cards
