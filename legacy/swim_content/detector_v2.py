"""
Detector v2 — pure function from (meet, pb_store, roster) to ContentCard list.

KEY ARCHITECTURAL CHANGE FROM v1:
    v1 emitted one Achievement per (swim, type) pair. A swim that broke a
    PB by 2.3 seconds AND won gold AND beat the BUCS qualifying time
    produced THREE separate items, all needing review. A 50-event meet
    typically produced 80+ items.

    v2 emits one ContentCard per swim, with a list of stacked Reasons.
    Each reason has its own score and metadata, but they live on the same
    card. The card's overall score is the max reason score (with a small
    bonus for stacking). 80 items collapse to ~25.

This module is PURE: no DB, no IO. All inputs are dataclasses, all outputs
are dataclasses. Side-effects (persisting, updating PB store) live in
reconcile.py and the Flask route, not here. This makes detection
deterministic and re-runnable.

What v2 does NOT do (deferred per pilot scope):
    - swimmingresults.org scraping (no public API; PDFs cover this)
    - LLM-generated captions (phrasebook-only for now)
    - club records detection (need a curated record list — Swansea Uni
      doesn't have one yet; surfaced in upload report as "manual confirm")
    - FINA points comparison
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum

from .parsers_hy3 import ParsedMeet, ParsedSwim, ParsedSwimmer
from .parsers_pb_pdf import PBStore, PBRow


# ----------------------------------------------------------------------
# Reason taxonomy
# ----------------------------------------------------------------------

class ReasonKind(str, Enum):
    BIG_PB             = "BIG_PB"             # PB by ≥1% margin (confirmed via PB store)
    CONFIRMED_PB       = "CONFIRMED_PB"       # PB confirmed via PB store, any margin
    LIKELY_PB          = "LIKELY_PB"          # Beats seed time but no PB store entry — surfaced in upload report only
    FIRST_EVER         = "FIRST_EVER"         # Swimmer's first recorded swim of this event
    BIGGEST_IMPROVEMENT_OF_MEET = "BIGGEST_IMPROVEMENT_OF_MEET"
    MEDAL_GOLD         = "MEDAL_GOLD"
    MEDAL_SILVER       = "MEDAL_SILVER"
    MEDAL_BRONZE       = "MEDAL_BRONZE"
    BARRIER_BREAK      = "BARRIER_BREAK"      # First sub-X for a meaningful X (e.g. sub-30 50FR)
    QT_MET             = "QT_MET"             # Beat a configured qualifying time
    STANDOUT_VS_FIELD  = "STANDOUT_VS_FIELD"  # Top 10% of meet field for that event


# Score weights. These are tuned to land ~10-30 swims at score ≥70 for a
# typical 40-swimmer pilot meet. Treat as defaults; can be overridden.
REASON_WEIGHTS: dict[ReasonKind, int] = {
    ReasonKind.BIG_PB:             85,
    ReasonKind.CONFIRMED_PB:       65,
    ReasonKind.LIKELY_PB:          0,   # never queues on its own; report only
    ReasonKind.FIRST_EVER:         50,
    ReasonKind.BIGGEST_IMPROVEMENT_OF_MEET: 75,
    ReasonKind.MEDAL_GOLD:         70,
    ReasonKind.MEDAL_SILVER:       55,
    ReasonKind.MEDAL_BRONZE:       50,
    ReasonKind.BARRIER_BREAK:      80,
    ReasonKind.QT_MET:             75,
    ReasonKind.STANDOUT_VS_FIELD:  50,
}


@dataclass
class Reason:
    kind: ReasonKind
    score: int
    # Free-form facts the captioner uses. Keep keys human-meaningful.
    detail: dict = field(default_factory=dict)


@dataclass
class ContentCard:
    """One swim = one card. Reasons stack."""
    asa_id: str
    swimmer_name: str         # 'Mathew Bradley'
    gender: str
    distance: int
    stroke: str
    course: str
    time_cs: int
    place: int | None
    swim_date: str | None
    meet_name: str
    round: str
    reasons: list[Reason] = field(default_factory=list)
    # Provenance — for upload report and debugging
    seed_time_cs: int | None = None
    prev_pb_cs: int | None = None
    prev_pb_meet: str | None = None
    prev_pb_date: str | None = None
    # Set later by ranker
    score: int = 0
    queue_decision: str = "archive"   # 'queue' | 'recap' | 'archive'

    def add_reason(self, kind: ReasonKind, **detail) -> None:
        score = REASON_WEIGHTS[kind]
        self.reasons.append(Reason(kind=kind, score=score, detail=dict(detail)))


# ----------------------------------------------------------------------
# Barrier-break configuration. Culturally meaningful "round number" thresholds.
# Times are in centiseconds (LC and SC may share or differ).
# ----------------------------------------------------------------------

# (gender, distance, stroke, course) -> list of barrier_cs (sorted desc).
# A swim that drops *under* one of these for the first time is a barrier break.
BARRIERS: dict[tuple[str, int, str, str], list[int]] = {
    # 50 Freestyle — sub-30, sub-28, sub-26, sub-25, sub-24
    ('F', 50, 'FR', 'LC'): [3000, 2800, 2700, 2600, 2500],
    ('M', 50, 'FR', 'LC'): [2700, 2500, 2400, 2300, 2200],
    # 100 Freestyle — sub-1:00, sub-58, sub-55, sub-50
    ('F', 100, 'FR', 'LC'): [6500, 6000, 5800, 5500, 5300],
    ('M', 100, 'FR', 'LC'): [6000, 5500, 5300, 5000, 4800],
    # 200 Freestyle
    ('F', 200, 'FR', 'LC'): [14000, 13000, 12500, 12000],
    ('M', 200, 'FR', 'LC'): [13000, 12000, 11500, 11000],
    # 100 Breast
    ('F', 100, 'BR', 'LC'): [8000, 7500, 7200, 7000],
    ('M', 100, 'BR', 'LC'): [7000, 6500, 6200, 6000],
    # 100 Fly
    ('F', 100, 'FL', 'LC'): [7000, 6500, 6200, 6000, 5800],
    ('M', 100, 'FL', 'LC'): [6000, 5500, 5300, 5200, 5000],
    # 100 Back
    ('F', 100, 'BK', 'LC'): [7500, 7000, 6500, 6200, 6000],
    ('M', 100, 'BK', 'LC'): [6500, 6000, 5500, 5300, 5200],
    # 200 IM
    ('F', 200, 'IM', 'LC'): [15000, 14000, 13500, 13000],
    ('M', 200, 'IM', 'LC'): [14000, 13000, 12500, 12000],
    # 400 IM
    ('F', 400, 'IM', 'LC'): [33000, 31000, 29000, 28000],
    ('M', 400, 'IM', 'LC'): [30000, 28000, 26000, 25000],
}


def _barrier_break(swim, prev_pb_cs: int | None) -> int | None:
    """Return the barrier (cs) just broken, or None.

    A barrier break requires:
      - swim.time_cs < barrier
      - prev_pb_cs is set AND prev_pb_cs >= barrier

    We deliberately require a confirmed prior PB above the barrier. Without
    history we cannot honestly claim "first time under X" — the swimmer may
    well have been under X many times before but their PB simply isn't in
    our store yet. Falsely celebrating a non-event is the worst kind of
    error for a content tool.
    """
    if prev_pb_cs is None:
        return None
    key = (swim.gender, swim.distance, swim.stroke, swim.course)
    barriers = BARRIERS.get(key)
    if not barriers or swim.finals_time_cs is None:
        return None
    for b in sorted(barriers, reverse=True):
        if swim.finals_time_cs < b and prev_pb_cs >= b:
            return b
    return None


# ----------------------------------------------------------------------
# Main detection
# ----------------------------------------------------------------------

@dataclass
class DetectionResult:
    cards: list[ContentCard]              # sorted high-score first (set by ranker)
    swims_processed: int                  # count of OUR swims fed in
    swims_skipped_no_time: int
    swims_skipped_dq: int
    no_pb_history: int                    # ours, no PB store match — manual confirm cases
    notes: list[str] = field(default_factory=list)


def detect(
    meet: ParsedMeet,
    pb_store: PBStore,
    our_swims: list[ParsedSwim],
    swimmers_by_asa: dict[str, ParsedSwimmer],
) -> DetectionResult:
    """Run detection over a pre-filtered list of "our" swims.

    Args:
        meet: parsed meet (used for meet name)
        pb_store: historical PB store keyed by (asa, dist, stroke, course)
        our_swims: swims we've already determined belong to our club (use
            club_filter.ClubRoster.filter_swims to produce this).
        swimmers_by_asa: lookup table for swimmer details.
    """
    cards: list[ContentCard] = []
    skipped_no_time = 0
    skipped_dq = 0
    no_pb_history = 0
    notes: list[str] = []

    # -- First pass: build a card per swim with PB-related reasons.
    pb_margin_pct: dict[int, float] = {}   # card_index -> margin% for ranking pass

    for sw in our_swims:
        if sw.dq:
            skipped_dq += 1
            continue
        if sw.finals_time_cs is None:
            skipped_no_time += 1
            continue

        swimmer = swimmers_by_asa.get(sw.asa_id)
        if not swimmer:
            continue   # shouldn't happen with HY3 hierarchy
        full_name = f"{swimmer.first_name} {swimmer.last_name}".strip()

        prev_pb = pb_store.get(sw.asa_id, sw.distance, sw.stroke, sw.course)
        prev_pb_cs = prev_pb.time_cs if prev_pb else None

        card = ContentCard(
            asa_id=sw.asa_id, swimmer_name=full_name, gender=sw.gender,
            distance=sw.distance, stroke=sw.stroke, course=sw.course,
            time_cs=sw.finals_time_cs, place=sw.place,
            swim_date=sw.swim_date, meet_name=meet.name, round=sw.round,
            seed_time_cs=sw.seed_time_cs,
            prev_pb_cs=prev_pb_cs,
            prev_pb_meet=prev_pb.pb_meet if prev_pb else None,
            prev_pb_date=prev_pb.pb_date if prev_pb else None,
        )

        # ---- PB reasons ----
        if prev_pb_cs is None:
            no_pb_history += 1
            # First ever recorded only if we trust the absence. We don't auto-
            # queue these (ASA ID just might not be in the PDFs yet). They
            # surface in the upload report as "needs human confirmation".
            # However, if the swim is also a podium / barrier break, the card
            # still earns those reasons below.
            #
            # Edge case: seed time == 0 AND no PB → reasonable evidence of
            # FIRST_EVER, but we keep this as a low-confidence reason.
            if sw.seed_time_cs is None or sw.seed_time_cs == 0:
                card.add_reason(ReasonKind.FIRST_EVER,
                                note="No prior PB on record; seed was blank")
            else:
                # We cannot mark as PB without history. Flag as LIKELY_PB
                # for the upload report only.
                card.add_reason(ReasonKind.LIKELY_PB,
                                seed_cs=sw.seed_time_cs,
                                note="No PB store entry; meet seed faster than PB DB")
        elif sw.finals_time_cs < prev_pb_cs:
            margin_cs = prev_pb_cs - sw.finals_time_cs
            margin_pct = 100.0 * margin_cs / prev_pb_cs
            pb_margin_pct[len(cards)] = margin_pct  # index of this card
            if margin_pct >= 1.0:
                card.add_reason(ReasonKind.BIG_PB,
                                margin_cs=margin_cs, margin_pct=round(margin_pct, 2),
                                prev_cs=prev_pb_cs)
            else:
                card.add_reason(ReasonKind.CONFIRMED_PB,
                                margin_cs=margin_cs, margin_pct=round(margin_pct, 2),
                                prev_cs=prev_pb_cs)

        # ---- Medal reasons (only in real finals/timed-finals — NOT heats) ----
        if sw.place in (1, 2, 3) and sw.round in ('final', 'timed_final'):
            kind = {1: ReasonKind.MEDAL_GOLD,
                    2: ReasonKind.MEDAL_SILVER,
                    3: ReasonKind.MEDAL_BRONZE}[sw.place]
            card.add_reason(kind, place=sw.place, round=sw.round)

        # ---- Barrier break ----
        b = _barrier_break(sw, prev_pb_cs)
        if b is not None:
            card.add_reason(ReasonKind.BARRIER_BREAK,
                            barrier_cs=b, barrier_str=_cs_label(b))

        cards.append(card)

    # -- Second pass: biggest improvement of meet (top 3 PB margins) ----
    if pb_margin_pct:
        top_3 = sorted(pb_margin_pct.items(), key=lambda kv: -kv[1])[:3]
        for idx, pct in top_3:
            if pct >= 0.5:   # don't celebrate sub-half-percent
                cards[idx].add_reason(
                    ReasonKind.BIGGEST_IMPROVEMENT_OF_MEET,
                    margin_pct=round(pct, 2),
                )

    return DetectionResult(
        cards=cards,
        swims_processed=len(cards) + skipped_no_time + skipped_dq,
        swims_skipped_no_time=skipped_no_time,
        swims_skipped_dq=skipped_dq,
        no_pb_history=no_pb_history,
        notes=notes,
    )


def _cs_label(cs: int) -> str:
    """Centiseconds -> '30.00' or '1:00.00' for barrier display."""
    mins = cs // 6000
    rem = cs - mins * 6000
    secs = rem // 100
    frac = rem % 100
    if mins:
        return f"{mins}:{secs:02d}.{frac:02d}"
    return f"{secs}.{frac:02d}"
