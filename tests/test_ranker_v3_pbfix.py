"""Regression tests for the PB-ranker fix package (P7) on ``swim_content.ranker_v3``.

Companion to ``test_ranker_v3_direct.py``. These lock in the behaviour of the
deterministic V3 ranker AFTER the P7 bug-fixes, and guard the exact defects the
diagnosis (docs/PB_RANKER_DIAGNOSIS.md) found latent:

  * F06 — out-of-window qualifier hits are soft-weighted below in-window ones
          (reads ``Claim.extra['in_window']``; missing flag = in-window;
          persisted ``"false"`` strings are coerced).
  * F35 — the queue-cap keep/demote PARTITION is deterministic (whole queue is
          ranked by ``(-score, card_id)`` then sliced — not input-order).
  * F55 — a cap-demoted card's suggested_format is recomputed, so a demoted
          spotlight keeps its ``athlete_spotlight`` format.
  * F60 — the same-stroke gold bonus reason matches the grouper vocabulary
          (2 = "doubles up", 3+ = "clean sweep"), and the >=3-notable bonus
          counts distinct EVENTS (prelim + final of one event is not two).
  * F53 — the previously-unasserted spotlight multi-event bonus, sweep bonus,
          and FMT_STORY assignment.

They call the real ``rank_cards`` and assert the stable contract (scores,
ordering, buckets, formats, and the user-visible reason strings).
"""

from __future__ import annotations

from swim_content.cards import (
    Claim,
    ContentCard,
    FMT_RECAP,
    FMT_SPOTLIGHT,
    FMT_STORY,
    TYPE_QUAL_ALERT,
    TYPE_SPOTLIGHT,
    TYPE_STANDOUT,
)
from swim_content.ranker_v3 import rank_cards


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def _claim(
    kind: str,
    *,
    swimmer: str = "Alex Kim",
    level: str | None = None,
    in_window=None,
    stroke: str = "Freestyle",
    distance: int = 100,
    course: str = "LC",
    round_: str = "F",
) -> Claim:
    extra: dict = {}
    if level is not None:
        extra["level"] = level
    if in_window is not None:
        extra["in_window"] = in_window
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
        place=1,
        round=round_,
        swim_date="2026-01-01",
        extra=extra,
    )


def _card(cid, ctype, *, swimmer=None, claims=None) -> ContentCard:
    return ContentCard(
        card_id=cid,
        card_type=ctype,
        headline=cid,
        primary_swimmer=swimmer,
        swimmer_names=[swimmer] if swimmer else [],
        claims=list(claims or []),
    )


def _by_id(cards):
    return {c.card_id: c for c in cards}


def _reasons(card):
    return " || ".join(card.score_reasons)


# --------------------------------------------------------------------------- #
# F06 — out-of-window qualifier soft-weighting
# --------------------------------------------------------------------------- #


def test_out_of_window_national_soft_weights_below_in_window_bucs():
    """An out-of-window national qual (+4 => 74) must rank BELOW a genuine
    in-window BUCS hit (+6 => 76) and an in-window national (+10 => 80)."""
    nat_in = _card("nat_in", TYPE_QUAL_ALERT, swimmer="A",
                   claims=[_claim("qual_hit", swimmer="A", level="national", in_window=True)])
    nat_out = _card("nat_out", TYPE_QUAL_ALERT, swimmer="B",
                    claims=[_claim("qual_hit", swimmer="B", level="national", in_window=False)])
    bucs_in = _card("bucs_in", TYPE_QUAL_ALERT, swimmer="C",
                    claims=[_claim("qual_hit", swimmer="C", level="university", in_window=True)])

    by = _by_id(rank_cards([nat_out, bucs_in, nat_in]))
    assert by["nat_in"].score == 80
    assert by["bucs_in"].score == 76
    assert by["nat_out"].score == 74  # soft-weighted to +4
    assert by["nat_in"].score > by["bucs_in"].score > by["nat_out"].score

    # The out-of-window card must NOT claim a national hit; its reason is honest.
    assert "national-level" not in _reasons(by["nat_out"])
    assert "outside its window" in _reasons(by["nat_out"])


def test_out_of_window_university_soft_weights_to_plus_four():
    by = _by_id(rank_cards([
        _card("uni_out", TYPE_QUAL_ALERT, swimmer="U",
              claims=[_claim("qual_hit", swimmer="U", level="university", in_window=False)]),
    ]))
    assert by["uni_out"].score == 74
    assert "BUCS" not in _reasons(by["uni_out"])
    assert "outside its window" in _reasons(by["uni_out"])


def test_missing_in_window_flag_defaults_to_full_weight():
    """Back-compat: a claim with no in_window flag keeps its prior full weight
    and an honest reason (never a fabricated "outside window" claim)."""
    by = _by_id(rank_cards([
        _card("nat_noflag", TYPE_QUAL_ALERT, swimmer="N",
              claims=[_claim("qual_hit", swimmer="N", level="national")]),
    ]))
    assert by["nat_noflag"].score == 80
    assert "national-level" in _reasons(by["nat_noflag"])
    assert "outside" not in _reasons(by["nat_noflag"])


def test_stringy_false_in_window_is_coerced_out_of_window():
    """Persisted JSON may round-trip the flag as the string "false"; a plain
    truthiness test would wrongly read it as in-window. It must soft-weight."""
    by = _by_id(rank_cards([
        _card("nat_strfalse", TYPE_QUAL_ALERT, swimmer="S",
              claims=[_claim("qual_hit", swimmer="S", level="national", in_window="false")]),
    ]))
    assert by["nat_strfalse"].score == 74
    assert "outside its window" in _reasons(by["nat_strfalse"])


def test_mixed_in_and_out_of_window_prefers_the_in_window_level():
    """A card with BOTH an out-of-window national and an in-window BUCS hit
    earns the in-window BUCS weight (+6), not the out-of-window national."""
    by = _by_id(rank_cards([
        _card("mixed", TYPE_QUAL_ALERT, swimmer="M", claims=[
            _claim("qual_hit", swimmer="M", level="national", in_window=False),
            _claim("qual_hit", swimmer="M", level="university", in_window=True),
        ]),
    ]))
    assert by["mixed"].score == 76  # in-window BUCS wins
    assert "BUCS" in _reasons(by["mixed"])


# --------------------------------------------------------------------------- #
# F35 — deterministic queue-cap partition (membership, not just order)
# --------------------------------------------------------------------------- #


def _tied_national_cards():
    return [
        _card(f"cap_q{i:02d}", TYPE_QUAL_ALERT, swimmer=f"S{i}",
              claims=[_claim("qual_hit", swimmer=f"S{i}", level="national", in_window=True)])
        for i in range(5)
    ]


def test_queue_cap_partition_is_input_order_independent():
    """Five identical (score 80) national qual cards, cap 2. Regardless of input
    order the SAME two cards (smallest card_ids) keep queue and the SAME three
    demote — the keep/demote membership is deterministic, not stable-sort luck."""
    fwd = _tied_national_cards()
    rev = list(reversed(_tied_national_cards()))

    by_fwd = _by_id(rank_cards(fwd, queue_cap=2))
    by_rev = _by_id(rank_cards(rev, queue_cap=2))

    kept_fwd = {cid for cid, c in by_fwd.items() if c.bucket == "queue"}
    kept_rev = {cid for cid, c in by_rev.items() if c.bucket == "queue"}

    assert kept_fwd == {"cap_q00", "cap_q01"}
    assert kept_rev == {"cap_q00", "cap_q01"}  # identical despite reversed input
    assert kept_fwd == kept_rev


def test_ranker_is_fully_deterministic_across_repeated_runs():
    """Same input -> byte-identical (bucket, format, ordered ids) every time.
    Guards the (bucket, -score, card_id) total order the fixes rely on."""
    def snapshot():
        cards = _tied_national_cards() + [
            _card("sp", TYPE_SPOTLIGHT, swimmer="Z", claims=[_claim("gold", swimmer="Z")]),
            _card("st", TYPE_STANDOUT, swimmer="Y", claims=[_claim("gold", swimmer="Y")]),
        ]
        ranked = rank_cards(cards, queue_cap=3)
        return [(c.card_id, c.bucket, c.suggested_format, c.score) for c in ranked]

    assert snapshot() == snapshot()


# --------------------------------------------------------------------------- #
# F55 — cap-demoted format is recomputed, not hardcoded
# --------------------------------------------------------------------------- #


def test_cap_demoted_spotlight_keeps_spotlight_format():
    """Spotlights (base 70) can only reach recap via the cap; a cap-demoted
    spotlight must keep FMT_SPOTLIGHT (recomputed), not become FMT_RECAP."""
    sp = [_card(f"sp{i}", TYPE_SPOTLIGHT, swimmer=f"P{i}",
                claims=[_claim("gold", swimmer=f"P{i}")]) for i in range(3)]
    by = _by_id(rank_cards(sp, queue_cap=1))
    demoted = [c for c in by.values() if c.bucket == "recap"]
    assert len(demoted) == 2
    for c in demoted:
        assert c.suggested_format == FMT_SPOTLIGHT
        assert any("Queue cap reached" in r for r in c.score_reasons)


def test_cap_demoted_qual_alert_still_gets_recap_format():
    """A cap-demoted qual_alert (no type-specific recap format) still resolves
    to FMT_RECAP through _suggested_format — the recompute is type-correct."""
    by = _by_id(rank_cards(_tied_national_cards(), queue_cap=2))
    demoted = [c for c in by.values() if c.bucket == "recap"]
    assert demoted and all(c.suggested_format == FMT_RECAP for c in demoted)


# --------------------------------------------------------------------------- #
# F60 — sweep vocabulary + event-distinct breadth
# --------------------------------------------------------------------------- #


def test_two_same_stroke_golds_is_doubles_up_not_clean_sweep():
    """Exactly two same-stroke golds must read "doubles up" (matching the
    grouper headline), never "clean sweep"."""
    card = _card("dbl", TYPE_SPOTLIGHT, swimmer="Dana", claims=[
        _claim("gold", swimmer="Dana", stroke="Backstroke", distance=100),
        _claim("gold", swimmer="Dana", stroke="Backstroke", distance=200),
    ])
    by = _by_id(rank_cards([card]))
    assert "doubles up" in _reasons(by["dbl"])
    assert "clean sweep" not in _reasons(by["dbl"])
    # bonus still applies (+5): base 70 + gold 8 + doubles 5 = 83
    assert by["dbl"].score == 83


def test_three_same_stroke_golds_is_clean_sweep():
    card = _card("swp", TYPE_SPOTLIGHT, swimmer="Cleo", claims=[
        _claim("gold", swimmer="Cleo", stroke="Fly", distance=50),
        _claim("gold", swimmer="Cleo", stroke="Fly", distance=100),
        _claim("gold", swimmer="Cleo", stroke="Fly", distance=200),
    ])
    by = _by_id(rank_cards([card]))
    assert "clean sweep" in _reasons(by["swp"])
    assert "doubles up" not in _reasons(by["swp"])


def test_breadth_bonus_counts_distinct_events_not_rounds():
    """A prelim + final of the SAME event is one event's breadth: a card whose
    only 3rd "swim" is a second round of an existing event must NOT earn the
    >=3-notable-events +5."""
    round_split = _card("rs", TYPE_SPOTLIGHT, swimmer="Rae", claims=[
        _claim("pb_confirmed", swimmer="Rae", stroke="Free", distance=100, round_="P"),
        _claim("gold", swimmer="Rae", stroke="Free", distance=100, round_="F"),
        _claim("gold", swimmer="Rae", stroke="Breast", distance=100, round_="F"),
    ])  # 2 distinct events -> no breadth bonus
    genuine = _card("ge", TYPE_SPOTLIGHT, swimmer="Gia", claims=[
        _claim("gold", swimmer="Gia", stroke="Free", distance=100, round_="F"),
        _claim("silver", swimmer="Gia", stroke="Back", distance=100, round_="F"),
        _claim("pb_confirmed", swimmer="Gia", stroke="Breast", distance=200, round_="F"),
    ])  # 3 distinct events -> breadth bonus
    by = _by_id(rank_cards([round_split, genuine]))

    assert not any("notable events" in r for r in by["rs"].score_reasons)
    assert any("Spotlight covers 3 notable events" in r for r in by["ge"].score_reasons)
    # round_split: 70 + pb 12 + gold 8 = 90 (no +5); genuine: 70 + gold 8 + pb 12 + breadth 5 = 95
    assert by["rs"].score == 90
    assert by["ge"].score == 95


# --------------------------------------------------------------------------- #
# F53 — previously-unasserted rules
# --------------------------------------------------------------------------- #


def test_spotlight_multi_event_bonus_awards_plus_five():
    """>=3 distinct events earns +5 with an event-count reason (F53 gap)."""
    card = _card("multi", TYPE_SPOTLIGHT, swimmer="Mia", claims=[
        _claim("gold", swimmer="Mia", stroke="Free", distance=50),
        _claim("gold", swimmer="Mia", stroke="Back", distance=100),
        _claim("gold", swimmer="Mia", stroke="Breast", distance=200),
    ])
    by = _by_id(rank_cards([card]))
    # 3 different strokes -> no same-stroke sweep; breadth +5 only.
    assert any("Spotlight covers 3 notable events (+5)" in r for r in by["multi"].score_reasons)
    assert not any("sweep" in r or "doubles" in r for r in by["multi"].score_reasons)
    assert by["multi"].score == 83  # 70 + gold 8 + breadth 5


def test_queue_bucket_standout_is_suggested_as_a_story():
    """The documented "default standalone medals to a story" branch: a standout
    that reaches the queue bucket gets FMT_STORY (F53 gap — never covered)."""
    card = _card("story", TYPE_STANDOUT, swimmer="Sky", claims=[
        _claim("pb_confirmed", swimmer="Sky"),
        _claim("gold", swimmer="Sky"),
        _claim("qual_hit", swimmer="Sky", level="national", in_window=True),
    ])  # 40 + 12 + 8 + 10 = 70 -> queue
    by = _by_id(rank_cards([card]))
    assert by["story"].score == 70
    assert by["story"].bucket == "queue"
    assert by["story"].suggested_format == FMT_STORY


def test_score_is_clamped_to_one_hundred():
    """A maximal spotlight (70 + 12 + 8 + 10 + 5 breadth + 5 sweep = 110) clamps
    to 100, never exceeds it."""
    card = _card("max", TYPE_SPOTLIGHT, swimmer="Max", claims=[
        _claim("gold", swimmer="Max", stroke="Fly", distance=50),
        _claim("gold", swimmer="Max", stroke="Fly", distance=100),
        _claim("gold", swimmer="Max", stroke="Fly", distance=200),
        _claim("pb_confirmed", swimmer="Max", stroke="Fly", distance=100),
        _claim("qual_hit", swimmer="Max", level="national", in_window=True),
    ])
    by = _by_id(rank_cards([card]))
    assert by["max"].score == 100


# --------------------------------------------------------------------------- #
# Composite — the fixes interact through the 20-cap (council-mandated)
# --------------------------------------------------------------------------- #


def test_composite_pipeline_no_unintended_threshold_crossings():
    """Run a diverse card set through the whole pipeline so the F06 re-scores,
    the F60 bonus changes, and the F35/F55 cap all compose. Assert the final
    ordering and that each card lands in the bucket its (post-fix) score dictates
    — nothing crosses 65/40 by accident."""
    cards = [
        _card("A_nat_in", TYPE_QUAL_ALERT, swimmer="A",
              claims=[_claim("qual_hit", swimmer="A", level="national", in_window=True)]),      # 80 queue
        _card("B_nat_out", TYPE_QUAL_ALERT, swimmer="B",
              claims=[_claim("qual_hit", swimmer="B", level="national", in_window=False)]),     # 74 queue
        _card("C_doubles", TYPE_SPOTLIGHT, swimmer="C", claims=[
            _claim("gold", swimmer="C", stroke="Fly", distance=100),
            _claim("gold", swimmer="C", stroke="Fly", distance=200)]),                          # 83 queue
        _card("D_gold_std", TYPE_STANDOUT, swimmer="D",
              claims=[_claim("gold", swimmer="D")]),                                             # 48 recap
        _card("E_bronze_std", TYPE_STANDOUT, swimmer="E",
              claims=[_claim("bronze", swimmer="E")]),                                           # 42 recap
        _card("F_likely_only", TYPE_STANDOUT, swimmer="F",
              claims=[_claim("pb_likely", swimmer="F")]),                                        # 35 archive
    ]
    ranked = rank_cards(cards, queue_cap=2)
    by = _by_id(ranked)

    assert by["A_nat_in"].score == 80 and by["A_nat_in"].bucket == "queue"
    assert by["C_doubles"].score == 83 and by["C_doubles"].bucket == "queue"
    # B (74) is queue-worthy but the cap=2 keeps only the top two (C=83, A=80).
    assert by["B_nat_out"].score == 74 and by["B_nat_out"].bucket == "recap"
    assert any("Queue cap reached" in r for r in by["B_nat_out"].score_reasons)
    assert by["D_gold_std"].bucket == "recap"
    assert by["E_bronze_std"].bucket == "recap"
    assert by["F_likely_only"].bucket == "archive"

    # Final order obeys (bucket, -score, card_id).
    bucket_rank = {"queue": 0, "recap": 1, "archive": 2}
    keys = [(bucket_rank[c.bucket], -c.score, c.card_id) for c in ranked]
    assert keys == sorted(keys)
