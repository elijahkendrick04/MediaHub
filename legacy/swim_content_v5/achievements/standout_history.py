"""
History-based standout detectors:
  - FastestSinceDetector: current time is fastest in event since date X
  - BiggestDropDetector: meet-level — single biggest improvement (only one fires)
  - MultiPBWeekendDetector: per swimmer, >=3 confirmed PBs in one meet
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
    return f"{key}:{dist}{stroke}{course}:{suffix}"


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


def _sec_to_str(sec: float) -> str:
    cs = round(sec * 100)
    return _cs_to_str(cs)


class FastestSinceDetector(AchievementDetector):
    """
    Fires when current time is fastest in event since a notable date.
    Uses full time history from pb_cache.
    """
    name = "fastest_since"

    def detect(self, swim, ctx, history, all_results=None, extra=None) -> list[Achievement]:
        if getattr(swim, "dq", False) or getattr(swim, "finals_time_cs", None) is None:
            return []

        time_sec = swim.finals_time_cs / 100.0
        times = history.times_in_event(swim.distance, swim.stroke, swim.course)

        if len(times) < 2:
            return []  # Need history to compare

        # times is (date_iso, time_sec) sorted fastest first
        current_best = min(t for _, t in times)
        if abs(time_sec - current_best) > 0.01:
            # Current is not the fastest — but is it fastest recent?
            return []

        # Find the last time they swam this fast
        # Sort by date, find previous times faster or equal
        dated = sorted(
            [(d, t) for d, t in times if d],
            key=lambda x: x[0],
            reverse=True,
        )

        if len(dated) < 2:
            return []

        # Latest entry should be the current swim — find second fastest historically
        # Filter to times faster than current (excluding current swim)
        swim_date = getattr(swim, "swim_date", "") or ctx.start_date or ""
        prior_times = [
            (d, t) for d, t in dated
            if d < swim_date[:10] and t <= time_sec * 1.005  # within 0.5%
        ]

        if not prior_times:
            return []

        last_fast_date = prior_times[0][0]  # most recent prior similar time
        year = last_fast_date[:4] if last_fast_date else "previously"

        evt = _event_label(swim)
        swimmer_name = (extra or {}).get("swimmer_name", history.swimmer_name)
        time_str = _cs_to_str(swim.finals_time_cs)

        return [Achievement(
            type="fastest_since",
            swim_id=_swim_id(swim, "fastest_since"),
            swimmer_id=swim.swimmer_key,
            swimmer_name=swimmer_name,
            event=evt,
            headline=f"{swimmer_name} fastest in {evt} since {year}: {time_str}",
            angle_hint=f"Best time in {evt} since {last_fast_date} — return to top form.",
            confidence=0.7,
            confidence_label="medium",
            evidence=[
                AchievementEvidence(
                    source_type="pb_cache",
                    source_name=history.source_name() or "PB lookup",
                    statement=f"Last comparable time was {_sec_to_str(prior_times[0][1])} on {last_fast_date}",
                    source_url=history.source_url(),
                    fetched_at=history.retrieved_at(),
                    confidence="medium",
                ),
            ],
            raw_facts={
                "time_sec": time_sec,
                "time_str": time_str,
                "last_comparable_date": last_fast_date,
                "year": year,
            },
            uncertainty_notes=["Depends on completeness of historical time data in cache"],
            detector_name=self.name,
        )]

    def _no_fire_reason(self, swim, ctx, history, all_results=None, extra=None) -> str:
        times = history.times_in_event(swim.distance, swim.stroke, swim.course)
        if len(times) < 2:
            return "insufficient history (< 2 times in event)"
        return "current time not fastest in history, or no prior comparable time found"


class BiggestDropDetector(AchievementDetector):
    """
    Meet-level detector: single swim with largest % improvement over prior PB.
    Only ONE fires per meet (meet-level achievement).

    The actual selection is done in report.py; this detector
    flags each swim's improvement for consideration.
    """
    name = "biggest_drop"

    def detect(self, swim, ctx, history, all_results=None, extra=None) -> list[Achievement]:
        if getattr(swim, "dq", False) or getattr(swim, "finals_time_cs", None) is None:
            return []

        prior = history.best_time_in_event(swim.distance, swim.stroke, swim.course)
        if prior is None or prior <= 0:
            return []

        time_sec = swim.finals_time_cs / 100.0
        if time_sec >= prior:
            return []

        drop_pct = 100.0 * (prior - time_sec) / prior
        # Only consider meaningful drops (>= 0.5%)
        if drop_pct < 0.5:
            return []

        # Mark this swim as a biggest-drop candidate; report.py selects the winner
        evt = _event_label(swim)
        swimmer_name = (extra or {}).get("swimmer_name", history.swimmer_name)
        time_str = _cs_to_str(swim.finals_time_cs)
        prior_str = _sec_to_str(prior)
        drop_sec = prior - time_sec

        return [Achievement(
            type="biggest_drop_candidate",
            swim_id=_swim_id(swim, "biggest_drop"),
            swimmer_id=swim.swimmer_key,
            swimmer_name=swimmer_name,
            event=evt,
            headline=f"{swimmer_name} biggest drop candidate: -{drop_sec:.2f}s ({drop_pct:.1f}%) in {evt}: {time_str}",
            angle_hint=f"Dropped {drop_pct:.1f}% from {prior_str} to {time_str} in {evt}.",
            confidence=0.85,
            confidence_label="high",
            evidence=[
                AchievementEvidence(
                    source_type="pb_cache",
                    source_name=history.source_name() or "PB lookup",
                    statement=f"Prior best: {prior_str}. New time: {time_str}. Drop: {drop_sec:.2f}s",
                    source_url=history.source_url(),
                    fetched_at=history.retrieved_at(),
                    confidence="high",
                ),
            ],
            raw_facts={
                "time_sec": time_sec,
                "time_str": time_str,
                "prior_pb_sec": prior,
                "prior_pb_str": prior_str,
                "drop_seconds": round(drop_sec, 3),
                "drop_pct": round(drop_pct, 2),
            },
            detector_name=self.name,
        )]

    def _no_fire_reason(self, swim, ctx, history, all_results=None, extra=None) -> str:
        prior = history.best_time_in_event(swim.distance, swim.stroke, swim.course)
        if prior is None:
            return "no prior PB data"
        time_sec = getattr(swim, "finals_time_cs", 0) / 100.0
        if time_sec >= prior:
            return "not a PB"
        drop_pct = 100.0 * (prior - time_sec) / prior
        if drop_pct < 0.5:
            return f"improvement {drop_pct:.2f}% < 0.5% threshold"
        return "did not fire"


class MultiPBWeekendDetector(AchievementDetector):
    """
    Per swimmer: fires if the swimmer has >= 3 confirmed PBs in this meet.
    This is a per-swimmer aggregated achievement.

    Because it's aggregated, it runs as a pseudo-swim against a sentinel
    swim, but actually needs extra['pb_count_for_swimmer'] to be set.
    The report builder sets this after running pb detectors.
    """
    name = "multi_pb_weekend"

    def detect(self, swim, ctx, history, all_results=None, extra=None) -> list[Achievement]:
        extra = extra or {}
        pb_count = extra.get("pb_count_for_swimmer", 0)

        if pb_count < 3:
            return []

        swimmer_name = extra.get("swimmer_name", history.swimmer_name)
        swimmer_key = swim.swimmer_key
        events = extra.get("pb_events", [])

        events_str = ", ".join(events[:5])

        return [Achievement(
            type="multi_pb_weekend",
            swim_id=f"{swimmer_key}:multi_pb",
            swimmer_id=swimmer_key,
            swimmer_name=swimmer_name,
            event="multiple events",
            headline=f"{swimmer_name} sets {pb_count} PBs in one meet ({events_str})",
            angle_hint=f"Outstanding meet: {pb_count} personal bests across {events_str}.",
            confidence=0.9,
            confidence_label="high",
            evidence=[
                AchievementEvidence(
                    source_type="results_file",
                    source_name="Meet results",
                    statement=f"{pb_count} confirmed/likely PBs in this meet: {events_str}",
                    confidence="high",
                ),
            ],
            raw_facts={
                "pb_count": pb_count,
                "events": events,
            },
            detector_name=self.name,
        )]

    def _no_fire_reason(self, swim, ctx, history, all_results=None, extra=None) -> str:
        pb_count = (extra or {}).get("pb_count_for_swimmer", 0)
        return f"only {pb_count} PB(s) in this meet — requires >=3"
