"""Regression test for the V5→V3 card bridge in pipeline_v4.

The V3 detector path is skipped for interpreter-parsed runs (swimmers carry no
ASA IDs), so historically ``run.cards`` ended up empty even when V5 recognition
found real achievements — the headline "upload succeeded but produced 0 content
cards" bug. ``run_pipeline_v4`` now synthesises V3 ContentCard stubs from the V5
``ranked_achievements`` so exports, the review page, and the trust report all
reflect the real findings.

This asserts the bridge holds: when a run has ranked V5 achievements, it must
also expose them as ``run.cards`` (one card per achievement, carrying the real
swimmer/headline/caption — never empty, never fabricated).
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SAMPLE_PDF = _REPO_ROOT / "sample_data" / "MISM-2024-Results.pdf"


@pytest.fixture(scope="module")
def manchester_run():
    if not _SAMPLE_PDF.exists():
        pytest.skip(f"Sample PDF missing: {_SAMPLE_PDF}")
    from mediahub.pipeline.pipeline_v4 import run_pipeline_v4

    run = run_pipeline_v4(
        file_bytes=_SAMPLE_PDF.read_bytes(),
        filename=_SAMPLE_PDF.name,
        profile_id=None,
        club_filter="City of Manchester Aquatics",
        use_pb_cache=True,
        fetch_pbs=False,
        run_id="test_v5_v3_card_bridge",
    )
    if run.error:
        pytest.skip(f"Pipeline failed: {run.error}")
    return run


def test_ranked_achievements_surface_as_cards(manchester_run):
    """If V5 ranked achievements exist, run.cards must be populated (the bridge)."""
    rr = getattr(manchester_run, "recognition_report", None) or {}
    ranked = rr.get("ranked_achievements") or []
    if not ranked:
        pytest.skip("No ranked achievements from pipeline (nothing to bridge)")

    cards = manchester_run.cards or []
    assert cards, (
        "run.cards is empty despite V5 ranked achievements — the V5→V3 bridge "
        "regressed (this is the 'upload succeeded but 0 content cards' bug)."
    )
    # One card per ranked achievement.
    assert len(cards) == len(ranked), (
        f"expected one card per ranked achievement: "
        f"{len(cards)} cards vs {len(ranked)} achievements"
    )


def test_bridged_cards_carry_real_content(manchester_run):
    """Bridged cards must reflect real V5 output, not fabricated/empty stubs."""
    rr = getattr(manchester_run, "recognition_report", None) or {}
    ranked = rr.get("ranked_achievements") or []
    if not ranked:
        pytest.skip("No ranked achievements from pipeline")

    cards = manchester_run.cards or []
    assert cards, "no cards to inspect"
    # At least one card names a real swimmer from the meet (grounded, not blank).
    assert any(getattr(c, "swimmer_names", None) for c in cards), (
        "no bridged card carries a swimmer name — content is not grounded in V5 output"
    )


def test_content_card_to_dict_exposes_caption_key():
    """ContentCard.to_dict() must include a flat 'caption' key.

    The export API and autotest observer read c.get('caption') — the singular
    form. Before this fix, to_dict() only produced 'captions' (plural, per-tone
    variants), so every card appeared to have an empty caption.
    """
    from swim_content.cards import ContentCard, CaptionVariants

    # Card with clean caption populated
    card = ContentCard(
        card_id="test-1",
        card_type="standout_swim",
        headline="Gold for Alice in 100m Freestyle",
        captions=CaptionVariants(clean="Alice goes gold", team="We love you Alice", hype="GOLD!"),
    )
    d = card.to_dict()
    assert "caption" in d, "to_dict() missing 'caption' key — export consumers always see empty"
    assert d["caption"] == "Alice goes gold", (
        f"caption should be captions.clean but got: {d['caption']!r}"
    )

    # user_caption takes priority when set (approved/edited caption)
    card.user_caption = "Edited by club social"
    d2 = card.to_dict()
    assert d2["caption"] == "Edited by club social", (
        f"user_caption should win over captions.clean but got: {d2['caption']!r}"
    )


def test_v5_stubs_have_non_empty_captions():
    """V5→V3 stubs must not have empty captions when voice_captions is absent.

    The stub builder previously left captions empty when the voice.learned
    renderer wasn't configured. The fix falls back to the achievement headline
    so cards always carry meaningful caption text.
    """
    from mediahub.pipeline.pipeline_v4 import _v5_ranked_to_v3_stubs

    ranked = [
        {
            "rank": 1,
            "achievement": {
                "swim_id": "swim-reg-1",
                "swimmer_name": "Bob Jones",
                "type": "pb_confirmed",
                "headline": "Bob Jones sets a new PB in 200m IM",
                "event": "200m IM (LC)",
            },
            "voice_captions": {},  # no voice captions configured
        },
        {
            "rank": 2,
            "achievement": {
                "swim_id": "swim-reg-2",
                "swimmer_name": "Carol Smith",
                "type": "medal_gold",
                "headline": "Gold for Carol Smith in 100m Backstroke",
                "event": "100m Backstroke (SC)",
            },
            # voice_captions key absent entirely
        },
    ]
    stubs = _v5_ranked_to_v3_stubs(ranked)
    assert len(stubs) == 2

    for stub, ra in zip(stubs, ranked):
        ach = ra["achievement"]
        d = stub.to_dict()
        assert d["caption"], (
            f"Stub for {ach['swim_id']} has empty 'caption' in to_dict() — "
            "the export API will show empty captions for this card"
        )
        assert stub.captions.clean, (
            f"Stub for {ach['swim_id']} has empty captions.clean — "
            "headline fallback not applied"
        )
        assert d["caption"] == ach["headline"], (
            f"Expected headline as fallback caption but got: {d['caption']!r}"
        )


def test_stub_card_ids_unique_when_one_swim_yields_multiple_achievements():
    """Two ranked achievements sharing a swim_id must yield DISTINCT card_ids.

    Workflow state is keyed per (run_id, card_id), so duplicate ids made
    approve/reject/caption-edit on one card silently apply to its twin. The
    first occurrence keeps the bare swim_id (back-compat with persisted
    workflow state); repeats get a deterministic counter suffix.
    """
    from mediahub.pipeline.pipeline_v4 import _v5_ranked_to_v3_stubs

    shared = "club:Smith,Jane:100FRLC:timed_final"
    ranked = [
        {
            "rank": 1,
            "achievement": {
                "swim_id": shared,
                "swimmer_name": "Jane Smith",
                "type": "pb_confirmed",
                "headline": "Jane Smith sets a new PB",
                "event": "100m Freestyle (LC)",
            },
        },
        {
            "rank": 2,
            "achievement": {
                "swim_id": shared,
                "swimmer_name": "Jane Smith",
                "type": "medal_gold",
                "headline": "Gold for Jane Smith",
                "event": "100m Freestyle (LC)",
            },
        },
    ]
    stubs = _v5_ranked_to_v3_stubs(ranked)
    ids = [s.card_id for s in stubs]
    assert ids[0] == shared, "first occurrence must keep the bare swim_id"
    assert ids[1] == f"{shared}~2", "repeat must get a deterministic counter suffix"
    assert len(set(ids)) == len(ids)


def test_b_final_provenance_rides_on_the_stub_subhead():
    """A B-final result must read as 'B Final' on the card subhead — honest
    provenance so it is never indistinguishable from the A-final win."""
    from types import SimpleNamespace

    from mediahub.pipeline.pipeline_v4 import _v5_ranked_to_v3_stubs

    result = SimpleNamespace(
        swimmer_key="club:Smith,Jane",
        distance=50,
        stroke="BR",
        course="LC",
        round="timed_final",
        extra={"final_label": "B Final", "final_rank": 2},
    )
    ranked = [
        {
            "rank": 1,
            "achievement": {
                "swim_id": "club:Smith,Jane:50BRLC:timed_final:gold",
                "swimmer_name": "Jane Smith",
                "type": "medal_gold",
                "headline": "Gold for Jane Smith in the B final",
                "event": "50m Breaststroke (LC)",
            },
        },
    ]
    (stub,) = _v5_ranked_to_v3_stubs(ranked, [result])
    assert stub.subhead == "50m Breaststroke (LC) — B Final"


def test_no_final_label_leaves_subhead_unchanged():
    from types import SimpleNamespace

    from mediahub.pipeline.pipeline_v4 import _v5_ranked_to_v3_stubs

    result = SimpleNamespace(
        swimmer_key="club:Smith,Jane",
        distance=50,
        stroke="BR",
        course="LC",
        round="timed_final",
        extra={"final_label": "", "final_rank": 0},
    )
    ranked = [
        {
            "rank": 1,
            "achievement": {
                "swim_id": "club:Smith,Jane:50BRLC:timed_final:gold",
                "swimmer_name": "Jane Smith",
                "type": "medal_gold",
                "headline": "Gold for Jane Smith",
                "event": "50m Breaststroke (LC)",
            },
        },
    ]
    (stub,) = _v5_ranked_to_v3_stubs(ranked, [result])
    assert stub.subhead == "50m Breaststroke (LC)"
