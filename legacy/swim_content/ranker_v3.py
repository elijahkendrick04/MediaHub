"""
Ranker V3 — context-aware scoring with explanations.

Each ContentCard ends with:
  - score (0-100)
  - score_reasons: short bullets the user reads on the card
  - bucket: 'queue' | 'recap' | 'archive'
  - suggested_format: see cards.FMT_*

Scoring rules (transparent and adjustable):

Base scores by card type:
  athlete_spotlight     base 70
  qual_alert            base 70
  pb_roundup            base 65
  podium_roundup        base 55
  standout_swim         base 40
  weekend_in_numbers    base 45
  recap_only            base 25

Modifiers per card:
  +10  national-level qualifier hit inside the window
  +6   university-level (BUCS) qualifier hit inside the window
  +4   any qualifier hit that is out-of-window, or of another (open) level
  +12  contains a confirmed PB (status CONFIRMED_PB)
  +5   contains a likely PB (LIKELY_PB)
  +8   contains a gold (only adds once per card)
  +4   contains a silver (only adds once per card)
  +2   contains a bronze (only adds once per card)
  +5   spotlight covers >=3 notable events (distinct distance/stroke/course)
  +5   same-stroke gold dominance (2 golds = "doubles up", 3+ = "clean sweep")
  -10  card has only LIKELY_PBs and no medal/qualifier

Anti-spam (defensive safety-net):
  After scoring, if a swimmer has a SPOTLIGHT card, each of their STANDOUT
  cards is demoted by 25 so the spotlight stays the canonical entry. The
  demoted card then buckets on its reduced score, so it lands in recap or
  (more often) archive depending on what is left — e.g. a gold standout (48)
  demotes to 23 -> archive. In the live pipeline the grouper emits a spotlight
  XOR standouts per swimmer (never both), so this rule only fires for card
  lists that carry both (tests, or a future producer that emits both): it is a
  deliberate safety-net, not dead code — keep it through a dead-code sweep.
  See grouper.group_claims_into_cards.

Buckets:
  >= 65         queue
  40 - 64       recap
  < 40          archive

We also cap the queue at 20 cards, demoting overflow to recap.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from .cards import (
    ContentCard, Claim,
    TYPE_STANDOUT, TYPE_SPOTLIGHT, TYPE_PB_ROUNDUP, TYPE_PODIUM_ROUNDUP,
    TYPE_QUAL_ALERT, TYPE_WEEKEND_NUMBERS, TYPE_RECAP,
    FMT_FEED, FMT_STORY, FMT_SPOTLIGHT, FMT_RECAP, FMT_NUMBERS, FMT_ARCHIVE,
)


_BASE_SCORE = {
    TYPE_SPOTLIGHT: 70,
    TYPE_QUAL_ALERT: 70,
    TYPE_PB_ROUNDUP: 65,
    TYPE_PODIUM_ROUNDUP: 55,
    TYPE_STANDOUT: 40,
    TYPE_WEEKEND_NUMBERS: 45,
    TYPE_RECAP: 25,
}


def _has_kind(card: ContentCard, kind: str) -> bool:
    return any(c.kind == kind for c in card.claims)


def _claim_in_window(extra: dict) -> bool:
    """Read a claim's ``in_window`` flag, coercing persisted/stringy values.

    detector_v3 always writes a real bool; a MISSING flag defaults to True
    (in-window) so pre-flag / hand-built claims keep their prior full weight.
    Persisted JSON may round-trip the flag as ``"false"`` / ``0`` / ``"0"`` —
    those are treated as out-of-window so the result is serialization-stable
    (a plain truthiness test would read the string ``"false"`` as in-window).
    """
    raw = extra.get("in_window", True)
    if isinstance(raw, str):
        return raw.strip().lower() not in ("false", "0", "no", "")
    if raw is None:
        return True
    return bool(raw)


def _qual_hits(card: ContentCard) -> list[tuple[str, bool]]:
    """Return ``(level, in_window)`` for each qual_hit claim on the card."""
    hits: list[tuple[str, bool]] = []
    for c in card.claims:
        if c.kind == "qual_hit":
            hits.append((c.extra.get("level", "open"), _claim_in_window(c.extra)))
    return hits


def _suggested_format(card: ContentCard) -> str:
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
    }.get(card.card_type, card.card_type)
    reasons.append(f"Base for {type_label} (+{_BASE_SCORE.get(card.card_type, 30)})")

    # Qualifier weighting. In-window hits earn full weight; out-of-window hits
    # (detector_v3 flags them in extra['in_window'] expressly for this) are
    # soft-weighted to +4, so an expired-window national hit no longer outranks
    # an in-window BUCS hit. A missing flag defaults to in-window (the detector
    # always sets it; older / hand-built claims keep their prior weight).
    qual_hits = _qual_hits(card)
    if qual_hits:
        in_window_levels = [lvl for lvl, ok in qual_hits if ok]
        if "national" in in_window_levels or "international" in in_window_levels:
            score += 10
            reasons.append("Hit a national-level qualifying standard (+10)")
        elif "university" in in_window_levels:
            score += 6
            reasons.append("Hit BUCS-level qualifying standard (+6)")
        else:
            score += 4
            # Only stamp "outside its window" when a hit is EXPLICITLY out of
            # window — never for a missing flag, which would fabricate an expiry
            # the evidence never asserted.
            if not in_window_levels and any(not ok for _, ok in qual_hits):
                reasons.append("Hit a qualifying standard, outside its window (+4)")
            else:
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
        # Breadth: count distinct EVENTS, not per-round swims. A prelim + final
        # of the same event is one event's worth of breadth, so round is
        # deliberately excluded from the key (else it double-counts one event).
        n_notable_events = len({(c.distance, c.stroke, c.course) for c in card.claims})
        if n_notable_events >= 3:
            score += 5
            reasons.append(f"Spotlight covers {n_notable_events} notable events (+5)")
        # Same-stroke gold dominance. Match the grouper's vocabulary: exactly two
        # same-stroke golds is a "doubles up", three or more is a "clean sweep"
        # (grouper.group_claims_into_cards). The +5 is the same either way; only
        # the reason label differs, so it never contradicts the card headline.
        gold_strokes = {c.stroke for c in card.claims if c.kind == "gold"}
        n_golds = sum(1 for c in card.claims if c.kind == "gold")
        if len(gold_strokes) == 1 and n_golds >= 2:
            score += 5
            label = "clean sweep" if n_golds >= 3 else "doubles up"
            reasons.append(f"Stroke '{label}' bonus (+5)")

    # Penalty for likely-PB-only cards (no medal, no qualifier)
    if (_has_kind(card, "pb_likely")
        and not _has_kind(card, "pb_confirmed")
        and not _has_kind(card, "gold")
        and not _has_kind(card, "silver")
        and not _has_kind(card, "bronze")
        and not _has_kind(card, "qual_hit")):
        score -= 10
        reasons.append("Only a likely (unverified) PB — needs evidence (-10)")

    # Clamp
    score = max(0, min(100, score))
    card.score = score
    card.score_reasons = reasons
    return card


def _spotlight_owners(cards: list[ContentCard]) -> set[str]:
    return {c.primary_swimmer for c in cards
            if c.card_type == TYPE_SPOTLIGHT and c.primary_swimmer}


def _bucket_for_score(card: ContentCard, score: int) -> str:
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

    # 4) cap the queue at queue_cap; overflow goes to recap. Rank the WHOLE
    #    queue by the same (-score, card_id) total order the final sort uses,
    #    THEN slice: this makes the keep/demote partition itself deterministic
    #    (not just the demoted cards' order) and consistent with the final sort,
    #    so which card is demoted at a tie no longer depends on input order.
    queue_cards = [c for c in cards if c.bucket == "queue"]
    queue_cards.sort(key=lambda x: (-x.score, x.card_id))
    if len(queue_cards) > queue_cap:
        for c in queue_cards[queue_cap:]:
            c.bucket = "recap"
            # Recompute the format for the new bucket rather than hardcoding
            # FMT_RECAP, so a demoted spotlight / weekend card keeps the format
            # _suggested_format assigns for a recap-bucket card of its type.
            c.suggested_format = _suggested_format(c)
            c.score_reasons.append(f"Queue cap reached at {queue_cap}; moved to recap")

    # 5) sort cards by bucket then score
    bucket_rank = {"queue": 0, "recap": 1, "archive": 2}
    cards.sort(key=lambda x: (bucket_rank.get(x.bucket, 9), -x.score, x.card_id))
    return cards
