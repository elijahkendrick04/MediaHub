"""
Ranker V3 — context-aware scoring with explanations.

Each ContentCard ends with:
  - score (0-100)
  - score_reasons: short bullets the user reads on the card
  - bucket: 'queue' | 'recap' | 'needs_confirmation' | 'archive'
  - suggested_format: see cards.FMT_*

Scoring rules (transparent and adjustable):

Base scores by card type:
  athlete_spotlight     base 70
  qual_alert            base 70
  pb_roundup            base 65
  podium_roundup        base 55
  standout_swim         base 40
  weekend_in_numbers    base 45
  needs_confirmation    base 30
  recap_only            base 25

Modifiers per card:
  +10  national-level qualifier hit inside the window
  +6   university-level (BUCS) qualifier hit inside the window
  +4   any qualifier hit (other / out-of-window)
  +12  contains a confirmed PB (status CONFIRMED_PB)
  +5   contains a likely PB (LIKELY_PB)
  +8   contains a gold (only adds once per card)
  +4   contains a silver (only adds once per card)
  +2   contains a bronze (only adds once per card)
  +5   spotlight covers >=3 notable swims
  +5   stroke "clean sweep" detected
  -8   meet importance is "open / host" without finals or qualifier hit
  -10  card has only LIKELY_PBs and no medal/qualifier
  -15  needs_confirmation flag set

Anti-spam:
  After scoring, a swimmer with a SPOTLIGHT card has all their STANDOUT cards
  demoted by 25 (they go to recap) so the spotlight is the canonical entry.

Buckets:
  >= 65         queue
  40 - 64       recap
  needs_conf    needs_confirmation
  < 40          archive

We also cap the queue at 20 cards, demoting overflow to recap.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from .cards import (
    ContentCard, Claim,
    TYPE_STANDOUT, TYPE_SPOTLIGHT, TYPE_PB_ROUNDUP, TYPE_PODIUM_ROUNDUP,
    TYPE_QUAL_ALERT, TYPE_WEEKEND_NUMBERS, TYPE_RECAP, TYPE_NEEDS_CONFIRMATION,
    FMT_FEED, FMT_STORY, FMT_SPOTLIGHT, FMT_RECAP, FMT_NUMBERS, FMT_HOLD, FMT_ARCHIVE,
)


_BASE_SCORE = {
    TYPE_SPOTLIGHT: 70,
    TYPE_QUAL_ALERT: 70,
    TYPE_PB_ROUNDUP: 65,
    TYPE_PODIUM_ROUNDUP: 55,
    TYPE_STANDOUT: 40,
    TYPE_WEEKEND_NUMBERS: 45,
    TYPE_NEEDS_CONFIRMATION: 30,
    TYPE_RECAP: 25,
}


def _has_kind(card: ContentCard, kind: str) -> bool:
    return any(c.kind == kind for c in card.claims)


def _qual_hit_levels(card: ContentCard) -> list[str]:
    """Return list of importance levels for any qual_hit claims."""
    levels = []
    for c in card.claims:
        if c.kind == "qual_hit":
            levels.append(c.extra.get("level", "open"))
    return levels


def _suggested_format(card: ContentCard) -> str:
    if card.bucket == "needs_confirmation":
        return FMT_HOLD
    if card.bucket == "archive":
        return FMT_ARCHIVE
    if card.card_type == TYPE_SPOTLIGHT:
        return FMT_SPOTLIGHT
    if card.card_type == TYPE_WEEKEND_NUMBERS:
        return FMT_NUMBERS
    if card.bucket == "recap":
        return FMT_RECAP
    if card.card_type in (TYPE_QUAL_ALERT, TYPE_PB_ROUNDUP, TYPE_PODIUM_ROUNDUP):
        return FMT_FEED
    if card.card_type == TYPE_STANDOUT:
        return FMT_STORY  # default standalone medals to a story rather than feed
    return FMT_FEED


def score_card(card: ContentCard) -> ContentCard:
    """Compute score + reasons + bucket + suggested format on the card."""
    reasons: list[str] = []
    score = _BASE_SCORE.get(card.card_type, 30)

    # Type tag for reason
    type_label = {
        TYPE_SPOTLIGHT: "athlete spotlight",
        TYPE_QUAL_ALERT: "qualifier alert",
        TYPE_PB_ROUNDUP: "PB roundup",
        TYPE_PODIUM_ROUNDUP: "podium roundup",
        TYPE_STANDOUT: "individual swim",
        TYPE_WEEKEND_NUMBERS: "weekend stats",
        TYPE_NEEDS_CONFIRMATION: "needs confirmation",
    }.get(card.card_type, card.card_type)
    reasons.append(f"Base for {type_label} (+{_BASE_SCORE.get(card.card_type, 30)})")

    # Qualifier weighting
    levels = _qual_hit_levels(card)
    if levels:
        if "national" in levels or "international" in levels:
            score += 10
            reasons.append("Hit a national-level qualifying standard (+10)")
        elif "university" in levels:
            score += 6
            reasons.append("Hit BUCS-level qualifying standard (+6)")
        else:
            score += 4
            reasons.append("Hit a qualifying standard (+4)")

    # PB weighting
    if _has_kind(card, "pb_confirmed"):
        score += 12
        reasons.append("Confirmed personal best (+12)")
    elif _has_kind(card, "pb_likely"):
        score += 5
        reasons.append("Likely personal best, pending pre-meet snapshot (+5)")

    # Medal weighting (only once per card)
    if _has_kind(card, "gold"):
        score += 8
        reasons.append("Includes a gold medal (+8)")
    elif _has_kind(card, "silver"):
        score += 4
        reasons.append("Includes a silver medal (+4)")
    elif _has_kind(card, "bronze"):
        score += 2
        reasons.append("Includes a bronze medal (+2)")

    # Spotlight bonuses
    if card.card_type == TYPE_SPOTLIGHT:
        n_notable_swims = len({(c.distance, c.stroke, c.course, c.round or "") for c in card.claims})
        if n_notable_swims >= 3:
            score += 5
            reasons.append(f"Spotlight covers {n_notable_swims} notable swims (+5)")
        # Sweep detection: all gold claims share a stroke
        gold_strokes = {c.stroke for c in card.claims if c.kind == "gold"}
        if len(gold_strokes) == 1 and sum(1 for c in card.claims if c.kind == "gold") >= 2:
            score += 5
            reasons.append("Stroke 'clean sweep' bonus (+5)")

    # Penalty for likely-PB-only cards (no medal, no qualifier)
    if (_has_kind(card, "pb_likely")
        and not _has_kind(card, "pb_confirmed")
        and not _has_kind(card, "gold")
        and not _has_kind(card, "silver")
        and not _has_kind(card, "bronze")
        and not _has_kind(card, "qual_hit")):
        score -= 10
        reasons.append("Only a likely (unverified) PB — needs evidence (-10)")

    # Needs-confirmation flag explicit penalty
    if card.needs_confirmation:
        score -= 15
        reasons.append("Card flagged as needing human confirmation (-15)")

    # Clamp
    score = max(0, min(100, score))
    card.score = score
    card.score_reasons = reasons
    return card


def _spotlight_owners(cards: list[ContentCard]) -> set[str]:
    return {c.primary_swimmer for c in cards
            if c.card_type == TYPE_SPOTLIGHT and c.primary_swimmer}


def _bucket_for_score(card: ContentCard, score: int) -> str:
    if card.needs_confirmation:
        return "needs_confirmation"
    if score >= 65:
        return "queue"
    if score >= 40:
        return "recap"
    return "archive"


def rank_cards(cards: list[ContentCard], *, queue_cap: int = 20) -> list[ContentCard]:
    """
    Score every card, apply anti-spam, assign buckets and suggested formats,
    and cap the queue at `queue_cap` (overflow demoted to recap).
    """
    # 1) score
    for c in cards:
        score_card(c)

    # 2) anti-spam: if a swimmer has a spotlight, demote their standalones
    spotlight_owners = _spotlight_owners(cards)
    for c in cards:
        if c.card_type == TYPE_STANDOUT and c.primary_swimmer in spotlight_owners:
            c.score = max(0, c.score - 25)
            c.score_reasons.append("Demoted: covered by athlete spotlight (-25)")

    # 3) bucket
    for c in cards:
        c.bucket = _bucket_for_score(c, c.score)
        c.suggested_format = _suggested_format(c)

    # 4) cap the queue at queue_cap; overflow goes to recap, lowest scores first
    queue_cards = [c for c in cards if c.bucket == "queue"]
    queue_cards.sort(key=lambda x: -x.score)
    if len(queue_cards) > queue_cap:
        for c in queue_cards[queue_cap:]:
            c.bucket = "recap"
            c.suggested_format = FMT_RECAP
            c.score_reasons.append(f"Queue cap reached at {queue_cap}; moved to recap")

    # 5) sort cards by bucket then score
    bucket_rank = {"queue": 0, "needs_confirmation": 1, "recap": 2, "archive": 3}
    cards.sort(key=lambda x: (bucket_rank.get(x.bucket, 9), -x.score, x.card_id))
    return cards
