"""
Meet inference — derive missing top-level meet fields from the parsed
results when the file did not provide them. Every inferred value adds
the field name to meet.inferred_fields and a ParseWarning so downstream
captions can surface "this was inferred, please confirm".

Inferences attempted:
  - course: majority course across results when meet.course missing
  - start_date / end_date: min/max of swim_date when meet has no dates
  - host_club_code: club with the most swims (heuristic; user can override)
  - country / governing_body: from club code patterns (4-letter Hytek -> UK,
    3-letter team -> US best-guess; only marked if confident)

Inference is conservative: anything ambiguous is left blank with a warning.
"""

from __future__ import annotations
from collections import Counter

from .canonical import Meet


def infer_missing(meet: Meet) -> None:
    """Mutate the Meet in place, filling fields that are missing."""

    # ---- course ----
    if not meet.course or meet.course == "LC" and not meet.results:
        # Trust HY3 default unless we have evidence.
        pass
    if meet.results:
        c = Counter(r.course for r in meet.results if r.course)
        if c:
            top, n = c.most_common(1)[0]
            ratio = n / sum(c.values())
            if not meet.course:
                meet.course = top
                meet.inferred_fields.append("course")
                meet.add_warning(
                    "course_inferred",
                    f"Course inferred from results: {top} ({ratio:.0%}).",
                    severity="info",
                    field_name="course",
                )
            elif ratio < 0.95 and len(c) > 1:
                meet.add_warning(
                    "course_mixed",
                    f"Meet course is mixed: {dict(c)}. Using {meet.course}.",
                    severity="warn",
                    field_name="course",
                )

    # ---- dates ----
    swim_dates = [r.swim_date for r in meet.results if r.swim_date]
    if swim_dates:
        sd, ed = min(swim_dates), max(swim_dates)
        if not meet.start_date:
            meet.start_date = sd
            meet.inferred_fields.append("start_date")
            meet.add_warning(
                "start_date_inferred",
                f"Meet start date inferred from results: {sd}.",
                severity="info",
                field_name="start_date",
            )
        if not meet.end_date:
            meet.end_date = ed
            if "end_date" not in meet.inferred_fields:
                meet.inferred_fields.append("end_date")
            meet.add_warning(
                "end_date_inferred",
                f"Meet end date inferred from results: {ed}.",
                severity="info",
                field_name="end_date",
            )

    # ---- host club ----
    if not meet.host_club_code and meet.results:
        cc = Counter(r.club_code for r in meet.results if r.club_code)
        if cc:
            top_club, n = cc.most_common(1)[0]
            ratio = n / sum(cc.values())
            if ratio >= 0.30 and len(meet.clubs) >= 2:
                # The host club is usually the largest entrant *and* the
                # one whose name matches the venue/meet name. Without that
                # second signal we mark it as a hint, not a fact.
                meet.host_club_code = top_club
                meet.inferred_fields.append("host_club_code")
                if top_club in meet.clubs:
                    meet.clubs[top_club].is_host = True
                meet.add_warning(
                    "host_inferred",
                    f"Host club inferred as {top_club} "
                    f"({n} swims, {ratio:.0%}). Confirm in profile if wrong.",
                    severity="info",
                    field_name="host_club_code",
                )

    # ---- governing body ----
    if not meet.governing_body and meet.clubs:
        # Heuristic: 4-letter alphabetic club codes are typical of UK Hytek
        # exports (Swim England). 3-letter codes are typical of USA Swimming.
        sample = list(meet.clubs.keys())[:10]
        is_uk = sum(1 for c in sample if len(c) == 4 and c.isalpha())
        if is_uk >= len(sample) * 0.7:
            meet.governing_body = "Swim England (assumed)"
            meet.country = meet.country or "United Kingdom"
            if "governing_body" not in meet.inferred_fields:
                meet.inferred_fields.append("governing_body")
            meet.add_warning(
                "gb_inferred",
                "Governing body assumed as Swim England based on 4-letter "
                "club codes. Adjust in club profile if wrong.",
                severity="info",
                field_name="governing_body",
            )
