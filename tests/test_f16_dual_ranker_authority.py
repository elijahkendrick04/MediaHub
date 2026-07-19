"""F16 regression — pipeline_v4 dual-ranker reconciliation (ADR-0032).

The pipeline runs two rankers whose orderings disagree on PB-vs-gold:

* V3 ``rank_cards`` scores a confirmed PB (+12) above a gold (+8).
* V5 ``rank_achievements`` ranks the gold (magnitude 1.0) above the PB (0.5)
  and bands the gold ELITE.

Historically both orderings could surface for one meet — the review queue
(``run.cards``, V3 order) contradicting the recognition report
(``ranked_achievements``, V5 order) on member-id (HY3/SDIF) uploads, the only
input class where the V3 detector produces cards.

ADR-0032 makes V5 recognition the single canonical ranking authority via a
**V5-first / V3-fallback** rule in ``_reconcile_review_cards``:

* whenever V5 recognition produced ranked achievements, ``run.cards`` is derived
  from them (in V5 priority order) on every parse path;
* only when V5 recognition is unavailable or empty do the rich V3 cards remain,
  as the honest fallback (so a V5 failure never regresses a run to zero cards).

These white-box tests exercise that seam directly — no .hy3 fixture and no
network required. They must NOT be weakened; the V3 ranker's own PB>gold
contract (``test_ranker_v3_direct.py``) and the stub-bridge invariants
(``test_v5_v3_card_bridge.py``) are deliberately left untouched.
"""
from __future__ import annotations

from mediahub.pipeline.pipeline_v4 import _reconcile_review_cards, PipelineRunV4
from swim_content.cards import ContentCard, CaptionVariants


def _v3_card(card_id: str, card_type: str = "pb_roundup") -> ContentCard:
    return ContentCard(
        card_id=card_id,
        card_type=card_type,
        headline=f"V3 {card_id}",
        captions=CaptionVariants(clean="c", team="c", hype="c"),
    )


def _ranked(swim_id: str, atype: str, name: str, event: str) -> dict:
    return {
        "rank": 1,
        "achievement": {
            "swim_id": swim_id,
            "swimmer_name": name,
            "type": atype,
            "headline": f"{atype} for {name}",
            "event": event,
        },
    }


# --------------------------------------------------------------------------- #
# V5-first: recognition present -> cards come from V5, in V5 order.
# --------------------------------------------------------------------------- #
def test_v5_recognition_present_wins_over_v3_cards():
    """Non-empty V3 cards + populated ranked_achievements -> V5 stub order,
    cards_order_source == 'v5'. This is the case that previously contradicted."""
    v3_cards = [_v3_card("v3-pb"), _v3_card("v3-gold")]
    # V5 ranks the gold FIRST (the opposite of V3's PB-first ordering).
    ranked = [
        _ranked("swim-gold", "medal_gold", "Bob", "100m Freestyle (LC)"),
        _ranked("swim-pb", "pb_confirmed", "Alice", "200m IM (LC)"),
    ]

    cards, source = _reconcile_review_cards(v3_cards, ranked, None)

    assert source == "v5"
    # Cards are the V5 stubs, not the V3 cards.
    assert [c.card_id for c in cards] == ["swim-gold", "swim-pb"]
    # None of the original V3 card_ids leak through.
    assert not ({"v3-pb", "v3-gold"} & {c.card_id for c in cards})
    # One card per ranked achievement (the stub-bridge 1:1 invariant).
    assert len(cards) == len(ranked)


def test_pb_vs_gold_no_longer_contradicts():
    """The canonical review-queue order for a PB-vs-gold meet is the V5 order
    (gold first), regardless of the V3 cards' PB-first ordering — so the review
    queue and the recognition report agree."""
    # V3 would put the PB first (PB +12 > gold +8); supply cards in that order.
    v3_cards = [_v3_card("pb-card"), _v3_card("gold-card")]
    ranked = [
        _ranked("gold", "medal_gold", "Bob", "50m Free (LC)"),
        _ranked("pb", "pb_confirmed", "Alice", "50m Free (LC)"),
    ]

    cards, source = _reconcile_review_cards(v3_cards, ranked, None)

    assert source == "v5"
    # Gold leads — matching the recognition report, not the V3 PB-first order.
    assert cards[0].card_id == "gold"
    assert cards[1].card_id == "pb"


# --------------------------------------------------------------------------- #
# V3-fallback: recognition absent/empty -> keep the rich V3 cards (no 0-cards).
# --------------------------------------------------------------------------- #
def test_recognition_none_falls_back_to_v3_cards():
    """recognition_report is None with non-empty V3 cards -> keep V3 cards,
    cards_order_source == 'v3-legacy'. Guards the '0 content cards' regression
    when V5 recognition throws (its online meet-identity research can fail)."""
    v3_cards = [_v3_card("v3-a"), _v3_card("v3-b")]

    cards, source = _reconcile_review_cards(v3_cards, None, None)

    assert source == "v3-legacy"
    assert [c.card_id for c in cards] == ["v3-a", "v3-b"]  # order preserved
    assert cards, "V3 fallback must never yield an empty review queue"


def test_recognition_empty_list_falls_back_to_v3_cards():
    """A run where V5 recognition returned zero achievements still keeps the
    rich V3 cards rather than blanking the queue."""
    v3_cards = [_v3_card("only")]

    cards, source = _reconcile_review_cards(v3_cards, [], None)

    assert source == "v3-legacy"
    assert [c.card_id for c in cards] == ["only"]


# --------------------------------------------------------------------------- #
# Degenerate: neither ranker produced anything.
# --------------------------------------------------------------------------- #
def test_no_cards_and_no_recognition_is_none_source():
    cards, source = _reconcile_review_cards([], None, None)
    assert cards == []
    assert source == "none"


def test_interpreter_path_is_unaffected_no_v3_cards():
    """Interpreter runs (PDF/CSV/LENEX) have no V3 cards here, so V5 recognition
    drives the queue exactly as before — the dominant path stays V5-ordered."""
    ranked = [_ranked("s1", "pb_confirmed", "Alice", "100m Free (LC)")]
    cards, source = _reconcile_review_cards([], ranked, None)
    assert source == "v5"
    assert [c.card_id for c in cards] == ["s1"]


# --------------------------------------------------------------------------- #
# Provenance default.
# --------------------------------------------------------------------------- #
def test_pipeline_run_defaults_cards_order_source_none():
    run = PipelineRunV4(run_id="r", started_at="t")
    assert run.cards_order_source == "none"


def test_persist_run_stores_cards_order_source(app, web_module):
    """The provenance marker must survive persistence: the runs_v4 JSON payload
    carries cards_order_source, so which authority ordered the cards ('v5' vs
    'v3-legacy') is auditable for every persisted run — not just in memory
    while the pipeline thread is alive (the audit-trail rule)."""
    import json

    run = PipelineRunV4(run_id="prov-1", started_at="t", finished_at="t", profile_id="club-a")
    run.cards_order_source = "v5"
    web_module._persist_run(run, "meet.hy3")

    payload = json.loads((web_module.RUNS_DIR / "prov-1.json").read_text())
    assert payload["cards_order_source"] == "v5"
