"""
swim_content_pb/audit.py
PBAudit dataclass helpers and audit logger utilities.

The PBAudit and RunPBAudit dataclasses live in schema.py.
This module provides:
  - to_dict() serialisers for JSON storage
  - from_dict() deserialisers for loading from stored runs
  - aggregate_run_audit() to build RunPBAudit from per-swimmer data
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .schema import (
    IdentityMatch, PBAudit, PBDecision, PreviousPB, RunPBAudit,
)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def identity_to_dict(im: IdentityMatch) -> dict:
    return {
        "asa_id": im.asa_id,
        "hy3_name": im.hy3_name,
        "sr_name": im.sr_name,
        "canonical_hy3_name": im.canonical_hy3_name,
        "canonical_sr_name": im.canonical_sr_name,
        "method": im.method,
        "confidence": im.confidence,
        "safe_to_use": im.safe_to_use,
        "notes": im.notes,
        "alternative_matches": im.alternative_matches,
    }


def previous_pb_to_dict(pb: Optional[PreviousPB]) -> Optional[dict]:
    if pb is None:
        return None
    return {
        "swimmer_asa_id": pb.swimmer_asa_id,
        "swimmer_name": pb.swimmer_name,
        "event_distance": pb.event_distance,
        "event_stroke": pb.event_stroke,
        "course": pb.course,
        "time_seconds": pb.time_seconds,
        "time_display": pb.time_display,
        "pb_date_iso": pb.pb_date_iso,
        "pb_meet_name": pb.pb_meet_name,
        "source_url": pb.source_url,
        "fetched_at": pb.fetched_at,
        "excluded_swims": pb.excluded_swims,
        "confidence": pb.confidence,
        "notes": pb.notes,
    }


def decision_to_dict(d: PBDecision) -> dict:
    return {
        "status": d.status,
        "swim_id": d.swim_id,
        "swimmer_asa_id": d.swimmer_asa_id,
        "swimmer_name": d.swimmer_name,
        "event": d.event,
        "course": d.course,
        "current_time_seconds": d.current_time_seconds,
        "current_time_display": d.current_time_display,
        "previous_pb": previous_pb_to_dict(d.previous_pb),
        "delta_seconds": d.delta_seconds,
        "improvement_percentage": d.improvement_percentage,
        "same_meet_excluded_count": d.same_meet_excluded_count,
        "reason": d.reason,
        "evidence": d.evidence,
        "safe_to_post": d.safe_to_post,
        "confidence": d.confidence,
        "uncertainty_notes": d.uncertainty_notes,
        "audit_trail": d.audit_trail,
    }


def swimmer_audit_to_dict(sa: PBAudit) -> dict:
    return {
        "asa_id": sa.asa_id,
        "hy3_name": sa.hy3_name,
        "sr_name": sa.sr_name,
        "identity": identity_to_dict(sa.identity) if sa.identity else None,
        "events_fetched": sa.events_fetched,
        "pb_decisions": [decision_to_dict(d) for d in sa.pb_decisions],
        "achievements_generated": sa.achievements_generated,
        "achievements_suppressed": sa.achievements_suppressed,
        "fetch_ok": sa.fetch_ok,
        "fetch_error": sa.fetch_error,
        "no_history": sa.no_history,
        "source_urls": sa.source_urls,
        "fetched_at": sa.fetched_at,
    }


def run_audit_to_dict(ra: RunPBAudit) -> dict:
    """Serialise a RunPBAudit for storage (excludes large snapshots dict)."""
    return {
        "run_id": ra.run_id,
        "swimmers_total": ra.swimmers_total,
        "swimmers_matched_verified": ra.swimmers_matched_verified,
        "swimmers_needs_verification": ra.swimmers_needs_verification,
        "swimmers_no_id": ra.swimmers_no_id,
        "swimmers_fetch_failed": ra.swimmers_fetch_failed,
        "swimmers_no_history": ra.swimmers_no_history,
        "pb_decisions_count": ra.pb_decisions_count,
        "pb_confirmed_count": ra.pb_confirmed_count,
        "pb_confirmed_official_count": ra.pb_confirmed_official_count,
        "pb_matched_count": ra.pb_matched_count,
        "pb_likely_count": ra.pb_likely_count,
        "pb_not_pb_count": ra.pb_not_pb_count,
        "pb_unverified_count": ra.pb_unverified_count,
        "pb_suppressed_count": ra.pb_suppressed_count,
        "pb_ambiguous_count": ra.pb_ambiguous_count,
        "fetch_total_seconds": ra.fetch_total_seconds,
        "fetch_budget_exceeded": ra.fetch_budget_exceeded,
        "cache_hits": ra.cache_hits,
        "cache_misses": ra.cache_misses,
        "per_swimmer": [swimmer_audit_to_dict(sa) for sa in ra.per_swimmer],
        "warnings": ra.warnings,
        "started_at": ra.started_at,
        "finished_at": ra.finished_at,
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_run_audit(
    run_id: str,
    per_swimmer: list[PBAudit],
    fetch_results: dict,
    started_at: str,
    fetch_start_wall: float,
    fetch_end_wall: float,
    budget_exceeded: bool,
) -> RunPBAudit:
    """Build a RunPBAudit from per-swimmer audit data."""
    now = datetime.now(timezone.utc).isoformat()

    total = len(per_swimmer)
    verified = sum(1 for sa in per_swimmer
                   if sa.identity and sa.identity.method == "asa_id_verified")
    needs_verif = sum(1 for sa in per_swimmer
                      if sa.identity and sa.identity.method == "needs_verification")
    no_id = sum(1 for sa in per_swimmer
                if sa.identity and sa.identity.method == "no_id")
    fetch_failed = sum(1 for sa in per_swimmer if not sa.fetch_ok)
    no_history = sum(1 for sa in per_swimmer
                     if sa.fetch_ok and getattr(sa, "no_history", False))

    cache_hits = sum(1 for fr in fetch_results.values() if getattr(fr, "from_cache", False))
    cache_misses = sum(1 for fr in fetch_results.values() if not getattr(fr, "from_cache", False))

    all_decisions: list[PBDecision] = []
    for sa in per_swimmer:
        all_decisions.extend(sa.pb_decisions)

    # V7.3: confirmed_official + confirmed_improvement both count as "confirmed PB"
    # for the user-facing summary on the audit page. Legacy 'CONFIRMED_PB' status
    # is also accepted for runs created before V7.3.
    confirmed_status_set = {
        "CONFIRMED_OFFICIAL_PB",     # V7.3: time + date match SR all-time PB
        "CONFIRMED_PB_IMPROVEMENT",  # V7.3: prior history proves improvement
        "CONFIRMED_PB",              # legacy, pre-V7.3
    }
    confirmed_official = sum(1 for d in all_decisions if d.status == "CONFIRMED_OFFICIAL_PB")
    confirmed = sum(1 for d in all_decisions if d.status in confirmed_status_set)
    matched_pb = sum(1 for d in all_decisions if d.status == "MATCHED_PB")
    likely = sum(1 for d in all_decisions if d.status == "LIKELY_PB")
    not_pb = sum(1 for d in all_decisions if d.status == "NOT_PB")
    unverified = sum(1 for d in all_decisions if d.status == "PB_UNVERIFIED")
    suppressed = sum(1 for d in all_decisions if d.status == "SUPPRESSED_NEEDS_VERIFICATION")
    ambiguous = sum(1 for d in all_decisions if d.status == "AMBIGUOUS")

    return RunPBAudit(
        run_id=run_id,
        swimmers_total=total,
        swimmers_matched_verified=verified,
        swimmers_needs_verification=needs_verif,
        swimmers_no_id=no_id,
        swimmers_fetch_failed=fetch_failed,
        swimmers_no_history=no_history,
        pb_decisions_count=len(all_decisions),
        pb_confirmed_count=confirmed,
        pb_confirmed_official_count=confirmed_official,
        pb_matched_count=matched_pb,
        pb_likely_count=likely,
        pb_not_pb_count=not_pb,
        pb_unverified_count=unverified,
        pb_suppressed_count=suppressed,
        pb_ambiguous_count=ambiguous,
        fetch_total_seconds=round(fetch_end_wall - fetch_start_wall, 2),
        fetch_budget_exceeded=budget_exceeded,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        per_swimmer=per_swimmer,
        warnings=[],
        started_at=started_at,
        finished_at=now,
    )
