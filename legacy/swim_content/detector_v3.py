"""
Detector V3 — produces a flat list of Claims from a parsed meet, the live
swimmingresults.org PB snapshots, and the qualification standards registry.

Inputs:
    parsed meet (HY3) + filtered swims for our club
    dict[tiref] -> SwimmerPBSnapshot
    list[Standard] (qualification registry)

Output:
    list[Claim] suitable for grouper.group_claims_into_cards()
    plus an EvidenceLog for the upload/verification report
    plus a stats summary used by the verification screen

This file does NOT decide card type — that is the grouper's job.
It also does NOT score — that is the ranker's job.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .cards import Claim
from .enrichment_swimmingresults import SwimmerPBSnapshot, compare_to_pb
from .quals_registry import Standard, check_swim_against_standards
from .evidence import Evidence, CONF_HIGH, CONF_MEDIUM, CONF_LOW


_STROKE_MAP = {"FR": "Freestyle", "BK": "Backstroke", "BR": "Breaststroke",
               "FL": "Butterfly", "IM": "Individual Medley"}


def _event_label(distance: int, stroke: str, course: str) -> str:
    return f"{distance}m {_STROKE_MAP.get(stroke, stroke)} ({course})"


def _cs_to_str(cs: int) -> str:
    """Centiseconds -> '30.00' or '1:00.00'."""
    mins = cs // 6000
    rem = cs - mins * 6000
    secs = rem // 100
    frac = rem % 100
    if mins:
        return f"{mins}:{secs:02d}.{frac:02d}"
    return f"{secs}.{frac:02d}"


def _parse_iso(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except Exception:
        # Try DD/MM/YYYY
        m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", s)
        if m:
            try:
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except Exception:
                return None
        return None


@dataclass
class DetectorOutput:
    claims: list[Claim] = field(default_factory=list)
    needs_confirmation_swims: list[dict] = field(default_factory=list)
    n_swims_processed: int = 0
    n_swims_skipped: int = 0
    n_pb_confirmed: int = 0
    n_pb_likely: int = 0
    n_pb_unverified: int = 0
    n_qual_hits: int = 0
    n_medals: int = 0


def detect_v3(
    *,
    meet,                                      # ParsedMeet
    our_swims: list,                           # list[ParsedSwim]
    swimmers_by_asa: dict,                     # dict[str, ParsedSwimmer]
    pb_snapshots: dict[str, SwimmerPBSnapshot],
    standards: list[Standard],
    club_code: str = "SUNY",
) -> DetectorOutput:
    out = DetectorOutput()
    meet_name = getattr(meet, "name", "")

    for sw in our_swims:
        if getattr(sw, "dq", False):
            out.n_swims_skipped += 1
            continue
        if getattr(sw, "finals_time_cs", None) is None:
            out.n_swims_skipped += 1
            continue

        out.n_swims_processed += 1

        swimmer = swimmers_by_asa.get(sw.asa_id)
        if not swimmer:
            continue
        full_name = f"{swimmer.first_name} {swimmer.last_name}".strip()
        time_str = _cs_to_str(sw.finals_time_cs)
        time_sec = sw.finals_time_cs / 100.0
        evt = _event_label(sw.distance, sw.stroke, sw.course)
        round_code = (sw.round or "").lower()
        # Map V2 round vocabulary onto a single-char code
        if round_code in ("final", "timed_final"):
            round_letter = "F"
        elif round_code in ("prelim", "heat", "heats"):
            round_letter = "P"
        elif round_code in ("semi", "semifinal"):
            round_letter = "S"
        else:
            round_letter = ""

        swim_date_iso = sw.swim_date  # already ISO from V2 parser
        swim_date = _parse_iso(swim_date_iso)

        # ---- Medal claims (finals only) ----
        if sw.place in (1, 2, 3) and round_letter == "F":
            kind = {1: "gold", 2: "silver", 3: "bronze"}[sw.place]
            out.claims.append(Claim(
                kind=kind,
                swimmer_name=full_name,
                swimmer_tiref=sw.asa_id,
                event_label=evt,
                distance=sw.distance,
                stroke=sw.stroke,
                course=sw.course,
                time_str=time_str,
                time_sec=time_sec,
                place=sw.place,
                round=round_letter,
                swim_date=swim_date_iso,
            ))
            out.n_medals += 1

        # ---- PB claims (using live swimmingresults.org snapshot) ----
        snap = pb_snapshots.get(sw.asa_id)
        cmp = compare_to_pb(
            snapshot=snap,
            distance=sw.distance, stroke=sw.stroke, course=sw.course,
            swim_time_sec=time_sec, swim_date_iso=swim_date_iso,
        )
        if cmp.status == "CONFIRMED_PB":
            out.claims.append(Claim(
                kind="pb_confirmed",
                swimmer_name=full_name,
                swimmer_tiref=sw.asa_id,
                event_label=evt,
                distance=sw.distance,
                stroke=sw.stroke,
                course=sw.course,
                time_str=time_str,
                time_sec=time_sec,
                place=sw.place,
                round=round_letter,
                swim_date=swim_date_iso,
                extra={
                    "delta_sec": cmp.delta_sec,
                    "prior_time_sec": cmp.prior_time_sec,
                    "prior_time_str": cmp.prior_time_str,
                    "prior_date_iso": cmp.prior_date_iso,
                    "source_url": cmp.source_url,
                    "retrieved_at": cmp.retrieved_at,
                },
            ))
            out.n_pb_confirmed += 1
        elif cmp.status == "LIKELY_PB":
            out.claims.append(Claim(
                kind="pb_likely",
                swimmer_name=full_name,
                swimmer_tiref=sw.asa_id,
                event_label=evt,
                distance=sw.distance,
                stroke=sw.stroke,
                course=sw.course,
                time_str=time_str,
                time_sec=time_sec,
                place=sw.place,
                round=round_letter,
                swim_date=swim_date_iso,
                extra={
                    "source_url": cmp.source_url,
                    "retrieved_at": cmp.retrieved_at,
                    "note": cmp.note,
                },
            ))
            out.n_pb_likely += 1
            # Also surface for the verification screen's "needs confirmation" list
            out.needs_confirmation_swims.append({
                "swimmer": full_name,
                "tiref": sw.asa_id,
                "event": evt,
                "time": time_str,
                "reason": cmp.note,
            })
        elif cmp.status == "PB_UNVERIFIED":
            out.n_pb_unverified += 1

        # ---- Qualification hits ----
        if swim_date is not None:
            hits = check_swim_against_standards(
                standards=standards,
                distance=sw.distance,
                stroke=sw.stroke,
                gender=sw.gender,
                course=sw.course,
                swim_time_sec=time_sec,
                swim_date=swim_date,
                club_code=club_code,
            )
            for h in hits:
                # Only include hits that are inside the qualification window;
                # out-of-window hits remain interesting (achieved the standard)
                # but are flagged in extra so the ranker can soft-weight them.
                out.claims.append(Claim(
                    kind="qual_hit",
                    swimmer_name=full_name,
                    swimmer_tiref=sw.asa_id,
                    event_label=evt,
                    distance=sw.distance,
                    stroke=sw.stroke,
                    course=sw.course,
                    time_str=time_str,
                    time_sec=time_sec,
                    place=sw.place,
                    round=round_letter,
                    swim_date=swim_date_iso,
                    extra={
                        "competition": h.competition,
                        "body": h.body,
                        "level": h.level,
                        "threshold_str": h.threshold_str,
                        "margin_sec": h.margin_sec,
                        "in_window": h.in_window,
                        "source_url": h.source_url,
                        "retrieved_at": h.retrieved_at,
                        "standard_id": h.standard_id,
                    },
                ))
                out.n_qual_hits += 1
        # Note: a "final" with no medal/PB/qual-hit produces no claim.

    return out
