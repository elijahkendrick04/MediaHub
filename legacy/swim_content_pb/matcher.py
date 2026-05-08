"""
swim_content_pb/matcher.py
Safe swim-vs-PB comparator.

Returns PBDecision with a complete audit trail for every step.

V7.3: Added Rule 0 — CONFIRMED_OFFICIAL_PB when the snapshot's listed PB
matches this swim by time (within 0.005s) and date (exact or within 1 day).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from .history import build_previous_pb
from .schema import IdentityMatch, ParsedSnapshot, PBDecision, PreviousPB

# Tolerance for "equal time" comparison (within 0.005 s -> matched PB)
_EQUALITY_TOLERANCE = 0.005


def _fmt_time(seconds: float) -> str:
    """Format seconds as mm:ss.cc or ss.cc."""
    cs = round(seconds * 100)
    mins = cs // 6000
    rem = cs - mins * 6000
    secs = rem // 100
    frac = rem % 100
    if mins:
        return f"{mins}:{secs:02d}.{frac:02d}"
    return f"{secs}.{frac:02d}"


def _date_within_days(date_a: str, date_b: str, n: int) -> bool:
    """Return True if date_a and date_b are within n days of each other."""
    try:
        da = date.fromisoformat(date_a)
        db = date.fromisoformat(date_b)
        return abs((da - db).days) <= n
    except Exception:
        return False


def _entries_for(snapshot: ParsedSnapshot, event_distance: int, event_stroke: str, course: str) -> list:
    """Return snapshot entries matching the event/course."""
    # Stroke matching: SR uses long-form ('free', 'back', 'breast', 'fly', 'im')
    # while HY3 uses short codes ('FR', 'BK', 'BR', 'FL', 'IM').
    # Normalise both to lower-case for comparison.
    _STROKE_NORM = {
        "FR": "free", "BK": "back", "BR": "breast", "FL": "fly", "IM": "im",
        "free": "free", "back": "back", "breast": "breast", "fly": "fly", "im": "im",
        "freestyle": "free", "backstroke": "back", "breaststroke": "breast",
        "butterfly": "fly", "individual medley": "im",
    }
    target_stroke = _STROKE_NORM.get(event_stroke.upper(), event_stroke.lower())
    target_stroke_short = _STROKE_NORM.get(event_stroke, event_stroke.lower())

    results = []
    for entry in (snapshot.entries or []):
        e_dist = getattr(entry, "distance", None)
        e_stroke_raw = getattr(entry, "stroke", "") or ""
        e_course = getattr(entry, "course", "") or ""
        e_time = getattr(entry, "time_seconds", 0)

        e_stroke = _STROKE_NORM.get(e_stroke_raw.upper(), _STROKE_NORM.get(e_stroke_raw, e_stroke_raw.lower()))

        if (e_dist == event_distance
                and (e_stroke == target_stroke or e_stroke == target_stroke_short)
                and e_course == course
                and e_time > 0):
            results.append(entry)
    return results


def decide_pb(
    *,
    swim_id: str,
    swimmer_asa_id: Optional[str],
    swimmer_name: str,
    event_distance: int,
    event_stroke: str,
    course: str,
    current_time_seconds: float,
    current_time_display: str,
    identity: IdentityMatch,
    snapshot: Optional[ParsedSnapshot],
    meet_name: Optional[str],
    meet_date_iso: Optional[str],
    venue: Optional[str],
) -> PBDecision:
    """The single comparator. Returns PBDecision with full audit trail.

    Decision tree:
    - Rule 0 (NEW V7.3): if snapshot has an entry for this event AND that
      entry's time matches current swim (within 0.005s) AND date matches
      the meet date (exact or within 1 day) -> CONFIRMED_OFFICIAL_PB
    - identity.safe_to_use is False -> SUPPRESSED_NEEDS_VERIFICATION
    - snapshot is None or not fetch_ok -> PB_UNVERIFIED
    - previous_pb is None (no historical data for event) -> PB_UNVERIFIED
    - current_time < previous_pb.time_seconds -> CONFIRMED_PB with delta
    - current_time == previous_pb.time_seconds (within 0.005s) -> CONFIRMED_PB (matched PB)
    - current_time > previous_pb.time_seconds -> NOT_PB with delta
    - Edge case: snapshot's listed PB is from this meet but we excluded it -> LIKELY_PB
    """
    trail: list[str] = []
    event_label = f"{event_distance}m {event_stroke} ({course})"

    trail.append(f"swim_id={swim_id}")
    trail.append(f"swimmer={swimmer_name} (ASA={swimmer_asa_id})")
    trail.append(f"event={event_label}")
    trail.append(f"current_time={current_time_display} ({current_time_seconds:.2f}s)")
    trail.append(f"identity.method={identity.method}, safe_to_use={identity.safe_to_use}")

    # -----------------------------------------------------------------------
    # Rule 0 (V7.3 — highest precedence): CONFIRMED_OFFICIAL_PB
    # If snapshot exists AND has an entry for this event AND that entry's
    # time matches our current swim time (within 0.005s) AND that entry's
    # date matches the meet date (or is within 1 day) -> this swim IS the
    # swimmer's official all-time PB on swimmingresults.org.
    # -----------------------------------------------------------------------
    if (identity.safe_to_use
            and snapshot is not None
            and snapshot.fetch_ok
            and meet_date_iso):
        matching_entries = _entries_for(snapshot, event_distance, event_stroke, course)
        for entry in matching_entries:
            entry_time = getattr(entry, "time_seconds", None)
            entry_date = getattr(entry, "date_iso", None)
            entry_meet = getattr(entry, "meet_name", None)
            if entry_time is None:
                continue
            if abs(entry_time - current_time_seconds) <= _EQUALITY_TOLERANCE:
                # Time matches — now check date
                date_matches = False
                if entry_date:
                    if entry_date == meet_date_iso:
                        date_matches = True
                    elif _date_within_days(entry_date, meet_date_iso, 1):
                        date_matches = True
                if date_matches:
                    trail.append(
                        f"Rule 0: snapshot entry time={_fmt_time(entry_time)} "
                        f"matches current={_fmt_time(current_time_seconds)} "
                        f"(delta={abs(entry_time - current_time_seconds):.4f}s <= {_EQUALITY_TOLERANCE}s)"
                    )
                    trail.append(
                        f"Rule 0: entry date={entry_date} matches meet date={meet_date_iso}"
                    )
                    trail.append("DECISION: CONFIRMED_OFFICIAL_PB")
                    evidence = [{
                        "source": "swimmingresults.org",
                        "url": snapshot.source_url,
                        "fetched_at": snapshot.fetched_at,
                        "entry_time": _fmt_time(entry_time),
                        "entry_date": entry_date,
                        "entry_meet": entry_meet or "",
                        "note": (
                            "Time matches swimmingresults.org all-time PB and "
                            "PB date matches the meet. This swim is the swimmer's official PB."
                        ),
                    }]
                    return PBDecision(
                        status="CONFIRMED_OFFICIAL_PB",
                        swim_id=swim_id,
                        swimmer_asa_id=swimmer_asa_id,
                        swimmer_name=swimmer_name,
                        event=event_label,
                        course=course,
                        current_time_seconds=current_time_seconds,
                        current_time_display=current_time_display,
                        previous_pb=None,
                        delta_seconds=None,
                        improvement_percentage=None,
                        same_meet_excluded_count=0,
                        reason=(
                            f"Time matches swimmingresults.org all-time PB and "
                            f"PB date matches the meet. This swim is the swimmer's official PB."
                        ),
                        evidence=evidence,
                        safe_to_post=True,
                        confidence="high",
                        uncertainty_notes=[],
                        audit_trail=trail,
                    )

    # -----------------------------------------------------------------------
    # Guard: identity not safe
    # -----------------------------------------------------------------------
    if not identity.safe_to_use:
        trail.append("DECISION: SUPPRESSED_NEEDS_VERIFICATION — identity not verified")
        return PBDecision(
            status="SUPPRESSED_NEEDS_VERIFICATION",
            swim_id=swim_id,
            swimmer_asa_id=swimmer_asa_id,
            swimmer_name=swimmer_name,
            event=event_label,
            course=course,
            current_time_seconds=current_time_seconds,
            current_time_display=current_time_display,
            previous_pb=None,
            delta_seconds=None,
            improvement_percentage=None,
            same_meet_excluded_count=0,
            reason=f"Identity not verified: {identity.method}. " + "; ".join(identity.notes),
            evidence=[],
            safe_to_post=False,
            confidence="low",
            uncertainty_notes=[f"Swimmer identity needs verification ({identity.method})"],
            audit_trail=trail,
        )

    # -----------------------------------------------------------------------
    # Guard: no snapshot / fetch failed
    # -----------------------------------------------------------------------
    if snapshot is None or not snapshot.fetch_ok:
        error = ""
        if snapshot and snapshot.error:
            error = f" ({snapshot.error})"
        trail.append(f"Snapshot unavailable{error}")
        trail.append("DECISION: PB_UNVERIFIED — no usable PB data")
        return PBDecision(
            status="PB_UNVERIFIED",
            swim_id=swim_id,
            swimmer_asa_id=swimmer_asa_id,
            swimmer_name=swimmer_name,
            event=event_label,
            course=course,
            current_time_seconds=current_time_seconds,
            current_time_display=current_time_display,
            previous_pb=None,
            delta_seconds=None,
            improvement_percentage=None,
            same_meet_excluded_count=0,
            reason=f"No PB snapshot available{error}",
            evidence=[],
            safe_to_post=False,
            confidence="low",
            uncertainty_notes=[f"PB data fetch failed or unavailable{error}"],
            audit_trail=trail,
        )

    trail.append(f"Snapshot OK: {len(snapshot.entries)} entries, fetched at {snapshot.fetched_at}")
    trail.append(f"Building PreviousPB for event {event_label}, meet='{meet_name}', date={meet_date_iso}")

    # -----------------------------------------------------------------------
    # Build previous PB (excluding same-meet swims)
    # -----------------------------------------------------------------------
    previous_pb = build_previous_pb(
        snapshot=snapshot,
        swimmer_asa_id=swimmer_asa_id or "",
        swimmer_name=swimmer_name,
        event_distance=event_distance,
        event_stroke=event_stroke,
        course=course,
        meet_name=meet_name,
        meet_date_iso=meet_date_iso,
        venue=venue,
    )

    excluded_count = len(previous_pb.excluded_swims) if previous_pb else 0

    # Check if ALL matching entries were excluded (all from this meet)
    all_matching = [
        e for e in snapshot.entries
        if (e.distance == event_distance
            and e.course == course
            and getattr(e, "time_seconds", 0) > 0)
    ]
    all_excluded = len(all_matching) > 0 and previous_pb is None

    if all_excluded:
        trail.append(f"All {len(all_matching)} matching entry/entries were excluded as same-meet.")
        trail.append("DECISION: LIKELY_PB — all historical data is from this meet")
        evidence = [{
            "source": "swimmingresults.org",
            "url": snapshot.source_url,
            "fetched_at": snapshot.fetched_at,
            "note": "All historical entries for this event are from this meet; prior history not visible.",
        }]
        return PBDecision(
            status="LIKELY_PB",
            swim_id=swim_id,
            swimmer_asa_id=swimmer_asa_id,
            swimmer_name=swimmer_name,
            event=event_label,
            course=course,
            current_time_seconds=current_time_seconds,
            current_time_display=current_time_display,
            previous_pb=None,
            delta_seconds=None,
            improvement_percentage=None,
            same_meet_excluded_count=excluded_count,
            reason="All SR history entries for this event are from this meet; likely a PB but can't confirm.",
            evidence=evidence,
            safe_to_post=False,
            confidence="medium",
            uncertainty_notes=["SR page has absorbed this meet's results; pre-meet history not available."],
            audit_trail=trail,
        )

    if previous_pb is None:
        trail.append("No historical entries found for this event/course after same-meet exclusion.")
        trail.append("DECISION: PB_UNVERIFIED — no prior time on file")
        return PBDecision(
            status="PB_UNVERIFIED",
            swim_id=swim_id,
            swimmer_asa_id=swimmer_asa_id,
            swimmer_name=swimmer_name,
            event=event_label,
            course=course,
            current_time_seconds=current_time_seconds,
            current_time_display=current_time_display,
            previous_pb=None,
            delta_seconds=None,
            improvement_percentage=None,
            same_meet_excluded_count=excluded_count,
            reason=f"No prior {course} time on file for this event.",
            evidence=[{"source": "swimmingresults.org", "url": snapshot.source_url,
                        "fetched_at": snapshot.fetched_at}],
            safe_to_post=False,
            confidence="low",
            uncertainty_notes=["No prior time available for this event/course."],
            audit_trail=trail,
        )

    trail.append(
        f"Previous PB: {previous_pb.time_display} ({previous_pb.time_seconds:.2f}s) "
        f"from {previous_pb.pb_date_iso or 'unknown date'}, "
        f"meet='{previous_pb.pb_meet_name}'"
    )
    if excluded_count:
        trail.append(f"{excluded_count} same-meet entry/entries excluded from PB derivation.")

    # -----------------------------------------------------------------------
    # Compare current time to previous PB
    # -----------------------------------------------------------------------
    delta = current_time_seconds - previous_pb.time_seconds  # negative = improvement

    evidence = [{
        "source": "swimmingresults.org",
        "url": snapshot.source_url,
        "fetched_at": snapshot.fetched_at,
        "previous_pb_time": previous_pb.time_display,
        "previous_pb_date": previous_pb.pb_date_iso,
        "previous_pb_meet": previous_pb.pb_meet_name,
    }]

    # Equal (within tolerance) — matched PB
    if abs(delta) <= _EQUALITY_TOLERANCE:
        trail.append(
            f"current={current_time_seconds:.3f}s vs previous={previous_pb.time_seconds:.3f}s "
            f"-> delta={delta:.3f}s (within tolerance {_EQUALITY_TOLERANCE}s) -> matched PB"
        )
        trail.append("DECISION: CONFIRMED_PB (matched PB — equalled previous best)")
        return PBDecision(
            status="CONFIRMED_PB",
            swim_id=swim_id,
            swimmer_asa_id=swimmer_asa_id,
            swimmer_name=swimmer_name,
            event=event_label,
            course=course,
            current_time_seconds=current_time_seconds,
            current_time_display=current_time_display,
            previous_pb=previous_pb,
            delta_seconds=delta,
            improvement_percentage=0.0,
            same_meet_excluded_count=excluded_count,
            reason=f"Matched previous PB of {previous_pb.time_display}.",
            evidence=evidence,
            safe_to_post=True,
            confidence="high",
            uncertainty_notes=[],
            audit_trail=trail,
        )

    # Faster — new PB
    if delta < -_EQUALITY_TOLERANCE:
        drop_pct = 100.0 * abs(delta) / previous_pb.time_seconds
        trail.append(
            f"current={current_time_seconds:.3f}s < previous={previous_pb.time_seconds:.3f}s "
            f"-> improvement of {abs(delta):.3f}s ({drop_pct:.2f}%)"
        )
        trail.append("DECISION: CONFIRMED_PB")
        return PBDecision(
            status="CONFIRMED_PB",
            swim_id=swim_id,
            swimmer_asa_id=swimmer_asa_id,
            swimmer_name=swimmer_name,
            event=event_label,
            course=course,
            current_time_seconds=current_time_seconds,
            current_time_display=current_time_display,
            previous_pb=previous_pb,
            delta_seconds=delta,
            improvement_percentage=round(drop_pct, 3),
            same_meet_excluded_count=excluded_count,
            reason=f"Improved on {previous_pb.time_display} by {abs(delta):.2f}s ({drop_pct:.2f}%).",
            evidence=evidence,
            safe_to_post=True,
            confidence="high",
            uncertainty_notes=[],
            audit_trail=trail,
        )

    # Slower — not a PB
    trail.append(
        f"current={current_time_seconds:.3f}s > previous={previous_pb.time_seconds:.3f}s "
        f"-> slower by {delta:.3f}s"
    )
    trail.append("DECISION: NOT_PB")
    return PBDecision(
        status="NOT_PB",
        swim_id=swim_id,
        swimmer_asa_id=swimmer_asa_id,
        swimmer_name=swimmer_name,
        event=event_label,
        course=course,
        current_time_seconds=current_time_seconds,
        current_time_display=current_time_display,
        previous_pb=previous_pb,
        delta_seconds=delta,
        improvement_percentage=None,
        same_meet_excluded_count=excluded_count,
        reason=f"Slower than previous PB of {previous_pb.time_display} by {delta:.2f}s.",
        evidence=evidence,
        safe_to_post=False,
        confidence="high",
        uncertainty_notes=[],
        audit_trail=trail,
    )
