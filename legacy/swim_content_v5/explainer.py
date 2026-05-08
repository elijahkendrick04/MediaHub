"""
build_swim_trace(swim, all_detector_outputs, ranker_decision) -> SwimTrace

For every swim, traces every detector that ran, what it returned,
why it fired or didn't, and what factors contributed to ranking.
"""
from __future__ import annotations

from typing import Optional

from .schema import DetectorTrace, Achievement

# Use extended SwimTrace from recognition if available, fallback to v5's own
try:
    from recognition.schema import SwimTrace
except Exception:
    from .schema import SwimTrace


def _cs_to_str(cs: Optional[int]) -> str:
    if cs is None:
        return "—"
    mins = cs // 6000
    rem = cs - mins * 6000
    secs = rem // 100
    frac = rem % 100
    if mins:
        return f"{mins}:{secs:02d}.{frac:02d}"
    return f"{secs}.{frac:02d}"


def _make_swim_id(swim, swimmer_name: str = "") -> str:
    key = getattr(swim, "swimmer_key", "")
    dist = getattr(swim, "distance", 0)
    stroke = getattr(swim, "stroke", "")
    course = getattr(swim, "course", "")
    rnd = getattr(swim, "round", "")
    return f"{key}:{dist}{stroke}{course}:{rnd}"


def _event_label(swim) -> str:
    from swim_content_v5.report import _event_label as _el
    return _el(swim)


def _summarise_no_achievements(traces: list[DetectorTrace]) -> str:
    """
    Produce a human-readable summary of why no achievements were generated,
    based on what the detectors returned.
    """
    fired_none = all(not t.fired for t in traces)
    if not fired_none:
        return "achievement detected"

    reasons: list[str] = []
    for t in traces:
        if t.ran and not t.fired and t.reason and t.reason not in (
            "no notable achievement detected", "did not fire"
        ):
            # Only add unique, informative reasons
            if t.reason not in reasons:
                reasons.append(f"{t.detector_name}: {t.reason}")

    if not reasons:
        return "no notable achievement detected by any detector"

    # Return top 3 most informative reasons
    return "; ".join(reasons[:3])


def build_swim_trace(
    swim,
    swimmer_name: str,
    detector_traces: list[DetectorTrace],
    achievement_count: int,
) -> SwimTrace:
    """Build a SwimTrace for one swim."""
    swim_id = _make_swim_id(swim, swimmer_name)
    evt = _event_label(swim)
    time_str = _cs_to_str(getattr(swim, "finals_time_cs", None))

    if achievement_count > 0:
        summary = f"{achievement_count} achievement(s) detected"
    else:
        summary = _summarise_no_achievements(detector_traces)

    # V7.3: categorise near-misses
    near_miss_cat = None
    if achievement_count == 0:
        near_miss_cat = _categorise_near_miss(detector_traces)

    return SwimTrace(
        swim_id=swim_id,
        swimmer_name=swimmer_name,
        event=evt,
        time_str=time_str,
        achievement_count=achievement_count,
        detector_traces=detector_traces,
        summary=summary,
        near_miss_category=near_miss_cat,
    )


def _categorise_near_miss(traces: list) -> str:
    """Categorise why no achievement was generated (for grouped near-miss UI)."""
    reasons_str = " ".join(
        (t.reason or "").lower() for t in traces if not t.fired
    )
    det_names = {t.detector_name for t in traces if not t.fired}

    # Priority checks
    if "suppressed_needs_verification" in reasons_str or "identity" in reasons_str:
        return "ambiguous_swimmer_match"
    if "almost" in reasons_str or "close" in reasons_str:
        return "almost_pb"
    if "no prior pb data" in reasons_str and "pb_cache" in reasons_str.lower():
        return "possible_pb_uncertain"
    if "no prior" in reasons_str or "no historical" in reasons_str:
        return "possible_pb_uncertain"
    if "barrier" in reasons_str and "first" in reasons_str:
        return "possible_barrier_no_history"
    if "relay" in " ".join(det_names):
        return "relay_mention_only"
    if "top_of_field" in " ".join(det_names) and "entrant" in reasons_str:
        return "good_placing_weak_field"
    if "outranked" in reasons_str or "not worthy" in reasons_str:
        return "lower_priority"
    return "lower_priority"
