"""
recognition/explainer.py — "Why this card?" plain-English explanations.

``explain_achievement(achievement, factors)`` takes the structured achievement
dict (with its evidence quotes) and the ranker's factor list, and returns a
plain-English explanation suitable for the review UI / content pack:

    {
      "headline":     "This swim ranked highly because …",       # 15-25 words
      "bullets":      ["Confirmed PB", "Strong field", …],        # 3-5 bullets
      "source_lines": [{"file_offset": int|None,
                        "raw_text":   str,                        # verbatim quote
                        "label":      str}],                      # 1-3 entries
    }

The explanation is **strictly grounded**: every bullet is derived from a real
``RankFactor`` (using its ``plain_summary`` field), and every source line is a
verbatim quote from the achievement's evidence entries. No AI rewording is
performed — these are evidence quotes only.

If neither the factor list nor the evidence yields enough grounding, the
function returns a fallback explanation that says only what is provable:

    {"headline": "Generated for: ranked top-N by overall score.",
     "bullets": [],
     "source_lines": []}
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TYPE_PHRASE = {
    "official_pb_confirmed": "an officially-confirmed personal best",
    "pb_confirmed":          "a confirmed personal best",
    "pb_likely":             "a likely personal best",
    "pb_magnitude_huge":     "a huge personal-best improvement",
    "pb_magnitude_big":      "a big personal-best improvement",
    "pb_magnitude_notable":  "a notable personal-best improvement",
    "first_sub_barrier":     "a first-time sub-barrier swim",
    "medal_gold":            "a gold medal",
    "medal_silver":          "a silver medal",
    "medal_bronze":          "a bronze medal",
    "relay_medal_gold":      "a gold-medal relay performance",
    "relay_medal_silver":    "a silver-medal relay performance",
    "relay_medal_bronze":    "a bronze-medal relay performance",
    "qual_hit_in_window":    "a qualifying-time hit inside the window",
    "qual_hit_out_of_window": "a qualifying-time hit",
    "top_of_field_top_3":    "a top-3 finish",
    "top_of_field_top_5":    "a top-5 finish",
    "top_of_field_top_10":   "a top-10 finish",
    "multi_pb_weekend":      "a multi-PB weekend",
    "biggest_drop_candidate": "one of the biggest time drops of the meet",
    "return_to_form":        "a return-to-form swim",
    "fastest_since":         "the fastest swim since a long break",
    "heat_to_final_drop":    "a heat-to-final improvement",
    "final_appearance":      "a final appearance",
}


def _achievement_phrase(a_type: str, profile=None) -> str:
    """Plain English noun phrase for an achievement type.

    When ``profile`` carries an AI-derived ``brand_operating_profile``
    with a per-type phrase override, that wins. Otherwise we fall back
    to the hardcoded default and finally to a slug-prettified version.
    """
    default = _TYPE_PHRASE.get(a_type, (a_type or "a notable swim").replace("_", " "))
    if profile is None:
        return default
    try:
        from mediahub.brand.derived import type_phrase_for
    except Exception:
        return default
    return type_phrase_for(profile, a_type, default)


def _factor_dict(f: Any) -> dict:
    """Normalise a RankFactor-or-dict to a plain dict."""
    if isinstance(f, dict):
        return f
    if hasattr(f, "to_dict"):
        try:
            return f.to_dict()
        except Exception:
            pass
    return {
        "name":          getattr(f, "name", ""),
        "value":         getattr(f, "value", 0.0),
        "weight":        getattr(f, "weight", 0.0),
        "reason":        getattr(f, "reason", ""),
        "plain_summary": getattr(f, "plain_summary", ""),
    }


def _significant_factors(factors: list[dict]) -> list[dict]:
    """Factors that meaningfully contributed (value × weight or value alone)."""
    out: list[dict] = []
    for f in factors:
        name = f.get("name", "")
        val = float(f.get("value", 0.0) or 0.0)
        wt = float(f.get("weight", 0.0) or 0.0)
        contribution = val * wt
        # profile_priority has weight 0 but its value matters when it's not the
        # neutral 1.0 multiplier.
        if name == "profile_priority":
            if abs(val - 1.0) > 0.05:
                out.append(f)
            continue
        if contribution >= 0.05 or val >= 0.5:
            out.append(f)
    # Rank highest-contribution first
    out.sort(
        key=lambda g: float(g.get("value", 0.0) or 0.0) * float(g.get("weight", 0.0) or 0.0),
        reverse=True,
    )
    return out


def _build_headline(achievement: dict, sig_factors: list[dict], profile=None) -> str:
    """Compose a 15-25 word headline using the achievement type + top factors."""
    phrase = _achievement_phrase(achievement.get("type", ""), profile=profile)
    confidence_label = (achievement.get("confidence_label") or "").lower()
    swimmer = (achievement.get("swimmer_name") or "").strip()
    event = (achievement.get("event") or "").strip()

    drivers: list[str] = []
    seen = set()
    for f in sig_factors[:3]:
        ps = (f.get("plain_summary") or "").strip()
        name = f.get("name", "")
        if not ps or name in seen:
            continue
        seen.add(name)
        drivers.append(ps.rstrip(".").lower())

    drivers_clause = ""
    if drivers:
        if len(drivers) == 1:
            drivers_clause = f" — driven by {drivers[0]}"
        else:
            drivers_clause = f" — driven by {drivers[0]} and {drivers[1]}"

    subject = "This swim"
    if swimmer and event:
        subject = f"{swimmer}'s {event} swim"
    elif swimmer:
        subject = f"{swimmer}'s swim"

    conf_clause = ""
    if confidence_label == "high":
        conf_clause = ", with high data confidence"
    elif confidence_label == "low":
        conf_clause = ", but with lower data confidence"

    headline = f"{subject} surfaced as {phrase}{drivers_clause}{conf_clause}."

    # Soft trim to ~25 words.
    words = headline.split()
    if len(words) > 25:
        headline = " ".join(words[:25]).rstrip(",.;: ") + "."
    return headline


def _build_bullets(achievement: dict, sig_factors: list[dict]) -> list[str]:
    """3-5 short bullets — one per contributing factor, plus a confidence note."""
    bullets: list[str] = []
    seen: set[str] = set()
    for f in sig_factors:
        ps = (f.get("plain_summary") or "").strip()
        if not ps:
            continue
        if ps in seen:
            continue
        seen.add(ps)
        bullets.append(ps)
        if len(bullets) >= 4:
            break

    # Always include a confidence bullet if we have one (and it's not already there).
    cl = (achievement.get("confidence_label") or "").lower()
    cv = achievement.get("confidence")
    if cl and cv is not None:
        try:
            cv_f = float(cv)
            conf_msg = f"Detector confidence: {cl} ({cv_f:.2f})."
        except (TypeError, ValueError):
            conf_msg = f"Detector confidence: {cl}."
        if conf_msg not in seen:
            bullets.append(conf_msg)

    # Cap at 5 bullets total.
    return bullets[:5]


def _build_source_lines(achievement: dict) -> list[dict]:
    """Up to 3 verbatim quotes from the achievement's evidence entries."""
    evidence = achievement.get("evidence") or []
    out: list[dict] = []
    for idx, ev in enumerate(evidence[:3]):
        if not isinstance(ev, dict):
            # Could be an AchievementEvidence dataclass; normalise.
            try:
                ev = ev.to_dict()
            except Exception:
                continue
        raw_text = (ev.get("statement") or "").strip()
        if not raw_text:
            continue
        source_name = (ev.get("source_name") or "").strip()
        source_type = (ev.get("source_type") or "").strip()
        if source_name and source_type and source_type != source_name:
            label = f"{source_name} ({source_type.replace('_', ' ')})"
        elif source_name:
            label = source_name
        elif source_type:
            label = source_type.replace("_", " ")
        else:
            label = "source"
        out.append({
            "file_offset": idx,            # position in the achievement's evidence list
            "raw_text":    raw_text,        # verbatim — not AI-reworded
            "label":       label,
        })
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def explain_achievement(
    achievement: dict | None,
    factors: list[Any] | None,
    *,
    rank: int | None = None,
    profile=None,
) -> dict:
    """Build a plain-English "Why this card?" explanation.

    Parameters
    ----------
    achievement : dict
        The achievement dict (as serialised by ``Achievement.to_dict()``).
        May be ``None`` or empty — the function then returns a generic fallback.
    factors : list of RankFactor or dict
        The ranker's factor list. Each item should have ``name``, ``value``,
        ``weight``, ``reason``, and (post-V9) ``plain_summary``.
    rank : int, optional
        The 1-based rank of this achievement, used only in the fallback
        message ("ranked top-N by overall score") when no factors / evidence
        are available.

    Returns
    -------
    dict
        ``{"headline": str, "bullets": list[str], "source_lines": list[dict]}``.
    """
    a = achievement or {}
    raw_factors = [_factor_dict(f) for f in (factors or [])]

    sig_factors = _significant_factors(raw_factors)
    source_lines = _build_source_lines(a)

    # Grounded only if we have at least one significant factor OR one evidence line.
    if not sig_factors and not source_lines:
        rank_label = f"top-{rank}" if rank else "top-N"
        return {
            "headline":     f"Generated for: ranked {rank_label} by overall score.",
            "bullets":      [],
            "source_lines": [],
        }

    return {
        "headline":     _build_headline(a, sig_factors, profile=profile),
        "bullets":      _build_bullets(a, sig_factors),
        "source_lines": source_lines,
    }


__all__ = ["explain_achievement"]
