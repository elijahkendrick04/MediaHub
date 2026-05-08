"""
Bridge canonical V4 Meet → V3 ParsedMeet structure so we can reuse V3's
already-validated detector / grouper / captions / ranker / self-check
modules without rewriting them.

Why a shim instead of porting V3 modules?
  - V3 logic was tuned and tested against a real meet (1665 swims,
    self-check 12 pass / 1 warn / 0 fail). Rewriting risks regression.
  - V4's canonical schema is a strict superset of what V3 needs.
  - Future native-V4 detector can be introduced incrementally.

The shim is read-only: it builds V3 ParsedMeet/ParsedSwim/ParsedSwimmer
objects from canonical inputs.
"""
from __future__ import annotations
from typing import Optional

from swim_content.parsers_hy3 import ParsedMeet, ParsedClub, ParsedSwimmer, ParsedSwim

from .canonical import Meet, Swimmer, RaceResult


def _swimmer_to_v3(sw: Swimmer) -> Optional[ParsedSwimmer]:
    if not sw.asa_id:
        return None
    return ParsedSwimmer(
        asa_id=sw.asa_id,
        gender=sw.gender,
        last_name=sw.last_name,
        first_name=sw.first_name,
        age=sw.age_at_meet,
        club_code=sw.club_code or "",
    )


def _result_to_v3(r: RaceResult, swimmer_asa_lookup: dict) -> Optional[ParsedSwim]:
    asa = swimmer_asa_lookup.get(r.swimmer_key)
    if not asa:
        return None
    return ParsedSwim(
        asa_id=asa,
        club_code=r.club_code or "",
        distance=r.distance,
        stroke=r.stroke,
        course=r.course,
        gender=r.gender,
        age_at_meet=None,  # not on RaceResult; V3 detector reads from swimmer
        age_band=r.age_band or "",
        finals_time_cs=r.finals_time_cs,
        seed_time_cs=r.seed_time_cs,
        place=r.place,
        round=r.round,
        dq=r.dq,
        swim_date=r.swim_date,
        splits_cs=[s.cumulative_cs for s in r.splits],
    )


def canonical_to_v3(meet: Meet) -> ParsedMeet:
    """Project a canonical Meet down to V3's ParsedMeet structure."""
    clubs_v3 = {
        code: ParsedClub(code=c.code, name=c.name, short_name=c.short_name)
        for code, c in meet.clubs.items()
    }

    # V3 keys swimmers by asa_id. Canonical uses swimmer_key. We only
    # propagate asa-identified swimmers because V3's matchers depend on
    # asa_id; non-asa swimmers will be missing from claims (acceptable
    # for the pilot — surfaced via warnings).
    swimmers_v3: dict[str, ParsedSwimmer] = {}
    asa_lookup: dict[str, str] = {}   # swimmer_key -> asa_id
    for key, sw in meet.swimmers.items():
        v3sw = _swimmer_to_v3(sw)
        if v3sw is None:
            continue
        swimmers_v3[v3sw.asa_id] = v3sw
        asa_lookup[key] = v3sw.asa_id

    swims_v3: list[ParsedSwim] = []
    for r in meet.results:
        v3s = _result_to_v3(r, asa_lookup)
        if v3s is None:
            continue
        # Fill age_at_meet from swimmer if available
        sw = swimmers_v3.get(v3s.asa_id)
        if sw and sw.age is not None:
            v3s.age_at_meet = sw.age
        swims_v3.append(v3s)

    return ParsedMeet(
        name=meet.name,
        venue=meet.venue,
        course=meet.course,
        start_date=meet.start_date,
        end_date=meet.end_date,
        clubs=clubs_v3,
        swimmers=swimmers_v3,
        swims=swims_v3,
    )
