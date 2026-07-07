"""Three-source signal gathering for the cross-source planner (P1.3).

A :class:`Signal` is one observed fact the planner may act on, tagged with
the source that produced it (docs/ARCHITECTURE_TARGET.md §1):

  * ``own``      — the club's data already in MediaHub: processed runs and
                   their workflow state, saved draft packs, posting history.
  * ``external`` — world context: meet identities the context engine has
                   discovered, and calendar facts (anniversaries of the
                   club's own past meets — a signal that only exists because
                   of today's date).
  * ``direct``   — what the operator typed in: upcoming events, structured
                   goals, blackout dates (``content_engine.inputs``).

Gathering is **deterministic and read-only** — it scans stores that already
exist, never calls the network or an LLM, and every signal carries
``provenance`` (where it was read from) so each plan item's reasoning is
source-grounded. Tenant isolation: every gatherer filters by ``profile_id``
and silently skips records owned by other orgs.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from mediahub.content_engine.inputs import load_planner_inputs

log = logging.getLogger(__name__)

ANNIVERSARY_WINDOW_DAYS = 7
MAX_RUN_SIGNALS = 12
MAX_PACK_SIGNALS = 12
MAX_DISCOVERED_MEET_SIGNALS = 24


def _norm_meet_name(name: str) -> str:
    """Casefold + collapse whitespace, for meet-name attribution matching."""
    return " ".join(name.split()).casefold()


@dataclass
class Signal:
    """One observed fact, tagged with the source that produced it."""

    source: str  # "own" | "external" | "direct"
    kind: str  # e.g. "run_results", "upcoming_event", "anniversary"
    summary: str  # one human sentence — used verbatim in plan reasons
    provenance: str  # where this was read from (file / store / cache key)
    occurs_at: Optional[str] = None  # ISO date the signal is anchored to
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "kind": self.kind,
            "summary": self.summary,
            "provenance": self.provenance,
            "occurs_at": self.occurs_at,
            "payload": self.payload,
        }


def _data_dir(data_dir: Optional[Path] = None) -> Path:
    if data_dir is not None:
        return Path(data_dir)
    return Path(os.environ.get("DATA_DIR", "."))


def _runs_dir(data_dir: Optional[Path] = None) -> Path:
    env = os.environ.get("RUNS_DIR")
    if env and data_dir is None:
        return Path(env)
    return _data_dir(data_dir) / "runs_v4"


def _parse_when(value: object) -> Optional[date]:
    s = str(value or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None


def _today(now: Optional[date] = None) -> date:
    return now or datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# OWN — runs, workflow state, draft packs, posting history
# ---------------------------------------------------------------------------


def _iter_org_runs(profile_id: str, data_dir: Optional[Path]) -> list[dict]:
    runs_dir = _runs_dir(data_dir)
    if not runs_dir.is_dir():
        return []
    out: list[dict] = []
    for p in runs_dir.glob("*.json"):
        if p.name.endswith("__workflow.json"):
            continue
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(rec, dict):
            continue
        # Tenant isolation: only the active org's runs may produce signals.
        if (rec.get("profile_id") or "") != profile_id:
            continue
        rec["_path"] = str(p)
        out.append(rec)
    out.sort(key=lambda r: str(r.get("finished_at") or ""), reverse=True)
    return out


def gather_own_signals(
    profile_id: str,
    *,
    data_dir: Optional[Path] = None,
    now: Optional[date] = None,
) -> list[Signal]:
    """The club's own data: processed runs + card states + draft packs."""
    if not profile_id:
        return []
    today = _today(now)
    signals: list[Signal] = []

    # --- Processed runs + workflow state -------------------------------
    runs = _iter_org_runs(profile_id, data_dir)
    if runs:
        try:
            from mediahub.workflow.store import WorkflowStore

            wf = WorkflowStore(_runs_dir(data_dir))
        except Exception:  # pragma: no cover - workflow is a core module
            wf = None
        for rec in runs[:MAX_RUN_SIGNALS]:
            run_id = str(rec.get("run_id") or "")
            meet = rec.get("meet") or {}
            meet_name = str(meet.get("name") or rec.get("file_name") or "a recent meet")
            finished = _parse_when(rec.get("finished_at"))
            age_days = (today - finished).days if finished else None
            n_achievements = int(
                (rec.get("recognition_report") or {}).get("n_achievements", 0) or 0
            )
            summary_counts = {}
            if wf is not None and run_id:
                try:
                    summary_counts = wf.summary(run_id)
                except Exception:
                    summary_counts = {}
            queued = int(summary_counts.get("queue", 0) or 0)
            approved = int(summary_counts.get("approved", 0) or 0)
            posted = int(summary_counts.get("posted", 0) or 0)
            age_txt = f"{age_days}d ago" if age_days is not None else "date unknown"
            signals.append(
                Signal(
                    source="own",
                    kind="run_results",
                    summary=(
                        f"Processed results: {meet_name} ({age_txt}) — "
                        f"{n_achievements} achievements detected, "
                        f"{queued} cards in review queue, {approved} approved, {posted} posted."
                    ),
                    provenance=f"runs_v4/{run_id}.json",
                    occurs_at=finished.isoformat() if finished else None,
                    payload={
                        "run_id": run_id,
                        "meet_name": meet_name,
                        "age_days": age_days,
                        "n_achievements": n_achievements,
                        "queued": queued,
                        "approved": approved,
                        "posted": posted,
                        "engine_sport": "swimming",
                    },
                )
            )

    # --- Saved draft packs (per type recency) ---------------------------
    packs_dir = _data_dir(data_dir) / "stub_packs"
    if packs_dir.is_dir():
        try:
            from mediahub.club_platform.post_types import canonical_slug
        except Exception:  # pragma: no cover - core module
            canonical_slug = lambda s: str(s)  # noqa: E731
        latest_by_type: dict[str, tuple[date, str]] = {}
        for p in packs_dir.glob("*.json"):
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(rec, dict):
                continue
            if (rec.get("profile_id") or "") != profile_id:
                continue
            slug = canonical_slug(rec.get("stub_type") or "")
            created = _parse_when(rec.get("created_at"))
            if not slug or created is None:
                continue
            prev = latest_by_type.get(slug)
            if prev is None or created > prev[0]:
                latest_by_type[slug] = (created, p.name)
        for slug, (created, fname) in sorted(latest_by_type.items())[:MAX_PACK_SIGNALS]:
            age = (today - created).days
            signals.append(
                Signal(
                    source="own",
                    kind="pack_recency",
                    summary=f"Last {slug.replace('_', ' ')} draft was {age}d ago.",
                    provenance=f"stub_packs/{fname}",
                    occurs_at=created.isoformat(),
                    payload={"post_type": slug, "age_days": age},
                )
            )

    return signals


def gather_performance_signals(
    profile_id: str,
    *,
    data_dir: Optional[Path] = None,
    now: Optional[date] = None,
) -> list[Signal]:
    """The club's own measured post performance (``analytics``) as planner
    signals — one per post type with enough samples to trust. Deterministic and
    read-only: it reads the stored metrics and computes a fixed attribution, so
    the same numbers always produce the same signals (and the same plan).

    Classed as an **own** signal — it is the club's first-party data. The planner
    turns an above/below-average index into a small, bounded, explained nudge.
    """
    if not profile_id:
        return []
    try:
        from mediahub.analytics.attribution import MIN_SAMPLES, attribute
        from mediahub.analytics.store import load_metrics
    except Exception:  # pragma: no cover - analytics is a sibling package
        return []
    metrics = load_metrics(profile_id, data_dir=data_dir)
    attribution = attribute(metrics)
    if attribution.n_posts == 0:
        return []
    signals: list[Signal] = []
    for tp in attribution.by_type:
        if tp.n < MIN_SAMPLES:
            continue
        pct = round((tp.index - 1.0) * 100)
        direction = "above" if pct >= 0 else "below"
        signals.append(
            Signal(
                source="own",
                kind="performance",
                summary=(
                    f"Your {tp.post_type.replace('_', ' ')} posts run {abs(pct)}% "
                    f"{direction} your average engagement ({tp.n} posts measured)."
                ),
                provenance=f"analytics/{profile_id}.json",
                payload={
                    "post_type": tp.post_type,
                    "index": tp.index,
                    "n": tp.n,
                    "pct": pct,
                },
            )
        )
    return signals


# ---------------------------------------------------------------------------
# EXTERNAL — discovered context + calendar facts
# ---------------------------------------------------------------------------


def gather_external_signals(
    profile_id: str,
    *,
    data_dir: Optional[Path] = None,
    now: Optional[date] = None,
) -> list[Signal]:
    """World context: discovered meet identities + calendar anniversaries.

    Reads only what the context engine has already discovered (no live
    network calls inside planning). Anniversaries cross the club's own past
    meet dates with today's date — a signal that exists only because of the
    calendar, so it is classed as external context.
    """
    if not profile_id:
        return []
    today = _today(now)
    signals: list[Signal] = []
    org_runs = _iter_org_runs(profile_id, data_dir)

    # --- Discovered meet identities (context_engine cache) --------------
    # The discovery cache is a shared, unattributed store (keyed by a hash of
    # meet/venue/year — no org field), so tenant isolation is enforced here:
    # an identity only signals for an org whose own runs carry a matching meet
    # name. Anything unmatched is another tenant's context and never leaks.
    own_meet_names = {
        _norm_meet_name(str((rec.get("meet") or {}).get("name") or "")) for rec in org_runs
    }
    own_meet_names.discard("")
    discovered_dir = _data_dir(data_dir) / "discovered" / "meets"
    if discovered_dir.is_dir() and own_meet_names:
        n_discovered = 0
        for p in sorted(discovered_dir.glob("*.json")):
            if n_discovered >= MAX_DISCOVERED_MEET_SIGNALS:
                break
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            payload = rec.get("payload") if isinstance(rec, dict) else None
            ident = payload if isinstance(payload, dict) else (rec if isinstance(rec, dict) else {})
            name = str(ident.get("canonical_name") or "").strip()
            body = str(ident.get("governing_body") or "").strip()
            level = str(ident.get("meet_level") or "").strip()
            # canonical_name is "<meet name> <year>" (context_engine.identity),
            # so match an org meet name exactly or as a year-suffixed prefix.
            # A record with no name cannot be attributed to this org → skip.
            norm = _norm_meet_name(name)
            if not norm or not any(
                norm == own or norm.startswith(own + " ") for own in own_meet_names
            ):
                continue
            bits = [b for b in (name, level, body) if b]
            signals.append(
                Signal(
                    source="external",
                    kind="discovered_meet",
                    summary="Context engine knows this meet: " + " — ".join(bits) + ".",
                    provenance=f"discovered/meets/{p.name}",
                    payload={"canonical_name": name, "governing_body": body, "meet_level": level},
                )
            )
            n_discovered += 1

    # --- Calendar anniversaries of the club's own meets -----------------
    for rec in org_runs:
        meet = rec.get("meet") or {}
        meet_name = str(meet.get("name") or "").strip()
        finished = _parse_when(rec.get("finished_at"))
        if not meet_name or finished is None:
            continue
        years = today.year - finished.year
        if years < 1:
            continue
        try:
            anniversary = finished.replace(year=today.year)
        except ValueError:  # 29 Feb
            anniversary = date(today.year, 3, 1)
        delta = (anniversary - today).days
        if abs(delta) <= ANNIVERSARY_WINDOW_DAYS:
            when_txt = (
                "today" if delta == 0 else (f"in {delta}d" if delta > 0 else f"{-delta}d ago")
            )
            signals.append(
                Signal(
                    source="external",
                    kind="anniversary",
                    summary=(
                        f"{years} year{'s' if years > 1 else ''} since {meet_name} "
                        f"(anniversary {when_txt})."
                    ),
                    provenance=f"calendar × runs_v4/{rec.get('run_id')}.json",
                    occurs_at=anniversary.isoformat(),
                    payload={"meet_name": meet_name, "years": years, "delta_days": delta},
                )
            )

    return signals


# ---------------------------------------------------------------------------
# DIRECT — operator-entered inputs
# ---------------------------------------------------------------------------


def gather_direct_signals(
    profile_id: str,
    *,
    data_dir: Optional[Path] = None,
    now: Optional[date] = None,
) -> list[Signal]:
    """Operator-entered inputs: upcoming events, structured goals, blackouts."""
    if not profile_id:
        return []
    today = _today(now)
    inputs = load_planner_inputs(profile_id, data_dir=data_dir)
    signals: list[Signal] = []

    for ev in inputs["upcoming_events"]:
        when = _parse_when(ev["date"])
        if when is None:
            continue
        delta = (when - today).days
        if delta < 0:
            continue
        signals.append(
            Signal(
                source="direct",
                kind="upcoming_event",
                summary=f"Operator-entered event: {ev['name']} on {ev['date']} (in {delta}d).",
                provenance="planner_inputs:upcoming_events",
                occurs_at=ev["date"],
                payload={"name": ev["name"], "date": ev["date"], "in_days": delta},
            )
        )

    for goal in inputs["goals"]:
        signals.append(
            Signal(
                source="direct",
                kind="goal",
                summary=(
                    f"Operator goal targets {goal['post_type'].replace('_', ' ')}"
                    + (f": {goal['note']}" if goal["note"] else ".")
                ),
                provenance="planner_inputs:goals",
                payload={"post_type": goal["post_type"], "note": goal["note"]},
            )
        )

    for d in inputs["blackout_dates"]:
        when = _parse_when(d)
        if when is None or when < today:
            continue
        signals.append(
            Signal(
                source="direct",
                kind="blackout",
                summary=f"Blackout date: {d} — nothing should be scheduled that day.",
                provenance="planner_inputs:blackout_dates",
                occurs_at=d,
                payload={"date": d},
            )
        )

    # --- Onboarding facts from the org profile (best-effort) ------------
    try:
        from mediahub.web.club_profile import load_profile

        prof = load_profile(profile_id)
    except Exception:
        prof = None
    sponsor = str(getattr(prof, "sponsor_name", "") or "").strip()
    if sponsor:
        signals.append(
            Signal(
                source="direct",
                kind="sponsor_configured",
                summary=f"Sponsor configured on the org profile: {sponsor}.",
                provenance="club_profile:sponsor_name",
                payload={"sponsor_name": sponsor},
            )
        )

    return signals


def gather_all_signals(
    profile_id: str,
    *,
    data_dir: Optional[Path] = None,
    now: Optional[date] = None,
) -> list[Signal]:
    """All three sources, in own → external → direct order. Performance signals
    (the analytics loop) ride with **own** — the club's first-party data."""
    return (
        gather_own_signals(profile_id, data_dir=data_dir, now=now)
        + gather_performance_signals(profile_id, data_dir=data_dir, now=now)
        + gather_external_signals(profile_id, data_dir=data_dir, now=now)
        + gather_direct_signals(profile_id, data_dir=data_dir, now=now)
    )


__all__ = [
    "Signal",
    "gather_all_signals",
    "gather_direct_signals",
    "gather_external_signals",
    "gather_own_signals",
    "gather_performance_signals",
]
