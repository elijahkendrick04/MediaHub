"""
QualifyingTimeDetector — uses the existing quals_registry plus research data.

Fires when a swim meets or beats a qualifying standard.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from swim_content_v5.schema import Achievement, AchievementEvidence
from .base import AchievementDetector


def _swim_id(swim, suffix: str = "") -> str:
    key = getattr(swim, "swimmer_key", "")
    dist = getattr(swim, "distance", 0)
    stroke = getattr(swim, "stroke", "")
    course = getattr(swim, "course", "")
    return f"{key}:{dist}{stroke}{course}:qual{suffix}"


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


def _parse_iso(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None


class QualifyingTimeDetector(AchievementDetector):
    """
    Uses swim_content.quals_registry to detect qualifying time hits.
    Extra parameter should include 'standards' and 'club_code'.
    """
    name = "qualifying_time"

    def detect(self, swim, ctx, history, all_results=None, extra=None) -> list[Achievement]:
        if getattr(swim, "dq", False) or getattr(swim, "finals_time_cs", None) is None:
            return []

        extra = extra or {}
        standards = extra.get("standards", [])
        if not standards:
            return []

        time_sec = swim.finals_time_cs / 100.0
        swim_date = _parse_iso(getattr(swim, "swim_date", None))
        if swim_date is None:
            # Try to use meet start date from context
            swim_date = _parse_iso(ctx.start_date)
        if swim_date is None:
            return []

        club_code = extra.get("club_code", "")

        try:
            from swim_content.quals_registry import check_swim_against_standards
            hits = check_swim_against_standards(
                standards=standards,
                distance=swim.distance,
                stroke=swim.stroke,
                gender=getattr(swim, "gender", ""),
                course=swim.course,
                swim_time_sec=time_sec,
                swim_date=swim_date,
                club_code=club_code,
            )
        except Exception:
            return []

        if not hits:
            return []

        evt = _event_label(swim)
        swimmer_name = extra.get("swimmer_name", history.swimmer_name)
        time_str = _cs_to_str(swim.finals_time_cs)
        results: list[Achievement] = []

        for h in hits:
            competition = getattr(h, "competition", "")
            body = getattr(h, "body", "")
            level = getattr(h, "level", "open")
            threshold_str = getattr(h, "threshold_str", "")
            margin_sec = getattr(h, "margin_sec", 0.0)
            in_window = getattr(h, "in_window", True)
            source_url = getattr(h, "source_url", None)
            retrieved_at = getattr(h, "retrieved_at", None)

            in_window_note = "" if in_window else " (outside qualification window)"
            confidence = 0.9 if in_window else 0.6
            confidence_label = "high" if in_window else "medium"
            uncertainty = [] if in_window else ["This qualifying time hit is outside the qualification window"]

            qual_type = "qual_hit_in_window" if in_window else "qual_hit_out_of_window"

            headline = (
                f"{swimmer_name} hits {competition} qualifying standard in {evt}: "
                f"{time_str} (standard: {threshold_str}{in_window_note})"
            )

            results.append(Achievement(
                type=qual_type,
                swim_id=_swim_id(swim, f":{level}"),
                swimmer_id=swim.swimmer_key,
                swimmer_name=swimmer_name,
                event=evt,
                headline=headline,
                angle_hint=f"Hit {competition} ({level}) qualifying standard with {time_str}. "
                           f"Required: {threshold_str}. Margin: {margin_sec:.2f}s under.",
                confidence=confidence,
                confidence_label=confidence_label,
                evidence=[
                    AchievementEvidence(
                        source_type="registry",
                        source_name=f"{body} qualifying standards",
                        statement=f"{competition} {level} standard is {threshold_str} for {evt}",
                        source_url=source_url,
                        fetched_at=retrieved_at,
                        confidence="high",
                    ),
                    AchievementEvidence(
                        source_type="results_file",
                        source_name="Meet results",
                        statement=f"Swam {time_str} — {margin_sec:.2f}s under the {threshold_str} standard",
                        confidence="high",
                    ),
                ],
                raw_facts={
                    "time_sec": time_sec,
                    "time_str": time_str,
                    "competition": competition,
                    "body": body,
                    "level": level,
                    "threshold_str": threshold_str,
                    "margin_sec": margin_sec,
                    "in_window": in_window,
                },
                uncertainty_notes=uncertainty,
                detector_name=self.name,
            ))

        return results

    def _no_fire_reason(self, swim, ctx, history, all_results=None, extra=None) -> str:
        extra = extra or {}
        standards = extra.get("standards", [])
        if not standards:
            return "no qualifying standards loaded"
        swim_date = _parse_iso(getattr(swim, "swim_date", None))
        if swim_date is None:
            return "no swim date — cannot check qualification window"
        return "time did not meet any qualifying standard"
