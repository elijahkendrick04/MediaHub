"""
recognition/swim_tiers.py — deterministic per-swim tiering over a
recognition report.

The recognition engine emits one Achievement per notable *thing* — a single
race can legitimately produce several (a PB, its magnitude derivative, an
official-PB confirmation, a medal…), so ``n_achievements`` overstates how
many *swims* actually stood out. This module answers the honest questions
the UI needs:

  * How many distinct swims were genuinely standout? (``n_standout``)
  * For every analysed swim, what is its score and tier so the review can
    show ALL swims ranked, standouts pinned on top?

It is a pure post-hoc classification over the ranker's existing output
(priority + quality_band) — it never re-scores, never re-ranks, and calls
no AI. The same persisted report dict always yields the same tiers, so old
runs need no migration.

Grouping key: every per-swimmer detector builds its swim_id as
``{swimmer_key}:{dist}{stroke}{course}:<round-or-token><suffix…>``, so the
first two ``:``-segments are the one prefix shared across all id schemes
(pb/medal/official carry the round in segment 3; barrier/qual/rtf/field
substitute a token; club_record appends two suffix segments). Relay ids
(``{club}:{dist}{stroke}:relay:…``) and the multi-PB aggregate
(``{key}:multi_pb``) group on their own two-segment prefixes — they are
meet-level moments, not rows in the per-swim table, but they still count
toward ``n_standout`` when they earn a standout band.
"""

from __future__ import annotations

from typing import Iterable, Optional

# Quality bands that make a swim "standout" — aligned with the recommender's
# notable set (elite + strong). Story/nice detections remain real achievements
# (they keep their cards) but no longer inflate the headline number.
STANDOUT_BANDS: frozenset[str] = frozenset({"elite", "strong"})

# Achievement type created when a human promotes a swim the automation didn't
# flag. Human-promoted moments always count as standout: the club has said
# "this matters", and the headline number should reflect that.
CUSTOM_HIGHLIGHT_TYPE = "custom_highlight"

# Per-swim tiers, strongest first.
TIER_STANDOUT = "standout"  # elite/strong band, or human-promoted
TIER_NOTABLE = "notable"  # has achievements, best band story/nice
TIER_CLOSE_CALL = "close_call"  # nothing fired, but a genuine near-miss
TIER_ORDINARY = "ordinary"  # nothing fired, nothing near — a completed swim

TIER_ORDER: list[str] = [TIER_STANDOUT, TIER_NOTABLE, TIER_CLOSE_CALL, TIER_ORDINARY]

TIER_LABELS: dict[str, str] = {
    TIER_STANDOUT: "Standout",
    TIER_NOTABLE: "Notable",
    TIER_CLOSE_CALL: "Close call",
    TIER_ORDINARY: "Completed swim",
}

_BAND_RANK: dict[str, int] = {
    "elite": 4,
    "strong": 3,
    "story": 2,
    "nice": 1,
    "not_worthy": 0,
}

# Mirrors web.py's close-call rule: every near-miss category except the plain
# "outranked" bucket is worth a reviewer's glance.
_NOT_CLOSE_CALL = ("", "lower_priority")


def swim_group_key(swim_id: str) -> str:
    """The first two ``:``-segments of a detector/trace swim_id — the one
    join prefix every id scheme shares (see module docstring)."""
    parts = (swim_id or "").split(":")
    if len(parts) >= 2:
        return f"{parts[0]}:{parts[1]}"
    return swim_id or ""


def _achievement_of(ra: dict) -> dict:
    ach = ra.get("achievement")
    return ach if isinstance(ach, dict) else ra


def group_ranked_achievements(ranked: Iterable[dict]) -> dict[str, list[dict]]:
    """Group ranked-achievement dicts by underlying swim (insertion-ordered)."""
    groups: dict[str, list[dict]] = {}
    for ra in ranked or []:
        if not isinstance(ra, dict):
            continue
        sid = str(_achievement_of(ra).get("swim_id") or "")
        groups.setdefault(swim_group_key(sid), []).append(ra)
    return groups


def best_band(ras: Iterable[dict]) -> str:
    """The strongest quality band across a swim's ranked achievements."""
    best = ""
    best_rank = -1
    for ra in ras or []:
        band = str(ra.get("quality_band") or "").strip().lower()
        rank = _BAND_RANK.get(band, 0)
        if rank > best_rank:
            best, best_rank = band, rank
    return best


def group_is_standout(ras: Iterable[dict]) -> bool:
    """Standout = ranker's elite/strong band, or a human-promoted highlight."""
    ras = list(ras or [])
    if best_band(ras) in STANDOUT_BANDS:
        return True
    return any(str(_achievement_of(ra).get("type") or "") == CUSTOM_HIGHLIGHT_TYPE for ra in ras)


def standout_summary(rr: Optional[dict]) -> dict:
    """Count distinct standout swims in a recognition-report dict.

    Returns ``{"n_standout": int, "n_swim_groups": int, "standout_keys": set}``.
    Tolerant of legacy/partial reports — missing keys mean zero counts.
    """
    ranked = (rr or {}).get("ranked_achievements") or []
    groups = group_ranked_achievements(ranked)
    standout_keys = {key for key, ras in groups.items() if group_is_standout(ras)}
    return {
        "n_standout": len(standout_keys),
        "n_swim_groups": len(groups),
        "standout_keys": standout_keys,
    }


def n_standout_for_report(rr: Optional[dict]) -> int:
    """Distinct standout swims for a recognition-report dict (0 when absent)."""
    return standout_summary(rr)["n_standout"]


def n_standout_from_run(run_data: Optional[dict]) -> int:
    """Distinct standout swims for a persisted run JSON dict (0 when absent)."""
    rr = (run_data or {}).get("recognition_report")
    return n_standout_for_report(rr if isinstance(rr, dict) else None)


def _is_close_call(near_miss_category: Optional[str]) -> bool:
    return (str(near_miss_category or "")).strip().lower() not in _NOT_CLOSE_CALL


def _attach_to_traces(traces: list[dict], groups: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Assign each achievement group to exactly one swim trace.

    Traces are keyed by their full swim_id (``key:evt:round``). When several
    traces share a group key (a prelim and a final of the same event), each
    achievement goes to the trace whose id is a prefix of the achievement's
    swim_id (round-carrying detectors), longest prefix first; token-round
    achievements (barrier/qual/rtf/field) fall back to the final ("F") round
    when present, else the first trace in report order.
    """
    traces_by_group: dict[str, list[dict]] = {}
    for t in traces:
        traces_by_group.setdefault(swim_group_key(str(t.get("swim_id") or "")), []).append(t)

    attached: dict[str, list[dict]] = {str(t.get("swim_id") or ""): [] for t in traces}
    for gkey, ras in groups.items():
        cands = traces_by_group.get(gkey)
        if not cands:
            continue  # relay / multi-PB / meet-level group — no per-swim row
        # Longest trace id first so "key:evt:FA" wins over "key:evt:F".
        by_len = sorted(cands, key=lambda t: -len(str(t.get("swim_id") or "")))
        fallback = next(
            (t for t in cands if str(t.get("swim_id") or "").split(":")[-1].upper() == "F"),
            cands[0],
        )
        for ra in ras:
            sid = str(_achievement_of(ra).get("swim_id") or "")
            home = next(
                (t for t in by_len if sid.startswith(str(t.get("swim_id") or ""))), fallback
            )
            attached[str(home.get("swim_id") or "")].append(ra)
    return attached


def swim_rows_for_report(rr: Optional[dict]) -> list[dict]:
    """One row per analysed swim, ranked: standouts first, then by score.

    Each row carries::

        swim_id, swimmer_name, event, time_str, tier, tier_label, band,
        score (max ranker priority across the swim's achievements, 0.0 when
        none), achievement_count, near_miss_category, close_call, summary,
        promotable (True when the automation flagged nothing — the swims a
        human may promote to a custom highlight), ranked (the attached
        ranked-achievement dicts, priority-descending)

    Sort order is deterministic: tier (standout → notable → close call →
    ordinary), then score descending, then swimmer name / event / swim_id.
    """
    rr = rr or {}
    traces = [t for t in (rr.get("swim_traces") or []) if isinstance(t, dict)]
    groups = group_ranked_achievements(rr.get("ranked_achievements") or [])
    attached = _attach_to_traces(traces, groups)

    rows: list[dict] = []
    for t in traces:
        sid = str(t.get("swim_id") or "")
        ras = sorted(attached.get(sid, []), key=lambda ra: -float(ra.get("priority", 0.0) or 0.0))
        nm = t.get("near_miss_category")
        if ras:
            band = best_band(ras)
            tier = TIER_STANDOUT if group_is_standout(ras) else TIER_NOTABLE
            score = max(float(ra.get("priority", 0.0) or 0.0) for ra in ras)
        else:
            band = ""
            tier = TIER_CLOSE_CALL if _is_close_call(nm) else TIER_ORDINARY
            score = 0.0
        # Promotable = the automation flagged nothing for this swim. Belt &
        # braces: trust the trace's own engine count AND the group index as
        # well as the attach result, so neither an unattachable achievement
        # id nor a sibling round (a prelim whose final earned the card —
        # same group, promotion would be refused as a duplicate) can make a
        # swim look promotable.
        engine_count = int(t.get("achievement_count") or 0)
        group_has_cards = bool(groups.get(swim_group_key(sid)))
        rows.append(
            {
                "swim_id": sid,
                "swimmer_name": str(t.get("swimmer_name") or ""),
                "event": str(t.get("event") or ""),
                "time_str": str(t.get("time_str") or ""),
                "tier": tier,
                "tier_label": TIER_LABELS[tier],
                "band": band,
                "score": round(score, 4),
                "achievement_count": len(ras),
                "near_miss_category": nm,
                "close_call": (not ras) and _is_close_call(nm),
                "summary": str(t.get("summary") or ""),
                "promotable": not ras and engine_count == 0 and not group_has_cards,
                "ranked": ras,
            }
        )

    tier_pos = {tier: i for i, tier in enumerate(TIER_ORDER)}
    rows.sort(
        key=lambda r: (
            tier_pos.get(r["tier"], len(TIER_ORDER)),
            -r["score"],
            r["swimmer_name"],
            r["event"],
            r["swim_id"],
        )
    )
    return rows
