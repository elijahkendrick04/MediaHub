"""
HY3 adapter — wraps V3 parsers_hy3 and converts the legacy ParsedMeet
into a canonical V4 Meet. We never re-parse from scratch; the V3 parser
was bit-verified against a real meet file and we want to reuse exactly
that proven path.

The adapter is tolerant: missing fields produce ParseWarnings, never
exceptions. A swimmer with no asa_id is given a stable hash key so we
still capture the swim with low identity_confidence.
"""

from __future__ import annotations
import hashlib
from typing import Optional

from ..canonical import (
    Meet,
    Club,
    Swimmer,
    RaceResult,
    Split,
    MeetAdapter,
    SourceEvidence,
)

# Reuse V3's verified parser
from swim_content.parsers_hy3 import parse_hy3_text, ParsedMeet


def _stable_swimmer_key(*, asa_id: Optional[str], club_code: str, last: str, first: str) -> str:
    if asa_id:
        return f"asa:{asa_id}"
    raw = f"{club_code}|{last.lower()}|{first.lower()}".encode("utf-8")
    return f"hash:{hashlib.md5(raw, usedforsecurity=False).hexdigest()[:10]}"


class HY3Adapter(MeetAdapter):
    format_id = "hy3"
    display_name = "Hytek Meet Manager (.hy3)"

    def can_parse(self, file_bytes: bytes, filename: str) -> float:
        name = (filename or "").lower()
        if name.endswith(".hy3"):
            return 0.95
        # Sniff: HY3 files start with 'A0' or 'A1' header records
        try:
            head = file_bytes[:4].decode("latin-1", errors="ignore")
            if head.startswith("A0") or head.startswith("A1"):
                return 0.85
        except Exception:
            pass
        return 0.0

    def parse(self, file_bytes: bytes, filename: str) -> Meet:
        try:
            text = file_bytes.decode("latin-1", errors="ignore")
        except Exception as e:
            m = Meet(source_format="hy3", source_filename=filename)
            m.add_warning("decode_failed", f"Could not decode HY3 file: {e}", severity="error")
            return m

        try:
            parsed: ParsedMeet = parse_hy3_text(text)
        except Exception as e:
            m = Meet(source_format="hy3", source_filename=filename)
            m.add_warning("parse_failed", f"HY3 parser raised: {e}", severity="error")
            return m

        meet = Meet(
            name=parsed.name or "(unknown)",
            venue=parsed.venue,
            course=parsed.course or "LC",
            start_date=parsed.start_date,
            end_date=parsed.end_date,
            source_format="hy3",
            source_filename=filename,
        )
        meet.source_evidence.append(
            SourceEvidence(
                source="Meet results file",
                note=f"Parsed from {filename} (HY3 format)",
                confidence="high",
            )
        )

        # Clubs
        for code, c in parsed.clubs.items():
            meet.clubs[code] = Club(
                code=code,
                name=c.name,
                short_name=c.short_name,
            )

        # Swimmers — keyed by asa_id when present, else stable hash
        for asa_id, sw in parsed.swimmers.items():
            key = _stable_swimmer_key(
                asa_id=asa_id,
                club_code=sw.club_code,
                last=sw.last_name,
                first=sw.first_name,
            )
            ident_conf = "high" if asa_id else "low"
            meet.swimmers[key] = Swimmer(
                swimmer_key=key,
                first_name=sw.first_name,
                last_name=sw.last_name,
                gender=sw.gender,
                age_at_meet=sw.age,
                asa_id=asa_id or None,
                club_code=sw.club_code,
                identity_confidence=ident_conf,
            )

        # Build asa_id -> swimmer_key map for swims
        asa_to_key = {sw.asa_id: sw.swimmer_key for sw in meet.swimmers.values() if sw.asa_id}

        # Race results
        kept = 0
        for s in parsed.swims:
            key = asa_to_key.get(s.asa_id)
            if not key:
                meet.add_warning(
                    "orphan_swim",
                    f"Swim has no matching swimmer record (asa_id={s.asa_id})",
                    severity="info",
                    record=f"swim:{s.distance}{s.stroke}",
                )
                continue
            # Splits: V3 stores cumulative cs only; we have no per-split diff
            splits = [
                Split(distance_marker=(i + 1) * 50, cumulative_cs=cs)
                for i, cs in enumerate(s.splits_cs or [])
            ]
            status = "completed"
            if s.dq:
                status = "dq"
            elif s.finals_time_cs is None:
                status = "dns"

            meet.results.append(
                RaceResult(
                    swimmer_key=key,
                    club_code=s.club_code,
                    distance=s.distance,
                    stroke=s.stroke,
                    course=s.course,
                    gender=s.gender,
                    age_band=s.age_band or "",
                    finals_time_cs=s.finals_time_cs,
                    seed_time_cs=s.seed_time_cs,
                    place=s.place,
                    round=s.round,
                    dq=s.dq,
                    status=status,
                    swim_date=s.swim_date,
                    splits=splits,
                )
            )
            kept += 1

        if kept == 0:
            meet.add_warning(
                "no_swims",
                "HY3 file parsed but contained no usable swim results.",
                severity="error",
            )

        return meet
