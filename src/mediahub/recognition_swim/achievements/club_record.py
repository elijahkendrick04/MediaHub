"""
recognition_swim/achievements/club_record.py — W.3 NEW CLUB RECORD detector.

Fires when a swim beats the club's stored record for the matching
(distance, stroke, course, gender, age-group) key. The records table
(`mediahub.club_records`) is seeded by CSV import and only ever updated
when a NEW CLUB RECORD card is *approved* — detection never mutates it.

Deterministic throughout; ranked above PBs by the V5 ranker
(``_TYPE_MAGNITUDE["club_record"]``).
"""

from __future__ import annotations

from typing import Optional

from swim_content_v5.achievements.base import AchievementDetector
from swim_content_v5.schema import Achievement, AchievementEvidence

from mediahub.club_records.store import format_time_cs


def _event_label(swim) -> str:
    from swim_content_v5.report import _event_label as _el

    return _el(swim)


def _swim_id(swim, suffix: str = ":clubrecord") -> str:
    key = getattr(swim, "swimmer_key", "") or ""
    dist = getattr(swim, "distance", 0)
    stroke = getattr(swim, "stroke", "")
    course = getattr(swim, "course", "")
    rnd = getattr(swim, "round", "")
    return f"{key}:{dist}{stroke}{course}:{rnd}{suffix}"


def _age_group_bounds(age_group: str) -> Optional[tuple[int, int]]:
    """'11-12' → (11, 12); '17+' → (17, 200); 'open' → None (always matches)."""
    s = (age_group or "").strip().lower()
    if not s or s == "open":
        return None
    if s.endswith("+") and s[:-1].isdigit():
        return (int(s[:-1]), 200)
    if "-" in s:
        lo, _, hi = s.partition("-")
        if lo.strip().isdigit() and hi.strip().isdigit():
            return (int(lo), int(hi))
    if s.isdigit():  # single-age band, e.g. "10"
        return (int(s), int(s))
    return None


class ClubRecordDetector(AchievementDetector):
    """Fires when a swim is faster than the stored club record."""

    name = "club_record"

    def detect(self, swim, ctx, history, all_results=None, extra=None) -> list[Achievement]:
        if getattr(swim, "dq", False) or getattr(swim, "finals_time_cs", None) is None:
            return []
        records = (extra or {}).get("club_records") or {}
        if not records:
            return []

        distance = getattr(swim, "distance", None)
        stroke = getattr(swim, "stroke", "") or ""
        course = getattr(swim, "course", "") or ""
        time_cs = int(getattr(swim, "finals_time_cs"))
        if not distance or not stroke or not course:
            return []

        meta = ((extra or {}).get("swimmer_meta") or {}).get(getattr(swim, "swimmer_key", ""), {})
        gender = (getattr(swim, "gender", "") or meta.get("gender") or "").upper()[:1]
        age = meta.get("age")
        if not gender:
            return []  # never guess gender for a record claim

        # Collect candidate record keys this swim is eligible for, then keep
        # the most specific broken one (narrow age band beats open).
        broken: list[tuple[int, tuple, dict, str]] = []
        for key, rec in records.items():
            r_dist, r_stroke, r_course, r_gender, r_age_group = key
            if (int(r_dist), str(r_stroke), str(r_course), str(r_gender)) != (
                int(distance),
                stroke,
                course,
                gender,
            ):
                continue
            bounds = _age_group_bounds(r_age_group)
            if bounds is not None:
                if age is None or not (bounds[0] <= int(age) <= bounds[1]):
                    continue
                specificity = bounds[1] - bounds[0]
            else:
                specificity = 10_000  # open — least specific
            if time_cs < int(rec["time_cs"]):
                broken.append((specificity, key, rec, r_age_group))

        if not broken:
            return []
        broken.sort(key=lambda item: item[0])
        specificity, key, rec, age_group = broken[0]

        swimmer_name = (extra or {}).get("swimmer_name", "") or getattr(history, "swimmer_name", "")
        evt_label = _event_label(swim)
        old_str = format_time_cs(int(rec["time_cs"]))
        new_str = format_time_cs(time_cs)
        group_label = "" if age_group == "open" else f" ({age_group})"
        holder = rec.get("holder") or "previous holder"

        return [
            Achievement(
                type="club_record",
                swim_id=_swim_id(swim),
                swimmer_id=getattr(swim, "swimmer_key", ""),
                swimmer_name=swimmer_name,
                event=evt_label,
                headline=(
                    f"NEW CLUB RECORD{group_label}: {swimmer_name} — {new_str} in the {evt_label}"
                ),
                angle_hint=(
                    f"Club record broken: the old mark of {old_str} ({holder}"
                    + (f", {rec['set_date']}" if rec.get("set_date") else "")
                    + f") falls by {format_time_cs(int(rec['time_cs']) - time_cs)}."
                ),
                confidence=0.95,
                confidence_label="high",
                evidence=[
                    AchievementEvidence(
                        source_type="registry",
                        source_name="Club records table",
                        statement=(
                            f"Stored club record for {evt_label}{group_label} was {old_str} "
                            f"by {holder}; this swim's verified time is {new_str}."
                        ),
                        confidence="high",
                    )
                ],
                raw_facts={
                    "distance": int(distance),
                    "stroke": stroke,
                    "course": course,
                    "gender": gender,
                    "age_group": age_group,
                    "old_time_cs": int(rec["time_cs"]),
                    "old_time": old_str,
                    "old_holder": holder,
                    "old_set_date": rec.get("set_date") or "",
                    "new_time_cs": time_cs,
                    "new_time": new_str,
                    "swim_date": getattr(swim, "swim_date", None),
                },
                uncertainty_notes=(
                    []
                    if age is not None or age_group == "open"
                    else ["Age-group records skipped: swimmer age unknown in this file."]
                ),
                detector_name=self.name,
            )
        ]

    def _no_fire_reason(self, swim, ctx, history, all_results=None, extra=None) -> str:
        if not ((extra or {}).get("club_records") or {}):
            return "no club records table for this workspace"
        return "no stored club record beaten by this swim"
