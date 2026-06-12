"""web.languages — the caption-language registry behind the W.13
multilingual feature (top-10 world languages + Welsh + Irish).

The registry is the single source of truth: settings validation, prompt
instructions, picker options and display labels all derive from it, so
these tests pin the invariants every consumer relies on.
"""

from __future__ import annotations

import pytest

from mediahub.web.club_profile import ClubProfile
from mediahub.web.languages import (
    DEFAULT_LANGUAGE,
    LANGUAGES_BY_CODE,
    SUPPORTED_LANGUAGES,
    bilingual_language_options,
    caption_language_instruction,
    get_language,
    language_label,
    language_setting_for,
    normalise_language_setting,
    primary_language_for,
    secondary_caption_rules,
    secondary_language_for,
    single_language_options,
    split_language_setting,
)


class TestRegistry:
    def test_top10_plus_welsh_and_irish(self):
        # Top-10 world languages by total speakers (Ethnologue) + cy + ga.
        assert {lang.code for lang in SUPPORTED_LANGUAGES} == {
            "en",
            "zh",
            "hi",
            "es",
            "fr",
            "ar",
            "bn",
            "pt",
            "ru",
            "ur",
            "cy",
            "ga",
        }

    def test_codes_unique_lowercase_and_indexed(self):
        codes = [lang.code for lang in SUPPORTED_LANGUAGES]
        assert len(codes) == len(set(codes))
        assert all(c == c.lower() for c in codes)
        assert set(LANGUAGES_BY_CODE) == set(codes)

    def test_every_language_fully_described(self):
        for lang in SUPPORTED_LANGUAGES:
            assert lang.name.strip() and lang.native_name.strip()

    def test_rtl_flags(self):
        assert get_language("ar").rtl and get_language("ur").rtl
        assert not any(
            get_language(c).rtl
            for c in ("en", "cy", "ga", "zh", "hi", "es", "fr", "bn", "pt", "ru")
        )

    def test_english_is_default(self):
        assert DEFAULT_LANGUAGE == "en"
        assert SUPPORTED_LANGUAGES[0].code == "en"

    def test_native_names(self):
        assert get_language("cy").native_name == "Cymraeg"
        assert get_language("ga").native_name == "Gaeilge"
        assert get_language("zh").native_name == "中文"

    def test_unknown_lookup_is_none(self):
        assert get_language("klingon") is None
        assert get_language("") is None
        assert get_language(None) is None


class TestNormalisation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("en", "en"),
            ("cy", "cy"),
            ("ga", "ga"),
            (" CY ", "cy"),
            ("bilingual", "en+cy"),  # legacy W.13 value
            ("en+cy", "en+cy"),
            ("EN+GA", "en+ga"),
            ("en+zh", "en+zh"),
            ("en+en", "en"),  # degenerate pair collapses
            ("klingon", "en"),
            ("en+klingon", "en"),
            ("klingon+cy", "en"),
            ("", "en"),
            (None, "en"),
        ],
    )
    def test_normalise(self, raw, expected):
        assert normalise_language_setting(raw) == expected

    def test_split(self):
        assert split_language_setting("en") == ("en", None)
        assert split_language_setting("ga") == ("ga", None)
        assert split_language_setting("en+cy") == ("en", "cy")
        assert split_language_setting("bilingual") == ("en", "cy")
        assert split_language_setting("nonsense") == ("en", None)

    def test_profile_helpers_object_dict_and_none(self):
        prof = ClubProfile(profile_id="t", display_name="T", language="en+ga")
        assert language_setting_for(prof) == "en+ga"
        assert primary_language_for(prof) == "en"
        assert secondary_language_for(prof) == "ga"

        legacy = {"language": "bilingual"}
        assert language_setting_for(legacy) == "en+cy"
        assert secondary_language_for(legacy) == "cy"

        assert primary_language_for(None) == "en"
        assert secondary_language_for(None) is None
        assert secondary_language_for({"language": "ur"}) is None


class TestPromptInstructions:
    def test_english_needs_no_instruction(self):
        assert caption_language_instruction("en") == ""
        assert secondary_caption_rules("en") == ""

    def test_unknown_code_is_silently_english(self):
        assert caption_language_instruction("xx") == ""

    def test_welsh_keeps_curated_swim_terms(self):
        line = caption_language_instruction("cy")
        assert "Welsh" in line and "Cymraeg" in line
        assert "dull rhydd" in line and "record personol" in line

    def test_irish_instruction(self):
        line = caption_language_instruction("ga")
        assert "Irish" in line and "Gaeilge" in line

    def test_every_language_guards_names_and_times(self):
        for lang in SUPPORTED_LANGUAGES:
            if lang.code == "en":
                continue
            line = caption_language_instruction(lang.code)
            assert lang.name in line and lang.native_name in line
            assert "exactly as given" in line
            assert "Western digits" in line

    def test_secondary_rules_name_the_json_key(self):
        for code in ("cy", "ga", "hi", "ar"):
            rules = secondary_caption_rules(code)
            assert rules.startswith("caption_secondary:")
            assert get_language(code).native_name in rules


class TestPickerOptions:
    def test_single_options_cover_registry(self):
        opts = single_language_options()
        assert [v for v, _ in opts] == [lang.code for lang in SUPPORTED_LANGUAGES]
        assert opts[0] == ("en", "English")
        assert ("cy", "Cymraeg (Welsh)") in opts
        assert ("ga", "Gaeilge (Irish)") in opts

    def test_bilingual_options_pair_every_other_language_with_english(self):
        opts = bilingual_language_options()
        assert len(opts) == len(SUPPORTED_LANGUAGES) - 1
        assert ("en+cy", "English + Cymraeg (Welsh)") in opts
        assert ("en+ga", "English + Gaeilge (Irish)") in opts
        assert all(v.startswith("en+") for v, _ in opts)

    def test_every_option_value_is_canonical(self):
        # Future-proofing: whatever the picker submits must round-trip
        # through the validator unchanged.
        for v, _ in single_language_options() + bilingual_language_options():
            assert normalise_language_setting(v) == v

    def test_labels(self):
        assert language_label("en") == "English"
        assert language_label("ur") == "اردو (Urdu)"
        assert language_label("zz") == "zz"
