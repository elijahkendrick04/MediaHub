"""
V4 pipeline — V7.5 integrated orchestrator.

Input: raw uploaded file bytes + filename + (club_filter | profile_id).
Output: PipelineRunV4 with canonical Meet, V3 cards, self-check, recognition.

Steps:
  1. Interpret document (V7.5 interpreter package — format-agnostic).
  2. Bridge InterpretedMeet → canonical Meet.
  3. Resolve club filter (explicit string OR via profile.club_codes/display_name).
  4. Filter results to that club.
  5. Bridge to V3, run detector / grouper / captions / ranker / self-check.
  6. PB enrichment via pb_discovery (live source discovery, no hardcoded source).
  7. V5 recognition report (uses context_engine for meet identity).
  8. Trust report.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Callable

from swim_content.quals_registry import (
    load_registry,
    stale_standards,
    relevant_standards,
)
from swim_content.detector_v3 import detect_v3
from swim_content.grouper import group_claims_into_cards
from swim_content.evidence_aggregate import attach_evidence_from_claims
from swim_content.captions_v3 import write_captions
from swim_content.ranker_v3 import rank_cards
from swim_content.self_check import run_self_check
from swim_content.cards import ContentCard, CaptionVariants

from mediahub.interpreter import interpret_document

from mediahub.web.canonical import Meet
from .interpreter_bridge import (
    interpreted_to_canonical,
    extract_clubs_from_interpreted,
    filter_meet_by_club_name,
)
from mediahub.web.inference import infer_missing
from mediahub.web.club_profile import (
    ClubProfile,
    load_profile,
    detect_likely_profile,
    seed_default_profiles,
)
from mediahub.web.v3_shim import canonical_to_v3
from mediahub.web.trust import build_trust_report, TrustReport
from mediahub.web.club_discovery import record_clubs


# Lightweight DispatchLog stub kept for backwards compatibility with the
# existing trust report / web UI consumers that read attribute names.
@dataclass
class DispatchLog:
    chosen_adapter: Optional[str] = None
    chosen_filename: Optional[str] = None
    chosen_score: float = 0.0
    candidates: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "chosen_adapter": self.chosen_adapter,
            "chosen_filename": self.chosen_filename,
            "chosen_score": self.chosen_score,
            "candidates": list(self.candidates),
            "notes": list(self.notes),
        }


@dataclass
class PipelineRunV4:
    run_id: str
    started_at: str
    finished_at: str = ""
    progress_log: list[str] = field(default_factory=list)

    # Canonical input
    canonical_meet: Optional[Meet] = None
    dispatch_log: Optional[DispatchLog] = None
    profile_id: str = ""
    profile_display: str = ""
    club_filter: str = ""

    # Discovered clubs (used by the universal club picker)
    discovered_clubs: list[str] = field(default_factory=list)

    # Counts
    parsed_swim_count: int = 0
    our_swim_count: int = 0
    other_swim_count: int = 0
    n_swimmers_ours: int = 0

    # PB enrichment (legacy v3 counters)
    pb_fetch_ok: int = 0
    pb_fetch_failed: int = 0
    pb_fetch_errors: list[str] = field(default_factory=list)
    pb_audit: Optional[object] = None

    # V3 outputs
    detector_summary: dict = field(default_factory=dict)
    cards: list = field(default_factory=list)
    self_check: Optional[dict] = None
    standards_meta: dict = field(default_factory=dict)

    # Trust + warnings
    trust: Optional[TrustReport] = None
    parse_warnings: list[dict] = field(default_factory=list)

    # Ground truth + recognition
    ground_truth_report: Optional[dict] = None
    recognition_report: Optional[dict] = None
    recognition_error: Optional[str] = None

    error: Optional[str] = None


def _resolve_club_filter(
    *,
    explicit_club_filter: Optional[str],
    profile: Optional[ClubProfile],
) -> str:
    """
    Resolve the effective club filter string. Explicit wins; else fall
    back to the profile's display name. Returns empty string if neither
    available — caller is expected to surface a warning.
    """
    if explicit_club_filter and explicit_club_filter.strip():
        return explicit_club_filter.strip()
    if profile is not None:
        if profile.display_name:
            return profile.display_name
        if profile.club_codes:
            return profile.club_codes[0]
    return ""


def _v5_ranked_to_v3_stubs(ranked: list[dict]) -> list[ContentCard]:
    """Convert V5 ranked achievements to minimal V3 ContentCard stubs.

    The V3 detector path is skipped for interpreter-parsed runs (no ASA IDs),
    so run.cards ends up empty even when V5 recognition finds achievements.
    This bridge populates run.cards with lightweight stubs so the export,
    review-page stats, and trust report all reflect the real V5 output.

    Stubs carry no V3 claims (the trust evaluator defaults to medium/review).
    """
    stubs: list[ContentCard] = []
    for ra in ranked:
        ach = ra.get("achievement") or {}
        swim_id = ach.get("swim_id") or f"v5-{ra.get('rank', len(stubs))}"
        swimmer = ach.get("swimmer_name") or ""
        cap = ""
        for vc in (ra.get("voice_captions") or {}).values():
            if isinstance(vc, dict):
                cap = vc.get("caption") or ""
            elif isinstance(vc, str):
                cap = vc
            if cap:
                break
        # When no voice caption is available, fall back to the achievement
        # headline so the card carries a meaningful caption instead of
        # empty strings. The headline is always populated by the recognition
        # engine and makes the export/observer output readable.
        headline = ach.get("headline") or ""
        if not cap:
            cap = headline
        stubs.append(
            ContentCard(
                card_id=swim_id,
                card_type=ach.get("type") or "standout_swim",
                headline=headline,
                subhead=ach.get("event") or "",
                swimmer_names=[swimmer] if swimmer else [],
                claims=[],
                bucket="queue",
                captions=CaptionVariants(clean=cap, team=cap, hype=cap),
            )
        )
    return stubs


def run_pipeline_v4(
    *,
    file_bytes: bytes,
    filename: str,
    profile_id: Optional[str] = None,
    club_filter: Optional[str] = None,
    use_pb_cache: bool = True,
    fetch_pbs: bool = True,
    progress_cb: Optional[Callable[[str], None]] = None,
    run_id: Optional[str] = None,
) -> PipelineRunV4:
    log: list[str] = []

    def step(msg: str) -> None:
        log.append(msg)
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    started = datetime.now(timezone.utc).isoformat()
    rid = run_id or started.replace(":", "-")
    run = PipelineRunV4(run_id=rid, started_at=started, progress_log=log)

    # 1. Interpret
    step("Interpreting document")
    try:
        interpreted = interpret_document(file_bytes, hint=None)
    except Exception as exc:
        run.error = f"interpreter failed: {exc}"
        run.finished_at = datetime.now(timezone.utc).isoformat()
        return run

    # Convert format hint into a synthetic dispatch log so the trust /
    # UI keeps working unchanged.
    fmt = (
        interpreted.sources_used[0].split(":", 1)[1]
        if interpreted.sources_used and ":" in interpreted.sources_used[0]
        else "unknown"
    )
    dlog = DispatchLog(
        chosen_adapter=f"interpreter:{fmt}",
        chosen_filename=filename,
        chosen_score=interpreted.overall_confidence,
        candidates=[
            {
                "adapter": "interpreter",
                "filename": filename,
                "score": round(interpreted.overall_confidence, 3),
            }
        ],
        notes=[
            f"Interpreter overall_confidence={interpreted.overall_confidence:.3f}",
            f"events={len(interpreted.events)}, "
            f"swims={sum(len(e.swims) for e in interpreted.events)}",
        ],
    )
    run.dispatch_log = dlog

    # 2. Bridge to canonical
    step("Bridging interpreted output → canonical meet")
    meet = interpreted_to_canonical(interpreted, source_filename=filename)
    run.canonical_meet = meet

    if not meet.results:
        meet.add_warning(
            "no_results",
            "Interpreter produced no race results. The file may be an "
            "unsupported format or require OCR.",
            severity="error",
        )
        run.error = "Could not extract any race results from the file."
        run.parse_warnings = [w.to_dict() for w in meet.warnings]
        run.finished_at = datetime.now(timezone.utc).isoformat()
        step(run.error)
        return run

    step(
        f"Interpreter parsed {len(meet.results)} swims, "
        f"{len(meet.swimmers)} swimmers across {len(meet.clubs)} clubs."
    )

    # 3. Infer missing
    infer_missing(meet)
    if meet.inferred_fields:
        step(f"Inferred missing fields: {', '.join(meet.inferred_fields)}.")

    # 4. Club discovery store + universal picker
    discovered = extract_clubs_from_interpreted(interpreted)
    run.discovered_clubs = discovered
    try:
        record_clubs(discovered, run_id=rid)
    except Exception as exc:
        step(f"Club discovery store warning: {exc}")

    # 5. Resolve profile (if any)
    seed_default_profiles()
    if profile_id is None and not club_filter:
        profile_id = detect_likely_profile(meet.clubs, meet.host_club_code)
        if profile_id:
            step(f"Auto-selected club profile: {profile_id}")
    profile: Optional[ClubProfile] = load_profile(profile_id) if profile_id else None
    if profile:
        run.profile_id = profile.profile_id
        run.profile_display = profile.display_name

    # 6. Resolve club filter (explicit > profile.display_name > profile.code[0])
    effective_filter = _resolve_club_filter(
        explicit_club_filter=club_filter,
        profile=profile,
    )
    run.club_filter = effective_filter

    if effective_filter:
        our_results, our_keys = filter_meet_by_club_name(meet, effective_filter)
    else:
        # No filter at all: include nothing — surface a warning so the UI
        # can prompt the user to pick a club.
        our_results, our_keys = [], set()
        meet.add_warning(
            "no_club_filter",
            "No club_filter and no profile selected. Pick a club to "
            "filter recognition to your swimmers.",
            severity="warn",
        )

    other = len(meet.results) - len(our_results)
    run.parsed_swim_count = len(meet.results)
    run.our_swim_count = len(our_results)
    run.other_swim_count = other
    run.n_swimmers_ours = len(our_keys)
    step(
        f"Filtered to '{effective_filter}': {len(our_results)} swims "
        f"by {len(our_keys)} swimmers, {other} excluded."
    )

    # 7. Bridge to V3 representation
    parsed_v3 = canonical_to_v3(meet)
    # In V3 land swimmers must have asa_id; interpreter swimmers don't,
    # so the V3 detector path has no swimmers and produces nothing. We
    # therefore feed our_v3_swims as empty for non-asa cases; V5
    # recognition (which works on canonical results) does the heavy
    # lifting in this pipeline.
    our_v3_swims = []
    for s in parsed_v3.swims:
        if s.asa_id and s.asa_id in our_keys:
            our_v3_swims.append(s)
        elif s.club_code and effective_filter and s.club_code == _slug_for_filter(effective_filter):
            our_v3_swims.append(s)

    # 8. PB baseline — authoritative online lookup, every run.
    #
    # "Is this a PB?" is answered against the swimmer's COMPLETE official record
    # on swimmingresults.org, looked up fresh each run. It is deterministic
    # (resolve member id → fetch personal-best page → parse → compare; no LLM),
    # so unlike the secondary discovery below it needs no provider and runs
    # whenever PB enrichment is permitted. A swimmer it can't resolve gets NO
    # baseline (an honest miss) — never a guessed one, which is what a partial
    # MediaHub-only record would have produced. The generic web discovery
    # remains a SECONDARY gap-filler for swimmers swimmingresults.org (British
    # Swimming) doesn't list (e.g. non-GB / unranked).
    pb_snapshots: dict = {}

    # If no LLM provider is configured, skip the SECONDARY web discovery (it
    # would spend 30–60 seconds on external HTTP the heuristic path can't use).
    # The swimmingresults.org baseline (8a below) is unaffected — it needs no
    # provider.
    try:
        from mediahub.media_ai.llm import active_provider as _active_provider

        _llm_provider = _active_provider()
    except Exception:
        _llm_provider = "heuristic"
    _skip_pb_discovery = _llm_provider == "heuristic"
    # Per-tenant enrichment opt-in: fetching PB history from public rankings
    # is data collection NOT from the data subject (UK GDPR Art 14) — the
    # club must have switched it on (and owes athletes/parents the Art 14
    # notice; template in docs/compliance/templates/). Default is on for
    # backward compatibility; the club can turn it off on /organisation/consent.
    if fetch_pbs and profile is not None and not getattr(profile, "pb_enrichment_enabled", True):
        step(
            "Skipping PB discovery: this organisation has switched off PB-history "
            "enrichment (Privacy → Consent & lawful basis)."
        )
        fetch_pbs = False

    # 8a. PRIMARY baseline: official PBs from swimmingresults.org, every run.
    # Deterministic and provider-free, so it runs regardless of LLM config.
    if fetch_pbs and our_results and effective_filter:
        try:
            from mediahub.swimmingresults import lookup_official_pbs

            _sr_snaps = lookup_official_pbs(
                meet,
                our_keys,
                club_name=effective_filter,
                force_refresh=not use_pb_cache,
                step=step,
            )
            pb_snapshots.update(_sr_snaps)
        except Exception as e:
            step(f"swimmingresults.org PB lookup failed: {e}")
            meet.add_warning("pb_enrichment_failed", str(e), severity="warn")

    if fetch_pbs and our_results and effective_filter and _skip_pb_discovery:
        step(
            "Skipping the secondary PB web lookup (gap-filler for swimmers not on "
            "swimmingresults.org): no LLM provider configured (set GEMINI_API_KEY "
            "or ANTHROPIC_API_KEY to enable)."
        )
    _pb_fetch_started_iso = ""
    _pb_fetch_start_wall = 0.0
    _pb_fetch_end_wall = 0.0
    _pb_budget_exceeded = False
    if fetch_pbs and our_results and effective_filter and not _skip_pb_discovery:
        import time as _time

        # Gap-filler only: research the swimmers swimmingresults.org could not
        # resolve (e.g. non-GB clubs, unranked swimmers). It never overrides the
        # authoritative swimmingresults.org baseline already in pb_snapshots.
        _unknown_keys = {k for k in our_keys if k not in pb_snapshots}
        if _unknown_keys:
            _pb_fetch_started_iso = datetime.now(timezone.utc).isoformat()
            _pb_fetch_start_wall = _time.time()
            try:
                _web_snaps, _pb_budget_exceeded = _enrich_pbs_via_discovery(
                    meet=meet,
                    our_swimmer_keys=_unknown_keys,
                    club_name=effective_filter,
                    run_id=rid,
                    step=step,
                    # The configure form's "use PB cache" toggle: unticked means
                    # the operator wants a genuine re-research, so bypass the
                    # run + warm caches instead of silently replaying them.
                    force_refresh=not use_pb_cache,
                )
                # Web fills gaps only — never override the swimmingresults.org baseline.
                for _k, _v in _web_snaps.items():
                    pb_snapshots.setdefault(_k, _v)
            except Exception as e:
                step(f"PB web lookup failed: {e}")
                meet.add_warning("pb_enrichment_failed", str(e), severity="warn")
            _pb_fetch_end_wall = _time.time()

    # Baseline coverage from whatever filled it (swimmingresults.org and/or the
    # secondary discovery), so the metric is correct even with no LLM provider.
    if fetch_pbs and our_results and effective_filter:
        run.pb_fetch_ok = sum(1 for s in pb_snapshots.values() if getattr(s, "fetch_ok", False))
        run.pb_fetch_failed = max(0, len(our_keys) - run.pb_fetch_ok)

    # 9. Standards
    standards = load_registry()
    stale = stale_standards(standards)
    primary_code = ""
    if profile and profile.club_codes:
        primary_code = profile.club_codes[0]
    relevant = relevant_standards(standards, primary_code, meet.course)
    run.standards_meta = {
        "total": len(standards),
        "stale_ids": [s.standard_id for s in stale],
        "relevant_ids": [s.standard_id for s in relevant],
        "important_ids": list(profile.important_standards) if profile else [],
    }
    step(
        f"Loaded {len(standards)} qualification standards "
        f"({len(stale)} stale, {len(relevant)} relevant)."
    )

    # 10. V3 detector / cards / ranker / self-check
    det = detect_v3(
        meet=parsed_v3,
        our_swims=our_v3_swims,
        swimmers_by_asa=parsed_v3.swimmers,
        pb_snapshots=pb_snapshots,
        standards=standards,
        club_code=primary_code,
    )
    run.detector_summary = {
        "n_processed": det.n_swims_processed,
        "n_skipped": det.n_swims_skipped,
        "n_pb_confirmed": det.n_pb_confirmed,
        "n_pb_likely": det.n_pb_likely,
        "n_pb_unverified": det.n_pb_unverified,
        "n_qual_hits": det.n_qual_hits,
        "n_medals": det.n_medals,
        "n_claims": len(det.claims),
    }
    step(f"V3 detector: {len(det.claims)} claims.")

    cards = group_claims_into_cards(det.claims, meet_name=meet.name)
    cards = attach_evidence_from_claims(cards)
    cards = write_captions(
        cards, club_short=(profile.display_name if profile else effective_filter)
    )
    cards = rank_cards(cards)
    run.cards = cards

    sc = run_self_check(
        cards=cards,
        parsed_swim_count=len(meet.results),
        our_swim_count=len(our_results),
        other_swim_count=other,
        opposition_leak_count=0,
        standards_meta=run.standards_meta,
        course=meet.course,
    )
    run.self_check = {
        "pass": sc.pass_count,
        "warn": sc.warn_count,
        "fail": sc.fail_count,
        "checks": [
            {"code": ck.code, "title": ck.title, "status": ck.status, "message": ck.message}
            for ck in sc.results
        ],
    }

    # 11. Trust report
    run.trust = build_trust_report(
        meet=meet,
        profile=profile or _ephemeral_profile(effective_filter),
        cards=cards,
        pb_snapshots=pb_snapshots,
        standards_meta=run.standards_meta,
    )
    run.parse_warnings = [w.to_dict() for w in meet.warnings]

    # 12. V5 recognition report
    try:
        run._pb_snapshots = pb_snapshots  # type: ignore[attr-defined]
        run._our_swimmer_keys = our_keys  # type: ignore[attr-defined]
        run._our_results = our_results  # type: ignore[attr-defined]
        from swim_content_v5.report import build_recognition_report_for_run

        # The report build starts with meet-identity research (web search +
        # page fetches) that can run for a minute on an uncached meet and
        # emits no progress lines of its own — heartbeat first so the
        # stale-run watchdog sees a fresh line going into the gap.
        step("Researching meet identity and recognising achievements…")
        run.recognition_report = build_recognition_report_for_run(run)
        step(f"V5 recognition: {run.recognition_report.get('n_achievements', 0)} achievements.")
    except Exception as exc:
        run.recognition_report = None
        run.recognition_error = f"{type(exc).__name__}: {exc}"
        step(f"v5 recognition failed: {exc}")

    # 12a. Per-swimmer PB audit, assembled AFTER recognition so it can map
    # the engine's real PB decisions. The V5 achievements are keyed by the
    # same canonical swimmer_key as the discovery snapshots; the V3 claims
    # (asa-keyed) only exist on the legacy path. Building from claims alone
    # left every interpreter-parsed run's audit showing zero decisions while
    # the cards showed PBs. Runs BEFORE the child-policy display transform:
    # the audit is the internal reconciliation record (it already shows full
    # names from the meet file for safeguarding verification), while every
    # published surface inherits the transformed identity from 12b onwards.
    if pb_snapshots:
        try:
            _ranked_for_audit = (run.recognition_report or {}).get("ranked_achievements") or []
            run.pb_audit = _build_pb_audit(
                run_id=rid,
                meet=meet,
                our_swimmer_keys=our_keys,
                pb_snapshots=pb_snapshots,
                claims=det.claims,
                ranked_achievements=_ranked_for_audit,
                started_at=_pb_fetch_started_iso,
                fetch_start_wall=_pb_fetch_start_wall,
                fetch_end_wall=_pb_fetch_end_wall,
                budget_exceeded=_pb_budget_exceeded,
            )
            step(
                f"PB audit saved: {len(getattr(run.pb_audit, 'per_swimmer', []) or [])} "
                f"swimmer audits, {getattr(run.pb_audit, 'pb_decisions_count', 0)} PB decisions."
            )
        except Exception as e:
            step(f"PB audit assembly failed: {e}")
            meet.add_warning("pb_audit_failed", str(e), severity="warn")

    # 12b. Children's Code content controls: transform under-18 athletes'
    # display identity (surname initialisation / age suppression) per the
    # tenant's policy BEFORE cards are synthesised and persisted, so every
    # downstream surface (stills, captions, reels, packs) inherits it.
    # Full name + age stay in raw_facts (internal) for consent/safeguarding.
    if run.recognition_report and profile is not None:
        try:
            from mediahub.compliance.child_policy import apply_to_ranked

            apply_to_ranked(profile, run.recognition_report.get("ranked_achievements") or [])
        except Exception as exc:
            step(f"child-policy transform failed (content left untransformed): {exc}")

    # 13. Bridge V5 → V3 stubs when V3 produced no cards.
    # The V3 detector path is intentionally skipped for interpreter-parsed
    # runs (swimmers have no ASA IDs), so run.cards is empty. V5 recognition
    # does the heavy lifting and its ranked_achievements are the real output.
    # Synthesise minimal ContentCard stubs so exports, review-page stats, and
    # the trust report all reflect the actual V5 findings rather than showing
    # "No content cards were generated."
    if not run.cards and run.recognition_report:
        _ranked = run.recognition_report.get("ranked_achievements") or []
        if _ranked:
            run.cards = _v5_ranked_to_v3_stubs(_ranked)
            run.trust = build_trust_report(
                meet=meet,
                profile=profile or _ephemeral_profile(effective_filter),
                cards=run.cards,
                pb_snapshots=pb_snapshots,
                standards_meta=run.standards_meta,
            )
            step(f"V3 stubs synthesised from {len(run.cards)} V5 achievements.")

    run.finished_at = datetime.now(timezone.utc).isoformat()
    return run


def _slug_for_filter(name: str) -> str:
    from .interpreter_bridge import _club_code

    return _club_code(name)


def _ephemeral_profile(club_filter: str) -> ClubProfile:
    """Synthesise a transient ClubProfile so legacy code paths that need
    a `profile` object keep working when the user only supplied a
    club_filter string."""
    slug = _slug_for_filter(club_filter)
    return ClubProfile(
        profile_id=f"adhoc-{slug}" if slug else "adhoc",
        display_name=club_filter or "(unknown club)",
        short_name=club_filter or "",
        club_codes=[slug] if slug else [],
    )


def _pb_fetch_budget_s() -> float:
    """Per-run wall-clock ceiling for the whole PB discovery phase, in
    seconds (``MEDIAHUB_PB_FETCH_BUDGET_S``, default 600; 0 = unlimited).
    A 100-swimmer meet must not research unbounded — swimmers not reached
    are skipped honestly and the run audit carries ``fetch_budget_exceeded``."""
    raw = os.environ.get("MEDIAHUB_PB_FETCH_BUDGET_S", "").strip()
    try:
        val = float(raw) if raw else 600.0
    except ValueError:
        val = 600.0
    return max(0.0, val)


def _pb_progress_tick_s() -> float:
    """How often the discovery phase emits a heartbeat line when no lookup
    has completed (``MEDIAHUB_PB_PROGRESS_TICK_S``, default 45s). Must stay
    well inside the web layer's stale-run watchdog (180s) so a slow batch of
    lookups reads as "working", never as "dead"."""
    raw = os.environ.get("MEDIAHUB_PB_PROGRESS_TICK_S", "").strip()
    try:
        val = float(raw) if raw else 45.0
    except ValueError:
        val = 45.0
    return max(0.05, val)


def _enrich_pbs_via_discovery(
    *,
    meet: Meet,
    our_swimmer_keys: set,
    club_name: str,
    run_id: str,
    step,
    force_refresh: bool = False,
) -> tuple[dict, bool]:
    """
    Run pb_discovery for each of our swimmers and bridge each result
    into the snapshot shape consumed by V3/V5 history.

    Returns ``(snapshots, budget_exceeded)``.

    PB discovery is the slowest pipeline phase: each swimmer chains a few web
    searches plus up to three page fetches — tens of seconds of network I/O.
    The lookups are independent and I/O-bound, so we fan them out across a
    bounded thread pool; a 38-swimmer meet drops from several minutes to well
    under one. Per-swimmer caches and the trust ledger are concurrency-safe.
    Set MEDIAHUB_PB_DISCOVERY_PARALLEL=0 to force the serial path (e.g. for
    deterministic tests); MEDIAHUB_PB_DISCOVERY_WORKERS tunes the pool size.

    Two run-level guards:
    * a wall-clock budget (``MEDIAHUB_PB_FETCH_BUDGET_S``) stops scheduling
      new lookups once spent — skipped swimmers surface in the audit and the
      run flag, never silently;
    * a periodic heartbeat line whenever no lookup completes within the tick
      window, so the stale-run watchdog can tell slow from dead.

    ``force_refresh=True`` (the configure form's "use PB cache" unticked)
    bypasses the per-run and warm caches for a genuine re-research.
    """
    import time as _time

    from mediahub.pb_discovery import discover_swimmer_pbs
    from .pb_bridge import discovery_to_snapshot

    # Resolve the swimmers we actually need to research (drop missing /
    # nameless keys up front so the progress count reflects real work).
    targets: list[tuple[str, str]] = []
    for key in sorted(our_swimmer_keys):
        sw = meet.swimmers.get(key)
        if sw is None:
            continue
        full_name = f"{sw.first_name} {sw.last_name}".strip()
        if not full_name:
            continue
        targets.append((key, full_name))

    snapshots: dict = {}
    total = len(targets)
    if total == 0:
        return snapshots, False

    budget_s = _pb_fetch_budget_s()
    deadline = (_time.monotonic() + budget_s) if budget_s > 0 else None
    budget_exceeded = False

    def _lookup(key: str, full_name: str) -> tuple[str, object]:
        disc = discover_swimmer_pbs(
            name=full_name, club=club_name, run_id=run_id, force_refresh=force_refresh
        )
        return key, discovery_to_snapshot(disc, swimmer_key=key)

    parallel = os.environ.get("MEDIAHUB_PB_DISCOVERY_PARALLEL", "1") != "0" and total > 1

    if parallel:
        from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

        max_workers = int(os.environ.get("MEDIAHUB_PB_DISCOVERY_WORKERS", "6") or "6")
        max_workers = max(1, min(max_workers, total))
        tick_s = _pb_progress_tick_s()
        # One up-front line so the page shows activity immediately; the
        # per-completion lines below keep the heartbeat fresh and report a
        # monotonic done-count even though lookups finish out of order.
        step(f"Looking up personal bests for {total} swimmers ({max_workers} in parallel)…")
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_lookup, key, name): name for key, name in targets}
            pending = set(futures)
            done_count = 0
            # This loop body runs only in the calling thread, so the counter,
            # the step() emissions and the snapshots dict need no extra locking.
            while pending:
                done_set, pending = wait(pending, timeout=tick_s, return_when=FIRST_COMPLETED)
                if not done_set:
                    # Nothing finished inside the tick window — heartbeat so
                    # the watchdog sees progress, not a dead worker.
                    step(f"Still researching personal bests ({done_count}/{total} done)…")
                for fut in done_set:
                    name = futures[fut]
                    done_count += 1
                    try:
                        key, snap = fut.result()
                    except Exception as exc:
                        step(f"PB lookup error for {name}: {exc}")
                        continue
                    snapshots[key] = snap
                    step(f"Looking up personal bests {done_count}/{total}: {name}")
                if (
                    deadline is not None
                    and not budget_exceeded
                    and pending
                    and _time.monotonic() > deadline
                ):
                    # Budget spent: stop queued lookups (cancel succeeds only
                    # for not-yet-started futures); in-flight ones finish.
                    cancelled = {f for f in pending if f.cancel()}
                    pending -= cancelled
                    budget_exceeded = True
                    step(
                        f"PB lookup budget reached ({budget_s:.0f}s) — skipping "
                        f"{len(cancelled)} remaining swimmers."
                    )
        return snapshots, budget_exceeded

    # Serial path (single swimmer, or explicitly disabled).
    for idx, (key, full_name) in enumerate(targets, start=1):
        if deadline is not None and _time.monotonic() > deadline:
            budget_exceeded = True
            step(
                f"PB lookup budget reached ({budget_s:.0f}s) — skipping "
                f"{total - idx + 1} remaining swimmers."
            )
            break
        step(f"Looking up personal bests {idx}/{total}: {full_name}")
        try:
            rkey, snap = _lookup(key, full_name)
        except Exception as exc:
            step(f"PB lookup error for {full_name}: {exc}")
            continue
        snapshots[rkey] = snap
    return snapshots, budget_exceeded


_EVENT_COURSE_RE = re.compile(r"\s*\((LC|SC|Y)\)\s*$", re.IGNORECASE)


def _event_course_from_label(label: str) -> tuple[str, str]:
    """Split a V5 event label like ``"100m Freestyle (LC)"`` into
    ``("100m Freestyle", "LC")``. Course defaults to "LC" when absent."""
    m = _EVENT_COURSE_RE.search(label or "")
    if not m:
        return (label or "").strip(), "LC"
    return label[: m.start()].strip(), m.group(1).upper()


# V5 achievement types → V7.3 audit decision statuses. pb_magnitude_* and
# multi_pb_weekend are derivatives of pb_confirmed on the same swim — mapping
# them too would double-count the decision.
_V5_AUDIT_STATUS = {
    "official_pb_confirmed": "CONFIRMED_OFFICIAL_PB",
    "pb_confirmed": "CONFIRMED_PB_IMPROVEMENT",
    "pb_likely": "LIKELY_PB",
}

_CONFIRMED_AUDIT_STATUSES = {"CONFIRMED_OFFICIAL_PB", "CONFIRMED_PB_IMPROVEMENT"}


def _v5_decision_from_achievement(ach: dict, pb_snapshots: dict):
    """Map one V5 achievement dict to a ``PBDecision`` (or None)."""
    from swim_content_pb.schema import PBDecision, PreviousPB

    status = _V5_AUDIT_STATUS.get(str(ach.get("type") or ""))
    if not status:
        return None, ""
    key = str(ach.get("swimmer_id") or "")
    label = str(ach.get("event") or "")
    event, course = _event_course_from_label(label)
    facts = ach.get("raw_facts") or {}
    evidence_urls = [
        e.get("source_url")
        for e in (ach.get("evidence") or [])
        if isinstance(e, dict) and e.get("source_url")
    ]
    snap = pb_snapshots.get(key)

    current_sec = facts.get("time_sec")
    if current_sec is None and facts.get("time_cs") is not None:
        current_sec = float(facts["time_cs"]) / 100.0

    prev = None
    prior_sec = facts.get("prior_pb_sec")
    if prior_sec:
        from .pb_bridge import _split_event

        distance, stroke = _split_event(event)
        prev = PreviousPB(
            swimmer_asa_id=key,
            swimmer_name=str(ach.get("swimmer_name") or ""),
            event_distance=distance or 0,
            event_stroke=stroke,
            course=course,
            time_seconds=float(prior_sec),
            time_display=str(facts.get("prior_pb_str") or ""),
            pb_date_iso=None,
            pb_meet_name=None,
            source_url=(
                evidence_urls[0] if evidence_urls else str(getattr(snap, "source_url", "") or "")
            ),
            fetched_at=str(getattr(snap, "retrieved_at", "") or "") if snap is not None else "",
        )

    drop_sec = facts.get("drop_seconds")
    delta = None
    if drop_sec is not None:
        try:
            delta = -float(drop_sec)
        except (TypeError, ValueError):
            delta = None
    improvement = facts.get("drop_pct")
    try:
        improvement = float(improvement) if improvement is not None else None
    except (TypeError, ValueError):
        improvement = None

    if status == "CONFIRMED_OFFICIAL_PB":
        reason = str(facts.get("reason") or "time and date match the swimmer's listed all-time PB")
    elif status == "CONFIRMED_PB_IMPROVEMENT":
        reason = "beat the best prior time found by live PB discovery"
    else:
        reason = "no verifiable prior history — faster than entry time"

    return (
        PBDecision(
            status=status,
            swim_id=str(ach.get("swim_id") or ""),
            swimmer_asa_id=key,
            swimmer_name=str(ach.get("swimmer_name") or ""),
            event=label,
            course=course,
            current_time_seconds=float(current_sec or 0.0),
            current_time_display=str(facts.get("time_str") or ""),
            previous_pb=prev,
            delta_seconds=delta,
            improvement_percentage=improvement,
            same_meet_excluded_count=0,
            reason=reason,
            evidence=evidence_urls,
            safe_to_post=status in _CONFIRMED_AUDIT_STATUSES,
            confidence=str(
                ach.get("confidence_label")
                or ("high" if status in _CONFIRMED_AUDIT_STATUSES else "medium")
            ),
            uncertainty_notes=list(ach.get("uncertainty_notes") or []),
        ),
        key,
    )


def _build_pb_audit(
    *,
    run_id: str,
    meet: Meet,
    our_swimmer_keys: set,
    pb_snapshots: dict,
    claims: list,
    started_at: str,
    fetch_start_wall: float,
    fetch_end_wall: float,
    ranked_achievements: Optional[list] = None,
    budget_exceeded: bool = False,
):
    """Assemble a ``RunPBAudit`` from discovery snapshots + engine decisions.

    Real data only: per-swimmer lookup outcomes, the events each lookup
    actually returned, the source URLs used, and the PB calls the engine
    actually made. Decisions come from BOTH engines that can make them:

    * V5 recognition achievements (``pb_confirmed`` / ``pb_likely`` /
      ``official_pb_confirmed``) — keyed by the same canonical
      ``swimmer_key`` as the snapshots. This is the engine that detects
      PBs on interpreter-parsed runs (which carry no ASA ids).
    * V3 detector claims (asa-keyed legacy path), skipped wherever V5
      already decided the same swimmer + event.

    Identity verification isn't part of the discovery flow, so ``identity``
    stays None (the audit page then shows the lookup outcome rather than
    inventing matches).
    """
    from swim_content_pb.schema import PBAudit, PBDecision, PreviousPB
    from swim_content_pb.audit import aggregate_run_audit

    decisions_by_key: dict[str, list] = {}
    decided: set[tuple[str, str]] = set()

    # --- V5 recognition decisions (authoritative on this pipeline) --------
    for ra in ranked_achievements or []:
        if not isinstance(ra, dict):
            continue
        ach = ra.get("achievement")
        if not isinstance(ach, dict):
            ach = ra
        decision, key = _v5_decision_from_achievement(ach, pb_snapshots)
        if decision is None:
            continue
        decisions_by_key.setdefault(key, []).append(decision)
        decided.add((key, decision.event))

    # --- V3 detector claims (asa-keyed legacy path) ------------------------
    # Claim kinds → V7.3 audit decision statuses. "pb_confirmed" here means
    # "beat the best prior time discovery found" — the improvement-proof
    # flavour of confirmation, not the official time+date match.
    claim_status = {
        "pb_confirmed": "CONFIRMED_PB_IMPROVEMENT",
        "pb_likely": "LIKELY_PB",
    }

    for c in claims:
        status = claim_status.get(getattr(c, "kind", ""))
        if not status:
            continue
        key = getattr(c, "swimmer_tiref", None) or ""
        if (str(key), getattr(c, "event_label", "") or "") in decided:
            continue
        extra = getattr(c, "extra", None) or {}
        prev = None
        prior_sec = extra.get("prior_time_sec")
        if prior_sec:
            prev = PreviousPB(
                swimmer_asa_id=str(key),
                swimmer_name=c.swimmer_name,
                event_distance=c.distance,
                event_stroke=c.stroke,
                course=c.course,
                time_seconds=float(prior_sec),
                time_display=extra.get("prior_time_str") or "",
                pb_date_iso=extra.get("prior_date_iso"),
                pb_meet_name=None,
                source_url=extra.get("source_url") or "",
                fetched_at=extra.get("retrieved_at") or "",
            )
        delta = extra.get("delta_sec")
        improvement = None
        if delta is not None and prior_sec:
            try:
                improvement = round(100.0 * (-float(delta)) / float(prior_sec), 2)
            except Exception:
                improvement = None
        decisions_by_key.setdefault(str(key), []).append(
            PBDecision(
                status=status,
                swim_id="",
                swimmer_asa_id=str(key),
                swimmer_name=c.swimmer_name,
                event=c.event_label,
                course=c.course,
                current_time_seconds=c.time_sec,
                current_time_display=c.time_str,
                previous_pb=prev,
                delta_seconds=float(delta) if delta is not None else None,
                improvement_percentage=improvement,
                same_meet_excluded_count=0,
                reason=(
                    extra.get("note")
                    or (
                        "beat the best prior time found by live PB discovery"
                        if status == "CONFIRMED_PB_IMPROVEMENT"
                        else "could not fully verify against prior history"
                    )
                ),
                evidence=[u for u in [extra.get("source_url")] if u],
                safe_to_post=status == "CONFIRMED_PB_IMPROVEMENT",
                confidence="high" if status == "CONFIRMED_PB_IMPROVEMENT" else "medium",
            )
        )

    per_swimmer: list = []
    for key in sorted(our_swimmer_keys):
        sw = meet.swimmers.get(key)
        name = f"{sw.first_name} {sw.last_name}".strip() if sw is not None else str(key)
        snap = pb_snapshots.get(key)
        events = sorted((getattr(snap, "pb_times", None) or {}).keys()) if snap is not None else []
        src = getattr(snap, "source_url", None) if snap is not None else None
        per_swimmer.append(
            PBAudit(
                asa_id=str(key),
                hy3_name=name,
                sr_name=None,
                identity=None,
                events_fetched=events,
                pb_decisions=decisions_by_key.get(str(key), []),
                fetch_ok=bool(getattr(snap, "fetch_ok", False)) if snap is not None else False,
                fetch_error=(
                    getattr(snap, "error", None) if snap is not None else "no lookup attempted"
                ),
                no_history=bool(getattr(snap, "no_history", False)) if snap is not None else False,
                source_urls=[src] if src else [],
                fetched_at=getattr(snap, "retrieved_at", None) if snap is not None else None,
            )
        )

    return aggregate_run_audit(
        run_id=run_id,
        per_swimmer=per_swimmer,
        # Snapshots carry pb_discovery's cache_hit flag as `from_cache`, so
        # the aggregate's cache-hit/miss counters reflect real lookups.
        fetch_results=pb_snapshots,
        started_at=started_at,
        fetch_start_wall=fetch_start_wall,
        fetch_end_wall=fetch_end_wall,
        budget_exceeded=budget_exceeded,
    )
