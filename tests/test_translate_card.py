"""web.translate_card — the review-card translation adapter over localize.

LLM mocked; pins the variant shape the route + workflow store rely on.
"""

from __future__ import annotations

from unittest import mock

import pytest

from mediahub.localize import translate as T
from mediahub.web.translate_card import ClaudeUnavailableError, translate_card_slots


def _patch_provider(return_value, provider="gemini-api"):
    return (
        mock.patch.object(T, "generate_json", return_value=return_value),
        mock.patch.object(T, "active_provider", return_value=provider),
    )


class TestTranslateCardSlots:
    def test_returns_variant_with_display_metadata(self):
        p_gj, p_prov = _patch_provider({"caption": "Nofio gwych!", "alt_text": "alt cy"})
        with p_gj, p_prov:
            v = translate_card_slots({"caption": "Great swim!", "alt_text": "alt en"}, "cy")
        assert v["language"] == "cy"
        assert v["language_base"] == "cy"
        assert v["language_label"] == "Cymraeg"
        assert v["rtl"] is False
        assert v["script"] == "latin"
        assert v["slots"]["caption"] == "Nofio gwych!"
        assert v["slots"]["alt_text"] == "alt cy"
        assert v["provider"] == "gemini-api"
        assert v["warnings"] == []

    def test_rtl_language_metadata(self):
        p_gj, p_prov = _patch_provider({"caption": "تعليق"})
        with p_gj, p_prov:
            v = translate_card_slots({"caption": "A caption"}, "ar")
        assert v["rtl"] is True
        assert v["script"] == "arabic"

    def test_regional_variant_flag(self):
        p_gj, p_prov = _patch_provider({"caption": "My favorite color"})
        with p_gj, p_prov:
            v = translate_card_slots(
                {"caption": "My favourite colour"}, "en-US", source_language="en-GB"
            )
        assert v["regional_only"] is True
        assert v["language"] == "en-US"

    def test_budget_overflow_surfaces_as_warning(self):
        long = "x" * 80
        p_gj, p_prov = _patch_provider({"headline": long})
        with p_gj, p_prov:
            v = translate_card_slots({"headline": "Win"}, "cy")  # headline budget = 60
        assert any("budget" in w for w in v["warnings"])

    def test_honest_error_propagates(self):
        def boom(*a, **k):
            raise ClaudeUnavailableError("no provider")

        with mock.patch.object(T, "generate_json", side_effect=boom):
            with pytest.raises(ClaudeUnavailableError):
                translate_card_slots({"caption": "Great swim!"}, "cy")
