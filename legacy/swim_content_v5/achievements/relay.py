"""
Relay detectors:
  - RelayMedalDetector: club relay team wins a medal
  - RelayStrongPerformanceDetector: relay time is strong vs the meet field
"""
from __future__ import annotations

from typing import Optional

from swim_content_v5.schema import Achievement, AchievementEvidence
from .base import AchievementDetector


def _relay_event_label(relay) -> str:
    dist = getattr(relay, "distance", 0)
    stroke = getattr(relay, "stroke", "")
    course = getattr(relay, "course", "")
    stroke_map = {"FR": "Freestyle", "MEDLEY": "Medley", "BK": "Backstroke",
                  "BR": "Breaststroke", "FL": "Butterfly"}
    stroke_name = stroke_map.get(stroke, stroke)
    return f"{dist}m {stroke_name} Relay ({course})"


def _cs_to_str(cs: int) -> str:
    mins = cs // 6000
    rem = cs - mins * 6000
    secs = rem // 100
    frac = rem % 100
    if mins:
        return f"{mins}:{secs:02d}.{frac:02d}"
    return f"{secs}.{frac:02d}"


class RelayMedalDetector(AchievementDetector):
    """
    Fires when a relay team from our club wins a podium place (1/2/3).
    Works on RelayResult objects — passed via extra['relay_results'].
    """
    name = "relay_medal"

    def detect(self, swim, ctx, history, all_results=None, extra=None) -> list[Achievement]:
        """
        For relay detectors, 'swim' is actually a RelayResult.
        We handle relay results separately in the pipeline.
        """
        # Check if this is being called as a relay sentinel
        extra = extra or {}
        relay_results = extra.get("relay_results", [])
        if not relay_results:
            return []

        results: list[Achievement] = []
        for relay in relay_results:
            if getattr(relay, "dq", False) or getattr(relay, "finals_time_cs", None) is None:
                continue
            place = getattr(relay, "place", None)
            if place not in (1, 2, 3):
                continue

            medal_map = {1: "gold", 2: "silver", 3: "bronze"}
            medal = medal_map[place]
            ordinal = {1: "1st", 2: "2nd", 3: "3rd"}[place]
            evt = _relay_event_label(relay)
            time_str = _cs_to_str(relay.finals_time_cs)
            club = getattr(relay, "club_code", "") or "Club"

            results.append(Achievement(
                type=f"relay_medal_{medal}",
                swim_id=f"{club}:{getattr(relay, 'distance', 0)}{getattr(relay, 'stroke', '')}:relay:{medal}",
                swimmer_id=club,
                swimmer_name=f"{club} relay",
                event=evt,
                headline=f"{club} relay wins {medal} medal ({ordinal}) in {evt} — {time_str}",
                angle_hint=f"Team relay {medal} medal in {evt}. Time: {time_str}.",
                confidence=0.9,
                confidence_label="high",
                evidence=[
                    AchievementEvidence(
                        source_type="results_file",
                        source_name="Meet results",
                        statement=f"Relay place {place} recorded in results file for {evt}",
                        confidence="high",
                    ),
                ],
                raw_facts={
                    "place": place,
                    "medal": medal,
                    "time_sec": relay.finals_time_cs / 100.0,
                    "time_str": time_str,
                    "club": club,
                },
                detector_name=self.name,
            ))

        return results

    def _no_fire_reason(self, swim, ctx, history, all_results=None, extra=None) -> str:
        relay_results = (extra or {}).get("relay_results", [])
        if not relay_results:
            return "no relay results provided"
        return "no relay podium finishes (place 1/2/3)"


class RelayStrongPerformanceDetector(AchievementDetector):
    """
    Fires when a club relay finishes in the top 5 of a field of >= 6 relay teams.
    """
    name = "relay_strong_performance"

    def detect(self, swim, ctx, history, all_results=None, extra=None) -> list[Achievement]:
        extra = extra or {}
        relay_results = extra.get("relay_results", [])
        all_relay_results = extra.get("all_relay_results", [])
        if not relay_results:
            return []

        results: list[Achievement] = []
        for relay in relay_results:
            if getattr(relay, "dq", False) or getattr(relay, "finals_time_cs", None) is None:
                continue
            place = getattr(relay, "place", None)
            if place is None or place <= 3:
                continue  # MedalDetector covers 1-3

            # Count field size for this relay event
            dist = getattr(relay, "distance", 0)
            stroke = getattr(relay, "stroke", "")
            course = getattr(relay, "course", "")
            gender = getattr(relay, "gender", "")

            field = [
                r for r in all_relay_results
                if not getattr(r, "dq", False)
                and getattr(r, "finals_time_cs", None) is not None
                and getattr(r, "distance", 0) == dist
                and getattr(r, "stroke", "") == stroke
                and getattr(r, "course", "") == course
                and (not gender or not getattr(r, "gender", "") or getattr(r, "gender", "") == gender)
            ]

            if len(field) < 6:
                continue
            if place > 5:
                continue

            evt = _relay_event_label(relay)
            time_str = _cs_to_str(relay.finals_time_cs)
            club = getattr(relay, "club_code", "") or "Club"
            ordinal = f"{place}th" if place > 3 else f"{place}rd"

            results.append(Achievement(
                type="relay_strong_performance",
                swim_id=f"{club}:{dist}{stroke}:relay:strong",
                swimmer_id=club,
                swimmer_name=f"{club} relay",
                event=evt,
                headline=f"{club} relay finishes {ordinal} of {len(field)} teams in {evt} — {time_str}",
                angle_hint=f"Top-5 relay finish in {evt} vs {len(field)} teams. Time: {time_str}.",
                confidence=0.75,
                confidence_label="medium",
                evidence=[
                    AchievementEvidence(
                        source_type="results_file",
                        source_name="Meet results",
                        statement=f"Relay position {place} of {len(field)} in {evt}",
                        confidence="high",
                    ),
                ],
                raw_facts={
                    "place": place,
                    "field_size": len(field),
                    "time_sec": relay.finals_time_cs / 100.0,
                    "time_str": time_str,
                    "club": club,
                },
                detector_name=self.name,
            ))

        return results

    def _no_fire_reason(self, swim, ctx, history, all_results=None, extra=None) -> str:
        relay_results = (extra or {}).get("relay_results", [])
        if not relay_results:
            return "no relay results provided"
        return "relay outside top 5, or field too small (< 6 teams)"
