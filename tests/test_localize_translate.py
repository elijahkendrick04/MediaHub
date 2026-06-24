"""localize.translate — the provider-backed translation engine.

The LLM is always mocked (``mediahub.localize.translate.generate_json``), so
these are hermetic: no provider, no network. They pin the contract the rest of
1.24 builds on — glossary-constrained prompt, honest error, warnings, provenance,
no-op and regional paths.
"""

from __future__ import annotations

from unittest import mock

import pytest

from mediahub.localize import translate as T
from mediahub.localize.translate import ClaudeUnavailableError, translate_slots, translate_text


class TestParseLocale:
    def test_split(self):
        assert T.parse_locale("en-GB") == ("en", "GB")
        assert T.parse_locale("en_US") == ("en", "US")
        assert T.parse_locale("cy") == ("cy", "")
        assert T.parse_locale("zh-Hans") == ("zh", "HANS")
        assert T.parse_locale("") == ("", "")
        assert T.parse_locale(None) == ("", "")


class TestAvailability:
    def test_available_reflects_provider(self):
        with mock.patch.object(T, "is_available", return_value=True):
            assert T.available() is True
        with mock.patch.object(T, "is_available", return_value=False):
            assert T.available() is False


class TestNoOp:
    def test_same_language_is_a_no_op_without_a_provider_call(self):
        gj = mock.MagicMock()
        with mock.patch.object(T, "generate_json", gj):
            res = translate_slots({"caption": "Great swim!"}, "en", source_language="en")
        gj.assert_not_called()
        assert res.slots == {"caption": "Great swim!"}
        assert res.provider == ""
        assert res.warnings == []

    def test_all_blank_slots_skip_the_provider(self):
        gj = mock.MagicMock()
        with mock.patch.object(T, "generate_json", gj):
            res = translate_slots({"caption": "  ", "headline": ""}, "cy")
        gj.assert_not_called()
        assert res.slots == {"caption": "  ", "headline": ""}

    def test_empty_or_unparseable_target_is_a_no_op(self):
        # An empty/blank target can't be translated to — return the source
        # untouched without spending (or requiring) a provider call.
        gj = mock.MagicMock()
        with mock.patch.object(T, "generate_json", gj):
            for target in ("", "   ", None):
                res = translate_slots({"caption": "Great swim!"}, target)
                assert res.slots == {"caption": "Great swim!"}
        gj.assert_not_called()


class TestTranslation:
    def _patch(self, return_value, provider="gemini-api"):
        gj = mock.MagicMock(return_value=return_value)
        return (
            mock.patch.object(T, "generate_json", gj),
            mock.patch.object(T, "active_provider", return_value=provider),
            gj,
        )

    def test_translates_slots_and_stamps_metadata(self):
        p_gj, p_prov, gj = self._patch({"headline": "Pennawd", "caption": "Capsiwn newydd"})
        with p_gj, p_prov:
            res = translate_slots(
                {"headline": "Headline", "caption": "New caption"},
                "cy",
                source_language="en",
            )
        assert res.slots == {"headline": "Pennawd", "caption": "Capsiwn newydd"}
        assert res.source_slots == {"headline": "Headline", "caption": "New caption"}
        assert res.provider == "gemini-api"
        assert res.target_language == "cy"
        assert res.rtl is False
        assert res.script == "latin"
        assert res.regional_only is False
        assert res.warnings == []
        gj.assert_called_once()

    def test_prompt_carries_glossary_and_generic_rules(self):
        p_gj, p_prov, gj = self._patch({"caption": "Camp newydd!"})
        with p_gj, p_prov:
            translate_slots({"caption": "New PB!"}, "cy")
        system = gj.call_args.kwargs["system"]
        # language named, generic protection, and the swimming glossary present
        assert "Welsh" in system and "Cymraeg" in system
        assert "Keep these EXACTLY" in system
        assert "record personol" in system  # verified Welsh term in glossary block
        assert "PB" in system

    def test_rtl_target_marks_result(self):
        p_gj, p_prov, gj = self._patch({"caption": "تعليق"})
        with p_gj, p_prov:
            res = translate_slots({"caption": "A caption"}, "ar")
        assert res.rtl is True
        assert res.script == "arabic"

    def test_honest_error_when_no_provider(self):
        def boom(*a, **k):
            raise ClaudeUnavailableError("no provider")

        with mock.patch.object(T, "generate_json", side_effect=boom):
            with pytest.raises(ClaudeUnavailableError):
                translate_slots({"caption": "Great swim!"}, "cy")

    def test_protected_term_drop_is_warned(self):
        # Model returns a translation that dropped the protected "PB".
        p_gj, p_prov, gj = self._patch({"caption": "Camp newydd i Hannah!"})
        with p_gj, p_prov:
            res = translate_slots({"caption": "New PB for Hannah!"}, "cy")
        assert any("PB" in w for w in res.warnings)

    def test_length_budget_overflow_is_warned_not_truncated(self):
        long = "A really rather long translated headline that won't fit"
        p_gj, p_prov, gj = self._patch({"headline": long})
        with p_gj, p_prov:
            res = translate_slots({"headline": "Big win"}, "cy", length_budgets={"headline": 10})
        assert res.slots["headline"] == long  # never silently truncated
        assert any("budget" in w for w in res.warnings)

    def test_missing_slot_keeps_source_and_warns(self):
        p_gj, p_prov, gj = self._patch({"headline": "Pennawd"})  # caption missing
        with p_gj, p_prov:
            res = translate_slots({"headline": "Headline", "caption": "Keep me"}, "cy")
        assert res.slots["caption"] == "Keep me"
        assert any('"caption"' in w and "not returned" in w for w in res.warnings)


class TestRegionalVariant:
    def test_en_gb_to_en_us_is_a_regional_pass(self):
        gj = mock.MagicMock(return_value={"caption": "My favorite color"})
        with (
            mock.patch.object(T, "generate_json", gj),
            mock.patch.object(T, "active_provider", return_value="gemini-api"),
        ):
            res = translate_slots(
                {"caption": "My favourite colour"}, "en-US", source_language="en-GB"
            )
        assert res.regional_only is True
        assert res.slots["caption"] == "My favorite color"
        system = gj.call_args.kwargs["system"]
        assert "spelling" in system.lower()
        assert "US" in system


class TestTranslateText:
    def test_single_string(self):
        with (
            mock.patch.object(T, "generate_json", return_value={"text": "Nofio gwych!"}),
            mock.patch.object(T, "active_provider", return_value="gemini-api"),
        ):
            assert translate_text("Great swim!", "cy") == "Nofio gwych!"

    def test_same_language_returns_input(self):
        gj = mock.MagicMock()
        with mock.patch.object(T, "generate_json", gj):
            assert translate_text("Great swim!", "en") == "Great swim!"
        gj.assert_not_called()
