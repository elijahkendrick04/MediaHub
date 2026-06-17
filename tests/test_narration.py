"""visual/narration.py — deterministic, fact-only narration scripts.

The narration layer must obey the same zero-invention rule as the renderer:
fixed templates over verified card facts, deterministic spoken-form times,
no LLM anywhere, and a length budget that drops bottom-ranked lines instead
of summarising.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mediahub.visual import narration

BRAND = {"displayName": "Riverbank SC", "shortName": "RSC"}


def _props(i: int = 1, label: str = "NEW PB") -> dict:
    return {
        "athleteFullName": f"Sample Swimmer{i}",
        "eventName": "100m Freestyle",
        "resultValue": "1:02.45",
        "achievementLabel": label,
    }


def _names_in(script: str, n: int = 5) -> list[int]:
    """The 1-based swimmer indices whose name appears in ``script``, in order."""
    return [i for i in range(1, n + 1) if f"Sample Swimmer{i}" in script]


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
            assert (
                banned not in line.lower()
            ), f"narration must stay AI-free; found {banned!r} in {line!r}"


# ===========================================================================
# R1.18 — narration script-style templates (verbose / compact / poetic /
# technical), strictly fact-only. The default register ('standard') must stay
# byte-identical to the pre-style behaviour.
# ===========================================================================


# ---------------------------------------------------------------------------
# Style registry sanity
# ---------------------------------------------------------------------------


def test_styles_registry_is_complete_and_ordered():
    assert narration.STYLES == ("standard", "compact", "verbose", "poetic", "technical")
    assert narration.DEFAULT_STYLE == "standard"
    assert narration.DEFAULT_STYLE in narration.STYLES
    assert narration.available_styles() == narration.STYLES
    # every advertised style is actually registered and described
    for name in narration.STYLES:
        assert name in narration._STYLES
        assert name in narration.STYLE_DESCRIPTIONS
        assert narration.STYLE_DESCRIPTIONS[name].strip()
    # no orphan registry entries beyond the advertised set
    assert set(narration._STYLES) == set(narration.STYLES)
    assert set(narration.STYLE_DESCRIPTIONS) == set(narration.STYLES)


@pytest.mark.parametrize(
    "raw,ok",
    [
        ("standard", True),
        ("POETIC", True),
        ("  technical  ", True),
        ("Compact", True),
        ("verbose", True),
        ("bogus", False),
        ("", False),
        (None, False),
    ],
)
def test_is_valid_style(raw, ok):
    assert narration.is_valid_style(raw) is ok


# ---------------------------------------------------------------------------
# Default register is byte-identical to the pre-style behaviour
# ---------------------------------------------------------------------------


def test_default_story_matches_explicit_standard(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_NARRATION_STYLE", raising=False)
    expected = "NEW PB: Sample Swimmer1, 100m Freestyle, 1 minute 2.45 seconds. Riverbank SC."
    assert narration.story_script(_props(), BRAND) == expected
    assert narration.story_script(_props(), BRAND, style="standard") == expected
    assert narration.story_script(_props(), BRAND, style=None) == expected


def test_default_reel_matches_explicit_standard(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_NARRATION_STYLE", raising=False)
    cards = [_props(1, "NEW PB"), _props(2, "GOLD"), _props(3, "STRONG SWIM")]
    default = narration.reel_script(cards, BRAND, "Spring Open", max_seconds=60.0)
    standard = narration.reel_script(
        cards, BRAND, "Spring Open", max_seconds=60.0, style="standard"
    )
    assert default == standard
    # The exact historic shape: opener, ranked lines, honest stats, sign-off.
    assert default.startswith("Spring Open.")
    assert "1 personal best and 1 medal." in default
    assert default.endswith("Follow Riverbank SC for more.")


# ---------------------------------------------------------------------------
# Every style speaks the same verified facts (only the phrasing changes)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("style", narration.STYLES)
def test_story_carries_every_fact_in_each_style(style):
    script = narration.story_script(_props(), BRAND, style=style)
    assert script
    for token in (
        "Sample Swimmer1",  # name
        "100m Freestyle",  # event
        "1 minute 2.45 seconds",  # spoken-form result
        "NEW PB",  # achievement label
        "Riverbank SC",  # club
    ):
        assert token in script, f"{style}: missing {token!r}"
    # the raw clock form is never spoken — only the announcer form
    assert "1:02.45" not in script


@pytest.mark.parametrize("style", narration.STYLES)
def test_story_empty_card_yields_empty_in_each_style(style):
    assert narration.story_script({}, BRAND, style=style) == ""
    # a label with no facts is still nothing to say
    assert narration.story_script({"achievementLabel": "NEW PB"}, BRAND, style=style) == ""


@pytest.mark.parametrize("style", narration.STYLES)
def test_story_and_reel_are_deterministic_per_style(style):
    a = narration.story_script(_props(), BRAND, style=style)
    b = narration.story_script(_props(), BRAND, style=style)
    assert a == b
    cards = [_props(i) for i in range(1, 4)]
    r1 = narration.reel_script(cards, BRAND, "Spring Open", max_seconds=30.0, style=style)
    r2 = narration.reel_script(cards, BRAND, "Spring Open", max_seconds=30.0, style=style)
    assert r1 == r2


# Per-style reel scaffolding: (opener prefix, stats sentence, club sign-off).
_REEL_EXPECT = {
    "standard": ("Spring Open.", "1 personal best and 1 medal.", "Follow Riverbank SC for more."),
    "compact": ("Spring Open.", "1 PB, 1 medal.", "Riverbank SC."),
    "verbose": (
        "Results from Spring Open.",
        "That's 1 personal best and 1 medal.",
        "Follow Riverbank SC for more updates.",
    ),
    "poetic": ("Spring Open.", "1 personal best — 1 medal.", "Follow Riverbank SC."),
    "technical": ("Spring Open.", "Totals: 1 personal best, 1 medal.", "Club: Riverbank SC."),
}


@pytest.mark.parametrize("style", narration.STYLES)
def test_reel_structure_per_style(style):
    cards = [_props(1, "NEW PB"), _props(2, "GOLD"), _props(3, "STRONG SWIM")]
    script = narration.reel_script(cards, BRAND, "Spring Open", max_seconds=60.0, style=style)
    opener, stats, closer = _REEL_EXPECT[style]
    assert script.startswith(opener)
    assert stats in script
    assert closer in script
    assert _names_in(script, 3) == [1, 2, 3]
    assert "1 minute 2.45 seconds" in script
    assert "1:02.45" not in script


def test_reel_styles_produce_distinct_scripts():
    cards = [_props(1, "NEW PB"), _props(2, "GOLD")]
    scripts = {
        s: narration.reel_script(cards, BRAND, "Spring Open", max_seconds=60.0, style=s)
        for s in narration.STYLES
    }
    # five registers, five distinct scripts
    assert len(set(scripts.values())) == len(narration.STYLES)


def test_reel_without_meet_or_club_opens_in_each_style():
    openers = {
        "standard": "Meet recap.",
        "compact": "Recap.",
        "verbose": "Meet results.",
        "poetic": "Meet recap.",
        "technical": "Meet recap.",
    }
    for style, opener in openers.items():
        script = narration.reel_script([_props(1)], {}, "", max_seconds=15.0, style=style)
        assert script.startswith(opener), style
        # no club → no sign-off fragment leaks in
        assert "Riverbank" not in script


# ---------------------------------------------------------------------------
# Fact-only safety: registers never re-speak a non-time as a time, and never
# inject editorialising language the source facts don't contain.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("style", narration.STYLES)
@pytest.mark.parametrize("value", ["DQ", "DNS", "2nd", "1st", "850 pts"])
def test_non_time_results_pass_through_in_each_style(style, value):
    card = {
        "athleteFullName": "Sample Swimmer1",
        "eventName": "100m Freestyle",
        "resultValue": value,
        "achievementLabel": "FINAL",
    }
    script = narration.story_script(card, BRAND, style=style)
    assert value in script, f"{style}: {value!r} not spoken verbatim"
    # a non-time is never dressed up with time words
    assert "minute" not in script
    assert "seconds" not in script


# Words a creative LLM would add but a fact-only template must never invent.
_BANNED_INVENTION = (
    "incredible",
    "amazing",
    "stunning",
    "blazing",
    "dominant",
    "sensational",
    "spectacular",
    "unbelievable",
    "phenomenal",
    "brilliant",
    "fantastic",
    "superb",
    "remarkable",
    "thrilling",
    "epic",
    "flawless",
    "masterclass",
)


@pytest.mark.parametrize("style", narration.STYLES)
def test_no_invented_editorialising_words(style):
    cards = [_props(1, "NEW PB"), _props(2, "GOLD"), _props(3, "STRONG SWIM")]
    story = narration.story_script(_props(), BRAND, style=style).lower()
    reel = narration.reel_script(cards, BRAND, "Spring Open", max_seconds=60.0, style=style).lower()
    for word in _BANNED_INVENTION:
        assert word not in story, f"{style} story invented {word!r}"
        assert word not in reel, f"{style} reel invented {word!r}"


# ---------------------------------------------------------------------------
# Length budget holds for every register; wordier registers fit fewer lines,
# and whatever fits is always a top-down prefix of the ranking.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("style", narration.STYLES)
def test_reel_fits_budget_every_style(style, monkeypatch):
    monkeypatch.delenv("MEDIAHUB_NARRATION_STYLE", raising=False)
    cards = [_props(i) for i in range(1, 6)]
    for budget in (8.0, 15.0, 23.0):
        script = narration.reel_script(cards, BRAND, "Spring Open", max_seconds=budget, style=style)
        assert narration.estimate_seconds(script) <= budget


@pytest.mark.parametrize("style", narration.STYLES)
def test_reel_budget_keeps_a_prefix_of_the_ranking(style, monkeypatch):
    monkeypatch.delenv("MEDIAHUB_NARRATION_STYLE", raising=False)
    cards = [_props(i) for i in range(1, 6)]
    tight = narration.reel_script(cards, BRAND, "Spring Open", max_seconds=11.0, style=style)
    present = _names_in(tight)
    assert present, f"{style}: even the tight budget must speak the top moment"
    assert present[0] == 1
    # no gaps: whatever fits is the top of the ranking, never a lower card
    # narrated past a dropped higher one
    assert present == list(range(1, len(present) + 1))
    roomy = narration.reel_script(cards, BRAND, "Spring Open", max_seconds=90.0, style=style)
    assert _names_in(roomy) == [1, 2, 3, 4, 5]


def test_verbose_fits_no_more_lines_than_compact(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_NARRATION_STYLE", raising=False)
    cards = [_props(i) for i in range(1, 6)]
    compact = narration.reel_script(cards, BRAND, "Spring Open", max_seconds=13.0, style="compact")
    verbose = narration.reel_script(cards, BRAND, "Spring Open", max_seconds=13.0, style="verbose")
    assert len(_names_in(compact)) >= len(_names_in(verbose))
    # the wordiest register still earns the top moment its voice
    assert len(_names_in(verbose)) >= 1


# ---------------------------------------------------------------------------
# Style selection: env default, explicit override, lenient fallback
# ---------------------------------------------------------------------------


def test_style_from_env_default_is_standard(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_NARRATION_STYLE", raising=False)
    assert narration.style_from_env() == "standard"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("poetic", "poetic"),
        ("TECHNICAL", "technical"),
        ("  compact  ", "compact"),
        ("verbose", "verbose"),
        ("nonsense", "standard"),  # unknown → safe default
        ("", "standard"),
    ],
)
def test_style_from_env_reads_and_falls_back(monkeypatch, raw, expected):
    monkeypatch.setenv("MEDIAHUB_NARRATION_STYLE", raw)
    assert narration.style_from_env() == expected


def test_no_style_arg_honours_env(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_NARRATION_STYLE", "poetic")
    auto = narration.story_script(_props(), BRAND)
    explicit = narration.story_script(_props(), BRAND, style="poetic")
    assert auto == explicit
    cards = [_props(i) for i in range(1, 4)]
    auto_reel = narration.reel_script(cards, BRAND, "Spring Open", max_seconds=40.0)
    explicit_reel = narration.reel_script(
        cards, BRAND, "Spring Open", max_seconds=40.0, style="poetic"
    )
    assert auto_reel == explicit_reel


def test_explicit_style_overrides_env(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_NARRATION_STYLE", "poetic")
    forced = narration.story_script(_props(), BRAND, style="technical")
    poetic = narration.story_script(_props(), BRAND, style="poetic")
    assert "Event: 100m Freestyle" in forced  # the explicit technical register won
    assert forced != poetic  # the env value did not override the explicit arg


@pytest.mark.parametrize("bogus", ["bogus", "", "  ", "POETICAL"])
def test_unknown_style_falls_back_to_standard(monkeypatch, bogus):
    monkeypatch.delenv("MEDIAHUB_NARRATION_STYLE", raising=False)
    cards = [_props(1, "NEW PB"), _props(2, "GOLD")]
    assert narration.story_script(_props(), BRAND, style=bogus) == narration.story_script(
        _props(), BRAND, style="standard"
    )
    assert narration.reel_script(
        cards, BRAND, "Spring Open", max_seconds=60.0, style=bogus
    ) == narration.reel_script(cards, BRAND, "Spring Open", max_seconds=60.0, style="standard")
