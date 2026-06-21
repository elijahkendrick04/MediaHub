"""The cross-source planner — MediaHub's strategy brain (P1.3).

Fuses the three signal sources (``content_engine.signals``: own / external /
direct) into a **ranked, explainable content plan** keyed by a sport profile
(``mediahub.sport_profiles`` + ``club_platform.post_types``, ADR-0013). This
generalises the swim newsworthiness ranker's transparent additive-scoring
pattern (``legacy/swim_content/ranker_v3.py``) from "rank these result cards"
to "rank what this club should post next".

Design rules (CLAUDE.md):

* **Deterministic.** Ranking is part of the deterministic engine — fixed
  bases + signal-driven modifiers, no LLM in the loop, same inputs → same
  plan. AI judgement (what the copy says, which photo) happens downstream in
  the existing generation surfaces, never here.
* **Explainable.** Every plan item carries ``reasons`` (one line per applied
  modifier, quoting the signal it came from) and ``sources_used`` — including
  the honest negative ("no <engine> results ingested yet") so "why ISN'T this
  ranked higher?" always has an answer.
* **Source-grounded.** A modifier only ever fires off a gathered
  :class:`~mediahub.content_engine.signals.Signal`; nothing is invented.
* **Tenant-isolated.** Signals are gathered per ``profile_id``; plans persist
  one directory per org (sanitised, one file per org).

The plan is *advice for the human*, not a publish decision: a human always
reviews and approves before any content leaves the system.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from mediahub.club_platform.post_types import SportPostType, post_types_for
from mediahub.content_engine.signals import Signal, gather_all_signals
from mediahub.sport_profiles import load_sport_profile

PLAN_VERSION = 1
HORIZON_DAYS_DEFAULT = 14

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")
_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Category bases — the editorial prior, in the open (ranker_v3 pattern).
# Result moments outrank pre-event promotion, which outranks evergreen
# community content; live session updates only matter mid-event.
# ---------------------------------------------------------------------------

RESULT_LED = frozenset(
    {
        "meet_recap",
        "result_recap",
        "pb_spotlight",
        "relay_splits",
        "club_record_board",
        "podium_recap",
        "finish_time_spotlight",
        "full_time_score",
        "goal_assist_leader",
        "final_box_score",
        "player_of_the_game",
    }
)
PRE_EVENT = frozenset(
    {
        "event_preview",
        "fixture_announcement",
        "heat_lane_preview",
        "matchday_lineup",
        "game_day_matchup",
        "race_preview",
        "fixture_run_in",
    }
)
EVERGREEN = frozenset(
    {
        "athlete_spotlight",
        "behind_the_scenes",
        "milestone_celebration",
        "birthday",
        "signings_recruitment",
        "ticket_merch_promo",
        "this_day_in_history",
        "free_text",
        "league_table",
        "standings",
        "club_championship_table",
        "training_block_milestone",
        "highlight_clip",
    }
)
SEASONAL = frozenset({"season_recap"})
LIVE = frozenset({"session_update"})
SPONSOR = frozenset({"sponsor_activation"})

_BASES: tuple[tuple[frozenset, int, str], ...] = (
    (RESULT_LED, 40, "result-led type — rises and falls with fresh results"),
    (PRE_EVENT, 35, "pre-event type — rises as a known event approaches"),
    (SPONSOR, 24, "sponsor type — needs a configured sponsor and a moment"),
    (EVERGREEN, 25, "evergreen community type"),
    (SEASONAL, 18, "seasonal type — peaks at season boundaries"),
    (LIVE, 12, "live type — only relevant mid-event"),
)

FRESH_RESULTS_DAYS = 7
STALE_TYPE_DAYS = 21
RECENT_TYPE_DAYS = 3


def _base_for(slug: str) -> tuple[int, str]:
    for members, base, why in _BASES:
        if slug in members:
            return base, why
    return 20, "uncategorised type — neutral baseline"


# ---------------------------------------------------------------------------
# Plan shapes
# ---------------------------------------------------------------------------


@dataclass
class PlanItem:
    """One ranked recommendation: a post type and why it ranks where it does."""

    post_type: str  # canonical slug (ADR-0013)
    title: str
    score: int
    reasons: list[str] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)  # ⊆ own/external/direct
    signal_refs: list[str] = field(default_factory=list)  # provenance strings
    default_autonomy: str = "approval_required"
    implemented: bool = False
    content_type: Optional[str] = None  # ContentType value when implemented
    template_namespace: str = ""
    data_inputs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "post_type": self.post_type,
            "title": self.title,
            "score": self.score,
            "reasons": list(self.reasons),
            "sources_used": list(self.sources_used),
            "signal_refs": list(self.signal_refs),
            "default_autonomy": self.default_autonomy,
            "implemented": self.implemented,
            "content_type": self.content_type,
            "template_namespace": self.template_namespace,
            "data_inputs": list(self.data_inputs),
        }


@dataclass
class ContentPlan:
    """A ranked, explainable content plan for one org + sport profile."""

    plan_id: str
    profile_id: str
    sport: str
    sport_display: str
    engine_sport: str
    generated_at: str
    horizon_days: int
    items: list[PlanItem] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    version: int = PLAN_VERSION

    def source_counts(self) -> dict[str, int]:
        counts = {"own": 0, "external": 0, "direct": 0}
        for s in self.signals:
            if s.source in counts:
                counts[s.source] += 1
        return counts

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "profile_id": self.profile_id,
            "sport": self.sport,
            "sport_display": self.sport_display,
            "engine_sport": self.engine_sport,
            "generated_at": self.generated_at,
            "horizon_days": self.horizon_days,
            "items": [i.to_dict() for i in self.items],
            "signals": [s.to_dict() for s in self.signals],
            "source_counts": self.source_counts(),
            "notes": list(self.notes),
            "version": self.version,
        }


# ---------------------------------------------------------------------------
# Scoring — fixed bases + signal-driven modifiers, every step a reason line
# ---------------------------------------------------------------------------


def _score_item(
    spt: SportPostType,
    *,
    engine_sport: str,
    signals: list[Signal],
    horizon_days: int,
) -> PlanItem:
    slug = spt.slug
    base, base_why = _base_for(slug)
    score = base
    reasons = [f"+{base} {base_why}"]
    sources: set[str] = set()
    refs: list[str] = []

    def apply(delta: int, why: str, sig: Optional[Signal] = None) -> None:
        nonlocal score
        score += delta
        reasons.append(f"{'+' if delta >= 0 else ''}{delta} {why}")
        if sig is not None:
            sources.add(sig.source)
            if sig.provenance not in refs:
                refs.append(sig.provenance)

    runs = [s for s in signals if s.kind == "run_results"]
    fresh_runs = [
        s
        for s in runs
        if s.payload.get("age_days") is not None
        and s.payload["age_days"] <= FRESH_RESULTS_DAYS
        and s.payload.get("engine_sport") == engine_sport
    ]
    sport_runs = [s for s in runs if s.payload.get("engine_sport") == engine_sport]

    # --- OWN: fresh results drive the result-led types ------------------
    if slug in RESULT_LED:
        if fresh_runs:
            best = max(fresh_runs, key=lambda s: int(s.payload.get("n_achievements", 0) or 0))
            queued = int(best.payload.get("queued", 0) or 0)
            approved = int(best.payload.get("approved", 0) or 0)
            n_ach = int(best.payload.get("n_achievements", 0) or 0)
            if queued:
                apply(
                    30, f"fresh results with {queued} cards awaiting review — {best.summary}", best
                )
            elif n_ach:
                apply(
                    22, f"fresh results with {n_ach} detected achievements — {best.summary}", best
                )
            else:
                apply(10, f"fresh results ingested — {best.summary}", best)
            if approved and slug in {"meet_recap", "result_recap"}:
                apply(8, f"{approved} approved cards not yet posted", best)
            if slug == "pb_spotlight" and n_ach:
                apply(8, "achievement detections available for a PB-led spotlight", best)
        elif sport_runs:
            apply(
                0,
                "results exist but none in the fresh window (≤7d) — no recency boost",
                sport_runs[0],
            )
        else:
            apply(
                0,
                f"no {engine_sport} results ingested yet — result-led boost unavailable "
                "(honest gap, not a guess)",
            )

    # --- OWN: athlete spotlight rides recent achievement-rich runs ------
    if slug == "athlete_spotlight" and fresh_runs:
        best = max(fresh_runs, key=lambda s: int(s.payload.get("n_achievements", 0) or 0))
        if int(best.payload.get("n_achievements", 0) or 0) > 0:
            apply(15, f"recent meet offers spotlight candidates — {best.summary}", best)

    # --- DIRECT: operator-entered upcoming events ----------------------
    events = [
        s
        for s in signals
        if s.kind == "upcoming_event" and 0 <= int(s.payload.get("in_days", 99)) <= horizon_days
    ]
    blackouts = {s.payload.get("date") for s in signals if s.kind == "blackout"}
    if slug in PRE_EVENT and events:
        nearest = min(events, key=lambda s: int(s.payload.get("in_days", 99)))
        in_days = int(nearest.payload.get("in_days", 0))
        proximity = 25 if in_days <= 3 else (18 if in_days <= 7 else 12)
        apply(proximity, f"event in {in_days}d — {nearest.summary}", nearest)
        if nearest.payload.get("date") in blackouts:
            apply(
                -15, f"event date {nearest.payload.get('date')} falls on a blackout date", nearest
            )
    if slug in LIVE and events:
        nearest = min(events, key=lambda s: int(s.payload.get("in_days", 99)))
        if int(nearest.payload.get("in_days", 99)) <= 1:
            apply(
                35, f"event is imminent — live updates become relevant ({nearest.summary})", nearest
            )

    # --- DIRECT: structured goals target a post type --------------------
    for s in signals:
        if s.kind == "goal" and s.payload.get("post_type") == slug:
            apply(15, f"operator goal targets this type — {s.summary}", s)

    # --- DIRECT: sponsor configured + a moment to activate --------------
    if slug in SPONSOR:
        sponsor_sig = next((s for s in signals if s.kind == "sponsor_configured"), None)
        if sponsor_sig is None:
            apply(0, "no sponsor configured on the org profile — nothing to activate")
        else:
            apply(8, sponsor_sig.summary, sponsor_sig)
            if fresh_runs:
                apply(12, "fresh results give the sponsor a real moment to activate", fresh_runs[0])

    # --- EXTERNAL: calendar anniversaries -------------------------------
    if slug in {"this_day_in_history", "milestone_celebration"}:
        for s in signals:
            if s.kind == "anniversary":
                apply(18, s.summary, s)
                break

    # --- EXTERNAL: discovered meet context strengthens previews ---------
    if slug in {"event_preview", "heat_lane_preview"} and events:
        ident = next((s for s in signals if s.kind == "discovered_meet"), None)
        if ident is not None:
            apply(5, f"discovered context can ground the preview — {ident.summary}", ident)

    # --- OWN: per-type staleness / recency ------------------------------
    pack_sig = next(
        (s for s in signals if s.kind == "pack_recency" and s.payload.get("post_type") == slug),
        None,
    )
    if pack_sig is not None:
        age = int(pack_sig.payload.get("age_days", 0) or 0)
        if age <= RECENT_TYPE_DAYS:
            apply(-10, f"drafted very recently ({age}d ago) — avoid repetition", pack_sig)
        elif age >= STALE_TYPE_DAYS:
            apply(6, f"nothing drafted in this type for {age}d", pack_sig)

    # --- OWN: measured performance (the analytics loop, 1.14) -----------
    # A type the club's own posts have over/under-performed earns a small,
    # bounded, explained nudge. Deterministic: it reads a stored attribution
    # index, so the same recorded metrics always produce the same plan.
    perf_sig = next(
        (s for s in signals if s.kind == "performance" and s.payload.get("post_type") == slug),
        None,
    )
    if perf_sig is not None:
        idx = float(perf_sig.payload.get("index", 1.0) or 1.0)
        if idx >= 1.15:
            apply(
                min(8, round((idx - 1.0) * 20)),
                f"outperforms your average — {perf_sig.summary}",
                perf_sig,
            )
        elif idx <= 0.85:
            apply(
                max(-6, round((idx - 1.0) * 20)),
                f"underperforms your average — {perf_sig.summary}",
                perf_sig,
            )

    return PlanItem(
        post_type=slug,
        title=spt.title,
        score=score,
        reasons=reasons,
        sources_used=sorted(sources),
        signal_refs=refs,
        default_autonomy=spt.config.default_autonomy.value,
        implemented=spt.content_type is not None,
        content_type=spt.content_type.value if spt.content_type is not None else None,
        template_namespace=spt.config.template_namespace,
        data_inputs=list(spt.config.data_inputs),
    )


def build_content_plan(
    sport: str,
    profile_id: str,
    *,
    signals: Optional[list[Signal]] = None,
    data_dir: Optional[Path] = None,
    now: Optional[date] = None,
    horizon_days: int = HORIZON_DAYS_DEFAULT,
) -> ContentPlan:
    """Build the ranked, explainable plan for one org + sport profile.

    ``signals`` may be injected (tests, previews); by default all three
    sources are gathered for ``profile_id``. Deterministic for fixed inputs.
    """
    profile = load_sport_profile(sport)
    today = now or datetime.now(timezone.utc).date()
    sigs = (
        signals
        if signals is not None
        else gather_all_signals(profile_id, data_dir=data_dir, now=today)
    )

    items = [
        _score_item(
            spt,
            engine_sport=profile.engine_sport,
            signals=sigs,
            horizon_days=horizon_days,
        )
        for spt in post_types_for(profile)
    ]
    items.sort(key=lambda i: (-i.score, i.post_type))

    notes: list[str] = []
    counts = {"own": 0, "external": 0, "direct": 0}
    for s in sigs:
        if s.source in counts:
            counts[s.source] += 1
    for source, n in counts.items():
        if n == 0:
            notes.append(
                f"No {source} signals available — the plan is honest about that "
                f"rather than inventing {source} context."
            )
    if not any(s.kind == "run_results" for s in sigs):
        notes.append(
            f"No processed {profile.engine_sport} results found for this org; "
            "result-led types rank on baseline only."
        )

    return ContentPlan(
        plan_id=uuid.uuid4().hex[:12],
        profile_id=profile_id,
        sport=profile.sport,
        sport_display=profile.display_name,
        engine_sport=profile.engine_sport,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        horizon_days=horizon_days,
        items=items,
        signals=list(sigs),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Persistence — one directory per org, latest-pointer, mirrors policy store
# ---------------------------------------------------------------------------


def _sanitise_org(org_id: str) -> str:
    s = _SAFE.sub("_", (org_id or "unknown").strip()) or "unknown"
    return s[:120]


def _plans_dir(org_id: str, data_dir: Optional[Path] = None) -> Path:
    base = Path(data_dir) if data_dir is not None else Path(os.environ.get("DATA_DIR", "."))
    d = base / "content_plans" / _sanitise_org(org_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_plan(plan: ContentPlan, *, data_dir: Optional[Path] = None) -> Path:
    """Persist the plan and update the org's ``latest.json`` pointer."""
    d = _plans_dir(plan.profile_id, data_dir)
    payload = json.dumps(plan.to_dict(), indent=2, ensure_ascii=False)
    path = d / f"{plan.plan_id}.json"
    with _LOCK:
        path.write_text(payload, encoding="utf-8")
        (d / "latest.json").write_text(payload, encoding="utf-8")
    return path


def load_latest_plan(org_id: str, *, data_dir: Optional[Path] = None) -> Optional[dict]:
    """The org's most recent plan as a dict, or None when never planned."""
    path = _plans_dir(org_id, data_dir) / "latest.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    # Tenant isolation: a latest.json can only ever live under its own org's
    # directory, but verify ownership anyway (defence in depth).
    if (raw.get("profile_id") or "") != org_id:
        return None
    return raw


__all__ = [
    "ContentPlan",
    "PlanItem",
    "build_content_plan",
    "load_latest_plan",
    "save_plan",
    "HORIZON_DAYS_DEFAULT",
    "PLAN_VERSION",
]
