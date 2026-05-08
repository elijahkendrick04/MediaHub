"""
Caption generator (V3) — three voices per card.

Voices:
  clean   — neutral results-style; reads like a club website headline
  team    — first-person team voice; uses 'we' and short sentences
  hype    — high-energy social style; rhythmic, exclamation-light, no emoji unless asked

Hard rules:
  - Never expose internal labels like BUCS_LC_2025_26.
  - Use the friendly competition name from the qualification standard if present.
  - LC and SC are kept implicit unless the caption talks about course explicitly.
  - Times always rendered as the swim time string (e.g. '57.99', '1:07.97').
  - No emojis unless the caller requests them.
"""
from __future__ import annotations

import random
from typing import Optional

from .cards import (
    ContentCard, Claim, CaptionVariants,
    TYPE_STANDOUT, TYPE_SPOTLIGHT, TYPE_PB_ROUNDUP, TYPE_PODIUM_ROUNDUP,
    TYPE_QUAL_ALERT, TYPE_WEEKEND_NUMBERS, TYPE_RECAP, TYPE_NEEDS_CONFIRMATION,
)


_STROKE_TITLE = {"FR": "Freestyle", "BK": "Backstroke", "BR": "Breaststroke",
                  "FL": "Butterfly", "IM": "Individual Medley"}


def _event(distance: int, stroke: str) -> str:
    return f"{distance}m {_STROKE_TITLE.get(stroke, stroke)}"


def _strongest_swim_claim(card: ContentCard) -> Optional[Claim]:
    """Pick the most caption-worthy claim on the card."""
    order = ("gold", "pb_confirmed", "qual_hit", "silver", "bronze",
             "pb_likely", "final", "pb_unverified")
    for kind in order:
        for c in card.claims:
            if c.kind == kind:
                return c
    return card.claims[0] if card.claims else None


def _gold_count(card: ContentCard) -> int:
    return sum(1 for c in card.claims if c.kind == "gold")


def _confirmed_pb_count(card: ContentCard) -> int:
    return sum(1 for c in card.claims if c.kind == "pb_confirmed")


def _qual_competition_name(card: ContentCard) -> Optional[str]:
    for c in card.claims:
        if c.kind == "qual_hit":
            name = c.extra.get("competition")
            if name:
                return name
    return None


# ---------- per-card-type generators ----------

def _captions_standout(card: ContentCard, club_short: str) -> CaptionVariants:
    swim = _strongest_swim_claim(card)
    if swim is None:
        return CaptionVariants(clean=card.headline, team=card.headline, hype=card.headline)
    name = card.primary_swimmer or "Our swimmer"
    event = _event(swim.distance, swim.stroke)
    time = swim.time_str
    parts = []
    if swim.kind == "gold":
        parts.append(f"Gold for {name}")
    elif swim.kind == "silver":
        parts.append(f"Silver for {name}")
    elif swim.kind == "bronze":
        parts.append(f"Bronze for {name}")
    elif swim.kind == "pb_confirmed":
        parts.append(f"PB for {name}")
    elif swim.kind == "qual_hit":
        comp = _qual_competition_name(card) or "qualifying standard"
        parts.append(f"{name} hits the {comp} standard")
    else:
        parts.append(f"{name} on the board")

    clean = f"{parts[0]} in the {event} — {time}."

    # Team voice
    if swim.kind in ("gold", "silver", "bronze"):
        team = (f"Big swim from {name} — {swim.kind} in the {event} ({time}). "
                f"Proud of you, {name.split()[0] if ' ' in name else name}.")
    elif swim.kind == "pb_confirmed":
        team = f"{name} dropped a new personal best in the {event} — {time}. Onwards."
    elif swim.kind == "qual_hit":
        comp = _qual_competition_name(card) or "the standard"
        team = f"{name} delivered when it mattered — {time} in the {event}, under {comp}."
    elif swim.kind == "pb_likely":
        team = f"{name} clocked {time} in the {event} — looks like a PB pending confirmation."
    else:
        team = f"{name} raced the {event} in {time}."

    # Hype voice — short, rhythmic, no emoji
    if swim.kind == "gold":
        hype = f"{name.upper()}. {time}. {event} GOLD. {club_short} on top."
    elif swim.kind in ("silver", "bronze"):
        medal = swim.kind.capitalize()
        hype = f"{medal} for {name}. {time} in the {event}. {club_short} on the podium."
    elif swim.kind == "pb_confirmed":
        hype = f"NEW PB. {name}. {event}. {time}. Always faster."
    elif swim.kind == "qual_hit":
        comp = _qual_competition_name(card) or "the standard"
        hype = f"{name} books the {comp}. {time} in the {event}. Earned."
    else:
        hype = f"{name} — {time}, {event}. Job done."

    return CaptionVariants(clean=clean, team=team, hype=hype)


def _captions_spotlight(card: ContentCard, club_short: str) -> CaptionVariants:
    name = card.primary_swimmer or "This swimmer"
    n_swims = len({(c.distance, c.stroke, c.course, c.round or "") for c in card.claims})
    n_gold = _gold_count(card)
    gold_strokes = {c.stroke for c in card.claims if c.kind == "gold"}
    pb_n = _confirmed_pb_count(card)

    # Build event list for clean voice
    swim_descs = []
    seen = set()
    for c in card.claims:
        key = (c.distance, c.stroke, c.course, c.round or "")
        if key in seen:
            continue
        seen.add(key)
        if c.kind in ("gold", "silver", "bronze", "pb_confirmed", "qual_hit"):
            swim_descs.append(f"{_event(c.distance, c.stroke)} ({c.time_str})")
    swim_list = ", ".join(swim_descs[:4])

    # Pre-build a tasteful PB suffix only if a PB is genuinely on the card.
    pb_suffix = ""
    if pb_n >= 1:
        pb_suffix = f" Plus {pb_n} new personal best{'s' if pb_n != 1 else ''}."

    if n_gold >= 3 and len(gold_strokes) == 1:
        stroke_word = _STROKE_TITLE[next(iter(gold_strokes))]
        clean = f"{name} sweeps the {stroke_word} events: {swim_list}."
        team = (f"What a meet from {name} — a clean sweep of the {stroke_word} events. "
                f"{n_gold} golds across {n_swims} notable swims.{pb_suffix} Take a bow.")
        hype = f"{name.upper()}. {stroke_word.upper()} CLEAN SWEEP. {n_gold} GOLDS. UNREAL."
    elif n_gold >= 2:
        clean = f"{name} — multi-event winner: {swim_list}."
        team = (f"{name} raised the level all weekend: {n_gold} golds across {n_swims} notable swims."
                f"{pb_suffix} Special performance.")
        hype = f"{name.upper()}. {n_gold}x GOLD. {n_swims} STANDOUT SWIMS. {club_short.upper()}."
    else:
        # Lead with whichever truth is strongest: medals, PBs, or just standout swims.
        n_medal = sum(1 for c in card.claims if c.kind in ("gold", "silver", "bronze"))
        n_qual = sum(1 for c in card.claims if c.kind == "qual_hit")
        clean = f"{name} — meet of the weekend: {swim_list}."
        if n_medal >= 1 and pb_n >= 1:
            team = (f"Standout meet from {name}: {n_medal} medal{'s' if n_medal!=1 else ''} "
                    f"and {pb_n} new personal best{'s' if pb_n!=1 else ''} across {n_swims} notable swims.")
        elif n_medal >= 1:
            team = (f"Standout meet from {name}: {n_medal} medal{'s' if n_medal!=1 else ''} "
                    f"across {n_swims} notable swims. Big weekend.")
        elif pb_n >= 1:
            team = (f"{name} chased times all weekend — {pb_n} new personal best{'s' if pb_n!=1 else ''} "
                    f"across {n_swims} notable swims.")
        elif n_qual >= 1:
            team = (f"{name} put down qualifier-level swims across {n_swims} events "
                    f"this weekend. Big level.")
        else:
            team = f"{n_swims} notable swims for {name} this weekend. Standout meet."
        hype = f"{name.upper()}. {n_swims} STANDOUT SWIMS. {club_short.upper()} STAND UP."

    return CaptionVariants(clean=clean, team=team, hype=hype)


def _captions_pb_roundup(card: ContentCard, club_short: str) -> CaptionVariants:
    pbs = [c for c in card.claims if c.kind == "pb_confirmed"]
    n = len(pbs)
    names = sorted({c.swimmer_name for c in pbs})
    n_swimmers = len(names)
    name_list = ", ".join(names[:4]) + ("…" if n_swimmers > 4 else "")
    clean = f"{n} personal bests across {n_swimmers} swimmers."
    team = (f"Personal bests are why we keep showing up. {n} new PBs this weekend "
            f"across {n_swimmers} of us — {name_list}.")
    hype = f"{n} PBs. {n_swimmers} SWIMMERS. {club_short.upper()} GOING FASTER."
    return CaptionVariants(clean=clean, team=team, hype=hype)


def _captions_podium_roundup(card: ContentCard, club_short: str) -> CaptionVariants:
    gold = sum(1 for c in card.claims if c.kind == "gold")
    silver = sum(1 for c in card.claims if c.kind == "silver")
    bronze = sum(1 for c in card.claims if c.kind == "bronze")
    total = gold + silver + bronze
    n_swimmers = len({c.swimmer_name for c in card.claims})
    clean = f"Medal haul: {gold} gold, {silver} silver, {bronze} bronze across {n_swimmers} swimmers."
    team = (f"{total} medals on the board this weekend — "
            f"{gold} gold, {silver} silver, {bronze} bronze. Proud of every swim.")
    hype = f"{gold}G · {silver}S · {bronze}B. {total} MEDALS. {club_short.upper()}."
    return CaptionVariants(clean=clean, team=team, hype=hype)


def _captions_weekend_numbers(card: ContentCard, club_short: str) -> CaptionVariants:
    sub = card.subhead or ""
    clean = f"Weekend in numbers — {sub}"
    team = f"The weekend, in numbers: {sub}. Big effort from everyone."
    hype = f"WEEKEND IN NUMBERS. {sub.upper()}."
    return CaptionVariants(clean=clean, team=team, hype=hype)


def _captions_qual_alert(card: ContentCard, club_short: str) -> CaptionVariants:
    return _captions_standout(card, club_short)


def _captions_needs_conf(card: ContentCard, club_short: str) -> CaptionVariants:
    name = card.primary_swimmer or "A swimmer"
    return CaptionVariants(
        clean=f"{name} — strong swim awaiting confirmation.",
        team=f"{name} put down a strong swim — we'll confirm the details before posting.",
        hype="HOLD — pending confirmation.",
    )


_GENERATORS = {
    TYPE_STANDOUT: _captions_standout,
    TYPE_SPOTLIGHT: _captions_spotlight,
    TYPE_PB_ROUNDUP: _captions_pb_roundup,
    TYPE_PODIUM_ROUNDUP: _captions_podium_roundup,
    TYPE_WEEKEND_NUMBERS: _captions_weekend_numbers,
    TYPE_QUAL_ALERT: _captions_qual_alert,
    TYPE_NEEDS_CONFIRMATION: _captions_needs_conf,
}


def write_captions(cards: list[ContentCard], *, club_short: str = "Swansea Uni") -> list[ContentCard]:
    for card in cards:
        gen = _GENERATORS.get(card.card_type)
        if gen is None:
            card.captions = CaptionVariants(clean=card.headline, team=card.headline, hype=card.headline)
        else:
            card.captions = gen(card, club_short)
    return cards
