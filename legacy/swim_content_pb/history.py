"""
swim_content_pb/history.py
PreviousPB derivation with same-meet duplicate exclusion.

Same-meet exclusion criteria (any one of these):
  - meet_name match (after canonicalisation, case-insensitive, strip non-alpha)
  - OR meet_date_iso exact match
  - OR (date within 2 days AND venue match)

False negatives on duplicate exclusion cause real PBs to be missed.
The logic is conservative: if uncertain whether a swim was at this meet,
exclude it (err on the side of suppressing a PB vs claiming a false PB).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from .schema import ParsedSnapshot, ParsedSwimEntry, PreviousPB


# ---------------------------------------------------------------------------
# Meet name canonicalisation for dedup
# ---------------------------------------------------------------------------

_NONALPHA_RE = re.compile(r"[^A-Z0-9 ]")
_WS_RE = re.compile(r"\s+")


def _canon_meet_name(name: Optional[str]) -> Optional[str]:
    """Normalise meet name for same-meet comparison.
    Uppercase, strip non-alphanumeric (keep spaces), collapse whitespace.
    """
    if not name:
        return None
    s = name.upper()
    s = _NONALPHA_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s or None


def _date_within_days(iso_a: Optional[str], iso_b: Optional[str], days: int) -> bool:
    """Return True if two ISO date strings are within `days` of each other."""
    if not iso_a or not iso_b:
        return False
    try:
        a = date.fromisoformat(iso_a)
        b = date.fromisoformat(iso_b)
        return abs((a - b).days) <= days
    except ValueError:
        return False


def _is_same_meet(
    entry: ParsedSwimEntry,
    *,
    meet_name: Optional[str],
    meet_date_iso: Optional[str],
    venue: Optional[str],
) -> tuple[bool, str]:
    """Determine if a history entry is from the current meet.

    Returns (is_same, reason_string).
    The reason is included in excluded_swims for the audit trail.
    """
    canon_current_meet = _canon_meet_name(meet_name)
    canon_entry_meet = _canon_meet_name(entry.meet_name)

    # Rule 1: meet_name exact match (after canonicalisation)
    if (canon_current_meet and canon_entry_meet
            and canon_current_meet == canon_entry_meet):
        return True, f"meet_name_match: '{entry.meet_name}'"

    # Rule 1b: meet_name strong containment OR token Jaccard >= 0.7.
    # Multi-day meets often appear under slightly different names on
    # swimmingresults.org (e.g. "Swansea Aquatics May Long Course 2026" vs
    # "City of Swansea Aquatics May Long Course Open Meet"). Both rules are
    # strict on token overlap and only fire when the names are clearly the
    # same event under different wording.
    if canon_current_meet and canon_entry_meet:
        a_tokens = set(canon_current_meet.split())
        b_tokens = set(canon_entry_meet.split())
        # ignore tokens shorter than 3 chars (e.g. "OF", "AT")
        a_tokens = {t for t in a_tokens if len(t) >= 3}
        b_tokens = {t for t in b_tokens if len(t) >= 3}
        if a_tokens and b_tokens:
            inter = a_tokens & b_tokens
            union = a_tokens | b_tokens
            jaccard = len(inter) / len(union) if union else 0.0
            # Strong containment: the smaller name is fully inside the larger
            smaller = a_tokens if len(a_tokens) <= len(b_tokens) else b_tokens
            larger = b_tokens if smaller is a_tokens else a_tokens
            contained = smaller.issubset(larger)
            # ALSO require dates to be within 7 days for these softer matches
            within_window = _date_within_days(entry.date_iso, meet_date_iso, 7)
            if within_window and (contained or jaccard >= 0.7):
                return True, (
                    f"meet_name_overlap_within_7_days: jaccard={jaccard:.2f}, "
                    f"contained={contained}, '{entry.meet_name}'"
                )

    # Rule 2: meet_date_iso exact match
    if meet_date_iso and entry.date_iso and meet_date_iso == entry.date_iso:
        return True, f"date_exact_match: {entry.date_iso}"

    # Rule 2b: date within 4 days AND meet_name overlaps even partially
    # (multi-day meets — e.g. day 1 of a 3-day meet vs day 2)
    if (entry.date_iso and meet_date_iso
            and _date_within_days(entry.date_iso, meet_date_iso, 4)
            and canon_current_meet and canon_entry_meet):
        a_tokens = {t for t in canon_current_meet.split() if len(t) >= 4}
        b_tokens = {t for t in canon_entry_meet.split() if len(t) >= 4}
        if a_tokens and b_tokens and (a_tokens & b_tokens):
            return True, (
                f"date_within_4_days_and_meet_name_overlap: "
                f"entry={entry.date_iso}, meet={meet_date_iso}, "
                f"shared_tokens={sorted(a_tokens & b_tokens)}"
            )

    # Rule 3: date within 2 days AND venue match (after normalisation)
    if (entry.date_iso and meet_date_iso
            and _date_within_days(entry.date_iso, meet_date_iso, 2)
            and venue and entry.venue):
        canon_current_venue = _canon_meet_name(venue)
        canon_entry_venue = _canon_meet_name(entry.venue)
        if (canon_current_venue and canon_entry_venue
                and canon_current_venue == canon_entry_venue):
            return True, (
                f"date_within_2_days_and_venue_match: "
                f"entry={entry.date_iso}, meet={meet_date_iso}, venue='{entry.venue}'"
            )

    return False, ""


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_previous_pb(
    *,
    snapshot: ParsedSnapshot,
    swimmer_asa_id: str,
    swimmer_name: str,
    event_distance: int,
    event_stroke: str,
    course: str,
    meet_name: Optional[str],
    meet_date_iso: Optional[str],
    venue: Optional[str],
) -> Optional[PreviousPB]:
    """Build a PreviousPB by:
      1. Filter snapshot entries matching (event_distance, event_stroke, course)
      2. Exclude entries that match the current meet (same_meet_dedup)
      3. Of remaining entries, pick the FASTEST (lowest time_seconds)
         — this is the previous PB
      4. If no entries remain, return None
      5. Tag entries that were excluded with reasons in PreviousPB.excluded_swims

    Course must match exactly. Course UNKNOWN entries are never used.
    """
    if not snapshot or not snapshot.fetch_ok:
        return None

    if course not in ("LC", "SC"):
        return None  # Hard reject: course mismatch

    # 1. Filter by event + course
    matching: list[ParsedSwimEntry] = [
        e for e in snapshot.entries
        if (e.distance == event_distance
            and e.stroke == event_stroke
            and e.course == course
            and e.course != "UNKNOWN"
            and e.time_seconds > 0)
    ]

    if not matching:
        return None

    # 2. Exclude same-meet entries
    kept: list[ParsedSwimEntry] = []
    excluded: list[dict] = []

    for entry in matching:
        same, reason = _is_same_meet(
            entry,
            meet_name=meet_name,
            meet_date_iso=meet_date_iso,
            venue=venue,
        )
        if same:
            excluded.append({
                "time_str": entry.time_str,
                "time_seconds": entry.time_seconds,
                "date_iso": entry.date_iso,
                "meet_name": entry.meet_name,
                "venue": entry.venue,
                "exclusion_reason": reason,
            })
        else:
            kept.append(entry)

    # 3. If nothing remains, return None
    if not kept:
        return None

    # 4. Pick the fastest (lowest time_seconds)
    best = min(kept, key=lambda e: e.time_seconds)

    # 5. Determine confidence
    confidence = "high"
    notes = []
    if len(excluded) > 0:
        notes.append(f"{len(excluded)} same-meet entry/entries excluded from PB derivation.")
    if len(kept) == 1:
        notes.append("Only one historical entry after same-meet exclusion.")

    return PreviousPB(
        swimmer_asa_id=swimmer_asa_id,
        swimmer_name=swimmer_name,
        event_distance=event_distance,
        event_stroke=event_stroke,
        course=course,
        time_seconds=best.time_seconds,
        time_display=best.time_str,
        pb_date_iso=best.date_iso,
        pb_meet_name=best.meet_name,
        source_url=snapshot.source_url,
        fetched_at=snapshot.fetched_at,
        excluded_swims=excluded,
        confidence=confidence,
        notes=notes,
    )
