"""
tests_v4/test_sportsystems_adapter.py — V7.4

Unit tests for the SPORTSYSTEMS PDF adapter and related V7.4 features.
"""
import os
import sys

import pytest

# Ensure the swim-content root is on the path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PDF_PATH = os.path.join(ROOT, "sample_data", "MISM-2024-Results.pdf")


def _skip_if_no_pdf():
    return pytest.mark.skipif(
        not os.path.exists(PDF_PATH),
        reason="Sample PDF not found"
    )


@_skip_if_no_pdf()
def test_parses_mism_2024_real_pdf():
    """Adapter parses the real MISM 2024 PDF and returns a valid Meet."""
    from engine_v4.adapters.sportsystems_pdf import SportSystemsPDFAdapter

    with open(PDF_PATH, "rb") as f:
        data = f.read()

    meet = SportSystemsPDFAdapter().parse(data)

    # Meet name correct
    assert meet.name.startswith("ARENA Manchester International"), \
        f"Expected meet name starting with 'ARENA Manchester', got: {meet.name!r}"

    # Sport and source format
    assert meet.source_format == "sportsystems_pdf"

    # Should find at least 30 events (via unique event numbers)
    unique_events = set(r.extra.get("event_num", "") for r in meet.results)
    assert len(unique_events) >= 30, \
        f"Expected ≥30 events, got {len(unique_events)}"

    # Should find many swimmers
    assert len(meet.swimmers) >= 200, \
        f"Expected ≥200 swimmers, got {len(meet.swimmers)}"

    # City of Manchester Aquatics should be present via club_name
    coma_swimmers = [
        s for s in meet.swimmers.values()
        if "Manch" in (getattr(s, "club_name", "") or "")
    ]
    assert len(coma_swimmers) >= 5, \
        f"Expected ≥5 COMA swimmers, got {len(coma_swimmers)}"

    # meet.races should be an alias for meet.results
    assert meet.races is meet.results

    # No blocking errors
    assert not meet.has_blocking_errors(), \
        f"Blocking errors: {[w.message for w in meet.warnings if w.severity == 'error']}"


def test_humanise_achievement_types():
    """humanise() converts raw type strings to friendly labels."""
    from mediahub.web.humanise import humanise, format_post_angle, humanise_status

    assert humanise("pb_confirmed") == "Confirmed PB"
    assert humanise("medal_gold") == "Gold medal"
    assert humanise("multi_pb_weekend") == "Multi-PB weekend"
    assert humanise("medal_silver") == "Silver medal"
    assert humanise("first_sub_barrier") == "First-time barrier break"

    assert format_post_angle("medal_gold") == "Gold medal"
    assert format_post_angle("pb_confirmed") == "Confirmed PB"

    assert humanise_status("pb_unverified") == "PB not verified"
    assert humanise_status("needs_verification") == "Needs check"
    assert humanise_status("verified") == "Verified"


def test_web_researcher_returns_results():
    """WebResearcher returns SearchResult objects (pplx or DDG)."""
    from mediahub.web_research.search import WebResearcher, SearchResult

    r = WebResearcher()
    results = r.search("Manchester Aquatics Centre swimming", num=3)

    # At minimum, should return a list (may be empty if network unavailable)
    assert isinstance(results, list)
    for sr in results:
        assert isinstance(sr, SearchResult)
        assert sr.url.startswith("http")
        assert sr.title


def test_multi_tone_renderer():
    """render_all_tones returns one entry per learned voice on disk.

    V7.5: voices are data, not code — the renderer enumerates whatever
    is in data/voices/{,/seed/} rather than three hardcoded tone slugs.
    """
    from mediahub.voice.multi_tone_renderer import render_all_tones
    from mediahub.voice.learned.store import list_voices
    from mediahub.web.club_profile import load_profile, seed_coma_profile_if_empty

    # Ensure COMA profile exists (still required by the function signature)
    prof = load_profile("coma") or seed_coma_profile_if_empty()

    dummy_achievement = {
        "achievement": {
            "type": "medal_gold",
            "swimmer_name": "Test Swimmer",
            "event": "100m Freestyle",
            "headline": "Test Swimmer wins gold in 100m Freestyle",
            "angle_hint": "Gold medal at Manchester International",
        },
        "priority": 1.0,
        "quality_band": "elite",
        "rank": 1,
    }

    voices = list_voices()
    captions = render_all_tones(dummy_achievement, prof)

    # Every loaded voice must have a rendered caption.
    assert set(captions.keys()) == {v.voice_id for v in voices}
    assert captions, "render_all_tones returned no captions — no voices on disk?"
    for vid, payload in captions.items():
        assert isinstance(payload, dict)
        assert "caption" in payload
        assert "display_name" in payload


def test_home_renders_without_profiles():
    """V8.2 Issue 5: profiles tool removed. Home must render fine with no profiles
    and must NOT contain a 'Club profiles' nav link or '/profiles' route reference.
    """
    import shutil
    import tempfile
    import os

    tmp_dir = tempfile.mkdtemp()
    try:
        old_env = os.environ.get("SWIM_CONTENT_PROFILES_DIR")
        os.environ["SWIM_CONTENT_PROFILES_DIR"] = tmp_dir

        import importlib
        import mediahub.web.club_profile as cp
        importlib.reload(cp)

        from mediahub.web.web import create_app
        app = create_app()
        # Bypass the first-run organisation gate (no profile is seeded).
        app.config["TESTING"] = True
        c = app.test_client()
        r = c.get("/")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "Club profiles" not in body
        assert "/profiles" not in body
        # /profiles route is gone
        r2 = c.get("/profiles")
        assert r2.status_code == 404
    finally:
        os.environ.pop("SWIM_CONTENT_PROFILES_DIR", None)
        if old_env is not None:
            os.environ["SWIM_CONTENT_PROFILES_DIR"] = old_env
        shutil.rmtree(tmp_dir, ignore_errors=True)
        importlib.reload(cp)


def test_adapter_dispatcher_recognises_pdf():
    """The dispatcher picks the sportsystems_pdf adapter for .pdf files."""
    from mediahub.web.adapters.dispatcher import dispatch

    if not os.path.exists(PDF_PATH):
        pytest.skip("Sample PDF not found")

    with open(PDF_PATH, "rb") as f:
        data = f.read()

    meet, log = dispatch(data, "MISM-2024-Results.pdf")
    assert log.chosen_adapter == "sportsystems_pdf", \
        f"Expected sportsystems_pdf adapter, got: {log.chosen_adapter}"
    assert len(meet.results) >= 200
