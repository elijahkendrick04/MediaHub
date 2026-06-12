"""visual/narration.py — deterministic, fact-only narration scripts.

The narration layer must obey the same zero-invention rule as the renderer:
fixed templates over verified card facts, deterministic spoken-form times,
no LLM anywhere, and a length budget that drops bottom-ranked lines instead
of summarising.
"""

from __future__ import annotations

from pathlib import Path

from mediahub.visual import narration

BRAND = {"displayName": "Riverbank SC", "shortName": "RSC"}


def _props(i: int = 1, label: str = "NEW PB") -> dict:
    return {
        "athleteFullName": f"Sample Swimmer{i}",
        "eventName": "100m Freestyle",
        "resultValue": "1:02.45",
        "achievementLabel": label,
    }


# ---------------------------------------------------------------------------
# spoken_time — deterministic, conservative
# ---------------------------------------------------------------------------


def test_spoken_time_minutes_and_seconds():
    assert narration.spoken_time("1:02.45") == "1 minute 2.45 seconds"
    assert narration.spoken_time("2:00") == "2 minutes 0 seconds"
    assert narration.spoken_time("10:15.3") == "10 minutes 15.3 seconds"


def test_spoken_time_bare_seconds():
    assert narration.spoken_time("54.32") == "54.32 seconds"
    assert narration.spoken_time("27.5") == "27.5 seconds"


def test_spoken_time_passes_non_times_verbatim():
    # Never mis-speak a value we did not understand.
    assert narration.spoken_time("DQ") == "DQ"
    assert narration.spoken_time("") == ""
    assert narration.spoken_time("4x50 Free") == "4x50 Free"
    assert narration.spoken_time("27") == "27"  # bare int: could be points/place
    assert narration.spoken_time("1:02:45.0") == "1:02:45.0"  # hours: unhandled


# ---------------------------------------------------------------------------
# story_script
# ---------------------------------------------------------------------------


def test_story_script_carries_the_card_facts_verbatim():
    script = narration.story_script(_props(), BRAND)
    assert "Sample Swimmer1" in script
    assert "100m Freestyle" in script
    assert "1 minute 2.45 seconds" in script
    assert "NEW PB" in script
    assert "Riverbank SC" in script


def test_story_script_empty_card_yields_empty_script():
    assert narration.story_script({}, BRAND) == ""
    assert narration.story_script({"achievementLabel": "NEW PB"}, BRAND) == ""


def test_story_script_is_deterministic():
    a = narration.story_script(_props(), BRAND)
    b = narration.story_script(_props(), BRAND)
    assert a == b


# ---------------------------------------------------------------------------
# reel_script — structure, honest stats, length budget
# ---------------------------------------------------------------------------


def test_reel_script_structure_and_honest_stats():
    cards = [_props(1, "NEW PB"), _props(2, "GOLD"), _props(3, "STRONG SWIM")]
    script = narration.reel_script(cards, BRAND, "Spring Open", max_seconds=23.0)
    assert script.startswith("Spring Open.")
    # Counted ONLY from the labels: one PB, one medal.
    assert "1 personal best" in script
    assert "1 medal" in script
    assert "Follow Riverbank SC for more." in script
    for i in (1, 2, 3):
        assert f"Sample Swimmer{i}" in script


def test_reel_script_budget_drops_bottom_ranked_lines_first():
    cards = [_props(i) for i in range(1, 6)]
    tight = narration.reel_script(cards, BRAND, "Spring Open", max_seconds=10.0)
    # The top-ranked card keeps its voice; the bottom of the ranking is cut.
    assert "Sample Swimmer1" in tight
    assert "Sample Swimmer5" not in tight
    roomy = narration.reel_script(cards, BRAND, "Spring Open", max_seconds=60.0)
    assert "Sample Swimmer5" in roomy


def test_reel_script_fits_its_budget_estimate():
    cards = [_props(i) for i in range(1, 6)]
    for budget in (8.0, 15.0, 23.0):
        script = narration.reel_script(cards, BRAND, "Spring Open", max_seconds=budget)
        assert narration.estimate_seconds(script) <= budget


def test_reel_script_without_meet_or_club_still_opens():
    script = narration.reel_script([_props(1)], {}, "", max_seconds=15.0)
    assert script.startswith("Meet recap.")


# ---------------------------------------------------------------------------
# Zero-invention guard: no LLM/AI surface in this module
# ---------------------------------------------------------------------------


def test_narration_module_has_no_ai_imports():
    src = Path(narration.__file__).read_text(encoding="utf-8")
    import_lines = [
        line for line in src.splitlines() if line.strip().startswith(("import ", "from "))
    ]
    for banned in ("media_ai", "ai_core", "llm", "gemini", "anthropic"):
        for line in import_lines:
            assert banned not in line.lower(), (
                f"narration must stay AI-free; found {banned!r} in {line!r}"
            )
