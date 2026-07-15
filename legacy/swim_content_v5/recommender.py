"""
recommend_post_type(ranked_achievements, ctx) -> list[ContentRecommendation]

Groups achievements per swimmer and decides the recommended post format.
"""
from __future__ import annotations

from collections import defaultdict

from .schema import (
    RankedAchievement, ContentRecommendation, QualityBand, PostType
)


def derive_safe_to_post(achievement):
    """
    Derive a SafeToPost level for an achievement.

    Returns SafeToPost(level, reason).
    """
    from mediahub.recognition.schema import SafeToPost

    conf = getattr(achievement, "confidence", 0.5)
    uncertainty_notes = getattr(achievement, "uncertainty_notes", []) or []
    atype = getattr(achievement, "type", "")

    # do_not_post if confidence very low
    if conf < 0.4:
        return SafeToPost("do_not_post", "Evidence is weak or ambiguous.")

    # needs_review if uncertainty notes OR medium confidence
    if uncertainty_notes:
        return SafeToPost("needs_review", "; ".join(uncertainty_notes[:2]))
    if conf < 0.7:
        return SafeToPost("needs_review", "Some evidence is incomplete.")
    
    # safe with per-type reason
    if atype == "official_pb_confirmed":
        return SafeToPost("safe", "Official PB confirmed by SwimmingResults time and date match.")
    if atype == "medal_gold":
        return SafeToPost("safe", "Gold medal placement read directly from results file.")
    if atype in ("medal_silver", "medal_bronze"):
        return SafeToPost("safe", "Medal placement read directly from results file.")
    if "pb_confirmed" in atype or "pb_magnitude" in atype:
        return SafeToPost("safe", "PB confirmed against verified historical data.")
    if "barrier" in atype:
        return SafeToPost("safe", "Sub-barrier crossing confirmed from results file.")
    if "qual_hit_in_window" in atype:
        return SafeToPost("safe", "Qualifying time hit confirmed from results file and standards data.")
    
    return SafeToPost("safe", "Verifiable claim with high-confidence evidence.")


def recommend_post_type(
    ranked_achievements: list[RankedAchievement],
    ctx,
) -> list[ContentRecommendation]:
    """
    Group achievements by swimmer and produce ContentRecommendation objects.

    Rules:
    - One elite + several strong → main-feed athlete spotlight
    - One strong → story or recap mention
    - Only nice → recap roll-up
    - 3+ elite/strong performances → headline meet recap (prepended)
    """
    recs: list[ContentRecommendation] = []

    # Group by swimmer (using swimmer_id)
    by_swimmer: dict[str, list[RankedAchievement]] = defaultdict(list)
    for ra in ranked_achievements:
        by_swimmer[ra.achievement.swimmer_id].append(ra)

    # Per-swimmer recommendations
    for swimmer_ras in by_swimmer.values():
        if not swimmer_ras:
            continue

        swimmer_name = swimmer_ras[0].achievement.swimmer_name
        bands = [ra.quality_band for ra in swimmer_ras]
        types = [ra.achievement.type for ra in swimmer_ras]

        elite_count = sum(1 for b in bands if b == QualityBand.ELITE)
        strong_count = sum(1 for b in bands if b == QualityBand.STRONG)
        story_count = sum(1 for b in bands if b == QualityBand.STORY)
        nice_count = sum(1 for b in bands if b == QualityBand.NICE)

        if elite_count >= 1 or (strong_count >= 2 and story_count >= 1):
            # Full athlete spotlight
            post_type = PostType.MAIN_FEED
            angle = f"Athlete spotlight: {swimmer_name} — {elite_count + strong_count} standout swims"
            title = f"Athlete spotlight: {swimmer_name}"
        elif strong_count >= 1 or story_count >= 1:
            # Story or high-value recap
            post_type = PostType.STORY
            angle = f"Story: {swimmer_name} — highlights from this meet"
            title = f"Meet highlights: {swimmer_name}"
        elif nice_count >= 2:
            # Multi-nice → recap mention
            post_type = PostType.RECAP
            angle = f"Recap mention: {swimmer_name}"
            title = f"Recap: {swimmer_name}"
        else:
            # Single nice or not worthy
            post_type = PostType.INTERNAL_NOTE
            angle = f"Internal note: {swimmer_name}"
            title = f"Note: {swimmer_name}"

        # Override post_type if swimmer has multiple strongs at national meet
        if ctx and ctx.meet_level == "national" and (elite_count + strong_count) >= 2:
            post_type = PostType.MAIN_FEED

        recs.append(ContentRecommendation(
            title=title,
            swimmer_or_group=swimmer_name,
            included_achievement_types=types,
            suggested_post_type=post_type,
            angle_hint=angle,
            ranked_achievements=sorted(swimmer_ras, key=lambda x: -x.priority),
        ))

    # Sort by best priority descending
    recs.sort(key=lambda r: -max((ra.priority for ra in r.ranked_achievements), default=0))

    # Add meet-level recap if enough notable achievements
    notable = [ra for ra in ranked_achievements if ra.quality_band in (QualityBand.ELITE, QualityBand.STRONG)]
    if len(notable) >= 3:
        meet_name = ctx.meet_name if ctx else "the meet"
        recs.insert(0, ContentRecommendation(
            title=f"Meet recap: {meet_name}",
            swimmer_or_group="meet recap",
            included_achievement_types=list({ra.achievement.type for ra in notable[:10]}),
            suggested_post_type=PostType.MAIN_FEED,
            angle_hint=f"Full meet recap for {meet_name}: {len(notable)} standout performances.",
            ranked_achievements=notable[:10],
        ))

    return recs
