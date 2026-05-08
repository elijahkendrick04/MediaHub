"""
Ranker — turns ContentCards from detector_v2 into a triaged review queue.

Card score = max(reason scores) + small stacking bonus.
The bonus is capped so a card with three weak reasons doesn't outrank a
card with one strong reason.

Thresholds (filters, NOT just sorts):
    score >= 70   queue       (review-ready, default-publish)
    40-69         recap       (rolls into "Weekend in Numbers" only)
    <40           archive     (visible in upload report, never reviewed)

These are deliberately strict. The user explicitly asked for 10-30 review
items per typical meet, not 80. We'd rather miss a marginal item than
flood the queue.
"""
from __future__ import annotations
from dataclasses import dataclass

from .detector_v2 import ContentCard, Reason


# Stacking bonus: each additional reason beyond the first adds N points,
# capped. This rewards multi-reason cards (e.g. "PB + gold + barrier") which
# are the strongest content moments.
STACK_BONUS_PER_EXTRA = 5
STACK_BONUS_CAP = 15


def _card_score(card: ContentCard) -> int:
    if not card.reasons:
        return 0
    # Ignore LIKELY_PB for scoring — it's an upload-report-only flag.
    queueable = [r for r in card.reasons if r.score > 0]
    if not queueable:
        return 0
    base = max(r.score for r in queueable)
    extras = max(0, len(queueable) - 1)
    bonus = min(extras * STACK_BONUS_PER_EXTRA, STACK_BONUS_CAP)
    return base + bonus


def _decision(score: int) -> str:
    if score >= 70:
        return 'queue'
    if score >= 40:
        return 'recap'
    return 'archive'


@dataclass
class RankedQueue:
    queue: list[ContentCard]      # score >= 70, sorted desc by score
    recap: list[ContentCard]      # 40-69
    archive: list[ContentCard]    # <40, kept for transparency in upload report

    @property
    def queue_size(self) -> int:
        return len(self.queue)


def rank(cards: list[ContentCard]) -> RankedQueue:
    """Compute scores, set decision, partition. Mutates the cards in place."""
    queue: list[ContentCard] = []
    recap: list[ContentCard] = []
    archive: list[ContentCard] = []

    for c in cards:
        c.score = _card_score(c)
        c.queue_decision = _decision(c.score)
        if c.queue_decision == 'queue':
            queue.append(c)
        elif c.queue_decision == 'recap':
            recap.append(c)
        else:
            archive.append(c)

    queue.sort(key=lambda c: (-c.score, c.swimmer_name))
    recap.sort(key=lambda c: (-c.score, c.swimmer_name))
    return RankedQueue(queue=queue, recap=recap, archive=archive)
