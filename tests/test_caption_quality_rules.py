"""tests/test_caption_quality_rules.py — MR-5/6/7 caption-quality rules.

Approved caption-quality pass (live Stockport Metro samples, 2026-06):

  MR-5  "(SC)"/"(LC)" course jargon appeared in every published caption.
        The event name must be stripped before prompt interpolation AND
        the system prompt must forbid the abbreviations outright.
  MR-6  The four tones were not distinct — Warm/Hype/AI shared the same
        "Another/What a … performance" openers and "testament to …"
        boilerplate; Precise carried subjective filler. Each tone now has
        a genuinely distinguishing instruction and the shared boilerplate
        is banned for all tones.
  MR-7  US spellings ("program") reached UK clubs. The club profile's
        ``country`` now drives a British-English (or per-country)
        spelling instruction; no country → no locale line.

All checks are deterministic — the prompt builders are pure string
functions, exercised with stub profiles and a patched call_claude.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.web.ai_caption import (  # noqa: E402
    _TONE_DESCRIPTORS,
    _locale_instruction,
    _sanitise_achievement_for_prompt,
    _strip_course_suffix,
    generate_caption_for_tone,
)
from mediahub.web.club_profile import ClubProfile  # noqa: E402


_ACH = {
    "swimmer_name": "Lucas Snowdon",
    "event": "100m Breaststroke (SC)",
    "time": "1:12.23",
    "place": 1,
    "type": "medal_gold",
}


def _capture_prompts(ach, profile=None, tone="ai"):
    """Run generate_caption_for_tone with a patched provider and return
    the (system, user) prompt strings it would have sent."""
    captured = {}

    def fake_call(system, user, max_tokens=400, **_kw):
        captured["system"] = system
        captured["user"] = user
        return "stub caption"

    with mock.patch("mediahub.web.ai_caption.call_claude", side_effect=fake_call):
        generate_caption_for_tone(ach, tone=tone, club_profile=profile)
    return captured["system"], captured["user"]


# ---------------------------------------------------------------------------
# MR-5 — course jargon
# ---------------------------------------------------------------------------


class TestCourseJargonStripping:
    def test_strip_sc_suffix(self):
        assert _strip_course_suffix("100m Breaststroke (SC)") == "100m Breaststroke"

    def test_strip_lc_suffix_case_insensitive(self):
        assert _strip_course_suffix("200m Freestyle (lc)") == "200m Freestyle"

    def test_strip_tolerates_whitespace(self):
        assert _strip_course_suffix("50m Fly ( SC )  ") == "50m Fly"

    def test_plain_event_untouched(self):
        assert _strip_course_suffix("400m IM") == "400m IM"

    def test_empty_event_safe(self):
        assert _strip_course_suffix("") == ""

    def test_sc_not_in_user_prompt(self):
        _system, user = _capture_prompts(dict(_ACH))
        assert "(SC)" not in user
        assert "100m Breaststroke" in user

    def test_caller_dict_not_mutated(self):
        ach = dict(_ACH)
        _capture_prompts(ach)
        assert ach["event"] == "100m Breaststroke (SC)"

    def test_course_field_spelled_out_not_abbreviated(self):
        sanitised = _sanitise_achievement_for_prompt(
            {"event": "100m Breaststroke (SC)", "course": "SC"}
        )
        assert sanitised["event"] == "100m Breaststroke"
        assert sanitised["course"] == "short course"

    def test_system_prompt_forbids_abbreviations(self):
        system, _user = _capture_prompts(dict(_ACH))
        assert '"(SC)"' in system
        assert '"(LC)"' in system
        assert "short course" in system


# ---------------------------------------------------------------------------
# MR-6 — tone distinctiveness
# ---------------------------------------------------------------------------


class TestToneDistinctiveness:
    def test_tone_instructions_pairwise_different(self):
        descs = list(_TONE_DESCRIPTORS.values())
        for i, a in enumerate(descs):
            for b in descs[i + 1 :]:
                assert a != b

    def test_hype_demands_short_sentences_and_energy(self):
        d = _TONE_DESCRIPTORS["hype"]
        assert "10 words" in d
        assert "energy" in d.lower()
        assert "reflective" in d.lower()

    def test_data_led_bans_subjective_adjectives_and_emoji(self):
        d = _TONE_DESCRIPTORS["data-led"]
        for banned in ("fantastic", "incredible", "well-deserved", "amazing"):
            assert banned in d
        assert "No emoji" in d
        assert "exclamation" in d.lower()

    def test_warm_club_is_community_first_person_plural(self):
        d = _TONE_DESCRIPTORS["warm-club"]
        assert "community" in d.lower()
        assert "we/our" in d
        assert "coaches" in d.lower()

    def test_ai_default_varies_openings_with_concrete_fact(self):
        d = _TONE_DESCRIPTORS["ai"]
        assert "Vary" in d or "vary" in d
        assert "concrete fact" in d

    def test_shared_boilerplate_ban_in_system_prompt_every_tone(self):
        for tone in ("ai", "warm-club", "hype", "data-led"):
            system, _user = _capture_prompts(dict(_ACH), tone=tone)
            assert "testament to" in system
            assert "Another" in system
            assert "What a" in system

    def test_each_tone_descriptor_reaches_system_prompt(self):
        for tone, desc in _TONE_DESCRIPTORS.items():
            system, _user = _capture_prompts(dict(_ACH), tone=tone)
            assert desc in system


# ---------------------------------------------------------------------------
# MR-7 — locale from club country
# ---------------------------------------------------------------------------


class TestLocaleFromCountry:
    def test_uk_profile_gets_british_english(self):
        profile = ClubProfile(
            profile_id="metro",
            display_name="Stockport Metro Swimming Club",
            country="United Kingdom",
        )
        system, _user = _capture_prompts(dict(_ACH), profile=profile)
        assert "British English" in system
        assert "programme" in system

    def test_uk_synonyms_case_insensitive(self):
        for name in ("uk", "Great Britain", "ENGLAND", "Scotland", "wales", "Northern Ireland"):
            assert "British English" in _locale_instruction(
                ClubProfile(profile_id="p", display_name="C", country=name)
            )

    def test_other_country_gets_variant_line(self):
        line = _locale_instruction(
            ClubProfile(profile_id="p", display_name="C", country="Australia")
        )
        assert line == "Write in the natural English variant for Australia."

    def test_empty_country_adds_no_locale_line(self):
        profile = ClubProfile(profile_id="p", display_name="C", country="")
        assert _locale_instruction(profile) == ""
        system, _user = _capture_prompts(dict(_ACH), profile=profile)
        assert "British English" not in system
        assert "English variant" not in system

    def test_none_profile_adds_no_locale_line(self):
        assert _locale_instruction(None) == ""
