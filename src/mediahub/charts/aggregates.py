"""charts.aggregates — the deterministic fact base behind charts & insights (roadmap 1.11).

Everything a chart plots or an insight phrases is computed **here, in code** — never
by an LLM (CLAUDE.md rule 5). This module walks a processed run (the canonical meet +
the recognition report the deterministic detectors produced) and rolls it up into
exact aggregates: how many swam, how many PB'd, the medal tally, the biggest time
drop, PBs per swimmer.

Crucially it consumes the **detector output** (``recognition_report.ranked_achievements``)
rather than re-deciding "is this a PB / a medal?" — that judgement already happened in
the deterministic engine (``recognition_swim``), and this layer must not second-guess
it. Each fact also records the **source rows** it came from, so an insight can cite
its evidence (the explainability rule) and a reader can trace any number back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Achievement type → bucket. We read the detectors' own type strings; this is a
# classification of *their* output, not a re-detection.
_PB_TYPES = ("pb_confirmed", "official_pb", "pb_magnitude")
_GOLD_TYPES = ("medal_gold", "relay_medal_gold")
_SILVER_TYPES = ("medal_silver", "relay_medal_silver")
_BRONZE_TYPES = ("medal_bronze", "relay_medal_bronze")
_FINAL_TYPES = ("final_appearance", "heat_to_final")


@dataclass
class MeetAggregates:
    """Exact, deterministic roll-up of one processed run."""

    meet_name: str = ""
    n_swimmers: int = 0
    n_swims: int = 0
    n_pbs: int = 0
    n_medals: int = 0
    n_gold: int = 0
    n_silver: int = 0
    n_bronze: int = 0
    n_finals: int = 0
    n_club_records: int = 0
    swimmers_with_pb: int = 0  # distinct swimmers who set >=1 PB (the conversion numerator)
    pb_rate_pct: float = 0.0  # distinct PB swimmers as a % of swimmers who raced (<=100)
    pbs_by_swimmer: dict[str, int] = field(default_factory=dict)
    medals_by_swimmer: dict[str, dict[str, int]] = field(default_factory=dict)  # name → {gold,silver,bronze}
    biggest_drop: Optional[dict] = None  # {swimmer, event, seconds, pct, source_ref}
    most_pbs: Optional[tuple[str, int]] = None
    # fact name → list of source refs (provenance for every headline number)
    sources: dict[str, list[str]] = field(default_factory=dict)

    def to_facts(self) -> dict:
        """A flat, numbers-only dict for the insights LLM (it phrases, never computes)."""
        facts: dict = {
            "meet_name": self.meet_name,
            "swimmers": self.n_swimmers,
            "swims": self.n_swims,
            "personal_bests": self.n_pbs,
            "medals_total": self.n_medals,
            "gold": self.n_gold,
            "silver": self.n_silver,
            "bronze": self.n_bronze,
            "finals": self.n_finals,
            "club_records": self.n_club_records,
            "swimmers_with_pb": self.swimmers_with_pb,
            "pb_conversion_percent": round(self.pb_rate_pct, 1),
        }
        if self.most_pbs:
            facts["most_pbs_swimmer"] = self.most_pbs[0]
            facts["most_pbs_count"] = self.most_pbs[1]
        if self.biggest_drop:
            facts["biggest_drop_swimmer"] = self.biggest_drop.get("swimmer", "")
            facts["biggest_drop_event"] = self.biggest_drop.get("event", "")
            facts["biggest_drop_seconds"] = round(float(self.biggest_drop.get("seconds", 0.0)), 2)
        return facts

    def sources_for(self, fact: str) -> list[str]:
        return list(self.sources.get(fact, []))

    def is_empty(self) -> bool:
        return self.n_swims == 0 and self.n_pbs == 0 and self.n_medals == 0


def compute_aggregates(run_data: dict) -> MeetAggregates:
    """Roll a processed run (as loaded from ``runs_v4/<id>.json``) into exact aggregates."""
    agg = MeetAggregates()
    if not isinstance(run_data, dict):
        return agg

    meet = run_data.get("canonical_meet") or {}
    report = run_data.get("recognition_report") or {}
    agg.meet_name = str(report.get("meet_name") or meet.get("name") or "Meet").strip()

    # Swim count + swimmer count come from the canonical meet (raw truth): the
    # roster that actually raced is the conversion denominator ("X of N swimmers").
    results = meet.get("results") or []
    agg.n_swims = report.get("n_swims_analysed") or len(results)
    raced_ids = {str(r.get("swimmer_key")) for r in results if r.get("swimmer_key")}

    ranked = report.get("ranked_achievements") or []
    pb_swimmer_ids: set[str] = set()
    seen_drop: Optional[dict] = None
    for ra in ranked:
        a = (ra.get("achievement") or {}) if isinstance(ra, dict) else {}
        atype = str(a.get("type", ""))
        name = str(a.get("swimmer_name", "")).strip()
        sid = str(a.get("swimmer_id", "")).strip()
        event = str(a.get("event", "")).strip()
        raw = a.get("raw_facts") or {}
        ref = a.get("swim_id") or f"{atype}:{name}:{event}"

        if _any_in(atype, _PB_TYPES):
            agg.n_pbs += 1
            if sid or name:
                pb_swimmer_ids.add(sid or name)
            if name:
                agg.pbs_by_swimmer[name] = agg.pbs_by_swimmer.get(name, 0) + 1
            agg.sources.setdefault("personal_bests", []).append(str(ref))

        medal_key = _medal_key(atype)
        if medal_key:
            agg.n_medals += 1
            setattr(agg, f"n_{medal_key}", getattr(agg, f"n_{medal_key}") + 1)
            if name:
                m = agg.medals_by_swimmer.setdefault(name, {"gold": 0, "silver": 0, "bronze": 0})
                m[medal_key] += 1
            agg.sources.setdefault("medals_total", []).append(str(ref))

        if _any_in(atype, _FINAL_TYPES):
            agg.n_finals += 1

        if atype == "club_record":
            agg.n_club_records += 1
            agg.sources.setdefault("club_records", []).append(str(ref))

        # Track the single biggest time drop of the meet.
        drop = _drop_seconds(raw)
        if drop is not None and (seen_drop is None or drop > seen_drop["seconds"]):
            seen_drop = {
                "swimmer": name,
                "event": event,
                "seconds": drop,
                "pct": float(raw.get("drop_pct", 0.0) or 0.0),
                "source_ref": str(ref),
            }

    # Distinct swimmers who raced (denominator), preferring the canonical roster.
    agg.n_swimmers = len(raced_ids) or len(meet.get("swimmers") or {}) or len(pb_swimmer_ids)
    agg.swimmers_with_pb = len(pb_swimmer_ids)
    agg.biggest_drop = seen_drop
    if seen_drop:
        agg.sources.setdefault("biggest_drop", []).append(seen_drop["source_ref"])

    if agg.pbs_by_swimmer:
        top = max(agg.pbs_by_swimmer.items(), key=lambda kv: (kv[1], kv[0]))
        agg.most_pbs = top
    if agg.n_swimmers > 0:
        # A true conversion rate: distinct PB swimmers / swimmers who raced (<=100%).
        agg.pb_rate_pct = min(100.0, 100.0 * agg.swimmers_with_pb / agg.n_swimmers)
    return agg


# --------------------------------------------------------------------------- #
# helpers (deterministic, no deps)
# --------------------------------------------------------------------------- #
def _any_in(atype: str, needles: tuple[str, ...]) -> bool:
    return any(n in atype for n in needles)


def _medal_key(atype: str) -> str:
    if _any_in(atype, _GOLD_TYPES):
        return "gold"
    if _any_in(atype, _SILVER_TYPES):
        return "silver"
    if _any_in(atype, _BRONZE_TYPES):
        return "bronze"
    return ""


def _drop_seconds(raw: dict) -> Optional[float]:
    """A positive 'time improved by N seconds' value, if the fact carries one."""
    for key in ("drop_seconds", "improvement_seconds", "pb_drop_seconds"):
        v = raw.get(key)
        if v is None:
            continue
        try:
            f = abs(float(v))
        except (TypeError, ValueError):
            continue
        if f > 0:
            return f
    return None


__all__ = ["MeetAggregates", "compute_aggregates"]
