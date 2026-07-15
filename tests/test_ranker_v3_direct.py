"""Direct unit tests for the production ranker (``swim_content.ranker_v3``).

``rank_cards`` is a CLAUDE.md-designated deterministic crown jewel — it decides
"which card outranks which?" and was previously only exercised transitively
through the pipeline. These tests build KNOWN cards (a medal, a confirmed PB, a
likely-only PB, a qualifier hit, an ordinary swim, a spotlight) and assert the
ranker's stable contract directly:

  * base scores per card type,
  * the medal / PB / qualifier weighting hierarchy,
  * the likely-PB-only penalty,
  * the needs-confirmation penalty + bucket,
  * anti-spam demotion of a standalone when the swimmer has a spotlight,
  * the queue cap demoting the lowest-scoring overflow to recap,
  * and that every ranked card comes back with populated
    ``score`` / ``score_reasons`` / ``bucket`` / ``suggested_format`` fields,
    sorted by (bucket, -score, card_id).

The assertions target the *stable* contract — relative ordering and score
monotonicity — plus the fixed integer base/modifier arithmetic that IS the
documented contract (see the module docstring of ``ranker_v3``). They call the
real ``rank_cards``, not a reimplementation.
"""

from __future__ import annotations

import inspect

from swim_content.cards import (
    Claim,
    ContentCard,
    FMT_ARCHIVE,
    FMT_HOLD,
    FMT_RECAP,
    FMT_SPOTLIGHT,
    TYPE_NEEDS_CONFIRMATION,
    TYPE_PB_ROUNDUP,
    TYPE_PODIUM_ROUNDUP,
    TYPE_QUAL_ALERT,
    TYPE_RECAP,
    TYPE_SPOTLIGHT,
    TYPE_STANDOUT,
    TYPE_WEEKEND_NUMBERS,
)
from swim_content.ranker_v3 import rank_cards

_VALID_BUCKETS = {"queue", "recap", "needs_confirmation", "archive"}


# --------------------------------------------------------------------------- #
# Builders — construct real ContentCard / Claim fixtures the ranker consumes
# --------------------------------------------------------------------------- #


def _claim(
    kind: str,
    *,
    swimmer: str = "Alex Kim",
    level: str | None = None,
    stroke: str = "Freestyle",
    distance: int = 100,
    course: str = "LC",
    round_: str = "F",
    place: int | None = None,
) -> Claim:
    """A fully-populated ``Claim`` of the given kind.

    ``level`` (for ``qual_hit`` claims) rides in ``extra`` exactly where the
    ranker reads it (``_qual_hits`` → ``c.extra.get("level")``).
    """
    extra: dict = {}
    if level is not None:
        extra["level"] = level
    return Claim(
        kind=kind,
        swimmer_name=swimmer,
        swimmer_tiref=None,
        event_label=f"{distance}m {stroke} ({course})",
        distance=distance,
        stroke=stroke,
        course=course,
        time_str="00:58.31",
        time_sec=58.31,
        place=place,
        round=round_,
        swim_date="2026-01-01",
        extra=extra,
    )


def _card(
    card_id: str,
    card_type: str,
    *,
    swimmer: str | None = None,
    claims: list[Claim] | None = None,
    needs_confirmation: bool = False,
) -> ContentCard:
    return ContentCard(
        card_id=card_id,
        card_type=card_type,
        headline=f"{card_type}:{card_id}",
        primary_swimmer=swimmer,
        swimmer_names=[swimmer] if swimmer else [],
        claims=list(claims or []),
        needs_confirmation=needs_confirmation,
    )


def _by_id(cards: list[ContentCard]) -> dict[str, ContentCard]:
    return {c.card_id: c for c in cards}


def _order(cards: list[ContentCard]) -> list[str]:
    return [c.card_id for c in cards]


# --------------------------------------------------------------------------- #
# Signature contract
# --------------------------------------------------------------------------- #


def test_rank_cards_signature_is_stable():
    """rank_cards(list[ContentCard], *, queue_cap=20) — the caller contract."""
    sig = inspect.signature(rank_cards)
    params = sig.parameters
    assert "queue_cap" in params
    qc = params["queue_cap"]
    assert qc.default == 20
    assert qc.kind is inspect.Parameter.KEYWORD_ONLY


# --------------------------------------------------------------------------- #
# Base scores by card type
# --------------------------------------------------------------------------- #


def test_base_scores_and_buckets_by_type():
    """With no claims, each card scores its documented base and buckets by it.

    Distinct swimmers so anti-spam (spotlight → standalone demotion) never
    fires and each base score is observed in isolation.
    """
    cards = [
        _card("spotlight", TYPE_SPOTLIGHT, swimmer="A One"),
        _card("qual", TYPE_QUAL_ALERT, swimmer="B Two"),
        _card("pbroundup", TYPE_PB_ROUNDUP, swimmer="C Three"),
        _card("podium", TYPE_PODIUM_ROUNDUP, swimmer="D Four"),
        _card("weekend", TYPE_WEEKEND_NUMBERS, swimmer="E Five"),
        _card("standout", TYPE_STANDOUT, swimmer="F Six"),
        _card("recap", TYPE_RECAP, swimmer="G Seven"),
    ]
    ranked = _by_id(rank_cards(cards))

    # Exact base scores (fixed arithmetic is the documented contract).
    assert ranked["spotlight"].score == 70
    assert ranked["qual"].score == 70
    assert ranked["pbroundup"].score == 65
    assert ranked["podium"].score == 55
    assert ranked["weekend"].score == 45
    assert ranked["standout"].score == 40
    assert ranked["recap"].score == 25

    # Buckets follow the thresholds (>=65 queue, 40-64 recap, <40 archive).
    assert ranked["spotlight"].bucket == "queue"
    assert ranked["qual"].bucket == "queue"
    assert ranked["pbroundup"].bucket == "queue"
    assert ranked["podium"].bucket == "recap"
    assert ranked["weekend"].bucket == "recap"
    assert ranked["standout"].bucket == "recap"
    assert ranked["recap"].bucket == "archive"


# --------------------------------------------------------------------------- #
# Medal / PB / ordinary hierarchy (same base, claim-driven ordering)
# --------------------------------------------------------------------------- #


def test_medal_hierarchy_gold_beats_silver_beats_bronze():
    """Same card type, only the medal differs → gold > silver > bronze."""
    gold = _card("gold", TYPE_STANDOUT, swimmer="G Au", claims=[_claim("gold", swimmer="G Au")])
    silver = _card(
        "silver", TYPE_STANDOUT, swimmer="S Ag", claims=[_claim("silver", swimmer="S Ag")]
    )
    bronze = _card(
        "bronze", TYPE_STANDOUT, swimmer="B Cu", claims=[_claim("bronze", swimmer="B Cu")]
    )
    ranked = rank_cards([bronze, silver, gold])  # deliberately unsorted input
    by = _by_id(ranked)

    # Base 40 + medal modifier (gold +8, silver +4, bronze +2).
    assert by["gold"].score == 48
    assert by["silver"].score == 44
    assert by["bronze"].score == 42
    assert by["gold"].score > by["silver"].score > by["bronze"].score

    # All three land in recap (40-64); the ranker returns them gold→silver→bronze.
    assert _order(ranked) == ["gold", "silver", "bronze"]
    assert any("gold medal" in r for r in by["gold"].score_reasons)


def test_confirmed_pb_outranks_medal_and_ordinary_swim():
    """A confirmed PB (+12) outscores a gold medal (+8), which beats an ordinary
    finals swim (no modifier)."""
    pb = _card(
        "pb", TYPE_STANDOUT, swimmer="P Best", claims=[_claim("pb_confirmed", swimmer="P Best")]
    )
    medal = _card(
        "medal", TYPE_STANDOUT, swimmer="M Gold", claims=[_claim("gold", swimmer="M Gold")]
    )
    ordinary = _card(
        "ordinary", TYPE_STANDOUT, swimmer="O Swim", claims=[_claim("final", swimmer="O Swim")]
    )
    ranked = rank_cards([ordinary, medal, pb])
    by = _by_id(ranked)

    assert by["pb"].score == 52  # 40 + 12
    assert by["medal"].score == 48  # 40 + 8
    assert by["ordinary"].score == 40  # base only
    assert by["pb"].score > by["medal"].score > by["ordinary"].score
    assert _order(ranked) == ["pb", "medal", "ordinary"]
    assert any("Confirmed personal best" in r for r in by["pb"].score_reasons)


# --------------------------------------------------------------------------- #
# Likely-PB-only penalty
# --------------------------------------------------------------------------- #


def test_likely_pb_only_is_penalised_and_archived():
    """A likely (unverified) PB with no medal/qualifier gets the -10 penalty and
    drops below archive threshold; a confirmed PB does not."""
    likely = _card(
        "likely", TYPE_STANDOUT, swimmer="L Maybe", claims=[_claim("pb_likely", swimmer="L Maybe")]
    )
    confirmed = _card(
        "confirmed",
        TYPE_STANDOUT,
        swimmer="C Sure",
        claims=[_claim("pb_confirmed", swimmer="C Sure")],
    )
    ranked = rank_cards([likely, confirmed])
    by = _by_id(ranked)

    # 40 + 5 (likely) - 10 (unverified penalty) = 35 → archive (<40).
    assert by["likely"].score == 35
    assert by["likely"].bucket == "archive"
    assert by["likely"].suggested_format == FMT_ARCHIVE
    assert any("needs evidence" in r for r in by["likely"].score_reasons)
    assert by["confirmed"].score > by["likely"].score
    assert _order(ranked) == ["confirmed", "likely"]


def test_likely_pb_with_a_medal_escapes_the_penalty():
    """The -10 only applies to bare likely PBs — a likely PB that also medalled
    keeps both bonuses and takes no penalty."""
    card = _card(
        "likely_gold",
        TYPE_STANDOUT,
        swimmer="H Hybrid",
        claims=[
            _claim("pb_likely", swimmer="H Hybrid"),
            _claim("gold", swimmer="H Hybrid"),
        ],
    )
    by = _by_id(rank_cards([card]))
    # 40 + 5 (likely) + 8 (gold) = 53, no penalty.
    assert by["likely_gold"].score == 53
    assert not any("needs evidence" in r for r in by["likely_gold"].score_reasons)


# --------------------------------------------------------------------------- #
# Qualifier level weighting
# --------------------------------------------------------------------------- #


def test_qualifier_level_weighting_orders_national_over_bucs_over_open():
    """qual_hit weighting: national +10 > university (BUCS) +6 > other +4."""
    national = _card(
        "national",
        TYPE_QUAL_ALERT,
        swimmer="N Nat",
        claims=[_claim("qual_hit", swimmer="N Nat", level="national")],
    )
    bucs = _card(
        "bucs",
        TYPE_QUAL_ALERT,
        swimmer="U Uni",
        claims=[_claim("qual_hit", swimmer="U Uni", level="university")],
    )
    open_ = _card(
        "open",
        TYPE_QUAL_ALERT,
        swimmer="O Open",
        claims=[_claim("qual_hit", swimmer="O Open", level="open")],
    )
    ranked = rank_cards([open_, bucs, national])
    by = _by_id(ranked)

    assert by["national"].score == 80  # 70 + 10
    assert by["bucs"].score == 76  # 70 + 6
    assert by["open"].score == 74  # 70 + 4
    assert by["national"].score > by["bucs"].score > by["open"].score
    assert _order(ranked) == ["national", "bucs", "open"]


# --------------------------------------------------------------------------- #
# Needs-confirmation penalty + bucket
# --------------------------------------------------------------------------- #


def test_needs_confirmation_flag_penalises_and_holds():
    """The needs_confirmation flag forces the needs_confirmation bucket + hold
    format and applies the -15 penalty regardless of other bonuses."""
    card = _card(
        "hold",
        TYPE_STANDOUT,
        swimmer="Q Query",
        claims=[_claim("gold", swimmer="Q Query")],
        needs_confirmation=True,
    )
    by = _by_id(rank_cards([card]))
    held = by["hold"]
    # 40 + 8 (gold) - 15 = 33.
    assert held.score == 33
    assert held.bucket == "needs_confirmation"
    assert held.suggested_format == FMT_HOLD
    assert any("human confirmation" in r for r in held.score_reasons)


# --------------------------------------------------------------------------- #
# Anti-spam: a spotlight demotes the same swimmer's standalone
# --------------------------------------------------------------------------- #


def test_spotlight_demotes_owning_swimmers_standalone():
    """When a swimmer has an athlete_spotlight, their standalone standout is
    demoted by 25 so the spotlight is the canonical entry — other swimmers'
    standalones are untouched."""
    spotlight = _card(
        "spot", TYPE_SPOTLIGHT, swimmer="Dana Lee", claims=[_claim("gold", swimmer="Dana Lee")]
    )
    dana_standout = _card(
        "dana_standout",
        TYPE_STANDOUT,
        swimmer="Dana Lee",
        claims=[_claim("gold", swimmer="Dana Lee")],
    )
    evan_standout = _card(
        "evan_standout",
        TYPE_STANDOUT,
        swimmer="Evan Poe",
        claims=[_claim("gold", swimmer="Evan Poe")],
    )
    ranked = rank_cards([spotlight, dana_standout, evan_standout])
    by = _by_id(ranked)

    # Evan's standalone: base 40 + gold 8 = 48, untouched.
    assert by["evan_standout"].score == 48
    assert not any("Demoted" in r for r in by["evan_standout"].score_reasons)

    # Dana's standalone: 48 - 25 = 23 → archive, with the demotion reason.
    assert by["dana_standout"].score == 23
    assert any("Demoted" in r and "spotlight" in r for r in by["dana_standout"].score_reasons)
    assert by["dana_standout"].bucket == "archive"

    # The undemoted standalone outranks the demoted one.
    assert _order(ranked).index("evan_standout") < _order(ranked).index("dana_standout")
    # The spotlight itself keeps its high score and its canonical format.
    assert by["spot"].suggested_format == FMT_SPOTLIGHT


# --------------------------------------------------------------------------- #
# Queue cap
# --------------------------------------------------------------------------- #


def test_queue_cap_demotes_lowest_scoring_overflow_to_recap():
    """With more queue-worthy cards than the cap, the lowest scorers spill to
    recap (highest scores keep their queue slots)."""
    national = _card(
        "national",
        TYPE_QUAL_ALERT,
        swimmer="N",
        claims=[_claim("qual_hit", swimmer="N", level="national")],
    )  # 80
    bucs = _card(
        "bucs",
        TYPE_QUAL_ALERT,
        swimmer="U",
        claims=[_claim("qual_hit", swimmer="U", level="university")],
    )  # 76
    open_ = _card(
        "open",
        TYPE_QUAL_ALERT,
        swimmer="O",
        claims=[_claim("qual_hit", swimmer="O", level="open")],
    )  # 74
    roundup = _card("roundup", TYPE_PB_ROUNDUP, swimmer="R")  # 65

    ranked = rank_cards([national, bucs, open_, roundup], queue_cap=2)
    by = _by_id(ranked)

    # Every card scored >= 65 (queue-worthy) before the cap.
    for cid in ("national", "bucs", "open", "roundup"):
        assert by[cid].score >= 65

    # Top two by score keep queue; the two lowest spill to recap.
    assert by["national"].bucket == "queue"
    assert by["bucs"].bucket == "queue"
    assert by["open"].bucket == "recap"
    assert by["roundup"].bucket == "recap"
    assert by["open"].suggested_format == FMT_RECAP
    assert any("Queue cap reached at 2" in r for r in by["open"].score_reasons)
    assert any("Queue cap reached at 2" in r for r in by["roundup"].score_reasons)


def test_default_queue_cap_keeps_a_small_queue_intact():
    """Under the default cap (20), a handful of queue cards all stay in queue."""
    cards = [
        _card(
            f"q{i}",
            TYPE_QUAL_ALERT,
            swimmer=f"S{i}",
            claims=[_claim("qual_hit", swimmer=f"S{i}", level="national")],
        )
        for i in range(3)
    ]
    by = _by_id(rank_cards(cards))
    assert all(by[f"q{i}"].bucket == "queue" for i in range(3))
    assert not any("Queue cap" in r for i in range(3) for r in by[f"q{i}"].score_reasons)


# --------------------------------------------------------------------------- #
# General population + sort invariant
# --------------------------------------------------------------------------- #


def test_rank_cards_populates_fields_and_returns_sorted():
    """Every ranked card carries score / reasons / bucket / format, and the
    returned list is sorted by (bucket_rank, -score, card_id)."""
    cards = [
        _card(
            "spot", TYPE_SPOTLIGHT, swimmer="Ana Vega", claims=[_claim("gold", swimmer="Ana Vega")]
        ),
        _card(
            "pb",
            TYPE_STANDOUT,
            swimmer="Ben Roe",
            claims=[_claim("pb_confirmed", swimmer="Ben Roe")],
        ),
        _card(
            "ord", TYPE_STANDOUT, swimmer="Cy Watts", claims=[_claim("final", swimmer="Cy Watts")]
        ),
        _card(
            "hold",
            TYPE_NEEDS_CONFIRMATION,
            swimmer="Di Fox",
            claims=[_claim("pb_likely", swimmer="Di Fox")],
            needs_confirmation=True,
        ),
        _card(
            "likely",
            TYPE_STANDOUT,
            swimmer="Ed Kane",
            claims=[_claim("pb_likely", swimmer="Ed Kane")],
        ),
    ]
    ranked = rank_cards(cards)

    # rank_cards mutates in place and returns the same list object.
    assert ranked is cards

    for c in ranked:
        assert isinstance(c.score, int)
        assert 0 <= c.score <= 100
        assert c.score_reasons, f"{c.card_id} has no score reasons"
        assert c.bucket in _VALID_BUCKETS
        assert c.suggested_format, f"{c.card_id} has no suggested format"

    # Sort invariant: keys are non-decreasing across the returned list.
    bucket_rank = {"queue": 0, "needs_confirmation": 1, "recap": 2, "archive": 3}
    keys = [(bucket_rank[c.bucket], -c.score, c.card_id) for c in ranked]
    assert keys == sorted(keys)
