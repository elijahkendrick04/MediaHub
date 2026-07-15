"""
rank_achievements(achievements, ctx, history_map) -> list[RankedAchievement]

Multi-factor ranking:
  - magnitude_factor: improvement size, time barrier, vs field
  - rarity_factor: medal at high-level meet > medal at club gala
  - meet_level_factor: national/international > university > regional > county > open > club
  - narrative_factor: multi-PBs, return to form, biggest drop
  - barrier_factor: sub-X barrier crossing bonus
  - certainty_factor: low confidence reduces priority
  - recency_factor: (weight 0) how recently the swimmer last competed in this
                    event, read from ``history_map``; recorded for
                    explainability and used only as a deterministic tie-break.
  - profile_priority_factor: (V7) club-configured per-achievement-type
                    MULTIPLIER, applied after the weighted sum.

Factor contract:
  Every *scoring* factor returns ``(value, weight, reason)`` where ``value`` is
  in ``[0, 1]`` and ``weight`` is its share of the weighted sum. Two factors are
  deliberate exceptions and carry weight 0 so they never enter the weighted-sum
  denominator:
    * ``recency`` — value in [0, 1], recorded for explainability + tie-break.
    * ``profile_priority`` — value is the club's configured MULTIPLIER
      (>= 0, 1.0 = neutral). It is applied **multiplicatively** to the
      weighted-sum base score (NOT additively), via an order-preserving boost
      that never collapses the ranking among boosted cards (see
      ``_compute_priority``).

Final priority = order-preserving(profile_multiplier, weighted_sum / max_possible).

Deterministic tie-break (F34): equal-priority achievements are ordered by
``score (priority) > PB confidence > recency > swim_id`` so the published order
never depends on detector emission order.

Coverage note (F59): coverage's ``--include`` globs need ``**`` to cross ``/``.
Measure this module's real coverage with e.g.::

    coverage run --include="**/swim_content_v5/ranker.py" -m pytest tests/ -q
    coverage report -m

A single-``*`` pattern such as ``*swim_content_v5/ranker.py`` silently collects
no data under coverage 7.x and reports 0%.
"""
from __future__ import annotations

import logging
from typing import Optional

from .schema import (
    Achievement, RankedAchievement, RankFactor, QualityBand, PostType
)

logger = logging.getLogger(__name__)


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
    "recency":          0.00,   # Weight 0 — recorded for explainability and
                                # used only as a deterministic tie-break; does
                                # not enter the weighted-sum denominator.
    "profile_priority": 0.00,   # Weight 0 — this factor is applied as an
                                # order-preserving multiplicative boost AFTER
                                # the weighted sum, not as another additive
                                # term. Recorded in the factor list for
                                # transparency; it does not add to max_possible.
}

_MEET_LEVEL_SCORE = {
    "international": 1.0,
    "national": 1.0,
    "regional": 0.75,   # UK hierarchy: national > regional > county > open
    "university": 0.8,
    "county": 0.6,
    "open": 0.4,
    "club": 0.2,
}

_TYPE_NARRATIVE_BONUS = {
    "club_record": 0.9,        # old mark vs new mark is a ready-made story
    "club_debut": 0.6,
    "race_milestone_25": 0.5,
    "race_milestone_50": 0.6,
    "race_milestone_100": 0.7,
    "race_milestone_250": 0.7,
    "race_milestone_500": 0.7,
    "multi_pb_weekend": 1.0,
    "biggest_drop_of_meet": 0.8,   # the relabelled winner (F08)
    "biggest_drop_candidate": 0.8,
    "return_to_form": 0.7,
    "fastest_since": 0.5,
    "heat_to_final_drop": 0.4,
    "final_appearance": 0.3,
}

_TYPE_MAGNITUDE = {
    "club_record": 1.0,   # W.3: the club's highest-emotion moment. Value stays
                          # in the [0,1] contract; club_record is kept top of
                          # every PB and gold via its high rarity + narrative
                          # and the ELITE band override, NOT via a >1.0 value
                          # (which used to invert when drop_pct was present).
    "club_debut": 0.65,
    "race_milestone_25": 0.6,
    "race_milestone_50": 0.75,
    "race_milestone_100": 0.85,
    "race_milestone_250": 0.9,
    "race_milestone_500": 0.95,
    "first_event_swim": 0.35,
    "medal_gold": 1.0,
    "medal_silver": 0.8,
    "medal_bronze": 0.6,
    "first_sub_barrier": 0.9,
    "pb_magnitude_huge": 0.95,
    "pb_magnitude_big": 0.75,
    "pb_magnitude_notable": 0.55,
    "official_pb_confirmed": 0.9,   # flagship, verified PB confirmation (F07)
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
    "relay_strong_performance": 0.35,  # detector's actual type (F19)
    "multi_pb_weekend": 0.7,           # aggregate weekend story (F07)
    "biggest_drop_of_meet": 0.7,       # relabelled headline drop (F08); +drop boost
    "biggest_drop_candidate": 0.6,
    "fastest_since": 0.5,
    "return_to_form": 0.55,
    "final_appearance": 0.45,
    "heat_to_final_drop": 0.45,
}


def _as_float(value, default: float = 0.0) -> float:
    """Coerce a raw_facts value to a finite float, or the default.

    ``drop_pct`` (and similar numeric raw_facts) may arrive as ``None``, a
    string, a list, or NaN/inf from a persisted JSON run or an externally
    produced detector. The plain ``x or 0.0`` idiom only rescues *falsy*
    values — a wrong *type* still raises when compared with ``>``. This coerces
    anything non-numeric (or non-finite) to ``default`` so the ranker can never
    crash on a malformed fact (F13).
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float("inf"), float("-inf")):   # NaN / ±inf
        return default
    return f


def _drop_pct(a: Achievement) -> float:
    raw = a.raw_facts if isinstance(a.raw_facts, dict) else {}
    return _as_float(raw.get("drop_pct"), 0.0)


def _magnitude_factor(a: Achievement, ctx) -> tuple[float, float, str]:
    base = _TYPE_MAGNITUDE.get(a.type, 0.3)
    # Boost by improvement % if available. drop_pct is coerced defensively — it
    # may be None / a string / non-finite on persisted or externally-produced
    # achievements (F13).
    drop_pct = _drop_pct(a)
    if drop_pct > 0:
        boost = min(0.2, drop_pct / 20.0)
        base = min(1.0, base + boost)   # boost only raises; never lowers (F14)
    reason = f"type {a.type} base magnitude {base:.2f}"
    return base, _WEIGHTS["magnitude"], reason


def _rarity_factor(a: Achievement, ctx) -> tuple[float, float, str]:
    """How rare is this achievement given the competition context?"""
    # Meet level affects rarity of medals
    meet_level = getattr(ctx, "meet_level", None) or "open" if ctx else "open"
    level_score = _MEET_LEVEL_SCORE.get(meet_level, 0.4)

    if a.type == "club_record":
        # A club all-time record is the rarest achievement for that club,
        # independent of the meet's level. This keeps it above any gold.
        rarity = 1.0
    elif "medal" in a.type:
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
    meet_level = getattr(ctx, "meet_level", None) or "open" if ctx else "open"
    score = _MEET_LEVEL_SCORE.get(meet_level, 0.4)
    reason = f"meet level '{meet_level}' → {score:.2f}"
    return score, _WEIGHTS["meet_level"], reason


def _narrative_factor(a: Achievement, ctx) -> tuple[float, float, str]:
    bonus = _TYPE_NARRATIVE_BONUS.get(a.type, 0.0)
    # PB achievements get a small narrative bump when they come with story.
    # drop_pct is coerced defensively (None / string / non-finite) so the
    # comparison can't raise (F13).
    if "pb" in a.type and _drop_pct(a) > 2.0:
        bonus = max(bonus, 0.4)
    reason = f"narrative bonus {bonus:.2f} for {a.type}"
    return bonus, _WEIGHTS["narrative"], reason


def _barrier_factor(a: Achievement, ctx) -> tuple[float, float, str]:
    if "barrier" in a.type:
        return 1.0, _WEIGHTS["barrier"], "first-time sub-barrier crossing"
    return 0.0, _WEIGHTS["barrier"], "no barrier crossing"


def _certainty_factor(a: Achievement, ctx) -> tuple[float, float, str]:
    c = a.confidence if isinstance(a.confidence, (int, float)) else 0.0
    notes = a.uncertainty_notes or []
    n = len(notes)
    # Penalise uncertainty notes. For 0–1 notes this is EXACTLY the old flat
    # 0.05/note behaviour at every confidence. For >= 2 notes the penalty is
    # capped at half the confidence so perfect confidence with several caveat
    # notes stays clearly above a genuinely zero-confidence achievement and the
    # reported penalty can never exceed the confidence (no nonsensical >1
    # penalty) (F54).
    raw_penalty = 0.05 * n
    penalty = raw_penalty if n <= 1 else min(raw_penalty, c * 0.5)
    score = max(0.0, c - penalty)
    reason = f"confidence {c:.2f} - uncertainty penalty {penalty:.2f}"
    return score, _WEIGHTS["certainty"], reason


def _recency_value(a: Achievement, ctx, history_map) -> float:
    """Recency of the swimmer's most recent prior swim vs the meet date.

    Returns a value in [0, 1]: 1.0 = swum right before this meet, 0.0 = a year+
    ago, 0.5 = unknown (no history data, no dates, or no meet date). Purely
    deterministic and defensive — any missing/unparseable input yields the
    neutral 0.5.
    """
    if not history_map:
        return 0.5
    hist = history_map.get(getattr(a, "swimmer_id", "")) if hasattr(history_map, "get") else None
    if hist is None or not getattr(hist, "has_data", False):
        return 0.5

    last_iso: Optional[str] = None
    try:
        snap = getattr(hist, "_snap", None)
        pb_times = getattr(snap, "pb_times", {}) or {}
        for entries in pb_times.values():
            for e in entries or []:
                d = e.get("date_iso") or e.get("date")
                if d and (last_iso is None or str(d) > last_iso):
                    last_iso = str(d)
    except Exception:
        return 0.5
    if not last_iso:
        return 0.5

    meet_date = getattr(ctx, "start_date", None) or getattr(ctx, "end_date", None) if ctx else None
    if not meet_date:
        return 0.5
    try:
        from datetime import date
        d1 = date.fromisoformat(str(last_iso)[:10])
        d2 = date.fromisoformat(str(meet_date)[:10])
        days = abs((d2 - d1).days)
        return max(0.0, min(1.0, 1.0 - days / 365.0))
    except Exception:
        return 0.5


def _recency_factor(a: Achievement, ctx, history_map) -> tuple[float, float, str]:
    value = _recency_value(a, ctx, history_map)
    if value >= 0.66:
        reason = "recent prior swims on record"
    elif value <= 0.34:
        reason = "no recent prior swims on record"
    else:
        reason = "recency unknown / neutral"
    return value, _WEIGHTS["recency"], reason


def _profile_priority_factor(a: Achievement, ctx) -> tuple[float, float, str]:
    """
    V7 factor: club-configured priority MULTIPLIER for this achievement type.

    The value is the configured multiplier (1.0 = neutral, >1.0 = boost,
    <1.0 = suppress). Weight is 0 — the factor is recorded for transparency but
    not counted in the weighted-sum denominator. The multiplier is applied
    after the base priority is computed (see ``_compute_priority``).

    On any lookup failure the multiplier stays neutral (1.0) but the reason
    records the *real* cause (F21) — it never silently claims 'no override'.
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
            except Exception as e:
                # Surface the real failure instead of swallowing it and lying
                # with 'no override' (F21).
                multiplier = 1.0
                reason = (
                    f"profile priority lookup failed for {a.type} "
                    f"({type(e).__name__}: {e}); using neutral 1.0"
                )
                logger.warning(
                    "profile priority lookup failed for %s: %s", a.type, e
                )

    return multiplier, _WEIGHTS["profile_priority"], reason


def _plain_summary(name: str, value: float, a: Achievement, ctx) -> str:
    """One-line plain-English summary of a ranking factor's contribution.

    The summary is grounded in the factor name + value + the achievement type
    so it can be surfaced in the "Why this card?" explainer without rewording
    by an LLM. Returns "" when the factor did not contribute (value ≈ 0).
    """
    meet_level = (getattr(ctx, "meet_level", None) or "open") if ctx is not None else "open"
    atype = a.type or ""

    if name == "magnitude":
        if value >= 0.85:
            return f"Strong on-paper achievement ({atype.replace('_', ' ')})."
        if value >= 0.5:
            return f"Solid result for this achievement type ({atype.replace('_', ' ')})."
        if value > 0:
            return f"Modest result for this achievement type ({atype.replace('_', ' ')})."
        return ""

    if name == "rarity":
        if value >= 0.7:
            return f"Rare at this level — {meet_level} meet."
        if value >= 0.4:
            return f"Moderately rare at a {meet_level} meet."
        if value > 0:
            return f"Common at a {meet_level} meet."
        return ""

    if name == "meet_level":
        return f"{meet_level.title()}-level competition."

    if name == "narrative":
        if value >= 0.7:
            return "Strong story angle (e.g. multi-PB weekend, biggest drop, return to form)."
        if value >= 0.3:
            return "Has a narrative angle that adds interest."
        return ""

    if name == "barrier":
        if value >= 0.5:
            return "First-time sub-barrier crossing."
        return ""

    if name == "certainty":
        if value >= 0.85:
            return f"High confidence in the underlying data ({value:.2f})."
        if value >= 0.5:
            return f"Moderate confidence in the underlying data ({value:.2f})."
        if value > 0:
            return f"Low confidence in the underlying data ({value:.2f})."
        return ""

    if name == "recency":
        if value >= 0.66:
            return "Swimmer has recent prior swims on record."
        if value <= 0.34:
            return "Swimmer has no recent prior swims on record."
        return ""

    if name == "profile_priority":
        if value > 1.05:
            return f"Club has flagged {atype.replace('_', ' ')} as a priority (×{value:.2f})."
        if value < 0.95:
            return f"Club has down-weighted {atype.replace('_', ' ')} (×{value:.2f})."
        return "No club priority override."

    return ""


def _compute_priority(
    a: Achievement, ctx, history_map: Optional[dict] = None
) -> tuple[float, list[RankFactor], float]:
    """Return (priority, factors, recency_value).

    ``recency_value`` is threaded back out so the caller can use it as a
    deterministic tie-break without recomputing it (F34).
    """
    factors: list[RankFactor] = []
    weighted_sum = 0.0
    max_possible = 0.0
    profile_multiplier = 1.0
    recency_value = 0.5

    computed = [
        ("magnitude", _magnitude_factor(a, ctx)),
        ("rarity", _rarity_factor(a, ctx)),
        ("meet_level", _meet_level_factor(a, ctx)),
        ("narrative", _narrative_factor(a, ctx)),
        ("barrier", _barrier_factor(a, ctx)),
        ("certainty", _certainty_factor(a, ctx)),
        ("recency", _recency_factor(a, ctx, history_map)),
        ("profile_priority", _profile_priority_factor(a, ctx)),
    ]

    for name, (value, weight, reason) in computed:
        rounded_value = round(value, 4)
        factors.append(RankFactor(
            name=name,
            value=rounded_value,
            weight=weight,
            reason=reason,
            plain_summary=_plain_summary(name, rounded_value, a, ctx),
        ))

        if name == "profile_priority":
            # Store multiplier to apply after weighted sum; not a weighted term.
            profile_multiplier = value
        elif name == "recency":
            recency_value = value
        else:
            weighted_sum += value * weight
            max_possible += 1.0 * weight

    base_priority = weighted_sum / max_possible if max_possible > 0 else 0.0

    # Apply the profile-priority multiplier as an ORDER-PRESERVING boost (F04).
    # A plain ``min(1.0, base * multiplier)`` clamp collapses every boosted card
    # to exactly 1.0, erasing the strength difference between a club's flagged
    # cards. Instead, for a boost (multiplier >= 1) we compress the *headroom*
    # toward 1.0 by the multiplier, which is strictly monotonic in base and so
    # never ties two distinct base scores:
    #     priority = 1 - (1 - base) / multiplier
    # For suppression (0 <= multiplier < 1, or a nonsensical negative from a
    # hand-edited profile) we scale down linearly and clamp to [0, 1].
    if profile_multiplier >= 1.0:
        priority = 1.0 - (1.0 - base_priority) / profile_multiplier
    else:
        priority = base_priority * profile_multiplier
    priority = min(1.0, max(0.0, priority))
    return priority, factors, recency_value


def _safe_to_post_level(safe_to_post) -> Optional[str]:
    """Extract the level string from a SafeToPost object or dict, if any."""
    if safe_to_post is None:
        return None
    level = getattr(safe_to_post, "level", None)
    if level is None and isinstance(safe_to_post, dict):
        level = safe_to_post.get("level")
    return level


def _assign_quality_band(
    priority: float,
    achievement_type: str,
    confidence: float = 1.0,
    safe_to_post=None,
) -> QualityBand:
    """Map priority score + type to a quality band.

    A ``do_not_post`` card is never banded ELITE (F15): the top band feeds the
    main feed, and the same system marking a card "do not post" must not label
    it a headline. It is still allowed to band STRONG so the content-pack
    builder routes it to *needs_review* rather than hiding it — capping it
    lower (nice/not_worthy) would send it to internal_notes/rejected and drop
    it from human review. The *type override* (which can promote a card above
    its computed priority) is additionally gated on a minimum confidence and on
    the safety verdict, so a low-confidence or do-not-post ``medal_gold`` is not
    banded ELITE via its type alone.
    """
    conf = confidence if isinstance(confidence, (int, float)) else 0.0
    level = _safe_to_post_level(safe_to_post)
    postable = level != "do_not_post"
    type_override_ok = conf >= 0.4 and postable

    def override(types: tuple) -> bool:
        return type_override_ok and achievement_type in types

    # ELITE (headline / main feed) is gated on the card being postable at all.
    if postable and (priority >= 0.80 or override(
        ("medal_gold", "first_sub_barrier", "pb_magnitude_huge", "club_record")
    )):
        return QualityBand.ELITE
    if priority >= 0.60 or override(
        ("medal_silver", "qual_hit_in_window", "pb_magnitude_big", "official_pb_confirmed")
    ):
        return QualityBand.STRONG
    if priority >= 0.40 or override(("return_to_form", "multi_pb_weekend", "fastest_since")):
        return QualityBand.STORY
    if priority >= 0.20 or override(("pb_confirmed", "pb_likely", "medal_bronze")):
        return QualityBand.NICE
    return QualityBand.NOT_WORTHY


def _assign_post_type(band: QualityBand, achievement_type: str, ctx, safe_to_post=None) -> PostType:
    # A do-not-post card is never suggested for any public surface — the honest
    # suggestion is "hold internally / review" (F15). This label must not read
    # MAIN_FEED/STORY/RECAP while the same card is marked do_not_post. (The
    # content-pack builder routes by band + safety, so this only fixes the
    # advisory label, but it removes the contradiction reviewers saw.)
    if _safe_to_post_level(safe_to_post) == "do_not_post":
        return PostType.INTERNAL_NOTE
    if band == QualityBand.ELITE:
        return PostType.MAIN_FEED
    if band == QualityBand.STRONG:
        # Big-meet strong performances get the main feed; lower gets a story.
        level = (getattr(ctx, "meet_level", None) or "") if ctx else ""
        if level in ("national", "international", "regional", "university"):
            return PostType.MAIN_FEED
        return PostType.STORY
    if band == QualityBand.STORY:
        return PostType.STORY
    if band == QualityBand.NICE:
        return PostType.RECAP
    return PostType.INTERNAL_NOTE


# post_angle mapping — kept aligned with content_pack/builder.py:_TYPE_TO_ANGLE
# so a card's angle label / caption directive is correct on both surfaces
# (F03, F19). Types absent here fall to "recap_mention".
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
    "relay_strong_performance": "relay_highlight",   # detector's actual type (F19)
    # Phase W — club history angles (aligned with builder._TYPE_TO_ANGLE, F03)
    "club_record": "club_record",
    "club_debut": "milestone",
    "race_milestone_25": "milestone",
    "race_milestone_50": "milestone",
    "race_milestone_100": "milestone",
    "race_milestone_250": "milestone",
    "race_milestone_500": "milestone",
    "first_event_swim": "milestone",
}


def rank_achievements(
    achievements: list[Achievement],
    ctx,
    history_map: Optional[dict] = None,
) -> list[RankedAchievement]:
    """
    Rank a list of achievements. Returns list sorted by priority descending,
    with deterministic tie-breaks (F34). Assigns rank integers starting at 1.

    ctx may optionally carry a ``.profile`` attribute (ClubProfile) so the
    profile_priority_factor can read per-club achievement weights, and
    ``.start_date`` / ``.end_date`` for the recency tie-break. ``history_map``
    (``dict[swimmer_id -> SwimmerHistory]``) feeds the recency dimension.
    """
    # Imported at call time (long after module import) to avoid any import-order
    # cycle with the recognition package; if it ever fails it fails loudly here.
    from .recommender import derive_safe_to_post

    ranked: list[tuple] = []

    for a in achievements:
        priority, factors, recency = _compute_priority(a, ctx, history_map)

        # V7.3: derive the safety verdict first — the quality band gates its
        # type overrides on it (F15).
        try:
            safe_to_post_obj = derive_safe_to_post(a)
        except Exception as e:
            # Do not fail open, and do not swallow silently: record a cautious
            # verdict with the real reason (F21/F62).
            logger.warning(
                "derive_safe_to_post failed for %s: %s", getattr(a, "swim_id", "?"), e
            )
            # Plain-dict verdict (no dependency on the recommender's SafeToPost
            # representation): every consumer reads safe_to_post via .to_dict()
            # or dict access, so a dict is handled everywhere.
            safe_to_post_obj = {
                "level": "needs_review",
                "reason": f"safety derivation failed ({type(e).__name__})",
            }

        band = _assign_quality_band(priority, a.type, a.confidence, safe_to_post_obj)
        post_type = _assign_post_type(band, a.type, ctx, safe_to_post_obj)

        # V7.3: post_angle. Respect a detector-preset angle (the field exists
        # for that); otherwise map from the type. Do NOT mutate the input
        # Achievement — the ranker only writes the resolved angle onto the
        # RankedAchievement, so a card can never serialise two contradictory
        # post_angle values (F24).
        preset_angle = getattr(a, "post_angle", None)
        post_angle_str = preset_angle or _POST_ANGLE_MAP.get(a.type, "recap_mention")

        ra = RankedAchievement(
            achievement=a,
            priority=round(priority, 4),
            factors=factors,
            quality_band=band,
            suggested_post_type=post_type,
        )
        # Plain attribute assignment: Achievement / RankedAchievement are
        # non-frozen dataclasses, so this always works and a future slots=True
        # would fail loudly rather than silently dropping these fields (F62).
        ra.safe_to_post = safe_to_post_obj
        ra.post_angle = post_angle_str

        # Tie-break key components carried alongside the object (F34). swim_id
        # is coerced to a string so a None / non-string id can never make the
        # sort's final key comparison raise (it is a required str, but a
        # malformed persisted run must not crash the whole ranking).
        conf = a.confidence if isinstance(a.confidence, (int, float)) else 0.0
        swim_id_key = str(getattr(a, "swim_id", "") or "")
        ranked.append((priority, conf, recency, swim_id_key, ra))

    # Deterministic sort: score (priority) > PB confidence > recency > swim_id.
    # swim_id (unique per card) guarantees a total order, so equal-priority
    # order never depends on detector emission order (F34).
    ranked.sort(key=lambda t: (-t[0], -t[1], -t[2], t[3]))

    # Assign ranks
    result: list[RankedAchievement] = []
    for i, item in enumerate(ranked):
        ra = item[4]
        ra.rank = i + 1
        result.append(ra)

    return result
