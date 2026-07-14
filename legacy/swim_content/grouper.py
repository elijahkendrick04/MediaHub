"""
Storyline grouper.

Takes a list of per-swim Claims and produces a list of ContentCards where:
  - one swimmer with multiple notable swims becomes an `athlete_spotlight`
    (sweep if all golds in same stroke, doubles if 2 wins, dominates if 3+ wins)
  - otherwise each notable swim becomes a `standout_swim`
  - confirmed PBs across the team become a single `pb_roundup`
  - qualifying-time hits become `qual_alert` cards (one per swim, but flagged)

Emission contract (per swimmer — the two card types are mutually exclusive):
  - A swimmer with 3+ notable swims OR a same-stroke gold double yields exactly
    ONE `athlete_spotlight` card and NO `standout_swim` cards.
  - Every other swimmer (1-2 notable swims, not a same-stroke gold double)
    yields one `standout_swim` per notable swim and NO spotlight.
  A single swimmer therefore never produces both a spotlight and standouts. The
  anti-spam rule the brief asked for ("one card instead of a flood of
  standalone swims") is enforced structurally here at grouping time — the
  spotlight is emitted *instead of* the per-swim standouts, not alongside them
  and then demoted downstream.

  Consequence for `ranker_v3.rank_cards`: this grouper keys swimmers by
  `swimmer_tiref or swimmer_name` (see the loop below), so a single athlete
  never yields both a spotlight and standouts. The ranker's step-2
  spotlight-owner demotion, however, keys on `primary_swimmer` — the display
  *name*. The two keys agree except when two DISTINCT athletes share a display
  name (distinct tirefs): only then can the name-keyed demotion fire on this
  grouper's output, and it fires on the *other* same-named athlete's standout.
  So the demotion is effectively a no-op on real output in the common case, but
  it is not strictly unreachable. Any change to that coupling (e.g. re-keying
  the demotion on tiref) must be coordinated with the ranker_v3 owner — see PR
  notes for finding F28.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .cards import (
    Claim, ContentCard, CaptionVariants,
    TYPE_STANDOUT, TYPE_SPOTLIGHT, TYPE_PB_ROUNDUP, TYPE_QUAL_ALERT,
    TYPE_PODIUM_ROUNDUP, TYPE_WEEKEND_NUMBERS, TYPE_RECAP, TYPE_NEEDS_CONFIRMATION,
)
from .evidence import Evidence, evidence_from_meet


# ---------- helpers ----------

# Stroke families for sweep-detection headlines. Both lookup sites
# (`_event_label` and the spotlight `family` local) use `.get(stroke, stroke)`,
# so an unknown/raw or empty stroke code degrades to a label instead of raising
# KeyError (finding F61).
_STROKE_FAMILY_TITLE = {"FR": "Freestyle", "BK": "Backstroke", "BR": "Breaststroke",
                         "FL": "Butterfly", "IM": "Individual Medley"}


def _event_label(distance: int, stroke: str, course: str) -> str:
    return f"{distance}m {_STROKE_FAMILY_TITLE.get(stroke, stroke)} ({course})"


def _is_medal(claim: Claim) -> bool:
    return claim.kind in ("gold", "silver", "bronze") and claim.place in (1, 2, 3)


def _is_gold(claim: Claim) -> bool:
    return claim.kind == "gold" and claim.place == 1


def _is_pb(claim: Claim) -> bool:
    return claim.kind in ("pb_confirmed", "pb_likely")


def _is_qual_hit(claim: Claim) -> bool:
    return claim.kind == "qual_hit"


# ---------- grouping ----------

def group_claims_into_cards(
    claims: list[Claim],
    *,
    meet_name: str,
) -> list[ContentCard]:
    """
    Top-level grouping. Returns ContentCards (unranked, no captions yet).
    Captions and final scoring/bucketing happen in ranker_v3 + captions_v3.
    """
    # Index claims by swimmer
    by_swimmer: dict[str, list[Claim]] = defaultdict(list)
    for c in claims:
        key = c.swimmer_tiref or c.swimmer_name
        by_swimmer[key].append(c)

    cards: list[ContentCard] = []

    # 1) Per-swimmer storylines
    for swimmer_key, claim_list in by_swimmer.items():
        primary_name = claim_list[0].swimmer_name
        primary_tiref = claim_list[0].swimmer_tiref

        # Group claims by swim (distance/stroke/course/round) so multiple claims
        # for the same swim (e.g. gold + PB + qual hit) merge into one swim entry.
        swim_groups: dict[tuple, list[Claim]] = defaultdict(list)
        for c in claim_list:
            key = (c.distance, c.stroke, c.course, c.round or "")
            swim_groups[key].append(c)

        # Identify notable swims for this swimmer
        notable_swims: list[list[Claim]] = []
        for swim_key, swim_claims in swim_groups.items():
            if any(_is_medal(c) or _is_pb(c) or _is_qual_hit(c) for c in swim_claims):
                notable_swims.append(swim_claims)

        if not notable_swims:
            continue

        gold_swims = [s for s in notable_swims if any(_is_gold(c) for c in s)]
        medal_swims = [s for s in notable_swims if any(_is_medal(c) for c in s)]

        # Spotlight criteria: 3+ notable swims OR 2+ gold swims in the same stroke
        gold_strokes = [s[0].stroke for s in gold_swims]
        same_stroke_sweep = len(gold_strokes) >= 2 and len(set(gold_strokes)) == 1
        many_notables = len(notable_swims) >= 3

        if same_stroke_sweep or many_notables:
            # Build a spotlight card
            stroke = gold_strokes[0] if same_stroke_sweep else None
            # Guard the family lookup like `_event_label` does: an unknown stroke
            # code degrades to its own label, and a missing/empty code degrades to
            # "", so building the headline never KeyErrors (finding F61). `family`
            # is only consumed on the same_stroke_sweep path below.
            family = _STROKE_FAMILY_TITLE.get(stroke, stroke) or ""
            if same_stroke_sweep and len(gold_swims) >= 3:
                headline = f"{primary_name} — {family.lower()} clean sweep"
                subhead = f"{len(gold_swims)} golds in the {family} events"
            elif same_stroke_sweep:
                headline = f"{primary_name} doubles up in the {family.lower()}"
                subhead = f"Two golds across the {family} events"
            elif len(gold_swims) >= 2 and len(gold_swims) >= len(medal_swims) - 1:
                headline = f"{primary_name} — multi-event winner"
                subhead = f"{len(gold_swims)} golds and {len(notable_swims)} notable swims"
            else:
                headline = f"{primary_name} — standout meet"
                subhead = f"{len(notable_swims)} notable swims"

            card = ContentCard(
                card_id=f"spotlight::{swimmer_key}",
                card_type=TYPE_SPOTLIGHT,
                headline=headline,
                subhead=subhead,
                swimmer_names=[primary_name],
                primary_swimmer=primary_name,
                primary_tiref=primary_tiref,
                claims=[c for swim in notable_swims for c in swim],
                evidence=[evidence_from_meet(
                    f"{primary_name} swam {len(notable_swims)} notable swims",
                    meet_name)],
            )
            cards.append(card)
        else:
            # One standout card per notable swim. A swimmer reaching this branch
            # has at most 2 notable swims (3+ notables or a same-stroke gold
            # double would have produced a spotlight above), so a single swimmer
            # can't flood the queue here. Across swimmers, the global queue cap in
            # ranker_v3 is the volume control (the ranker never dedups cards).
            for swim_claims in notable_swims:
                ref = swim_claims[0]
                ev_label = _event_label(ref.distance, ref.stroke, ref.course)
                # Headline depends on the strongest claim on this swim
                medal_claim = next((c for c in swim_claims if _is_medal(c)), None)
                pb_claim = next((c for c in swim_claims if _is_pb(c)), None)
                qual_claim = next((c for c in swim_claims if _is_qual_hit(c)), None)
                if medal_claim and _is_gold(medal_claim):
                    headline = f"Gold for {primary_name} — {ev_label}"
                elif medal_claim:
                    medal_word = {"silver": "Silver", "bronze": "Bronze"}[medal_claim.kind]
                    headline = f"{medal_word} for {primary_name} — {ev_label}"
                elif pb_claim and pb_claim.kind == "pb_confirmed":
                    headline = f"PB for {primary_name} — {ev_label}"
                elif pb_claim:
                    headline = f"Likely PB for {primary_name} — {ev_label}"
                elif qual_claim:
                    headline = f"{primary_name} hits qualifying time — {ev_label}"
                else:
                    headline = f"{primary_name} — {ev_label}"

                subhead = f"{ref.time_str} · {meet_name}"
                card = ContentCard(
                    card_id=f"standout::{swimmer_key}::{ref.distance}_{ref.stroke}_{ref.course}_{ref.round or ''}",
                    card_type=TYPE_STANDOUT,
                    headline=headline,
                    subhead=subhead,
                    swimmer_names=[primary_name],
                    primary_swimmer=primary_name,
                    primary_tiref=primary_tiref,
                    claims=swim_claims,
                    evidence=[evidence_from_meet(
                        f"{primary_name} {ref.time_str} in {ev_label}",
                        meet_name)],
                )
                cards.append(card)

    # 2) PB roundup — only if there are at least 4 confirmed PBs across the team
    confirmed_pb_claims = [c for c in claims if c.kind == "pb_confirmed"]
    if len(confirmed_pb_claims) >= 4:
        names = sorted({c.swimmer_name for c in confirmed_pb_claims})
        cards.append(ContentCard(
            card_id="pb_roundup::all",
            card_type=TYPE_PB_ROUNDUP,
            headline=f"{len(confirmed_pb_claims)} personal bests for the squad",
            subhead=f"PBs across {len(names)} swimmers",
            swimmer_names=names,
            claims=confirmed_pb_claims,
            evidence=[evidence_from_meet(
                f"{len(confirmed_pb_claims)} confirmed PBs across {len(names)} swimmers",
                meet_name)],
        ))

    # 3) Podium roundup — only if there are 5+ medals
    medal_claims = [c for c in claims if _is_medal(c)]
    if len(medal_claims) >= 5:
        gold_n = sum(1 for c in medal_claims if c.kind == "gold")
        silver_n = sum(1 for c in medal_claims if c.kind == "silver")
        bronze_n = sum(1 for c in medal_claims if c.kind == "bronze")
        names = sorted({c.swimmer_name for c in medal_claims})
        cards.append(ContentCard(
            card_id="podium_roundup::all",
            card_type=TYPE_PODIUM_ROUNDUP,
            headline=f"Medal haul: {gold_n}G · {silver_n}S · {bronze_n}B",
            subhead=f"Across {len(names)} swimmers",
            swimmer_names=names,
            claims=medal_claims,
            evidence=[evidence_from_meet(
                f"{len(medal_claims)} medals across {len(names)} swimmers",
                meet_name)],
        ))

    # 4) Weekend in numbers — always include if the dataset is non-trivial
    if len(claims) >= 8:
        n_swimmers = len({c.swimmer_tiref or c.swimmer_name for c in claims})
        n_finals = sum(1 for c in claims if c.round == "F")
        n_pbs = len([c for c in claims if c.kind == "pb_confirmed"])
        n_quals = len([c for c in claims if _is_qual_hit(c)])
        cards.append(ContentCard(
            card_id="weekend_in_numbers",
            card_type=TYPE_WEEKEND_NUMBERS,
            headline="Weekend in numbers",
            subhead=f"{n_swimmers} swimmers · {n_finals} finals · {n_pbs} PBs · {n_quals} qualifiers",
            swimmer_names=[],
            claims=[],
            evidence=[evidence_from_meet(
                "Aggregate counts derived from the uploaded meet file.",
                meet_name)],
        ))

    return cards
