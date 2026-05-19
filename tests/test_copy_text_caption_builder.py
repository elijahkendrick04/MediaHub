"""Tests for `mediahub.recognition.copy_text.build_caption_text`.

The plain-text caption builder is the single source of truth for what
appears on the user's clipboard when they tap "Copy caption". It must
never leak HTML and must support both V4 (legacy `captions.clean/team/hype`)
and V5 (`active_caption.headline/body/cta`) card shapes.

Existing coverage in `tests/test_v73_modules.py` exercises the V5 happy
path. This file pins the V4 fallback, edge cases, mode-specific output,
and HTML-stripping guarantees.
"""
from __future__ import annotations

import pytest

from mediahub.recognition.copy_text import build_caption_text


# ---------------------------------------------------------------------------
# V5 (active_caption) shape
# ---------------------------------------------------------------------------


def _v5_card(**overrides) -> dict:
    base = {
        "active_caption": {
            "headline": "Jane Smith — official PB confirmed",
            "body": "1:02.34 in 100m Freestyle (LC).",
            "cta": "Tap to share",
        },
        "hashtags": ["#AquaticSharks", "#PB"],
    }
    base.update(overrides)
    return base


class TestV5Captions:
    def test_caption_only_includes_all_three_parts(self) -> None:
        text = build_caption_text(_v5_card(), mode="caption_only")
        assert "Jane Smith" in text
        assert "1:02.34" in text
        assert "Tap to share" in text

    def test_caption_only_excludes_hashtags(self) -> None:
        text = build_caption_text(_v5_card(), mode="caption_only")
        assert "#AquaticSharks" not in text
        assert "#PB" not in text

    def test_with_hashtags_includes_them(self) -> None:
        text = build_caption_text(_v5_card(), mode="with_hashtags")
        assert "#AquaticSharks" in text
        assert "#PB" in text

    def test_empty_body_does_not_emit_blank_block(self) -> None:
        card = _v5_card()
        card["active_caption"]["body"] = ""
        text = build_caption_text(card)
        # Headline present, body skipped — no double-blank in output.
        assert "\n\n\n" not in text


# ---------------------------------------------------------------------------
# V4 (captions.clean/team/hype) fallback
# ---------------------------------------------------------------------------


class TestV4Captions:
    def test_prefers_clean_caption(self) -> None:
        card = {
            "headline": "Jane Smith — PB",
            "captions": {
                "clean": "Jane swam a clean PB.",
                "team": "Squad version.",
                "hype": "INSANE TIME!",
            },
        }
        text = build_caption_text(card)
        assert "Jane Smith" in text
        assert "Jane swam a clean PB." in text
        # Team and hype variants must NOT appear when clean exists.
        assert "Squad version." not in text
        assert "INSANE TIME!" not in text

    def test_falls_back_to_team_when_no_clean(self) -> None:
        card = {
            "headline": "Headline",
            "captions": {"team": "Team caption.", "hype": "HYPE!"},
        }
        text = build_caption_text(card)
        assert "Team caption." in text

    def test_falls_back_to_hype_when_only_hype_present(self) -> None:
        card = {
            "headline": "Headline",
            "captions": {"hype": "HYPE!"},
        }
        text = build_caption_text(card)
        assert "HYPE!" in text

    def test_card_level_headline_used_when_caption_missing(self) -> None:
        card = {"headline": "Card-level headline"}
        text = build_caption_text(card)
        assert "Card-level headline" in text

    def test_empty_card_returns_empty(self) -> None:
        assert build_caption_text({}) == ""


# ---------------------------------------------------------------------------
# Hashtags
# ---------------------------------------------------------------------------


class TestHashtagsMode:
    def test_hashtags_joined_with_spaces(self) -> None:
        text = build_caption_text(
            _v5_card(hashtags=["#A", "#B", "#C"]),
            mode="with_hashtags",
        )
        assert "#A #B #C" in text

    def test_hashtags_html_stripped(self) -> None:
        text = build_caption_text(
            _v5_card(hashtags=["<b>#A</b>", "#B"]),
            mode="with_hashtags",
        )
        # The HTML tags must be stripped before joining.
        assert "<b>" not in text
        assert "#A" in text

    def test_no_hashtags_in_with_hashtags_mode_doesnt_crash(self) -> None:
        card = _v5_card()
        card["hashtags"] = []
        text = build_caption_text(card, mode="with_hashtags")
        # Should still produce the caption text, just no hashtag line.
        assert "Jane Smith" in text


# ---------------------------------------------------------------------------
# full_brief mode
# ---------------------------------------------------------------------------


class TestFullBriefMode:
    def test_includes_suggested_format(self) -> None:
        card = _v5_card(suggested_post_type="story_card")
        text = build_caption_text(card, mode="full_brief")
        assert "Suggested format: story_card" in text

    def test_falls_back_to_main_feed_when_unset(self) -> None:
        card = _v5_card()
        text = build_caption_text(card, mode="full_brief")
        assert "Suggested format: main_feed" in text

    def test_confidence_float_formatted_as_percent(self) -> None:
        card = _v5_card(confidence=0.98)
        text = build_caption_text(card, mode="full_brief")
        assert "Confidence: 98%" in text

    def test_confidence_string_rendered_verbatim(self) -> None:
        card = _v5_card(confidence="high")
        text = build_caption_text(card, mode="full_brief")
        assert "Confidence: high" in text

    def test_priority_used_when_no_confidence(self) -> None:
        card = _v5_card(priority=0.5)
        text = build_caption_text(card, mode="full_brief")
        assert "Confidence:" in text

    def test_safe_to_post_rendered(self) -> None:
        card = _v5_card(safe_to_post={"level": "green", "reason": "All sources high"})
        text = build_caption_text(card, mode="full_brief")
        assert "Safe to post: green" in text
        assert "All sources high" in text

    def test_post_angle_included(self) -> None:
        card = _v5_card(post_angle="celebrate PB; tag athlete")
        text = build_caption_text(card, mode="full_brief")
        assert "Post angle: celebrate PB; tag athlete" in text

    def test_evidence_block_emits_sources(self) -> None:
        card = _v5_card(evidence=[
            {
                "source_url": "https://example.org/pb",
                "source_name": "Example PB",
                "statement": "Listed PB matches",
            },
        ])
        text = build_caption_text(card, mode="full_brief")
        assert "Sources:" in text
        assert "Example PB" in text
        assert "https://example.org/pb" in text
        assert "Listed PB matches" in text

    def test_evidence_block_caps_at_three(self) -> None:
        card = _v5_card(evidence=[
            {"source_name": f"src_{i}"} for i in range(8)
        ])
        text = build_caption_text(card, mode="full_brief")
        assert "src_0" in text
        assert "src_2" in text
        # Fourth and beyond should be elided.
        assert "src_3" not in text
        assert "src_7" not in text

    def test_full_brief_separator_present(self) -> None:
        text = build_caption_text(_v5_card(), mode="full_brief")
        assert "---" in text


# ---------------------------------------------------------------------------
# HTML safety — the single hard contract
# ---------------------------------------------------------------------------


class TestHtmlStripping:
    @pytest.mark.parametrize(
        "mode", ["caption_only", "with_hashtags", "full_brief"],
    )
    def test_no_html_tags_for_any_mode(self, mode: str) -> None:
        card = {
            "active_caption": {
                "headline": "<b>Bold headline</b>",
                "body": "<script>alert(1)</script>Body text",
                "cta": "<i>Italic CTA</i>",
            },
            "hashtags": ["<b>#tag</b>"],
            "evidence": [{"source_name": "<u>Src</u>"}],
            "post_angle": "<em>angle</em>",
            "suggested_post_type": "<b>story_card</b>",
            "safe_to_post": {"level": "<i>green</i>", "reason": "<b>ok</b>"},
        }
        text = build_caption_text(card, mode=mode)
        assert "<" not in text
        assert ">" not in text

    def test_decodes_common_entities(self) -> None:
        card = {
            "headline": "Smith &amp; Jones — &quot;hello&quot;",
            "captions": {"clean": "It&#39;s great"},
        }
        text = build_caption_text(card)
        assert "&amp;" not in text
        assert "&" in text
        assert "&quot;" not in text
        assert '"' in text
        assert "&#39;" not in text
        assert "It's great" in text

    def test_handles_inline_style_attempts(self) -> None:
        card = {
            "active_caption": {
                "headline": "<span style='color:red'>RED</span>",
                "body": "",
                "cta": "",
            },
        }
        text = build_caption_text(card)
        assert "<span" not in text
        assert "RED" in text

    def test_nested_html_handled(self) -> None:
        card = {
            "active_caption": {
                "headline": "<div><b>Nested</b></div>",
                "body": "",
                "cta": "",
            },
        }
        text = build_caption_text(card)
        assert "Nested" in text
        assert "<" not in text


# ---------------------------------------------------------------------------
# Mode boundary
# ---------------------------------------------------------------------------


class TestModeBoundary:
    def test_invalid_mode_falls_back_to_caption_only(self) -> None:
        # Unknown mode should not crash; it just doesn't add the
        # hashtag / brief blocks.
        text = build_caption_text(
            _v5_card(),
            mode="not-a-real-mode",
        )
        assert "Jane Smith" in text
        assert "#" not in text  # hashtags only appear in known modes
        assert "Suggested format" not in text
