"""sites.grounding — the deterministic fact base a club microsite is built from.

A :class:`SiteFacts` is the normalised, source-grounded data both the archetype
builders (:mod:`sites.archetypes`) and the AI copy flow (:mod:`sites.draft`)
consume. It carries the club's identity (name, tagline, contact, socials,
sponsors), its **approved** content (card embeds), and its performance numbers
(headline KPI tiles, reusing the document/chart fact base). The AI never computes
a number; it only phrases copy around the numbers already on this sheet, and every
number is validated back (facts are code, CLAUDE.md rule).

The web layer assembles a :class:`SiteFacts` from the active club profile, its
approved cards and its processed runs; the engine itself stays decoupled (plain
data in, pages out), which keeps it deterministically testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SiteFacts:
    """A normalised, source-grounded fact base for one club microsite."""

    club_name: str = ""
    tagline: str = ""
    about: str = ""  # a club-supplied (not AI) blurb, if any
    logo_src: str = ""
    contact_email: str = ""
    location: str = ""

    socials: list[dict] = field(default_factory=list)  # [{platform, url}]
    sponsors: list[dict] = field(default_factory=list)  # [{src, alt, url}]
    cards: list[dict] = field(default_factory=list)  # approved embeds [{src,alt,caption,href}]
    links: list[dict] = field(default_factory=list)  # link-in-bio targets [{label,url,note}]
    stats: list[dict] = field(default_factory=list)  # KPI tiles [{value,label,sublabel}]

    # Single-event context (meet microsite / event page).
    event_name: str = ""
    event_date: str = ""
    event_time: str = ""
    venue: str = ""
    address: str = ""

    period: str = ""  # "June 2026" / "2025/26 season" — for prose + number allow-list
    source_refs: list[str] = field(default_factory=list)

    def allowed_numbers(self) -> set[float]:
        """Every number the AI is allowed to state: the stat values + the period
        year(s) + the small ordinals 1..3 (mirrors documents.grounding)."""
        nums: set[float] = {1.0, 2.0, 3.0}
        for s in self.stats:
            raw = str(s.get("value", "")).replace(",", "")
            for tok in re.findall(r"-?\d+(?:\.\d+)?", raw):
                try:
                    nums.add(float(tok))
                except ValueError:
                    pass
        for y in re.findall(r"\d{4}", self.period or ""):
            nums.add(float(y))
        return nums

    def facts_block(self) -> str:
        """The fact sheet handed to the LLM (identity + numbers only)."""
        lines = []
        if self.club_name:
            lines.append(f"  club: {self.club_name}")
        if self.location:
            lines.append(f"  location: {self.location}")
        if self.period:
            lines.append(f"  period: {self.period}")
        if self.event_name:
            lines.append(f"  event: {self.event_name}")
        for s in self.stats:
            label = str(s.get("label", "")).strip()
            value = str(s.get("value", "")).strip()
            if label and value:
                lines.append(f"  {label}: {value}")
        return "\n".join(lines)

    def is_empty(self) -> bool:
        return not (self.cards or self.stats or self.links or self.event_name)


def stats_from_doc_facts(doc_facts: Any, *, limit: int = 6) -> list[dict]:
    """Lift the headline KPI tiles from a :class:`documents.grounding.DocFacts`
    (or any object exposing ``headline_stats``) into site stat tiles."""
    raw = getattr(doc_facts, "headline_stats", None) or []
    out: list[dict] = []
    for s in raw[:limit]:
        if isinstance(s, dict) and s.get("value") is not None:
            out.append(
                {
                    "value": str(s.get("value", "")),
                    "label": str(s.get("label", "")),
                    "sublabel": str(s.get("sublabel", "")),
                }
            )
    return out


def site_facts_with_performance(
    facts: SiteFacts,
    doc_facts: Optional[Any] = None,
) -> SiteFacts:
    """Fold a deterministic performance fact base (DocFacts) into ``facts``:
    its headline stats become the site's KPI tiles and its sources are merged."""
    if doc_facts is None:
        return facts
    if not facts.stats:
        facts.stats = stats_from_doc_facts(doc_facts)
    if not facts.period:
        facts.period = str(getattr(doc_facts, "period", "") or "")
    refs = list(getattr(doc_facts, "source_refs", []) or [])
    for r in refs:
        if r not in facts.source_refs:
            facts.source_refs.append(str(r))
    return facts


__all__ = ["SiteFacts", "stats_from_doc_facts", "site_facts_with_performance"]
