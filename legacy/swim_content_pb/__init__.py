"""
swim_content_pb — V6 PB Accuracy & History Intelligence subsystem.

Top-level package, sibling to swim_content_v4/ and swim_content_v5/.
Importable by both. Lives at swim_content_pb/.

Main entry point: run_pb_subsystem()
"""
from __future__ import annotations

__version__ = "6.0.0"

# ---------------------------------------------------------------------------
# Public convenience re-exports
# ---------------------------------------------------------------------------
from .schema import (
    IdentityMatch,
    PreviousPB,
    PBDecision,
    PBAudit,
    RunPBAudit,
    ParsedSnapshot,
    FetchResult,
)
from .identity import canonicalise_name, match_swimmer
from .corrections import CorrectionsStore
from .cache import PBCache
from .fetcher import PBFetcher
from .parser import parse_pb_html
from .history import build_previous_pb
from .matcher import decide_pb
from .audit import run_audit_to_dict, aggregate_run_audit

import time
from datetime import datetime, timezone
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Stroke code mapping: V3 codes → V6 canonical long-form
# V3 detector uses FR, BK, BR, FL, IM  →  V6 uses free, back, breast, fly, im
# ---------------------------------------------------------------------------
_V3_TO_V6_STROKE = {
    "FR": "free",
    "BK": "back",
    "BR": "breast",
    "FL": "fly",
    "IM": "im",
}

_V6_TO_V3_STROKE = {v: k for k, v in _V3_TO_V6_STROKE.items()}


def _v3_stroke_to_v6(s: str) -> Optional[str]:
    return _V3_TO_V6_STROKE.get(s.upper())


# ---------------------------------------------------------------------------
# V3-compatible shim: wraps ParsedSnapshot with .pb_times API
# so that V5 SwimmerHistory can consume V6 data unchanged
# ---------------------------------------------------------------------------

class _V3PBEntryShim:
    """Minimal shim exposing V3 PBEntry interface for compare_to_pb() compatibility."""
    def __init__(self, time_sec: float, time_str: str, date_iso: Optional[str],
                 meet: str, venue: str):
        self.time_sec = time_sec
        self.time_str = time_str
        self.date_iso = date_iso
        self.meet = meet or ""
        self.venue = venue or ""


class _V3CompatSnapshot:
    """Wraps a V6 ParsedSnapshot and exposes the V3 SwimmerPBSnapshot interface.

    Exposes:
      - .by_event()  → dict["dist_STROKE_COURSE": _V3PBEntryShim]  (for compare_to_pb)
      - .pb_times    → dict["<dist><STROKE><COURSE>": list[dict]]   (for SwimmerHistory)
      - .fetch_ok    → bool
      - .error       → str | None
      - .tiref       → str
    """

    def __init__(self, v6_snapshot: ParsedSnapshot):
        self._snap = v6_snapshot
        self.fetch_ok = v6_snapshot.fetch_ok
        self.error = v6_snapshot.error
        self.tiref = v6_snapshot.asa_id
        self.name = v6_snapshot.swimmer_name
        self.source_url = v6_snapshot.source_url
        self.retrieved_at = v6_snapshot.fetched_at

        # Build pb_times index (V5 SwimmerHistory format)
        # Key: "<dist><V3stroke><course>" e.g. "100FRLC"
        self.pb_times: dict[str, list[dict]] = {}
        for entry in v6_snapshot.entries:
            v3_stroke = _V6_TO_V3_STROKE.get(entry.stroke, entry.stroke.upper())
            key = f"{entry.distance}{v3_stroke}{entry.course}"
            rec = {
                "time_sec": entry.time_seconds,
                "date_iso": entry.date_iso,
                "source_url": v6_snapshot.source_url,
                "retrieved_at": v6_snapshot.fetched_at,
                "meet_name": entry.meet_name,
                "venue": entry.venue,
            }
            self.pb_times.setdefault(key, []).append(rec)

        # Build _by_event index (V3 compare_to_pb format)
        # Key: "<dist>_<V3stroke>_<course>" e.g. "100_FR_LC"
        # Value: best (fastest) _V3PBEntryShim
        self._by_event: dict[str, _V3PBEntryShim] = {}
        for entry in v6_snapshot.entries:
            v3_stroke = _V6_TO_V3_STROKE.get(entry.stroke, entry.stroke.upper())
            key = f"{entry.distance}_{v3_stroke}_{entry.course}"
            existing = self._by_event.get(key)
            if existing is None or entry.time_seconds < existing.time_sec:
                self._by_event[key] = _V3PBEntryShim(
                    time_sec=entry.time_seconds,
                    time_str=entry.time_str,
                    date_iso=entry.date_iso,
                    meet=entry.meet_name or "",
                    venue=entry.venue or "",
                )

    def by_event(self) -> dict:
        """V3 API: dict keyed by 'dist_STROKE_COURSE' with best PBEntry per event."""
        return self._by_event

    # Sort each event's entries fastest-first (V5 expects this)
    def sorted_pb_times(self) -> dict:
        return {
            k: sorted(v, key=lambda x: x.get("time_sec", 9999))
            for k, v in self.pb_times.items()
        }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_pb_subsystem(
    *,
    run_id: str,
    meet,                           # canonical Meet from V4
    our_swimmers: list,             # list of V3 ParsedSwim objects (have .asa_id, .name, etc.)
    use_cache: bool = True,
    progress_cb: Optional[Callable[[str], None]] = None,
    total_budget_sec: float = 90.0,
    max_workers: int = 3,
) -> RunPBAudit:
    """Main entry point for the V6 PB subsystem.

    Handles: identity matching, fetching, parsing, history building,
    decision making, audit logging.

    Returns RunPBAudit for the UI plus snapshots dicts for the legacy v3 trust
    path (so existing code still works).

    Never raises — all errors are captured in the audit.
    """
    def _step(msg: str) -> None:
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    started_at = datetime.now(timezone.utc).isoformat()
    _step("V6 PB subsystem: starting")

    corrections = CorrectionsStore()
    cache = PBCache()
    fetcher = PBFetcher(
        max_workers=max_workers,
        total_budget_sec=total_budget_sec,
    )

    # -----------------------------------------------------------------------
    # 1. Collect unique ASA IDs from our swimmers
    # -----------------------------------------------------------------------
    # our_swimmers are V3 ParsedSwim objects (have .asa_id but no name fields).
    # Names must be looked up from the canonical Meet.swimmers dict which is
    # keyed by "asa:{asa_id}" and contains Swimmer objects with full name data.
    asa_to_name: dict[str, str] = {}
    asa_to_hy3name: dict[str, str] = {}

    # Build ASA-ID → canonical Swimmer map from meet (V4 canonical Meet)
    canonical_swimmers: dict[str, object] = {}
    meet_swimmers_dict = getattr(meet, "swimmers", {}) or {}
    for key, csw in meet_swimmers_dict.items():
        csw_asa = getattr(csw, "asa_id", None) or ""
        if csw_asa:
            canonical_swimmers[csw_asa] = csw

    for sw in our_swimmers:
        asa_id = getattr(sw, "asa_id", None) or ""
        if not asa_id:
            continue
        if asa_id in asa_to_name:
            continue  # already recorded from a previous swim by same swimmer

        # Prefer canonical Swimmer object (has first_name, last_name, full_name)
        csw = canonical_swimmers.get(asa_id)
        if csw is not None:
            first = getattr(csw, "first_name", "") or ""
            last = getattr(csw, "last_name", "") or ""
            full = getattr(csw, "full_name", "") or f"{first} {last}".strip()
        else:
            # Fallback: try V3 ParsedSwim fields (may be empty for hy3 adapter)
            first = getattr(sw, "first_name", "") or ""
            last = getattr(sw, "last_name", "") or ""
            full = f"{first} {last}".strip() or getattr(sw, "name", "") or ""

        name = full or asa_id
        asa_to_name[asa_id] = name

        # Build HY3-style "LASTNAME, FIRSTNAME" for canonicalisation
        if last:
            hy3_name = f"{last.upper()}, {first.upper()}".strip(", ")
        elif full:
            hy3_name = full.upper()
        else:
            hy3_name = asa_id
        asa_to_hy3name[asa_id] = hy3_name

    unique_asa_ids = list(asa_to_name.keys())
    _step(f"V6 PB subsystem: {len(unique_asa_ids)} unique ASA IDs to fetch")

    if not unique_asa_ids:
        # No swimmers with ASA IDs — return empty audit
        empty_audit = RunPBAudit(
            run_id=run_id,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc).isoformat(),
            warnings=["No swimmers with ASA IDs found."],
        )
        return empty_audit

    # -----------------------------------------------------------------------
    # 2. Fetch (concurrent, budgeted, circuit breaker)
    # -----------------------------------------------------------------------
    fetch_wall_start = time.monotonic()
    budget_exceeded = False

    fetch_progress = {"done": 0, "total": len(unique_asa_ids)}

    def _fetch_progress_cb(done, total, result):
        fetch_progress["done"] = done
        if done % 5 == 0 or done == total:
            ok = result.fetch_ok if result else False
            _step(
                f"V6 PB fetch: {done}/{total} "
                f"({'cache' if getattr(result, 'from_cache', False) else 'network'},"
                f" {'ok' if ok else 'failed'})"
            )

    try:
        fetch_results = fetcher.fetch_many(
            asa_ids=unique_asa_ids,
            cache=cache,
            progress_cb=_fetch_progress_cb,
        )
    except Exception as e:
        _step(f"V6 PB fetch error: {e}")
        fetch_results = {}
        budget_exceeded = True

    fetch_wall_end = time.monotonic()
    fetch_elapsed = fetch_wall_end - fetch_wall_start

    # Check if any were budget-skipped
    for fr in fetch_results.values():
        if getattr(fr, "source", "") == "skipped_budget":
            budget_exceeded = True
            break

    _step(f"V6 PB fetch complete: {fetch_elapsed:.1f}s")

    # -----------------------------------------------------------------------
    # 3. Derive meet context for same-meet dedup
    # -----------------------------------------------------------------------
    meet_name = getattr(meet, "name", None)
    meet_date_iso = getattr(meet, "date_iso", None) or getattr(meet, "date", None)
    if not meet_date_iso:
        # Try to get date from meet.start_date
        sd = getattr(meet, "start_date", None)
        if sd:
            if hasattr(sd, "isoformat"):
                meet_date_iso = sd.isoformat()
            else:
                meet_date_iso = str(sd)
    venue = getattr(meet, "venue", None) or getattr(meet, "host_venue", None)

    # -----------------------------------------------------------------------
    # 4. Per-swimmer: identity match + PB decisions per swim
    # -----------------------------------------------------------------------
    per_swimmer_audits: list[PBAudit] = []
    all_v6_decisions: list[PBDecision] = []
    # Build decisions_by_swim_id for RunPBAudit lookup
    decisions_by_swim_id: dict[str, PBDecision] = {}
    # Build snapshots_by_asa_id for legacy v3 compat
    snapshots_by_asa_id: dict[str, object] = {}

    # Group our_swimmers by asa_id for per-swimmer processing
    swims_by_asa: dict[str, list] = {}
    for sw in our_swimmers:
        asa_id = getattr(sw, "asa_id", None) or ""
        if asa_id:
            swims_by_asa.setdefault(asa_id, []).append(sw)

    for asa_id in unique_asa_ids:
        hy3_name = asa_to_hy3name.get(asa_id, asa_id)
        swimmer_name = asa_to_name.get(asa_id, asa_id)

        fetch_result = fetch_results.get(asa_id)
        snapshot = fetch_result.snapshot if fetch_result else None
        fetch_ok = bool(fetch_result and fetch_result.fetch_ok)
        fetch_error = fetch_result.error if fetch_result and not fetch_ok else None

        # Build V3-compatible shim (for legacy path)
        if snapshot and fetch_ok:
            v3_compat = _V3CompatSnapshot(snapshot)
            # Sort entries
            v3_compat.pb_times = v3_compat.sorted_pb_times()
            snapshots_by_asa_id[asa_id] = v3_compat

        # Identity match
        identity = match_swimmer(
            hy3_name=hy3_name,
            asa_id=asa_id,
            sr_snapshot=snapshot,
            corrections=corrections,
            run_id=run_id,
        )

        # PB decisions for this swimmer's swims
        decisions: list[PBDecision] = []
        swims = swims_by_asa.get(asa_id, [])

        for sw in swims:
            distance = getattr(sw, "distance", None)
            stroke_v3 = getattr(sw, "stroke", None) or ""
            course = getattr(sw, "course", None) or ""

            if distance is None or not stroke_v3 or not course:
                continue

            stroke_v6 = _v3_stroke_to_v6(stroke_v3)
            if not stroke_v6:
                continue

            finals_cs = getattr(sw, "finals_time_cs", None)
            if finals_cs is None:
                continue

            current_sec = finals_cs / 100.0
            current_display = _cs_to_str(finals_cs)

            # Build swim_id consistent with V5 pb.py _swim_id()
            swimmer_key = getattr(sw, "swimmer_key", asa_id) or asa_id
            rnd = getattr(sw, "round", "") or ""
            swim_id = f"{swimmer_key}:{distance}{stroke_v3}{course}:{rnd}:pb"

            decision = decide_pb(
                swim_id=swim_id,
                swimmer_asa_id=asa_id,
                swimmer_name=swimmer_name,
                event_distance=distance,
                event_stroke=stroke_v6,
                course=course,
                current_time_seconds=current_sec,
                current_time_display=current_display,
                identity=identity,
                snapshot=snapshot if fetch_ok else None,
                meet_name=meet_name,
                meet_date_iso=meet_date_iso,
                venue=venue,
            )
            decisions.append(decision)
            all_v6_decisions.append(decision)
            decisions_by_swim_id[swim_id] = decision

        # Also index by a v5-style swim_id (without the final :pb suffix)
        # so v5 detectors that use _swim_id(swim, ":pb") can find decisions
        for d in decisions:
            decisions_by_swim_id[d.swim_id] = d

        swimmer_audit = PBAudit(
            asa_id=asa_id,
            hy3_name=hy3_name,
            sr_name=snapshot.swimmer_name if snapshot else None,
            identity=identity,
            events_fetched=[
                f"{e.distance} {e.stroke} {e.course}"
                for e in (snapshot.entries if snapshot else [])
            ],
            pb_decisions=decisions,
            achievements_generated=[],  # filled by V5 detectors later
            achievements_suppressed=[],
            fetch_ok=fetch_ok,
            fetch_error=fetch_error,
            source_urls=[snapshot.source_url] if snapshot and snapshot.source_url else [],
            fetched_at=snapshot.fetched_at if snapshot else None,
        )
        per_swimmer_audits.append(swimmer_audit)

    # -----------------------------------------------------------------------
    # 5. Aggregate into RunPBAudit
    # -----------------------------------------------------------------------
    run_audit = aggregate_run_audit(
        run_id=run_id,
        per_swimmer=per_swimmer_audits,
        fetch_results=fetch_results,
        started_at=started_at,
        fetch_start_wall=fetch_wall_start,
        fetch_end_wall=fetch_wall_end,
        budget_exceeded=budget_exceeded,
    )
    run_audit.snapshots_by_asa_id = snapshots_by_asa_id
    run_audit.decisions_by_swim_id = decisions_by_swim_id

    _step(
        f"V6 PB subsystem complete: "
        f"{run_audit.swimmers_matched_verified} verified, "
        f"{run_audit.swimmers_needs_verification} needs verification, "
        f"{run_audit.pb_confirmed_count} confirmed PBs, "
        f"{run_audit.pb_decisions_count} total decisions"
    )
    return run_audit


def _cs_to_str(cs: int) -> str:
    """Format centiseconds as mm:ss.cc or ss.cc."""
    mins = cs // 6000
    rem = cs - mins * 6000
    secs = rem // 100
    frac = rem % 100
    if mins:
        return f"{mins}:{secs:02d}.{frac:02d}"
    return f"{secs}.{frac:02d}"
