"""
Caption generation — phrasebook, no LLM, no internal labels.

Input: a ContentCard (one swim, stacked reasons).
Output: 1-3 caption variants the human reviewer picks from / edits.

No more leaks like "BUCS_LC_2025_26 qualified". The phrasebook only ever
emits human language. Every stat shown to the reader is taken from the
card's reason details, not from internal codes.

If a meaningful stat isn't in the card's reasons, we don't make one up.
We'd rather emit a shorter caption than fabricate.
"""
from __future__ import annotations
import random
from typing import Iterable

from .detector_v2 import ContentCard, ReasonKind, Reason


STROKE_WORD = {
    'FR': 'Freestyle', 'BK': 'Backstroke', 'BR': 'Breaststroke',
    'FL': 'Butterfly', 'IM': 'Individual Medley',
}


def _event_phrase(card: ContentCard) -> str:
    """E.g. '50m Freestyle' (no course suffix in caption — too noisy for IG)."""
    return f"{card.distance}m {STROKE_WORD.get(card.stroke, card.stroke)}"


def _time_phrase(cs: int) -> str:
    mins = cs // 6000
    rem = cs - mins * 6000
    secs = rem // 100
    frac = rem % 100
    if mins:
        return f"{mins}:{secs:02d}.{frac:02d}"
    return f"{secs}.{frac:02d}"


def _place_word(p: int | None) -> str | None:
    return {1: 'gold', 2: 'silver', 3: 'bronze'}.get(p or 0)


def _reasons_by_kind(card: ContentCard) -> dict[ReasonKind, Reason]:
    return {r.kind: r for r in card.reasons}


# ----------------------------------------------------------------------
# Caption templates — written in club voice, edited later by the marketer
# ----------------------------------------------------------------------

def _caption_pb_with_medal(card: ContentCard) -> str | None:
    rs = _reasons_by_kind(card)
    pb = rs.get(ReasonKind.BIG_PB) or rs.get(ReasonKind.CONFIRMED_PB)
    medal = rs.get(ReasonKind.MEDAL_GOLD) or rs.get(ReasonKind.MEDAL_SILVER) or rs.get(ReasonKind.MEDAL_BRONZE)
    if not (pb and medal):
        return None
    place_word = _place_word(card.place)
    margin_cs = pb.detail.get('margin_cs')
    margin = f" — {margin_cs/100:.2f}s off her PB" if (margin_cs and card.gender == 'F') else \
             (f" — {margin_cs/100:.2f}s off his PB" if margin_cs else "")
    return (
        f"{card.swimmer_name} takes {place_word} in the {_event_phrase(card)} "
        f"in {_time_phrase(card.time_cs)}{margin}."
    )


def _caption_big_pb(card: ContentCard) -> str | None:
    rs = _reasons_by_kind(card)
    pb = rs.get(ReasonKind.BIG_PB)
    if not pb:
        return None
    margin_cs = pb.detail.get('margin_cs') or 0
    pronoun = "her" if card.gender == 'F' else "his"
    return (
        f"Massive PB for {card.swimmer_name} — "
        f"{_time_phrase(card.time_cs)} in the {_event_phrase(card)}, "
        f"taking {margin_cs/100:.2f}s off {pronoun} previous best."
    )


def _caption_confirmed_pb(card: ContentCard) -> str | None:
    rs = _reasons_by_kind(card)
    pb = rs.get(ReasonKind.CONFIRMED_PB)
    if not pb:
        return None
    return (
        f"New PB for {card.swimmer_name} in the {_event_phrase(card)} — "
        f"{_time_phrase(card.time_cs)}."
    )


def _caption_medal_only(card: ContentCard) -> str | None:
    rs = _reasons_by_kind(card)
    medal = rs.get(ReasonKind.MEDAL_GOLD) or rs.get(ReasonKind.MEDAL_SILVER) or rs.get(ReasonKind.MEDAL_BRONZE)
    if not medal:
        return None
    place_word = _place_word(card.place)
    return (
        f"{place_word.capitalize()} for {card.swimmer_name} in the "
        f"{_event_phrase(card)} — {_time_phrase(card.time_cs)}."
    )


def _caption_barrier(card: ContentCard) -> str | None:
    rs = _reasons_by_kind(card)
    b = rs.get(ReasonKind.BARRIER_BREAK)
    if not b:
        return None
    barrier_str = b.detail.get('barrier_str', '')
    pronoun = "her" if card.gender == 'F' else "his"
    return (
        f"{card.swimmer_name} dips under {barrier_str} for the first time — "
        f"{_time_phrase(card.time_cs)} in the {_event_phrase(card)}, "
        f"a milestone in {pronoun} progression."
    )


def _caption_first_ever(card: ContentCard) -> str | None:
    rs = _reasons_by_kind(card)
    if ReasonKind.FIRST_EVER not in rs:
        return None
    pronoun = "her" if card.gender == 'F' else "his"
    return (
        f"{card.swimmer_name} swims {pronoun} first official "
        f"{_event_phrase(card)} — {_time_phrase(card.time_cs)}. "
        f"A new event in the bag."
    )


# Order matters: the first matching template wins for variant 1.
TEMPLATE_ORDER = [
    _caption_pb_with_medal,
    _caption_big_pb,
    _caption_barrier,
    _caption_medal_only,
    _caption_confirmed_pb,
    _caption_first_ever,
]


def captions_for_card(card: ContentCard, n_variants: int = 2) -> list[str]:
    """Return up to n_variants caption strings, never empty if card has reasons."""
    out: list[str] = []
    seen: set[str] = set()
    for fn in TEMPLATE_ORDER:
        c = fn(card)
        if c and c not in seen:
            out.append(c)
            seen.add(c)
            if len(out) >= n_variants:
                break
    if not out:
        # Genuinely no match — shouldn't happen if card has any reason, but
        # fall back to a neutral statement of fact rather than nothing.
        out.append(
            f"{card.swimmer_name} — {_event_phrase(card)} in {_time_phrase(card.time_cs)}."
        )
    return out


# ----------------------------------------------------------------------
# Weekend-in-numbers (recap) — aggregates queue + recap cards
# ----------------------------------------------------------------------

def weekend_recap(meet_name: str, queue: list[ContentCard],
                  recap: list[ContentCard]) -> str:
    n_pbs = sum(1 for c in (queue + recap)
                if any(r.kind in (ReasonKind.BIG_PB, ReasonKind.CONFIRMED_PB)
                       for r in c.reasons))
    n_gold = sum(1 for c in queue if c.place == 1)
    n_silver = sum(1 for c in queue if c.place == 2)
    n_bronze = sum(1 for c in queue if c.place == 3)
    n_swimmers = len({c.asa_id for c in (queue + recap)})

    lines = [f"Weekend in numbers — {meet_name}:"]
    lines.append(f"• {n_swimmers} Swansea Uni swimmers in the water")
    if n_pbs:
        lines.append(f"• {n_pbs} personal bests")
    if n_gold or n_silver or n_bronze:
        medals = []
        if n_gold: medals.append(f"{n_gold} gold")
        if n_silver: medals.append(f"{n_silver} silver")
        if n_bronze: medals.append(f"{n_bronze} bronze")
        lines.append("• " + ", ".join(medals))
    return "\n".join(lines)
