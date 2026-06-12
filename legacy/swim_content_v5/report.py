"""
build_recognition_report_for_run(run: PipelineRunV4) -> dict

Top-level orchestrator for V5. Called from pipeline_v4.py.
Returns a dict (RecognitionReport.to_dict()) for storage and UI.

Also exports:
  - _event_label(swim) → str (used by detectors)
  - build_recognition_report_from_data(meet, our_swims, pb_snapshots, ...) → dict
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from .schema import (
    RecognitionReport, Achievement, QualityBand, PostType,
    AchievementEvidence,
)
from .context_profile import build_meet_context
from .history import SwimmerHistory, build_history_map
from .ranker import rank_achievements
from .recommender import recommend_post_type
from .explainer import build_swim_trace
from .achievements import get_all_detectors


def _normalise_meet_level(level: Optional[str]) -> Optional[str]:
    """
    Map context_engine's free-form meet level ("National Championships",
    "Level 2", "Open Meet", ...) to the V5 ranker's coarse buckets
    (national / university / regional / county / open).
    The mapping is heuristic and intentionally tolerant — the engine
    learns these labels at runtime from search results.
    """
    if not level:
        return None
    low = level.lower()
    if any(t in low for t in ("international", "world", "olympic", "european")):
        return "international"
    if any(t in low for t in ("national", "british", "level 1", "level 2")):
        return "national"
    if any(t in low for t in ("university", "varsity", "bucs")):
        return "university"
    if any(t in low for t in ("regional", "region")):
        return "regional"
    if any(t in low for t in ("county", "district")):
        return "county"
    return "open"

if TYPE_CHECKING:
    from swim_content_v4.pipeline_v4 import PipelineRunV4


# ---------------------------------------------------------------------------
# Helpers shared with detector modules
# ---------------------------------------------------------------------------

_STROKE_MAP = {
    "FR": "Freestyle", "BK": "Backstroke", "BR": "Breaststroke",
    "FL": "Butterfly", "IM": "Individual Medley", "MEDLEY": "Relay Medley",
}


def _event_label(swim) -> str:
    """Canonical event label from a RaceResult."""
    dist = getattr(swim, "distance", 0)
    stroke = getattr(swim, "stroke", "")
    course = getattr(swim, "course", "")
    stroke_name = _STROKE_MAP.get(stroke, stroke)
    return f"{dist}m {stroke_name} ({course})"


def _cs_to_str(cs: int) -> str:
    mins = cs // 6000
    rem = cs - mins * 6000
    secs = rem // 100
    frac = rem % 100
    if mins:
        return f"{mins}:{secs:02d}.{frac:02d}"
    return f"{secs}.{frac:02d}"


# ---------------------------------------------------------------------------
# Core detection runner
# ---------------------------------------------------------------------------

def _run_detectors_for_swim(
    swim,
    swimmer_name: str,
    ctx,
    history: SwimmerHistory,
    all_results: list,
    standards: list,
    club_code: str,
    detectors: list,
    extra_context: dict | None = None,
) -> tuple[list[Achievement], list]:
    """Run all detectors for one swim. Returns (achievements, detector_traces)."""
    extra = {
        "swimmer_name": swimmer_name,
        "standards": standards,
        "club_code": club_code,
    }
    # Phase W: workspace-scoped context (athlete milestones, club records,
    # swimmer gender/age metadata). Absent keys leave detectors silent.
    if extra_context:
        extra.update(extra_context)

    all_achievements: list[Achievement] = []
    detector_traces = []

    for detector in detectors:
        try:
            trace = detector.trace(swim, ctx, history, all_results=all_results, extra=extra)
            detector_traces.append(trace)
            if trace.fired:
                achs = detector.detect(swim, ctx, history, all_results=all_results, extra=extra)
                all_achievements.extend(achs)
        except Exception:
            from .schema import DetectorTrace
            detector_traces.append(_make_error_trace(detector.name))

    return all_achievements, detector_traces


def _make_error_trace(name: str):
    from .schema import DetectorTrace
    return DetectorTrace(
        detector_name=name,
        ran=False,
        fired=False,
        reason="detector raised an exception",
    )


# ---------------------------------------------------------------------------
# Post-processing: select biggest-drop winner + multi-PB aggregates
# ---------------------------------------------------------------------------

def _select_biggest_drop(all_achievements: list[Achievement]) -> list[Achievement]:
    """
    From all biggest_drop_candidate achievements, select only the single
    biggest one by drop_pct and relabel it as 'biggest_drop_of_meet'.
    Remove all candidates.
    """
    candidates = [a for a in all_achievements if a.type == "biggest_drop_candidate"]
    non_candidates = [a for a in all_achievements if a.type != "biggest_drop_candidate"]

    if not candidates:
        return non_candidates

    winner = max(candidates, key=lambda a: a.raw_facts.get("drop_pct", 0.0))
    winner.type = "biggest_drop_of_meet"
    winner.headline = winner.headline.replace("biggest drop candidate: -", "biggest drop of meet: -")

    return non_candidates + [winner]


def _add_multi_pb_achievements(
    all_achievements: list[Achievement],
    our_swims: list,
    history_map: dict[str, SwimmerHistory],
    ctx,
    detectors: list,
) -> list[Achievement]:
    """
    After detecting PBs per swim, check per-swimmer PB counts and fire
    MultiPBWeekendDetector if a swimmer hits >= 3.
    """
    # Count confirmed + likely PBs per swimmer
    pb_by_swimmer: dict[str, list[str]] = defaultdict(list)
    for a in all_achievements:
        if a.type in ("pb_confirmed", "pb_likely"):
            pb_by_swimmer[a.swimmer_id].append(a.event)

    from .achievements.standout_history import MultiPBWeekendDetector
    multi_detector = MultiPBWeekendDetector()

    extra_achievements: list[Achievement] = []
    for swimmer_id, events in pb_by_swimmer.items():
        if len(events) < 3:
            continue
        history = history_map.get(swimmer_id, SwimmerHistory(swimmer_id, swimmer_id))
        swimmer_name = history.swimmer_name or swimmer_id

        # Find a representative swim for this swimmer
        rep_swim = None
        for sw in our_swims:
            if getattr(sw, "swimmer_key", "") == swimmer_id:
                rep_swim = sw
                break

        if rep_swim is None:
            continue

        extra = {
            "swimmer_name": swimmer_name,
            "pb_count_for_swimmer": len(events),
            "pb_events": events,
        }
        achs = multi_detector.detect(rep_swim, ctx, history, extra=extra)
        extra_achievements.extend(achs)

    return all_achievements + extra_achievements


# ---------------------------------------------------------------------------
# Relay detection
# ---------------------------------------------------------------------------

def _detect_relay_achievements(
    our_relays: list,
    all_relays: list,
    ctx,
    detectors: list,
) -> list[Achievement]:
    """Run relay detectors using relay results."""
    from .achievements.relay import RelayMedalDetector, RelayStrongPerformanceDetector

    relay_detectors = [
        d for d in detectors
        if isinstance(d, (RelayMedalDetector, RelayStrongPerformanceDetector))
    ]
    if not relay_detectors or not our_relays:
        return []

    # Use a sentinel to pass relay results through extra
    extra = {
        "relay_results": our_relays,
        "all_relay_results": all_relays,
    }

    results: list[Achievement] = []
    from .schema import MeetContext
    dummy_history = SwimmerHistory("relay", "relay")

    # We run relay detectors once with the full list
    for detector in relay_detectors:
        try:
            if our_relays:
                dummy_swim = our_relays[0]
                achs = detector.detect(dummy_swim, ctx, dummy_history, all_results=all_relays, extra=extra)
                results.extend(achs)
        except Exception:
            pass

    return results


# ---------------------------------------------------------------------------
# Main entry point from pipeline_v4
# ---------------------------------------------------------------------------

def build_recognition_report_for_run(run: "PipelineRunV4") -> dict:
    """
    Called from pipeline_v4.py after all v4 stages complete.
    Builds a recognition report and returns it as a dict.
    """
    meet = getattr(run, "canonical_meet", None)
    if meet is None:
        return {"error": "no canonical_meet on run", "ok": False}

    # Gather what we need from the run
    profile_id = getattr(run, "profile_id", "")
    pb_snapshots = {}   # We don't have direct access here; use the v3 shim path

    # Try to get pb_snapshots from the run via private attribute (set in pipeline)
    pb_snapshots = getattr(run, "_pb_snapshots", {}) or {}

    # Get our swims from canonical meet using the profile
    try:
        from swim_content_v4.club_profile import load_profile
        profile = load_profile(profile_id) if profile_id else None
    except Exception:
        profile = None

    all_results = list(meet.results)
    # V7.5: pipeline_v4 already filtered to club_filter and stashed the
    # filtered results on the run via _our_results. Use that if present
    # so we honour the universal club picker even without a profile.
    pre_filtered = getattr(run, "_our_results", None)
    if pre_filtered is not None:
        our_results = list(pre_filtered)
    elif profile:
        our_results = [r for r in all_results if profile.is_ours(r.club_code, None)]
    else:
        our_results = all_results

    all_relays = list(meet.relays)
    our_relays = []
    pre_filtered_keys = getattr(run, "_our_swimmer_keys", None)
    if pre_filtered_keys is not None:
        our_relays = [r for r in all_relays if r.club_code and r.club_code in {sw.club_code for sw in meet.swimmers.values() if sw.swimmer_key in pre_filtered_keys}]
    elif profile:
        our_relays = [r for r in all_relays if profile.is_ours(r.club_code, None)]

    # Build meet context — V7.5 uses context_engine.identity for governing
    # body / level / host club discovery instead of a raw web search.
    research_data = None
    try:
        from context_engine.identity import discover_meet_identity
        meet_name = getattr(meet, "name", "") or ""
        venue = getattr(meet, "venue", "") or ""
        year = ""
        if getattr(meet, "start_date", None):
            year = str(meet.start_date)[:4]
        if meet_name:
            identity = discover_meet_identity(
                meet_name=meet_name,
                venue=venue,
                year=year or "",
            )
            sources = []
            for s in identity.sources or []:
                sources.append({
                    "url": s.url,
                    "name": s.title or s.domain,
                    "snippet": s.excerpt[:200] if s.excerpt else "",
                    "source_backend": s.domain,
                    "fetched_at": s.fetched_at,
                })
            research_data = {
                "ok": True,
                "sources": sources,
                "governing_body": identity.governing_body,
                "meet_level": _normalise_meet_level(identity.meet_level),
                "host_club": identity.host_club,
            }
    except Exception:
        # Research is purely additive — never block the pipeline
        research_data = None

    ctx = build_meet_context(meet, research_data=research_data)
    # V7: attach profile to ctx so the ranker can apply club priority weights
    if profile is not None:
        ctx.profile = profile

    # Build swimmer name lookup from canonical meet
    swimmer_names: dict[str, str] = {}
    for sk, sw in meet.swimmers.items():
        name = f"{getattr(sw, 'first_name', '')} {getattr(sw, 'last_name', '')}".strip()
        swimmer_names[sk] = name

    # Build history map from pb_snapshots
    history_map = _build_history_map_from_snapshots(our_results, pb_snapshots, swimmer_names)

    # Load standards and club code. W.4: season packs merge with quals.json
    # and the club's Organisation picks narrow which standards fire.
    standards: list = []
    club_code = ""
    try:
        from mediahub.standards import standards_for_profile

        standards = standards_for_profile(profile)
    except Exception:
        try:
            from swim_content.quals_registry import load_registry
            standards = load_registry()
        except Exception:
            pass
    if profile and profile.club_codes:
        club_code = profile.club_codes[0]

    # Get all detectors. The mediahub recognition_swim set leads with the
    # V7.3 OfficialPBDetector (fires when the lookup source already lists
    # this swim as the all-time PB — a case no V5 PB detector covers);
    # imported lazily so this module keeps working standalone.
    try:
        from mediahub.recognition_swim import production_detectors

        detectors = production_detectors()
    except ImportError:
        detectors = get_all_detectors()

    # Phase W detectors + context (athlete registry milestones, club records).
    # All optional enrichment: failure or absence leaves the V5 path untouched.
    extra_context: dict = {}
    try:
        from mediahub.recognition_swim.achievements.club_record import ClubRecordDetector
        from mediahub.recognition_swim.achievements.milestones import MilestoneDetector

        detectors = detectors + [MilestoneDetector(), ClubRecordDetector()]
    except Exception:
        pass
    if profile_id:
        try:
            from mediahub.athletes.registry import milestone_context

            am = milestone_context(profile_id, exclude_run_id=run.run_id)
            if am:
                extra_context["athlete_milestones"] = am
        except Exception:
            pass
        try:
            from mediahub.club_records.store import records_map

            cr = records_map(profile_id)
            if cr:
                extra_context["club_records"] = cr
        except Exception:
            pass
    # Swimmer gender/age metadata for record matching (from the canonical meet).
    swimmer_meta: dict = {}
    meet_year = None
    if getattr(meet, "start_date", None):
        try:
            meet_year = int(str(meet.start_date)[:4])
        except (TypeError, ValueError):
            meet_year = None
    for sk, sw in meet.swimmers.items():
        gender = (getattr(sw, "gender", "") or "").upper()[:1]
        yob = None
        dob = getattr(sw, "dob", None)
        if dob:
            try:
                yob = int(str(dob)[:4])
            except (TypeError, ValueError):
                yob = None
        age = (meet_year - yob) if (meet_year and yob) else None
        swimmer_meta[sk] = {"gender": gender, "yob": yob, "age": age}
    if swimmer_meta:
        extra_context["swimmer_meta"] = swimmer_meta

    # Run detectors
    all_achievements: list[Achievement] = []
    swim_traces = []

    for swim in our_results:
        if getattr(swim, "dq", False) or getattr(swim, "finals_time_cs", None) is None:
            continue

        swimmer_key = getattr(swim, "swimmer_key", "")
        swimmer_name = swimmer_names.get(swimmer_key, swimmer_key)
        history = history_map.get(swimmer_key, SwimmerHistory(swimmer_key, swimmer_name))

        achs, traces = _run_detectors_for_swim(
            swim=swim,
            swimmer_name=swimmer_name,
            ctx=ctx,
            history=history,
            all_results=all_results,
            standards=standards,
            club_code=club_code,
            detectors=detectors,
            extra_context=extra_context,
        )
        all_achievements.extend(achs)
        swim_trace = build_swim_trace(swim, swimmer_name, traces, len(achs))
        swim_traces.append(swim_trace)

    # Relay achievements
    relay_achs = _detect_relay_achievements(our_relays, all_relays, ctx, detectors)
    all_achievements.extend(relay_achs)

    # Post-processing
    all_achievements = _select_biggest_drop(all_achievements)
    all_achievements = _add_multi_pb_achievements(all_achievements, our_results, history_map, ctx, detectors)

    # Rank
    ranked = rank_achievements(all_achievements, ctx, history_map)

    # Recommend
    recommendations = recommend_post_type(ranked, ctx)

    # Collect all sources
    all_sources = _collect_sources(all_achievements, ctx)

    # Build counts by band
    n_elite = sum(1 for r in ranked if r.quality_band == QualityBand.ELITE)
    n_strong = sum(1 for r in ranked if r.quality_band == QualityBand.STRONG)
    n_story = sum(1 for r in ranked if r.quality_band == QualityBand.STORY)
    n_nice = sum(1 for r in ranked if r.quality_band == QualityBand.NICE)

    report = RecognitionReport(
        run_id=run.run_id,
        meet_name=meet.name,
        meet_context=ctx,
        ranked_achievements=ranked,
        recommendations=recommendations,
        swim_traces=swim_traces,
        n_swims_analysed=len(our_results),
        n_achievements=len(all_achievements),
        n_elite=n_elite,
        n_strong=n_strong,
        n_story=n_story,
        n_nice=n_nice,
        all_sources=all_sources,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    report_dict = report.to_dict()

    # V7.5: Apply learned voice captions to each ranked achievement.
    # Voices are loaded from data/voices/ + data/voices/seed/ — the set
    # is data, not code. Each achievement gets one rendered caption per
    # available voice, keyed by voice_id.
    try:
        from voice.learned.store import list_voices
        from voice.learned.render import render_caption
        _voices = list_voices()
        for ra_dict in report_dict.get("ranked_achievements", []):
            ach = ra_dict.get("achievement") or ra_dict
            achievement_payload = {
                "swimmer_first": (ach.get("swimmer_name", "") or "").split(" ")[0],
                "swimmer_last": " ".join((ach.get("swimmer_name", "") or "").split(" ")[1:]),
                "event": ach.get("event", ""),
                "time": ach.get("time", "") or ach.get("swim_time", ""),
                "pb": ach.get("prev_pb", ""),
                "club": ach.get("club", ""),
                "meet": meet.name,
                "place": ach.get("place", ""),
                "headline": ach.get("headline", ""),
            }
            voice_captions: dict[str, dict[str, str]] = {}
            for vp in _voices:
                try:
                    captions = render_caption(achievement_payload, vp, n_variants=1, seed=hash(ach.get("id", "")) & 0xFFFF)
                    text = captions[0] if captions else ""
                except Exception:
                    text = ""
                voice_captions[vp.voice_id] = {
                    "display_name": vp.display_name,
                    "caption": text,
                }
            ra_dict["voice_captions"] = voice_captions
    except Exception:
        pass  # voice captions are additive — failure is non-blocking

    # V7.3: attach weekend_in_numbers card
    try:
        from recognition.weekend_in_numbers import build_weekend_in_numbers as _bwin
        report_dict["weekend_in_numbers"] = _bwin(report_dict)
    except Exception:
        report_dict["weekend_in_numbers"] = None
    return report_dict


def _build_history_map_from_snapshots(
    our_results: list,
    pb_snapshots: dict,
    swimmer_names: dict[str, str],
) -> dict[str, SwimmerHistory]:
    """Build history map from canonical results + pb_snapshots dict."""
    history_map: dict[str, SwimmerHistory] = {}
    seen = set()

    for r in our_results:
        key = getattr(r, "swimmer_key", "")
        if not key or key in seen:
            continue
        seen.add(key)

        # pb_snapshots are keyed by asa_id, which equals swimmer_key for our swimmers
        snap = pb_snapshots.get(key)
        name = swimmer_names.get(key, key)
        history_map[key] = SwimmerHistory(key, name, snap)

    return history_map


def _collect_sources(achievements: list[Achievement], ctx) -> list[dict]:
    """Collect all unique research sources from achievements and meet context."""
    seen_urls: set[str] = set()
    sources: list[dict] = []

    for a in achievements:
        for ev in a.evidence:
            url = ev.source_url
            if url and url not in seen_urls:
                seen_urls.add(url)
                sources.append({
                    "url": url,
                    "name": ev.source_name,
                    "used_for": f"{a.swimmer_name}: {a.type}",
                    "fetched_at": ev.fetched_at,
                    "confidence": ev.confidence,
                })

    for src in ctx.research_sources:
        url = src.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            sources.append(src)

    return sources
