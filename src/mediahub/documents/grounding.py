"""documents.grounding — the deterministic fact base a club document is built from.

A :class:`DocFacts` is the one normalised, numbers-only fact base both the
deterministic format builders (:mod:`documents.formats`) and the AI drafting flow
(:mod:`documents.draft`) consume. It is computed **in code** from a processed run
(or a window of runs) via :mod:`charts.aggregates` / :mod:`charts.series` — the
exact same detector output the cards and charts use. The AI never computes a
number; it only phrases prose around the numbers on this sheet, and every number
it writes is validated back against :meth:`DocFacts.allowed_numbers` (facts are
code, CLAUDE.md rule).

Everything here is deterministic: same run → same facts → same document skeleton.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from mediahub.charts.aggregates import MeetAggregates, compute_aggregates


@dataclass
class DocFacts:
    """A normalised, source-grounded fact base for one club document."""

    title: str = ""
    club_name: str = ""
    period: str = ""  # "June 2026" / "2025/26 season"
    scope: str = "meet"  # "meet" | "season"
    numbers: dict[str, Any] = field(default_factory=dict)  # flat numbers-only sheet
    headline_stats: list[dict[str, str]] = field(default_factory=list)  # KPI tiles
    tables: dict[str, dict] = field(default_factory=dict)  # name → {columns, rows, caption}
    chart_specs: list[dict] = field(default_factory=list)  # ChartSpec dicts to embed
    highlights: list[str] = field(default_factory=list)  # standout lines (data, not AI)
    source_refs: list[str] = field(default_factory=list)

    def allowed_numbers(self) -> set[float]:
        """Every number the AI is allowed to state: the fact numbers + the period
        year(s) (so prose can name the season) + the small ordinals 1..3."""
        nums: set[float] = {1.0, 2.0, 3.0}
        for v in self.numbers.values():
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                nums.add(float(v))
        for y in re.findall(r"\d{4}", self.period or ""):
            nums.add(float(y))
        return nums

    def facts_block(self) -> str:
        """The numbers sheet handed to the LLM (numbers + key labels only)."""
        lines = []
        if self.club_name:
            lines.append(f"  club: {self.club_name}")
        if self.period:
            lines.append(f"  period: {self.period}")
        for k, v in self.numbers.items():
            if v in ("", None):
                continue
            lines.append(f"  {k}: {v}")
        return "\n".join(lines)

    def is_empty(self) -> bool:
        return not self.headline_stats and not self.tables and not self.highlights


# ---------------------------------------------------------------------------
# Builders (deterministic)
# ---------------------------------------------------------------------------


def _pb_makers_table(pbs_by_swimmer: dict[str, int], *, top: int = 10) -> Optional[dict]:
    if not pbs_by_swimmer:
        return None
    rows = sorted(pbs_by_swimmer.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    return {
        "columns": ["Swimmer", "Personal bests"],
        "rows": [[name, str(n)] for name, n in rows],
        "caption": "Top personal-best makers",
    }


def _medal_table(medals_by_swimmer: dict[str, dict[str, int]], *, top: int = 10) -> Optional[dict]:
    if not medals_by_swimmer:
        return None

    def total(m: dict) -> int:
        return m.get("gold", 0) * 100 + m.get("silver", 0) * 10 + m.get("bronze", 0)

    rows = sorted(medals_by_swimmer.items(), key=lambda kv: (-total(kv[1]), kv[0]))[:top]
    return {
        "columns": ["Swimmer", "Gold", "Silver", "Bronze"],
        "rows": [
            [name, str(m.get("gold", 0)), str(m.get("silver", 0)), str(m.get("bronze", 0))]
            for name, m in rows
            if total(m) > 0
        ],
        "caption": "Medal table",
    }


def _headline_stats(agg: MeetAggregates) -> list[dict[str, str]]:
    stats: list[dict[str, str]] = []
    if agg.n_swims:
        stats.append({"value": str(agg.n_swims), "label": "Swims"})
    if agg.n_swimmers:
        stats.append({"value": str(agg.n_swimmers), "label": "Swimmers"})
    if agg.n_pbs:
        sub = f"{round(agg.pb_rate_pct)}% of swimmers" if agg.pb_rate_pct else ""
        stats.append({"value": str(agg.n_pbs), "label": "Personal bests", "sublabel": sub})
    if agg.n_medals:
        sub = f"{agg.n_gold}G {agg.n_silver}S {agg.n_bronze}B"
        stats.append({"value": str(agg.n_medals), "label": "Medals", "sublabel": sub})
    if agg.n_club_records:
        stats.append({"value": str(agg.n_club_records), "label": "Club records"})
    if agg.n_finals:
        stats.append({"value": str(agg.n_finals), "label": "Finals"})
    return stats


def _highlights(agg: MeetAggregates) -> list[str]:
    out: list[str] = []
    if agg.most_pbs:
        name, n = agg.most_pbs
        out.append(f"{name} set {n} personal best{'s' if n != 1 else ''} — the most of the meet.")
    if agg.biggest_drop:
        d = agg.biggest_drop
        secs = round(float(d.get("seconds", 0.0)), 2)
        if d.get("swimmer") and secs > 0:
            ev = f" in the {d['event']}" if d.get("event") else ""
            out.append(f"{d['swimmer']} took {secs}s off a previous best{ev} — the biggest drop.")
    if agg.n_club_records:
        out.append(
            f"The club set {agg.n_club_records} new club record"
            f"{'s' if agg.n_club_records != 1 else ''}."
        )
    return out


def _chart_specs(run_data: dict, *, limit: int = 3) -> list[dict]:
    """A few real charts the run supports (deterministic; guarded — never fatal)."""
    try:
        from mediahub.charts.series import build_chart_candidates

        cands = build_chart_candidates(run_data)
        return [c.spec.to_dict() for c in cands[:limit]]
    except Exception:
        return []


def facts_from_run(run_data: dict, *, club_name: str = "", run_id: str = "") -> DocFacts:
    """Build the document fact base from one processed run."""
    agg = compute_aggregates(run_data)
    facts = DocFacts(
        title=agg.meet_name or "Meet",
        club_name=club_name,
        period=str((run_data.get("recognition_report") or {}).get("meet_date") or ""),
        scope="meet",
        numbers=agg.to_facts(),
        headline_stats=_headline_stats(agg),
        chart_specs=_chart_specs(run_data),
        highlights=_highlights(agg),
        source_refs=([f"run:{run_id}"] if run_id else []) + ["meet results file"],
    )
    pb = _pb_makers_table(agg.pbs_by_swimmer)
    if pb:
        facts.tables["pb_makers"] = pb
    md = _medal_table(agg.medals_by_swimmer)
    if md:
        facts.tables["medal_table"] = md
    return facts


def facts_from_runs(
    runs: list[dict],
    *,
    club_name: str = "",
    period: str = "",
    run_ids: Optional[list[str]] = None,
) -> DocFacts:
    """Merge a window of processed runs into a season-scope fact base.

    Deterministic roll-up: per-run aggregates summed in code (never an LLM)."""
    run_ids = run_ids or []
    aggs = [compute_aggregates(r) for r in (runs or [])]
    n_meets = sum(1 for a in aggs if not a.is_empty())
    tot = {
        "meets": n_meets,
        "swims": sum(a.n_swims for a in aggs),
        "personal_bests": sum(a.n_pbs for a in aggs),
        "medals_total": sum(a.n_medals for a in aggs),
        "gold": sum(a.n_gold for a in aggs),
        "silver": sum(a.n_silver for a in aggs),
        "bronze": sum(a.n_bronze for a in aggs),
        "club_records": sum(a.n_club_records for a in aggs),
        "finals": sum(a.n_finals for a in aggs),
    }
    # Merge per-swimmer PBs + medals across the window.
    pbs: dict[str, int] = {}
    medals: dict[str, dict[str, int]] = {}
    for a in aggs:
        for name, n in a.pbs_by_swimmer.items():
            pbs[name] = pbs.get(name, 0) + n
        for name, m in a.medals_by_swimmer.items():
            acc = medals.setdefault(name, {"gold": 0, "silver": 0, "bronze": 0})
            for k in ("gold", "silver", "bronze"):
                acc[k] += m.get(k, 0)
    tot["swimmers"] = len({*pbs.keys(), *medals.keys()})

    headline = [
        {"value": str(tot["meets"]), "label": "Meets"},
        {"value": str(tot["personal_bests"]), "label": "Personal bests"},
        {"value": str(tot["medals_total"]), "label": "Medals",
         "sublabel": f"{tot['gold']}G {tot['silver']}S {tot['bronze']}B"},
    ]
    if tot["club_records"]:
        headline.append({"value": str(tot["club_records"]), "label": "Club records"})

    highlights: list[str] = []
    if pbs:
        top_name, top_n = max(pbs.items(), key=lambda kv: (kv[1], kv[0]))
        highlights.append(f"{top_name} set {top_n} personal bests across the {period or 'season'}.")
    if tot["medals_total"]:
        highlights.append(
            f"The club won {tot['medals_total']} medals "
            f"({tot['gold']} gold, {tot['silver']} silver, {tot['bronze']} bronze)."
        )

    facts = DocFacts(
        title=f"{club_name or 'Club'} — {period or 'Season'} report".strip(),
        club_name=club_name,
        period=period,
        scope="season",
        numbers=tot,
        headline_stats=headline,
        highlights=highlights,
        source_refs=[f"run:{rid}" for rid in run_ids] + ["season meet results"],
    )
    pb_t = _pb_makers_table(pbs)
    if pb_t:
        facts.tables["pb_makers"] = pb_t
    md_t = _medal_table(medals)
    if md_t:
        facts.tables["medal_table"] = md_t
    return facts


__all__ = ["DocFacts", "facts_from_run", "facts_from_runs"]
