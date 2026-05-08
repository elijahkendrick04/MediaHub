"""
ReturnToFormDetector — first event swim after >6 months, within 2% of historic best.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from swim_content_v5.schema import Achievement, AchievementEvidence
from .base import AchievementDetector


def _swim_id(swim, suffix: str = "") -> str:
    key = getattr(swim, "swimmer_key", "")
    dist = getattr(swim, "distance", 0)
    stroke = getattr(swim, "stroke", "")
    course = getattr(swim, "course", "")
    return f"{key}:{dist}{stroke}{course}:rtf{suffix}"


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


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None


SIX_MONTHS = timedelta(days=183)


class ReturnToFormDetector(AchievementDetector):
    """
    Fires when:
    1. The swimmer's last recorded swim in this event was >6 months ago.
    2. Current time is within 2% of their all-time best in this event.
    """
    name = "return_to_form"

    def detect(self, swim, ctx, history, all_results=None, extra=None) -> list[Achievement]:
        if getattr(swim, "dq", False) or getattr(swim, "finals_time_cs", None) is None:
            return []

        if not history.has_data:
            return []

        dist = swim.distance
        stroke = swim.stroke
        course = swim.course

        last_swim_str = history.last_swam_event(dist, stroke, course)
        if not last_swim_str:
            return []

        swim_date = _parse_date(getattr(swim, "swim_date", None) or ctx.start_date)
        last_swim_date = _parse_date(last_swim_str)

        if swim_date is None or last_swim_date is None:
            return []

        gap = swim_date - last_swim_date
        if gap < SIX_MONTHS:
            return []

        # Check if current time is within 2% of all-time best
        best = history.best_time_in_event(dist, stroke, course)
        if best is None or best <= 0:
            return []

        time_sec = swim.finals_time_cs / 100.0
        pct_off = 100.0 * (time_sec - best) / best

        if pct_off > 2.0:
            return []

        evt = _event_label(swim)
        swimmer_name = (extra or {}).get("swimmer_name", history.swimmer_name)
        time_str = _cs_to_str(swim.finals_time_cs)
        best_str = _sec_to_str(best)
        months_gap = gap.days // 30

        return [Achievement(
            type="return_to_form",
            swim_id=_swim_id(swim),
            swimmer_id=swim.swimmer_key,
            swimmer_name=swimmer_name,
            event=evt,
            headline=f"{swimmer_name} returns to {evt} after {months_gap} months: {time_str} (within 2% of best {best_str})",
            angle_hint=f"Back in the pool after {months_gap} months away from {evt}. "
                       f"Swam {time_str} — just {pct_off:.1f}% off their best of {best_str}.",
            confidence=0.7,
            confidence_label="medium",
            evidence=[
                AchievementEvidence(
                    source_type="pb_cache",
                    source_name=history.source_name() or "PB lookup",
                    statement=f"Last recorded swim in {evt}: {last_swim_str} ({months_gap} months ago). "
                              f"All-time best: {best_str}",
                    source_url=history.source_url(),
                    fetched_at=history.retrieved_at(),
                    confidence="medium",
                ),
            ],
            raw_facts={
                "time_sec": time_sec,
                "time_str": time_str,
                "all_time_best_sec": best,
                "all_time_best_str": best_str,
                "pct_off_best": round(pct_off, 2),
                "last_swim_date": last_swim_str,
                "gap_days": gap.days,
                "gap_months": months_gap,
            },
            uncertainty_notes=[
                "Gap based on pb_cache history completeness — may not capture all swims"
            ],
            detector_name=self.name,
        )]

    def _no_fire_reason(self, swim, ctx, history, all_results=None, extra=None) -> str:
        if not history.has_data:
            return "no history data available"

        last = history.last_swam_event(swim.distance, swim.stroke, swim.course)
        if not last:
            return "no prior swims in this event recorded"

        swim_date = _parse_date(getattr(swim, "swim_date", None) or ctx.start_date)
        last_date = _parse_date(last)
        if swim_date and last_date:
            gap = swim_date - last_date
            if gap < SIX_MONTHS:
                return f"last swam {gap.days} days ago — less than 6-month threshold"

        best = history.best_time_in_event(swim.distance, swim.stroke, swim.course)
        if best:
            time_sec = getattr(swim, "finals_time_cs", 0) / 100.0
            pct_off = 100.0 * (time_sec - best) / best
            if pct_off > 2.0:
                return f"time is {pct_off:.1f}% off best — exceeds 2% threshold"

        return "did not fire"
