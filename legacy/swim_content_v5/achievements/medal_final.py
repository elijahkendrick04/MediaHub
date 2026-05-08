"""
Medal and finals detectors:
  - MedalDetector: place 1/2/3 in an event
  - FinalAppearanceDetector: swims labelled as finals
  - HeatToFinalDropDetector: same swimmer improved from heat to final
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
    rnd = getattr(swim, "round", "")
    return f"{key}:{dist}{stroke}{course}:{rnd}{suffix}"


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


class MedalDetector(AchievementDetector):
    """Fires for place 1/2/3 in events with round='final' or 'timed_final'."""
    name = "medal"

    def detect(self, swim, ctx, history, all_results=None, extra=None) -> list[Achievement]:
        if getattr(swim, "dq", False) or getattr(swim, "finals_time_cs", None) is None:
            return []

        place = getattr(swim, "place", None)
        if place not in (1, 2, 3):
            return []

        rnd = (getattr(swim, "round", "") or "").lower()
        # Medals valid in finals and timed finals
        if rnd not in ("final", "timed_final", ""):
            return []

        medal_map = {1: ("gold", "gold"), 2: ("silver", "silver"), 3: ("bronze", "bronze")}
        medal_type, medal_label = medal_map[place]
        evt = _event_label(swim)
        swimmer_name = (extra or {}).get("swimmer_name", history.swimmer_name)
        time_str = _cs_to_str(swim.finals_time_cs)

        meet_level_note = ""
        if ctx.meet_level in ("national", "university"):
            meet_level_note = f" at {ctx.meet_level}-level meet ({ctx.meet_name})"
        elif ctx.meet_name:
            meet_level_note = f" at {ctx.meet_name}"

        ordinal = {1: "1st", 2: "2nd", 3: "3rd"}[place]

        return [Achievement(
            type=f"medal_{medal_type}",
            swim_id=_swim_id(swim, f":{medal_type}"),
            swimmer_id=swim.swimmer_key,
            swimmer_name=swimmer_name,
            event=evt,
            headline=f"{swimmer_name} wins {medal_label} medal ({ordinal}) in {evt} — {time_str}{meet_level_note}",
            angle_hint=f"{ordinal} place finish in {evt}. Time: {time_str}.",
            confidence=0.95,
            confidence_label="high",
            evidence=[
                AchievementEvidence(
                    source_type="results_file",
                    source_name="Meet results",
                    statement=f"Place {place} recorded in results file for {evt}",
                    confidence="high",
                ),
            ],
            raw_facts={
                "place": place,
                "medal": medal_type,
                "time_sec": swim.finals_time_cs / 100.0,
                "time_str": time_str,
                "meet_level": ctx.meet_level,
            },
            detector_name=self.name,
        )]

    def _no_fire_reason(self, swim, ctx, history, all_results=None, extra=None) -> str:
        place = getattr(swim, "place", None)
        rnd = (getattr(swim, "round", "") or "").lower()
        if place not in (1, 2, 3):
            return f"place {place} — not a podium finish"
        if rnd not in ("final", "timed_final", ""):
            return f"round '{rnd}' — not a final"
        return "did not fire"


class FinalAppearanceDetector(AchievementDetector):
    """Fires when swimmer appears in a final (but not necessarily medals)."""
    name = "final_appearance"

    def detect(self, swim, ctx, history, all_results=None, extra=None) -> list[Achievement]:
        if getattr(swim, "dq", False) or getattr(swim, "finals_time_cs", None) is None:
            return []

        rnd = (getattr(swim, "round", "") or "").lower()
        if rnd != "final":
            return []

        # Only fire if not already a medal (medal detector fires too)
        place = getattr(swim, "place", None)
        if place in (1, 2, 3):
            return []  # MedalDetector covers this

        evt = _event_label(swim)
        swimmer_name = (extra or {}).get("swimmer_name", history.swimmer_name)
        time_str = _cs_to_str(swim.finals_time_cs)

        place_str = f" (place {place})" if place else ""

        return [Achievement(
            type="final_appearance",
            swim_id=_swim_id(swim, ":final_appearance"),
            swimmer_id=swim.swimmer_key,
            swimmer_name=swimmer_name,
            event=evt,
            headline=f"{swimmer_name} makes the final in {evt}{place_str} — {time_str}",
            angle_hint=f"Final appearance in {evt}{place_str}. Time: {time_str}.",
            confidence=0.9,
            confidence_label="high",
            evidence=[
                AchievementEvidence(
                    source_type="results_file",
                    source_name="Meet results",
                    statement=f"Round 'final' recorded in results file for {evt}",
                    confidence="high",
                ),
            ],
            raw_facts={
                "place": place,
                "time_sec": swim.finals_time_cs / 100.0,
                "time_str": time_str,
            },
            detector_name=self.name,
        )]

    def _no_fire_reason(self, swim, ctx, history, all_results=None, extra=None) -> str:
        rnd = (getattr(swim, "round", "") or "").lower()
        if rnd != "final":
            return f"round is '{rnd}' — not explicitly a final"
        place = getattr(swim, "place", None)
        if place in (1, 2, 3):
            return "podium — handled by MedalDetector"
        return "did not fire"


class HeatToFinalDropDetector(AchievementDetector):
    """
    Fires when the same swimmer improved from heat to final by >0.3s
    in the same event on the same day.
    Requires all_results to find the matching heat swim.
    """
    name = "heat_to_final_drop"

    def detect(self, swim, ctx, history, all_results=None, extra=None) -> list[Achievement]:
        if getattr(swim, "dq", False) or getattr(swim, "finals_time_cs", None) is None:
            return []

        rnd = (getattr(swim, "round", "") or "").lower()
        if rnd != "final":
            return []  # Only check final swims

        if not all_results:
            return []

        # Find the matching heat swim for this swimmer + event
        swimmer_key = swim.swimmer_key
        dist = swim.distance
        stroke = swim.stroke
        course = swim.course
        swim_date = getattr(swim, "swim_date", None) or ""

        heat_swim = None
        for r in all_results:
            if getattr(r, "swimmer_key", "") != swimmer_key:
                continue
            if getattr(r, "distance", 0) != dist:
                continue
            if getattr(r, "stroke", "") != stroke:
                continue
            if getattr(r, "course", "") != course:
                continue
            r_rnd = (getattr(r, "round", "") or "").lower()
            if r_rnd not in ("heat", "prelim", "heats"):
                continue
            r_date = getattr(r, "swim_date", "") or ""
            # Same date or within 1 day
            if r_date[:10] == swim_date[:10]:
                heat_swim = r
                break

        if heat_swim is None or heat_swim.finals_time_cs is None:
            return []

        final_cs = swim.finals_time_cs
        heat_cs = heat_swim.finals_time_cs
        drop_cs = heat_cs - final_cs

        if drop_cs < 30:  # < 0.30s improvement
            return []

        drop_sec = drop_cs / 100.0
        evt = _event_label(swim)
        swimmer_name = (extra or {}).get("swimmer_name", history.swimmer_name)
        final_str = _cs_to_str(final_cs)
        heat_str = _cs_to_str(heat_cs)

        return [Achievement(
            type="heat_to_final_drop",
            swim_id=_swim_id(swim, ":h2f"),
            swimmer_id=swimmer_key,
            swimmer_name=swimmer_name,
            event=evt,
            headline=f"{swimmer_name} drops {drop_sec:.2f}s from heat to final in {evt}: {heat_str} → {final_str}",
            angle_hint=f"Improved {drop_sec:.2f}s from heat ({heat_str}) to final ({final_str}) in {evt}.",
            confidence=0.85,
            confidence_label="high",
            evidence=[
                AchievementEvidence(
                    source_type="results_file",
                    source_name="Meet results",
                    statement=f"Heat time: {heat_str}, Final time: {final_str}, improvement: {drop_sec:.2f}s",
                    confidence="high",
                ),
            ],
            raw_facts={
                "final_sec": final_cs / 100.0,
                "final_str": final_str,
                "heat_sec": heat_cs / 100.0,
                "heat_str": heat_str,
                "drop_seconds": round(drop_sec, 3),
            },
            detector_name=self.name,
        )]

    def _no_fire_reason(self, swim, ctx, history, all_results=None, extra=None) -> str:
        rnd = (getattr(swim, "round", "") or "").lower()
        if rnd != "final":
            return f"round is '{rnd}' — not a final"
        if not all_results:
            return "no all_results provided — cannot find heat swim"
        return "no matching heat swim found, or improvement < 0.30s"
