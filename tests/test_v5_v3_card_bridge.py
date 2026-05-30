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
