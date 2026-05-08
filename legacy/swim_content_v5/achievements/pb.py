"""
PB detectors:
  - PBConfirmedDetector: prior PB exists and current time is faster
  - PBLikelyDetector: entry time > final time but no prior PB data
  - PBImprovementMagnitudeDetector: how big is the improvement?
"""
from __future__ import annotations

from typing import Optional

from swim_content_v5.schema import Achievement, AchievementEvidence
from .base import AchievementDetector


def _swim_id(swim, suffix: str = "") -> str:
    key = getattr(swim, "swimmer_key", "") or ""
    dist = getattr(swim, "distance", 0)
    stroke = getattr(swim, "stroke", "")
    course = getattr(swim, "course", "")
    rnd = getattr(swim, "round", "")
    return f"{key}:{dist}{stroke}{course}:{rnd}{suffix}"


def _event_label(swim) -> str:
    from swim_content_v5.report import _event_label as _el
    return _el(swim)


def _cs_to_sec(cs) -> float:
    return cs / 100.0 if cs is not None else 0.0


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


def _magnitude_bucket(pct: float) -> str:
    if pct > 5.0:
        return "huge"
    if pct > 2.0:
        return "big"
    if pct > 0.5:
        return "notable"
    return "tiny"


class PBConfirmedDetector(AchievementDetector):
    """Fires when prior PB exists and current time is faster. Confidence: high."""
    name = "pb_confirmed"

    def detect(self, swim, ctx, history, all_results=None, extra=None) -> list[Achievement]:
        if getattr(swim, "dq", False) or getattr(swim, "finals_time_cs", None) is None:
            return []

        time_sec = _cs_to_sec(swim.finals_time_cs)
        prior = history.best_time_in_event(swim.distance, swim.stroke, swim.course)
        if prior is None or prior <= 0:
            return []

        if time_sec >= prior:
            return []

        drop_sec = prior - time_sec
        drop_pct = 100.0 * drop_sec / prior
        time_str = _cs_to_str(swim.finals_time_cs)
        prior_str = _sec_to_str(prior)
        evt = _event_label(swim)
        swimmer_name = (extra or {}).get("swimmer_name", history.swimmer_name)

        evidence = [
            AchievementEvidence(
                source_type="results_file",
                source_name="Meet results",
                statement=f"Swam {time_str} in {evt}",
                confidence="high",
            ),
            AchievementEvidence(
                source_type="pb_cache",
                source_name=history.source_name() or "PB lookup",
                statement=f"Prior best was {prior_str}",
                source_url=history.source_url(),
                fetched_at=history.retrieved_at(),
                confidence="high",
            ),
        ]

        return [Achievement(
            type="pb_confirmed",
            swim_id=_swim_id(swim, ":pb"),
            swimmer_id=swim.swimmer_key,
            swimmer_name=swimmer_name,
            event=evt,
            headline=f"{swimmer_name} sets new PB: {time_str} in {evt} (was {prior_str}, -{drop_sec:.2f}s)",
            angle_hint=f"Personal best of {time_str}, dropping {drop_sec:.2f}s from previous best of {prior_str}.",
            confidence=0.95,
            confidence_label="high",
            evidence=evidence,
            raw_facts={
                "time_sec": time_sec,
                "time_str": time_str,
                "prior_pb_sec": prior,
                "prior_pb_str": prior_str,
                "drop_seconds": round(drop_sec, 3),
                "drop_pct": round(drop_pct, 2),
                "magnitude": _magnitude_bucket(drop_pct),
            },
            detector_name=self.name,
        )]

    def _no_fire_reason(self, swim, ctx, history, all_results=None, extra=None) -> str:
        if getattr(swim, "finals_time_cs", None) is None:
            return "no time recorded (DQ/NS)"
        prior = history.best_time_in_event(swim.distance, swim.stroke, swim.course)
        if prior is None:
            return "no prior PB data in cache"
        time_sec = _cs_to_sec(swim.finals_time_cs)
        if time_sec >= prior:
            return f"time {_sec_to_str(time_sec)} not faster than prior PB {_sec_to_str(prior)}"
        return "did not fire"


class PBLikelyDetector(AchievementDetector):
    """
    Fires when entry time > final time but no prior PB data.
    Confidence: medium. Adds uncertainty note.
    """
    name = "pb_likely"

    def detect(self, swim, ctx, history, all_results=None, extra=None) -> list[Achievement]:
        if getattr(swim, "dq", False) or getattr(swim, "finals_time_cs", None) is None:
            return []

        # Skip if we have confirmed PB data (PBConfirmedDetector handles it)
        if history.has_data and history.best_time_in_event(swim.distance, swim.stroke, swim.course) is not None:
            return []

        seed_cs = getattr(swim, "seed_time_cs", None)
        if not seed_cs or seed_cs <= 0:
            return []

        final_cs = swim.finals_time_cs
        if final_cs >= seed_cs:
            return []

        # Sanity check: improvement must be plausible (< 20%)
        drop_pct = 100.0 * (seed_cs - final_cs) / seed_cs
        if drop_pct > 20.0:
            return []

        time_str = _cs_to_str(final_cs)
        seed_str = _cs_to_str(seed_cs)
        drop_sec = (seed_cs - final_cs) / 100.0
        evt = _event_label(swim)
        swimmer_name = (extra or {}).get("swimmer_name", history.swimmer_name)

        return [Achievement(
            type="pb_likely",
            swim_id=_swim_id(swim, ":pb_likely"),
            swimmer_id=swim.swimmer_key,
            swimmer_name=swimmer_name,
            event=evt,
            headline=f"{swimmer_name} likely PB: {time_str} in {evt} (entry was {seed_str})",
            angle_hint=f"Likely personal best of {time_str}, beating entry time of {seed_str} by {drop_sec:.2f}s.",
            confidence=0.6,
            confidence_label="medium",
            evidence=[
                AchievementEvidence(
                    source_type="results_file",
                    source_name="Meet results",
                    statement=f"Final time {time_str} faster than entry time {seed_str}",
                    confidence="medium",
                ),
            ],
            raw_facts={
                "time_sec": final_cs / 100.0,
                "time_str": time_str,
                "seed_sec": seed_cs / 100.0,
                "seed_str": seed_str,
                "drop_seconds": round(drop_sec, 3),
                "drop_pct": round(drop_pct, 2),
            },
            uncertainty_notes=["no prior PB data available — comparison is against entry time only"],
            detector_name=self.name,
        )]

    def _no_fire_reason(self, swim, ctx, history, all_results=None, extra=None) -> str:
        if history.has_data and history.best_time_in_event(swim.distance, swim.stroke, swim.course) is not None:
            return "prior PB data exists — handled by pb_confirmed detector"
        seed_cs = getattr(swim, "seed_time_cs", None)
        if not seed_cs or seed_cs <= 0:
            return "no entry/seed time to compare against"
        final_cs = getattr(swim, "finals_time_cs", None)
        if final_cs is None:
            return "no final time (DQ/NS)"
        if final_cs >= seed_cs:
            return "did not beat entry time"
        return "did not fire"


class PBImprovementMagnitudeDetector(AchievementDetector):
    """
    Fires alongside PBConfirmed to produce a magnitude-based achievement.
    Only fires for notable (>0.5%) or bigger improvements.
    """
    name = "pb_magnitude"

    def detect(self, swim, ctx, history, all_results=None, extra=None) -> list[Achievement]:
        if getattr(swim, "dq", False) or getattr(swim, "finals_time_cs", None) is None:
            return []

        prior = history.best_time_in_event(swim.distance, swim.stroke, swim.course)
        if prior is None or prior <= 0:
            return []

        time_sec = _cs_to_sec(swim.finals_time_cs)
        if time_sec >= prior:
            return []

        drop_pct = 100.0 * (prior - time_sec) / prior
        bucket = _magnitude_bucket(drop_pct)

        # Only fire for notable/big/huge
        if bucket == "tiny":
            return []

        evt = _event_label(swim)
        swimmer_name = (extra or {}).get("swimmer_name", history.swimmer_name)
        drop_sec = prior - time_sec
        time_str = _cs_to_str(swim.finals_time_cs)
        prior_str = _sec_to_str(prior)

        label_map = {
            "notable": "notable improvement",
            "big": "big improvement",
            "huge": "huge improvement",
        }
        label = label_map.get(bucket, bucket)

        return [Achievement(
            type=f"pb_magnitude_{bucket}",
            swim_id=_swim_id(swim, f":mag_{bucket}"),
            swimmer_id=swim.swimmer_key,
            swimmer_name=swimmer_name,
            event=evt,
            headline=f"{swimmer_name} makes {label} in {evt}: {drop_sec:.2f}s ({drop_pct:.1f}%)",
            angle_hint=f"{drop_pct:.1f}% improvement from {prior_str} to {time_str} — a {bucket} drop.",
            confidence=0.9,
            confidence_label="high",
            evidence=[
                AchievementEvidence(
                    source_type="pb_cache",
                    source_name=history.source_name() or "PB lookup",
                    statement=f"Prior best: {prior_str}. New time: {time_str}. Drop: {drop_sec:.2f}s ({drop_pct:.1f}%)",
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
                "magnitude": bucket,
            },
            detector_name=self.name,
        )]

    def _no_fire_reason(self, swim, ctx, history, all_results=None, extra=None) -> str:
        prior = history.best_time_in_event(swim.distance, swim.stroke, swim.course)
        if prior is None:
            return "no prior PB data"
        time_sec = _cs_to_sec(getattr(swim, "finals_time_cs", None) or 0)
        if time_sec >= prior:
            return "not a PB"
        drop_pct = 100.0 * (prior - time_sec) / prior
        return f"improvement {drop_pct:.2f}% is below notable threshold (0.5%)"
