"""
tests_v75/test_pipeline_integration.py
=======================================

End-to-end V7.5 pipeline smoke test.

Runs ``run_pipeline_v4`` against ``sample_data/MISM-2024-Results.pdf`` using
``club_filter='City of Manchester Aquatics'`` and asserts:

  1. The interpreter produced a usable canonical meet (no pipeline error).
  2. The fuzzy club filter matched at least some "Co Manch Aq"-style swims.
  3. Recognition produced at least one achievement.
  4. context_engine identity discovery populated the meet context.
  5. Voices learned from disk rendered captions for at least 3 cards.

This is the canonical V7.5 acceptance gate. If this test fails, the live
pipeline is broken end-to-end.
"""
from __future__ import annotations

from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SAMPLE_PDF = _REPO_ROOT / "sample_data" / "MISM-2024-Results.pdf"


@pytest.fixture(scope="module")
def integration_run():
    """Run the V7.5 pipeline once for the whole module."""
    if not _SAMPLE_PDF.exists():
        pytest.skip(f"sample PDF missing: {_SAMPLE_PDF}")

    from mediahub.pipeline.pipeline_v4 import run_pipeline_v4

    file_bytes = _SAMPLE_PDF.read_bytes()
    run = run_pipeline_v4(
        file_bytes=file_bytes,
        filename=_SAMPLE_PDF.name,
        profile_id=None,
        club_filter="City of Manchester Aquatics",
        use_pb_cache=True,
        fetch_pbs=False,  # network off in tests
        run_id="test_v75_integration",
    )
    return run


# ── Pipeline ran cleanly ──────────────────────────────────────────────────────

def test_pipeline_completed_without_error(integration_run):
    assert integration_run.error is None, (
        f"Pipeline error: {integration_run.error}"
    )


def test_club_filter_was_recorded(integration_run):
    assert integration_run.club_filter == "City of Manchester Aquatics"


def test_fuzzy_club_filter_matched_swims(integration_run):
    """The fuzzy filter must match Co Manch Aq → City of Manchester Aquatics."""
    assert integration_run.our_swim_count > 0, (
        "Fuzzy club filter matched zero swims — token-alias matching is broken."
    )
    # Sanity upper bound: this meet has ~1700 total swims; "our" club should
    # be a meaningful subset, not the entire field.
    assert integration_run.our_swim_count < 1500, (
        f"our_swim_count={integration_run.our_swim_count} suspiciously large; "
        f"club filter may not be filtering at all."
    )


# ── Recognition report ────────────────────────────────────────────────────────

def test_recognition_report_has_achievements(integration_run):
    rr = integration_run.recognition_report
    assert rr is not None, "recognition_report missing"
    assert isinstance(rr, dict), f"expected dict, got {type(rr).__name__}"
    assert rr.get("n_achievements", 0) > 0, (
        "Recognition produced zero achievements end-to-end."
    )


# ── Context engine populated meet identity ───────────────────────────────────

def test_meet_context_populated_by_context_engine(integration_run):
    rr = integration_run.recognition_report
    mc = rr.get("meet_context")
    assert mc is not None, "meet_context missing from recognition report"

    # meet_context is the dict produced by report.py from the canonical Meet.
    # context_engine.identity.discover_meet_identity() fills:
    #   governing_body, meet_level, host_club_code (and research_sources if set)
    # In offline mode we mostly require AT LEAST ONE of these to be set, since
    # network discovery may be skipped.
    if isinstance(mc, dict):
        gb = mc.get("governing_body")
        ml = mc.get("meet_level")
        identity_signals = [gb, ml]
    else:
        gb = getattr(mc, "governing_body", None)
        ml = getattr(mc, "meet_level", None)
        identity_signals = [gb, ml]

    assert any(identity_signals), (
        "context_engine.identity produced no governing_body or meet_level "
        "for this meet."
    )


# ── Voices rendered from disk ────────────────────────────────────────────────

def test_voices_rendered_for_multiple_cards(integration_run):
    """At least 3 ranked achievements must have voice captions rendered.

    The captions come from voice/learned voices on disk (warm_club, hype,
    data_led seeds). If this fails, the V7.5 voice rendering path is not
    wired into recognition.
    """
    rr = integration_run.recognition_report
    ranked = rr.get("ranked_achievements") or []
    cards_with_voices = [
        a for a in ranked
        if isinstance(a, dict) and a.get("voice_captions")
    ]
    assert len(cards_with_voices) >= 3, (
        f"Only {len(cards_with_voices)} cards had voice captions; "
        f"expected >= 3."
    )

    # Each rendered captions dict must have at least one voice slug → text.
    sample = cards_with_voices[0]["voice_captions"]
    assert isinstance(sample, dict) and sample, (
        f"voice_captions on first card is empty: {sample!r}"
    )
    # Every voice id should map to some non-empty caption payload (string or
    # dict with a 'caption' field).
    for vid, payload in sample.items():
        if isinstance(payload, dict):
            text = payload.get("caption") or payload.get("body") or ""
        else:
            text = str(payload)
        assert text, f"voice {vid!r} rendered empty caption: {payload!r}"


# ── No hardcoded provider leaked into evidence ───────────────────────────────

def test_evidence_source_names_are_not_hardcoded(integration_run):
    """No achievement evidence should literally name 'swimmingresults.org'.

    Evidence labels for PB lookups must come from the live snapshot
    (i.e. learned at runtime), not from a hardcoded constant.
    """
    rr = integration_run.recognition_report
    forbidden = "swimmingresults.org"
    bad: list[str] = []
    for ach in rr.get("ranked_achievements") or []:
        a = ach.get("achievement") if isinstance(ach, dict) else None
        if a is None:
            continue
        ev_list = a.get("evidence") if isinstance(a, dict) else getattr(a, "evidence", [])
        for ev in ev_list or []:
            name = ev.get("source_name") if isinstance(ev, dict) else getattr(ev, "source_name", "")
            if name and forbidden in str(name).lower():
                bad.append(str(name))
    assert not bad, (
        f"{len(bad)} achievement(s) carry a hardcoded provider in their "
        f"evidence (first few: {bad[:3]})"
    )
