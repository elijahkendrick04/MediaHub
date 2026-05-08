"""
TopOfFieldDetector — top 3/5/10 finishers across the entire meet field.

Fires for swimmers who finished in the top tier vs ALL entrants in their
event (not just club swimmers). Uses all_results.
"""
from __future__ import annotations

from typing import Optional

from swim_content_v5.schema import Achievement, AchievementEvidence
from .base import AchievementDetector


def _swim_id(swim, suffix: str = "") -> str:
    key = getattr(swim, "swimmer_key", "")
    dist = getattr(swim, "distance", 0)
    stroke = getattr(swim, "stroke", "")
    course = getattr(swim, "course", "")
    return f"{key}:{dist}{stroke}{course}:field{suffix}"


def _event_label(swim) -> str:
    from swim_content_v5.report import _event_label as _el
    return _el(swim)


def _cs_to_str(cs: int) -> str:
    mins = cs // 6000
    rem = cs - mins * 6000
    secs = rem // 100
    frac = rem % 100
    if mins:
        return f"{mins}:{secs:02d}.{frac:02d}"
    return f"{secs}.{frac:02d}"


class TopOfFieldDetector(AchievementDetector):
    """
    Top 3/5/10 in their event across the whole meet.
    Useful at large multi-club meets where a club swimmer
    beats a much larger field.
    """
    name = "top_of_field"

    def detect(self, swim, ctx, history, all_results=None, extra=None) -> list[Achievement]:
        if getattr(swim, "dq", False) or getattr(swim, "finals_time_cs", None) is None:
            return []

        # Need all_results to rank the field
        if not all_results:
            return []

        dist = swim.distance
        stroke = swim.stroke
        course = swim.course
        gender = getattr(swim, "gender", "")
        rnd = (getattr(swim, "round", "") or "").lower()
        age_band = getattr(swim, "age_band", "") or ""

        # Only fire for finals/timed finals
        if rnd == "heat":
            return []

        # Gather all valid swims in the same event
        field = []
        for r in all_results:
            if getattr(r, "dq", False):
                continue
            if getattr(r, "finals_time_cs", None) is None:
                continue
            if getattr(r, "distance", 0) != dist:
                continue
            if getattr(r, "stroke", "") != stroke:
                continue
            if getattr(r, "course", "") != course:
                continue
            r_gender = getattr(r, "gender", "")
            if gender and r_gender and r_gender != gender:
                continue
            r_rnd = (getattr(r, "round", "") or "").lower()
            if r_rnd == "heat" and rnd != "heat":
                continue  # Don't mix rounds
            # Age band: compare only if both have the same age band
            r_band = getattr(r, "age_band", "") or ""
            if age_band and r_band and age_band != r_band:
                continue
            field.append(r)

        if len(field) < 4:
            return []  # Not meaningful with < 4 swimmers

        # Sort by time
        field_sorted = sorted(field, key=lambda x: x.finals_time_cs)
        swimmer_key = swim.swimmer_key
        our_position = None
        for i, r in enumerate(field_sorted):
            if getattr(r, "swimmer_key", "") == swimmer_key:
                our_position = i + 1
                break

        if our_position is None:
            return []

        field_size = len(field_sorted)
        evt = _event_label(swim)
        swimmer_name = (extra or {}).get("swimmer_name", history.swimmer_name)
        time_str = _cs_to_str(swim.finals_time_cs)

        # Determine tier and whether to fire
        if our_position <= 3:
            tier = "top_3"
            tier_label = f"top 3 of {field_size}"
            confidence = 0.9
        elif our_position <= 5:
            tier = "top_5"
            tier_label = f"top 5 of {field_size}"
            confidence = 0.8
        elif our_position <= 10 and field_size >= 15:
            tier = "top_10"
            tier_label = f"top 10 of {field_size}"
            confidence = 0.7
        else:
            return []

        ordinal_map = {1: "1st", 2: "2nd", 3: "3rd"}
        pos_str = ordinal_map.get(our_position, f"{our_position}th")

        return [Achievement(
            type=f"top_of_field_{tier}",
            swim_id=_swim_id(swim, f":{tier}"),
            swimmer_id=swimmer_key,
            swimmer_name=swimmer_name,
            event=evt,
            headline=f"{swimmer_name} finishes {pos_str} in {evt} vs full field ({tier_label}) — {time_str}",
            angle_hint=f"{pos_str} place in {evt} vs {field_size} swimmers. Time: {time_str}.",
            confidence=confidence,
            confidence_label="high" if confidence >= 0.85 else "medium",
            evidence=[
                AchievementEvidence(
                    source_type="results_file",
                    source_name="Meet results",
                    statement=f"Position {our_position} of {field_size} in {evt}",
                    confidence="high",
                ),
            ],
            raw_facts={
                "field_position": our_position,
                "field_size": field_size,
                "tier": tier,
                "time_sec": swim.finals_time_cs / 100.0,
                "time_str": time_str,
            },
            detector_name=self.name,
        )]

    def _no_fire_reason(self, swim, ctx, history, all_results=None, extra=None) -> str:
        if not all_results:
            return "no all_results provided"
        rnd = (getattr(swim, "round", "") or "").lower()
        if rnd == "heat":
            return "heat swim — only finals are ranked vs field"
        return "not in top 10 of field, or field too small (< 4 swimmers)"
