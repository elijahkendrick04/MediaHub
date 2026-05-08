"""
rank_achievements(achievements, ctx, history_map) -> list[RankedAchievement]

Multi-factor ranking:
  - magnitude_factor: improvement size, time barrier, vs field
  - rarity_factor: medal at high-level meet > medal at club gala
  - meet_level_factor: national > county > university > open
  - narrative_factor: multi-PBs, return to form, biggest drop
  - barrier_factor: sub-X barrier crossing bonus
  - certainty_factor: low confidence reduces priority
  - profile_priority_factor: (V7) club-configured per-achievement-type multiplier

Each factor returns (value 0-1, weight, reason_str).
Final priority = weighted sum / max possible.
Profile priority is ADDITIVE — a new factor in the list that uses the
club's configured multiplier as both value and weight signal.
"""
from __future__ import annotations

from typing import Optional

from .schema import (
    Achievement, RankedAchievement, RankFactor, QualityBand, PostType
)


# ---------------------------------------------------------------------------
# Factor weights
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "magnitude":        0.30,
    "rarity":           0.20,
    "meet_level":       0.15,
    "narrative":        0.15,
    "barrier":          0.10,
    "certainty":        0.10,
    "profile_priority": 0.00,   # Weight is 0 — this factor is applied as a
                                 # multiplicative boost AFTER the weighted sum,
                                 # not as another additive term.
                                 # The factor is recorded in the list for
                                 # transparency; it does not add to max_possible.
}

_MEET_LEVEL_SCORE = {
    "national": 1.0,
    "international": 1.0,
    "university": 0.8,
    "county": 0.6,
    "open": 0.4,
    "club": 0.2,
}

_TYPE_NARRATIVE_BONUS = {
    "multi_pb_weekend": 1.0,
    "biggest_drop_candidate": 0.8,
    "return_to_form": 0.7,
    "fastest_since": 0.5,
    "heat_to_final_drop": 0.4,
    "final_appearance": 0.3,
}

_TYPE_MAGNITUDE = {
    "medal_gold": 1.0,
    "medal_silver": 0.8,
    "medal_bronze": 0.6,
    "first_sub_barrier": 0.9,
    "pb_magnitude_huge": 0.95,
    "pb_magnitude_big": 0.75,
    "pb_magnitude_notable": 0.55,
    "pb_confirmed": 0.5,
    "pb_likely": 0.35,
    "qual_hit_in_window": 0.7,
    "qual_hit_out_of_window": 0.4,
    "top_of_field_top_3": 0.8,
    "top_of_field_top_5": 0.55,
    "top_of_field_top_10": 0.35,
    "relay_medal_gold": 0.7,
    "relay_medal_silver": 0.5,
    "relay_medal_bronze": 0.4,
}


def _magnitude_factor(a: Achievement, ctx) -> tuple[float, float, str]:
    base = _TYPE_MAGNITUDE.get(a.type, 0.3)
    # Boost by improvement % if available
    drop_pct = a.raw_facts.get("drop_pct", 0.0) or 0.0
    if drop_pct > 0:
        boost = min(0.2, drop_pct / 20.0)
        base = min(1.0, base + boost)
    reason = f"type {a.type} base magnitude {base:.2f}"
    return base, _WEIGHTS["magnitude"], reason


def _rarity_factor(a: Achievement, ctx) -> tuple[float, float, str]:
    """How rare is this achievement given the competition context?"""
    # Meet level affects rarity of medals
    meet_level = ctx.meet_level if ctx else "open"
    level_score = _MEET_LEVEL_SCORE.get(meet_level, 0.4)

    if "medal" in a.type:
        rarity = level_score
    elif "first_sub_barrier" in a.type:
        rarity = 0.8
    elif "biggest_drop" in a.type:
        rarity = 0.6
    elif "qual_hit_in_window" in a.type:
        rarity = 0.7
    else:
        rarity = 0.3

    reason = f"rarity={rarity:.2f} at {meet_level} meet"
    return rarity, _WEIGHTS["rarity"], reason


def _meet_level_factor(a: Achievement, ctx) -> tuple[float, float, str]:
    meet_level = ctx.meet_level if ctx else "open"
    score = _MEET_LEVEL_SCORE.get(meet_level, 0.4)
    reason = f"meet level '{meet_level}' → {score:.2f}"
    return score, _WEIGHTS["meet_level"], reason


def _narrative_factor(a: Achievement, ctx) -> tuple[float, float, str]:
    bonus = _TYPE_NARRATIVE_BONUS.get(a.type, 0.0)
    # PB achievements get a small narrative bump when they come with story
    if "pb" in a.type and a.raw_facts.get("drop_pct", 0) > 2.0:
        bonus = max(bonus, 0.4)
    reason = f"narrative bonus {bonus:.2f} for {a.type}"
    return bonus, _WEIGHTS["narrative"], reason


def _barrier_factor(a: Achievement, ctx) -> tuple[float, float, str]:
    if "barrier" in a.type:
        return 1.0, _WEIGHTS["barrier"], "first-time sub-barrier crossing"
    return 0.0, _WEIGHTS["barrier"], "no barrier crossing"


def _certainty_factor(a: Achievement, ctx) -> tuple[float, float, str]:
    c = a.confidence
    # Penalise uncertainty notes
    penalty = len(a.uncertainty_notes) * 0.05
    score = max(0.0, c - penalty)
    reason = f"confidence {c:.2f} - uncertainty penalty {penalty:.2f}"
    return score, _WEIGHTS["certainty"], reason


def _profile_priority_factor(a: Achievement, ctx) -> tuple[float, float, str]:
    """
    V7 additive factor: club-configured priority multiplier for this achievement type.

    The value is the configured multiplier (1.0 = neutral, >1.0 = boost, <1.0 = suppress).
    Weight is 0 — the factor is recorded for transparency but not counted in the
    weighted-sum denominator.  The multiplier is applied after the base priority is
    computed (see _compute_priority).
    """
    multiplier = 1.0
    reason = "no profile priority override"

    if ctx is not None:
        # ctx.profile may be a ClubProfile or a dict
        profile = getattr(ctx, "profile", None)
        if profile is not None:
            try:
                multiplier = float(
                    profile.get_achievement_priority(a.type)
                    if hasattr(profile, "get_achievement_priority")
                    else profile.get("achievement_priorities", {}).get(
                        a.type,
                        profile.get("achievement_priorities", {}).get("_default", 1.0)
                    )
                )
                reason = f"Club priority for {a.type} = {multiplier:.2f}"
            except Exception:
                pass

    return multiplier, _WEIGHTS["profile_priority"], reason


def _compute_priority(a: Achievement, ctx) -> tuple[float, list[RankFactor]]:
    factors = []
    weighted_sum = 0.0
    max_possible = 0.0
    profile_multiplier = 1.0

    for name, fn in [
        ("magnitude", _magnitude_factor),
        ("rarity", _rarity_factor),
        ("meet_level", _meet_level_factor),
        ("narrative", _narrative_factor),
        ("barrier", _barrier_factor),
        ("certainty", _certainty_factor),
        ("profile_priority", _profile_priority_factor),
    ]:
        value, weight, reason = fn(a, ctx)
        factors.append(RankFactor(name=name, value=round(value, 4), weight=weight, reason=reason))

        if name == "profile_priority":
            # Store multiplier to apply after weighted sum; don't add to denominator
            profile_multiplier = value
        else:
            weighted_sum += value * weight
            max_possible += 1.0 * weight

    base_priority = weighted_sum / max_possible if max_possible > 0 else 0.0

    # Apply profile priority as a multiplicative scaling of the base score
    # Clamp to [0, 1]
    priority = min(1.0, max(0.0, base_priority * profile_multiplier))
    return priority, factors


def _assign_quality_band(priority: float, achievement_type: str) -> QualityBand:
    """Map priority score + type to a quality band."""
    if priority >= 0.80 or achievement_type in ("medal_gold", "first_sub_barrier", "pb_magnitude_huge"):
        return QualityBand.ELITE
    if priority >= 0.60 or achievement_type in ("medal_silver", "qual_hit_in_window", "pb_magnitude_big"):
        return QualityBand.STRONG
    if priority >= 0.40 or achievement_type in ("return_to_form", "multi_pb_weekend", "fastest_since"):
        return QualityBand.STORY
    if priority >= 0.20 or achievement_type in ("pb_confirmed", "pb_likely", "medal_bronze"):
        return QualityBand.NICE
    return QualityBand.NOT_WORTHY


def _assign_post_type(band: QualityBand, achievement_type: str, ctx) -> PostType:
    if band == QualityBand.ELITE:
        return PostType.MAIN_FEED
    if band == QualityBand.STRONG:
        # University-level gets main feed; lower gets story
        if ctx and ctx.meet_level in ("national", "university"):
            return PostType.MAIN_FEED
        return PostType.STORY
    if band == QualityBand.STORY:
        return PostType.STORY
    if band == QualityBand.NICE:
        return PostType.RECAP
    return PostType.INTERNAL_NOTE


def rank_achievements(
    achievements: list[Achievement],
    ctx,
    history_map: Optional[dict] = None,
) -> list[RankedAchievement]:
    """
    Rank a list of achievements. Returns list sorted by priority descending.
    Assigns rank integers starting at 1.

    ctx may optionally carry a .profile attribute (ClubProfile) so the
    profile_priority_factor can read per-club achievement weights.
    """
    ranked: list[tuple[float, RankedAchievement]] = []

    for a in achievements:
        priority, factors = _compute_priority(a, ctx)
        band = _assign_quality_band(priority, a.type)
        post_type = _assign_post_type(band, a.type, ctx)

        # V7.3: derive safe_to_post and post_angle
        safe_to_post_obj = None
        try:
            from swim_content_v5.recommender import derive_safe_to_post
            safe_to_post_obj = derive_safe_to_post(a)
        except Exception:
            pass
        
        # V7.3: determine post_angle from achievement type
        _POST_ANGLE_MAP = {
            "official_pb_confirmed": "confirmed_official_pb",
            "pb_confirmed": "pb_improvement",
            "pb_magnitude_huge": "pb_improvement",
            "pb_magnitude_big": "pb_improvement",
            "pb_magnitude_notable": "pb_improvement",
            "pb_likely": "likely_pb",
            "first_sub_barrier": "first_sub_barrier",
            "medal_gold": "medal_gold",
            "medal_silver": "medal_silver",
            "medal_bronze": "medal_bronze",
            "final_appearance": "finalist",
            "heat_to_final_drop": "heat_to_final_drop",
            "top_of_field_top_3": "top_of_field",
            "top_of_field_top_5": "top_of_field",
            "top_of_field_top_10": "top_of_field",
            "qual_hit_in_window": "qualifying_time",
            "qual_hit_out_of_window": "qualifying_time",
            "biggest_drop_of_meet": "biggest_drop",
            "biggest_drop_candidate": "biggest_drop",
            "fastest_since": "fastest_since",
            "multi_pb_weekend": "multi_pb_weekend",
            "return_to_form": "return_to_form",
            "relay_medal_gold": "relay_highlight",
            "relay_medal_silver": "relay_highlight",
            "relay_medal_bronze": "relay_highlight",
            "relay_strong": "relay_highlight",
        }
        post_angle_str = _POST_ANGLE_MAP.get(a.type, "recap_mention")
        # Set post_angle on the achievement if it supports it
        try:
            if not getattr(a, "post_angle", None):
                object.__setattr__(a, "post_angle", post_angle_str)
        except Exception:
            pass
        
        ra = RankedAchievement(
            achievement=a,
            priority=round(priority, 4),
            factors=factors,
            quality_band=band,
            suggested_post_type=post_type,
        )
        # Set V7.3 extended fields
        try:
            object.__setattr__(ra, "safe_to_post", safe_to_post_obj)
            object.__setattr__(ra, "post_angle", post_angle_str)
        except Exception:
            pass
        ranked.append((priority, ra))

    # Sort by priority descending
    ranked.sort(key=lambda x: -x[0])

    # Assign ranks
    result: list[RankedAchievement] = []
    for i, (_, ra) in enumerate(ranked):
        ra.rank = i + 1
        result.append(ra)

    return result
