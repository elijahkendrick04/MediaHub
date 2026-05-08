"""
Upload Test Report — what to show the operator immediately after ingesting
a meet, BEFORE they spend time reviewing content cards.

Goals:
  1. Surface counts so the operator can sanity-check the parser worked.
  2. Surface "needs human confirmation" cases — swims for which we cannot
     make a confident automated judgement (e.g. swimmer not in PB store,
     possible name typo, PB store is post-meet so PB detection unreliable).
  3. Make the temporal-validity check loud: if the PB store was generated
     AFTER the meet, mark all "no PB" cases as low-confidence.

Use this report as the ALWAYS-FIRST screen after upload. The operator
must look at it before being shown the content queue.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from .parsers_hy3 import ParsedMeet, ParsedSwim, ParsedSwimmer
from .parsers_pb_pdf import PBStore
from .club_filter import ClubRoster
from .detector_v2 import ContentCard, ReasonKind


@dataclass
class UploadReport:
    # Parser stats
    meet_name: str
    meet_dates: tuple[str | None, str | None]
    pb_store_generated: str | None        # ISO date if known
    n_clubs: int
    n_swimmers_total: int
    n_swims_total: int

    # Roster filter stats
    our_swimmers: int
    our_swims: int
    excluded_host_swimmers: int           # SWAY (Swansea Aquatics) explicitly excluded

    # Detection stats
    cards_total: int
    queue_size: int
    recap_size: int
    archive_size: int

    # Confidence flags
    pb_store_after_meet: bool             # if true, PB-detection is suspect
    swimmers_missing_from_pb_store: list[str] = field(default_factory=list)
    swims_no_pb_match: int = 0
    likely_pbs: int = 0                   # cards with LIKELY_PB reason
    first_evers: int = 0                  # cards with FIRST_EVER reason

    # Top-line warnings: render these as red banners in the UI
    warnings: list[str] = field(default_factory=list)

    # Manual confirmation list — swims that need an operator decision
    # before publishing. Each entry: (swimmer, event, time, reason, suggested_action)
    needs_confirmation: list[dict] = field(default_factory=list)


def build_report(
    meet: ParsedMeet,
    pb_store: PBStore,
    roster: ClubRoster,
    cards_in_queue: list[ContentCard],
    cards_in_recap: list[ContentCard],
    cards_in_archive: list[ContentCard],
    pb_store_generated_iso: str | None = None,
) -> UploadReport:
    all_cards = cards_in_queue + cards_in_recap + cards_in_archive
    our_swimmers = [s for s in meet.swimmers.values()
                    if s.club_code in roster.club_codes]
    our_swims = [s for s in meet.swims if s.club_code in roster.club_codes]
    excluded_host = sum(1 for s in meet.swimmers.values()
                        if s.club_code in roster.exclude_codes)

    # Coverage gaps
    missing = []
    for sm in our_swimmers:
        if sm.asa_id not in pb_store.by_asa:
            missing.append(f"{sm.first_name} {sm.last_name} (ASA {sm.asa_id})")

    # Temporal-validity check
    pb_after = False
    if pb_store_generated_iso and meet.start_date:
        try:
            if datetime.fromisoformat(pb_store_generated_iso) >= datetime.fromisoformat(meet.start_date):
                pb_after = True
        except ValueError:
            pass

    likely_pbs = sum(1 for c in all_cards
                     if any(r.kind == ReasonKind.LIKELY_PB for r in c.reasons))
    first_evers = sum(1 for c in all_cards
                      if any(r.kind == ReasonKind.FIRST_EVER for r in c.reasons))
    no_pb_match = sum(1 for c in all_cards if c.prev_pb_cs is None)

    warnings = []
    if pb_after:
        warnings.append(
            "PB store appears to have been exported AFTER this meet. "
            "Automated PB detection cannot work in this state — please "
            "upload a PB-store snapshot dated BEFORE the meet, or verify "
            "PBs by hand against the operator's own records."
        )
    if not our_swims:
        warnings.append(
            "No swims attributed to your club. Verify the club code in "
            "your roster configuration matches the file."
        )
    if missing:
        warnings.append(
            f"{len(missing)} of {len(our_swimmers)} of your swimmers "
            "have no PB-store entry at all. They will appear in the "
            "manual confirmation list below."
        )

    # Needs-confirmation list — actionable items the operator must look at.
    needs = []
    # 1. LIKELY_PB cases: medal + apparent improvement but no PB store data
    for c in cards_in_queue + cards_in_recap:
        if any(r.kind == ReasonKind.LIKELY_PB for r in c.reasons):
            needs.append({
                'swimmer': c.swimmer_name,
                'event': f"{c.distance}m {c.stroke} {c.course}",
                'time': _cs_to_str(c.time_cs),
                'seed': _cs_to_str(c.seed_time_cs) if c.seed_time_cs else '-',
                'place': c.place,
                'reason': 'No PB store entry — confirm whether this is a real PB',
                'suggested_action': 'Check internal PB log or club records before publishing.',
            })
    # 2. Cap the list at 20 to keep the report readable.
    needs = needs[:20]

    return UploadReport(
        meet_name=meet.name,
        meet_dates=(meet.start_date, meet.end_date),
        pb_store_generated=pb_store_generated_iso,
        n_clubs=len(meet.clubs),
        n_swimmers_total=len(meet.swimmers),
        n_swims_total=len(meet.swims),
        our_swimmers=len(our_swimmers),
        our_swims=len(our_swims),
        excluded_host_swimmers=excluded_host,
        cards_total=len(all_cards),
        queue_size=len(cards_in_queue),
        recap_size=len(cards_in_recap),
        archive_size=len(cards_in_archive),
        pb_store_after_meet=pb_after,
        swimmers_missing_from_pb_store=missing,
        swims_no_pb_match=no_pb_match,
        likely_pbs=likely_pbs,
        first_evers=first_evers,
        warnings=warnings,
        needs_confirmation=needs,
    )


def _cs_to_str(cs: int | None) -> str:
    if cs is None:
        return '-'
    mins = cs // 6000
    rem = cs - mins * 6000
    secs = rem // 100
    frac = rem % 100
    if mins:
        return f"{mins}:{secs:02d}.{frac:02d}"
    return f"{secs}.{frac:02d}"


def render_text(rep: UploadReport) -> str:
    """Plain-text version of the report — handy for CLI / debugging."""
    out = []
    out.append("=" * 72)
    out.append(f"UPLOAD REPORT — {rep.meet_name}")
    out.append(f"Dates:   {rep.meet_dates[0]} \u2192 {rep.meet_dates[1]}")
    out.append(f"PB store generated: {rep.pb_store_generated or 'unknown'}")
    out.append("=" * 72)

    if rep.warnings:
        out.append("\nWARNINGS:")
        for w in rep.warnings:
            out.append(f"  ! {w}")

    out.append("\nPARSER:")
    out.append(f"  clubs in file:   {rep.n_clubs}")
    out.append(f"  swimmers total:  {rep.n_swimmers_total}")
    out.append(f"  swims total:     {rep.n_swims_total}")

    out.append("\nROSTER FILTER:")
    out.append(f"  your swimmers:   {rep.our_swimmers}")
    out.append(f"  your swims:      {rep.our_swims}")
    out.append(f"  host club excl.: {rep.excluded_host_swimmers}")

    out.append("\nDETECTION:")
    out.append(f"  total cards:     {rep.cards_total}")
    out.append(f"  queue (\u226570):     {rep.queue_size}")
    out.append(f"  recap (40-69):   {rep.recap_size}")
    out.append(f"  archive (<40):   {rep.archive_size}")
    out.append(f"  no PB match:     {rep.swims_no_pb_match}")
    out.append(f"  LIKELY_PB flag:  {rep.likely_pbs}")
    out.append(f"  FIRST_EVER flag: {rep.first_evers}")

    if rep.swimmers_missing_from_pb_store:
        out.append(f"\nSWIMMERS NOT IN PB STORE ({len(rep.swimmers_missing_from_pb_store)}):")
        for s in rep.swimmers_missing_from_pb_store[:8]:
            out.append(f"  - {s}")
        if len(rep.swimmers_missing_from_pb_store) > 8:
            out.append(f"  ... and {len(rep.swimmers_missing_from_pb_store)-8} more")

    if rep.needs_confirmation:
        out.append("\nNEEDS HUMAN CONFIRMATION (top 20):")
        for i, n in enumerate(rep.needs_confirmation, 1):
            out.append(f"  {i:2}. {n['swimmer']} | {n['event']} | "
                       f"swam {n['time']} | seed {n['seed']} | place {n['place']}")
            out.append(f"      {n['reason']}")

    out.append("=" * 72)
    return "\n".join(out)
