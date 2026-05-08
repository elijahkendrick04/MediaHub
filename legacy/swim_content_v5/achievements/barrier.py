"""
FirstSubBarrierDetector — STRICT mode.

For each event, defines natural time barriers.
Only fires when:
  1. History shows the swimmer has previously swum ABOVE the barrier.
  2. Current swim is BELOW (faster than) the barrier.

If no history, skips entirely and adds an uncertainty trace.
"""
from __future__ import annotations

from typing import Optional

from swim_content_v5.schema import Achievement, AchievementEvidence
from .base import AchievementDetector


# Map (distance, stroke, course) -> list of barriers (seconds), from slowest to fastest
# Swimmer crosses from above→below a barrier = achievement
_BARRIERS: dict[tuple, list[float]] = {
    # 50m Free LC
    (50, "FR", "LC"): [30.0, 28.0, 27.0, 25.0, 24.0],
    # 100m Free LC
    (100, "FR", "LC"): [60.0, 58.0, 55.0, 52.0, 50.0, 48.0],
    # 200m Free LC
    (200, "FR", "LC"): [2*60+20.0, 2*60+10.0, 2*60.0, 1*60+55.0, 1*60+50.0],
    # 400m Free LC
    (400, "FR", "LC"): [5*60.0, 4*60+40.0, 4*60+30.0, 4*60+10.0, 4*60.0],
    # 50m Back LC
    (50, "BK", "LC"): [35.0, 33.0, 31.0, 30.0, 28.0],
    # 100m Back LC
    (100, "BK", "LC"): [70.0, 68.0, 65.0, 62.0, 60.0],
    # 50m Breast LC
    (50, "BR", "LC"): [38.0, 36.0, 34.0, 32.0, 30.0],
    # 100m Breast LC
    (100, "BR", "LC"): [80.0, 75.0, 72.0, 70.0, 68.0],
    # 50m Fly LC
    (50, "FL", "LC"): [34.0, 32.0, 30.0, 28.0, 27.0],
    # 100m Fly LC
    (100, "FL", "LC"): [70.0, 66.0, 63.0, 60.0, 58.0],
    # 200m IM LC
    (200, "IM", "LC"): [2*60+40.0, 2*60+20.0, 2*60+10.0, 2*60.0, 1*60+55.0],
    # SC equivalents (typically ~3-4% faster)
    (50, "FR", "SC"): [29.0, 27.0, 26.0, 24.0, 23.0],
    (100, "FR", "SC"): [58.0, 56.0, 54.0, 52.0, 50.0],
    (50, "BK", "SC"): [33.0, 31.0, 30.0, 28.0, 27.0],
    (100, "BK", "SC"): [66.0, 63.0, 60.0, 58.0, 56.0],
    (50, "BR", "SC"): [36.0, 34.0, 32.0, 31.0, 29.0],
    (100, "BR", "SC"): [75.0, 72.0, 70.0, 67.0, 65.0],
    (50, "FL", "SC"): [32.0, 30.0, 28.0, 27.0, 26.0],
    (100, "FL", "SC"): [66.0, 63.0, 60.0, 58.0, 56.0],
    (200, "IM", "SC"): [2*60+20.0, 2*60+5.0, 2*60.0, 1*60+55.0, 1*60+50.0],
    (200, "FR", "SC"): [2*60+10.0, 2*60.0, 1*60+55.0, 1*60+50.0, 1*60+45.0],
}


def _sec_to_str(sec: float) -> str:
    cs = round(sec * 100)
    mins = cs // 6000
    rem = cs - mins * 6000
    secs = rem // 100
    frac = rem % 100
    if mins:
        return f"{mins}:{secs:02d}.{frac:02d}"
    return f"{secs}.{frac:02d}"


def _swim_id(swim, suffix: str = "") -> str:
    key = getattr(swim, "swimmer_key", "")
    dist = getattr(swim, "distance", 0)
    stroke = getattr(swim, "stroke", "")
    course = getattr(swim, "course", "")
    return f"{key}:{dist}{stroke}{course}:barrier{suffix}"


def _event_label(swim) -> str:
    from swim_content_v5.report import _event_label as _el
    return _el(swim)


class FirstSubBarrierDetector(AchievementDetector):
    """
    STRICT mode: only fires when history confirms the swimmer was above the barrier.
    If no history, adds uncertainty trace but does NOT fire.
    """
    name = "first_sub_barrier"

    def detect(self, swim, ctx, history, all_results=None, extra=None) -> list[Achievement]:
        if getattr(swim, "dq", False) or getattr(swim, "finals_time_cs", None) is None:
            return []

        dist = swim.distance
        stroke = swim.stroke
        course = swim.course
        time_sec = swim.finals_time_cs / 100.0

        key = (dist, stroke, course)
        barriers = _BARRIERS.get(key, [])
        if not barriers:
            return []

        evt = _event_label(swim)
        swimmer_name = (extra or {}).get("swimmer_name", history.swimmer_name)
        results: list[Achievement] = []

        for barrier in barriers:
            if time_sec >= barrier:
                continue  # didn't cross this barrier

            # Swimmer is now below this barrier — was prior swim above it?
            prior_best = history.best_time_in_event(dist, stroke, course)

            if prior_best is None:
                # STRICT: no history → can't verify. Don't fire.
                continue

            if prior_best < barrier:
                # Already had a time below this barrier → not "first time"
                continue

            # prior_best >= barrier and current < barrier → genuine first-time crossing!
            barrier_str = _sec_to_str(barrier)
            time_str = _sec_to_str(time_sec)
            prior_str = _sec_to_str(prior_best)

            results.append(Achievement(
                type="first_sub_barrier",
                swim_id=_swim_id(swim, f":{int(barrier*100)}"),
                swimmer_id=swim.swimmer_key,
                swimmer_name=swimmer_name,
                event=evt,
                headline=f"{swimmer_name} goes sub-{barrier_str} for the first time in {evt}: {time_str}",
                angle_hint=f"First time under {barrier_str} in {evt}. Previous best was {prior_str}.",
                confidence=0.9,
                confidence_label="high",
                evidence=[
                    AchievementEvidence(
                        source_type="results_file",
                        source_name="Meet results",
                        statement=f"Swam {time_str} — below barrier of {barrier_str}",
                        confidence="high",
                    ),
                    AchievementEvidence(
                        source_type="pb_cache",
                        source_name=history.source_name() or "PB lookup",
                        statement=f"Prior best was {prior_str} — above barrier of {barrier_str}",
                        source_url=history.source_url(),
                        fetched_at=history.retrieved_at(),
                        confidence="high",
                    ),
                ],
                raw_facts={
                    "time_sec": time_sec,
                    "time_str": time_str,
                    "barrier_sec": barrier,
                    "barrier_str": barrier_str,
                    "prior_pb_sec": prior_best,
                    "prior_pb_str": prior_str,
                    "margin_sec": round(barrier - time_sec, 3),
                },
                detector_name=self.name,
            ))

        return results

    def _no_fire_reason(self, swim, ctx, history, all_results=None, extra=None) -> str:
        key = (getattr(swim, "distance", 0), getattr(swim, "stroke", ""), getattr(swim, "course", ""))
        barriers = _BARRIERS.get(key, [])
        if not barriers:
            return "no barrier thresholds defined for this event"
        if getattr(swim, "finals_time_cs", None) is None:
            return "no time recorded"
        time_sec = swim.finals_time_cs / 100.0
        crossed = [b for b in barriers if time_sec < b]
        if not crossed:
            return f"time {_sec_to_str(time_sec)} is above all defined barriers"
        prior = history.best_time_in_event(swim.distance, swim.stroke, swim.course)
        if prior is None:
            return "no prior history — strict mode requires prior data to confirm first-time crossing"
        below = [b for b in crossed if prior < b]
        if below:
            return f"swimmer already had times below barrier(s): {[_sec_to_str(b) for b in below]}"
        return "no qualifying first-time barrier crossing found"
