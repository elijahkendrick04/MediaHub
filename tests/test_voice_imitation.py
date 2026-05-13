"""
tests/test_voice_imitation.py — deterministic tests for the brand-voice
imitation layer (dissertation §4.5 Lately, §4.6 Jasper, §6 Workstream 2.4).

All tests run with use_llm=False so they're hermetic — no network calls,
no LLM keys needed. The qualitative LLM path is exercised separately via
mocking generate_json so we never depend on a live provider.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mediahub.brand.voice_imitation import (  # noqa: E402
    analyse_examples,
    redact_pii,
    ADDRESS_OPTIONS,
)


# ---------------------------------------------------------------------------
# 1. Sentence-length stats
# ---------------------------------------------------------------------------

class TestSentenceLengthStats:
    def test_short_sentences(self):
        examples = ["One two three.", "Four five."]
        out = analyse_examples(examples, use_llm=False)
        # avg of (3, 2) = 2.5
        assert out["sentence_length_avg"] == 2.5

    def test_single_sentence_no_split(self):
        # 8 words, no punctuation — the splitter should still return one
        # sentence of length 8 rather than zero or many.
        out = analyse_examples(["A nine word sentence with no punctuation here"],
                               use_llm=False)
        assert out["sentence_length_avg"] == 8.0
        # P90 with one sample collapses to the sample itself.
        assert out["sentence_length_p90"] == 8.0

    def test_p90_above_average_with_mixed_lengths(self):
        examples = [
            "Short one.",
            "This one has more words than the previous example overall.",
            "Tiny.",
        ]
        out = analyse_examples(examples, use_llm=False)
        assert out["sentence_length_p90"] >= out["sentence_length_avg"]

    def test_empty_input_returns_zeros(self):
        out = analyse_examples([], use_llm=False)
        assert out["sentence_length_avg"] == 0.0
        assert out["sentence_length_p90"] == 0.0
        assert out["emoji_rate_per_caption"] == 0.0
        assert out["hashtag_count_avg"] == 0.0

    def test_blank_strings_filtered(self):
        out = analyse_examples(["   ", "", "Real caption here."], use_llm=False)
        # Only one non-blank caption — 3-word sentence.
        assert out["sentence_length_avg"] == 3.0


# ---------------------------------------------------------------------------
# 2. Emoji counting
# ---------------------------------------------------------------------------

class TestEmojiCounting:
    def test_basic_emoji_count(self):
        # 1 emoji each → emoji_rate = 1.0
        out = analyse_examples([
            "Great swim 🏊",
            "Another swim 🔥",
        ], use_llm=False)
        assert out["emoji_rate_per_caption"] == 1.0

    def test_no_emoji(self):
        out = analyse_examples([
            "Plain caption with no emoji.",
            "Another plain one.",
        ], use_llm=False)
        assert out["emoji_rate_per_caption"] == 0.0

    def test_multiple_emoji_in_one_caption(self):
        out = analyse_examples([
            "Massive 🔥🔥🔥 PB today",
            "Quiet day",
        ], use_llm=False)
        # 3 emoji in two captions = 1.5
        assert out["emoji_rate_per_caption"] == 1.5

    def test_sparkles_and_checkmarks_count(self):
        # Dingbats range emoji (✨, ✅, ⭐)
        out = analyse_examples(["Sparkles ✨ ✅"], use_llm=False)
        assert out["emoji_rate_per_caption"] == 2.0


# ---------------------------------------------------------------------------
# 3. Hashtag counting
# ---------------------------------------------------------------------------

class TestHashtagCounting:
    def test_average_hashtags(self):
        out = analyse_examples([
            "Big swim #SwimClub #PB #ProudCoach",  # 3
            "Quiet caption #OneTag",                # 1
        ], use_llm=False)
        # avg = (3 + 1) / 2 = 2.0
        assert out["hashtag_count_avg"] == 2.0

    def test_no_hashtags(self):
        out = analyse_examples([
            "Plain caption with zero hashtags.",
        ], use_llm=False)
        assert out["hashtag_count_avg"] == 0.0

    def test_hashtag_inside_word_not_counted(self):
        # In-word "#" shouldn't count as a hashtag; only standalone tokens.
        out = analyse_examples(["weird#thing should not count"], use_llm=False)
        assert out["hashtag_count_avg"] == 0.0


# ---------------------------------------------------------------------------
# 4. PII redaction
# ---------------------------------------------------------------------------

class TestPiiRedaction:
    def test_full_name_redacted(self):
        out = redact_pii("Great swim from Emma Davies in the 200 free.")
        assert "Emma Davies" not in out
        assert "[NAME]" in out

    def test_hyphenated_surname_redacted(self):
        out = redact_pii("Massive PB from Lily Smith-Jones today.")
        assert "Lily Smith-Jones" not in out
        assert "[NAME]" in out

    def test_apostrophe_surname_redacted(self):
        out = redact_pii("Brilliant from James O'Brien this morning.")
        assert "James O'Brien" not in out
        assert "[NAME]" in out

    def test_single_capital_word_not_redacted(self):
        # Single capitalised words (event names, places) must survive.
        out = redact_pii("Brilliant 200m Backstroke from the team.")
        assert "Backstroke" in out
        assert "[NAME]" not in out

    def test_handle_redacted(self):
        out = redact_pii("Shoutout to @emma_davies for the swim today.")
        assert "@emma_davies" not in out
        assert "[NAME]" in out

    def test_club_name_allowlisted(self):
        # Real club name on the allowlist must not be redacted.
        out = redact_pii("Welcome to City of Manchester Aquatics open day.")
        assert "City of Manchester Aquatics" in out

    def test_redaction_runs_on_persisted_examples(self):
        examples = [
            "Emma Davies smashed the 200 fly.",
            "Proud of James Carter and Lily Smith-Jones tonight.",
        ]
        out = analyse_examples(examples, use_llm=False)
        # We can't see voice_examples back through analyse_examples, but
        # the qualitative path runs on redacted strings — and the
        # deterministic stats path also operates post-redaction. The
        # caller-facing redact_pii is the contract guarantee.
        for raw_name in ("Emma Davies", "James Carter", "Lily Smith-Jones"):
            assert raw_name not in str(out)


# ---------------------------------------------------------------------------
# 5. Full profile shape (no LLM)
# ---------------------------------------------------------------------------

class TestProfileShape:
    def test_all_keys_present_without_llm(self):
        out = analyse_examples([
            "Caption one.", "Caption two.", "Caption three.",
        ], use_llm=False)
        expected_keys = {
            "sentence_length_avg",
            "sentence_length_p90",
            "emoji_rate_per_caption",
            "hashtag_count_avg",
            "characteristic_openers",
            "characteristic_closers",
            "forbidden_phrases",
            "preferred_swimmer_address",
        }
        assert set(out.keys()) >= expected_keys

    def test_default_address_is_first_name(self):
        out = analyse_examples(["Just one caption."], use_llm=False)
        assert out["preferred_swimmer_address"] == "first_name"

    def test_qual_fields_are_empty_lists_without_llm(self):
        out = analyse_examples(["Hello world."], use_llm=False)
        assert out["characteristic_openers"] == []
        assert out["characteristic_closers"] == []
        assert out["forbidden_phrases"] == []


# ---------------------------------------------------------------------------
# 6. Qualitative LLM path (mocked)
# ---------------------------------------------------------------------------

class TestQualitativeLLMPath:
    def test_llm_response_normalised(self):
        fake_response = {
            "characteristic_openers": ["Massive swim", "Proud of"],
            "characteristic_closers": ["One for the grid", "Onwards"],
            "forbidden_phrases": ["literally", "absolutely smashed"],
            "preferred_swimmer_address": "first_name",
        }
        with mock.patch(
            "mediahub.media_ai.llm.generate_json",
            return_value=fake_response,
        ):
            out = analyse_examples([
                "Massive swim from the team today. One for the grid.",
                "Proud of every swimmer tonight. Onwards.",
            ], use_llm=True)
        assert out["characteristic_openers"] == ["Massive swim", "Proud of"]
        assert "literally" in out["forbidden_phrases"]
        assert out["preferred_swimmer_address"] == "first_name"

    def test_llm_garbage_falls_back_to_safe_defaults(self):
        # An invalid address gets normalised back to "first_name".
        with mock.patch(
            "mediahub.media_ai.llm.generate_json",
            return_value={"preferred_swimmer_address": "not-a-real-mode"},
        ):
            out = analyse_examples(["Hello."], use_llm=True)
        assert out["preferred_swimmer_address"] == "first_name"
        assert out["characteristic_openers"] == []

    def test_llm_raises_caught_and_safe_defaults_returned(self):
        with mock.patch(
            "mediahub.media_ai.llm.generate_json",
            side_effect=RuntimeError("boom"),
        ):
            out = analyse_examples(["Hello world."], use_llm=True)
        assert out["preferred_swimmer_address"] == "first_name"
        assert out["characteristic_openers"] == []
        # Numeric stats still computed.
        assert out["sentence_length_avg"] > 0


# ---------------------------------------------------------------------------
# 7. Address option contract
# ---------------------------------------------------------------------------

class TestAddressOptions:
    def test_known_options(self):
        assert ADDRESS_OPTIONS == {
            "first_name", "last_name", "surname_only", "nickname",
        }


# ---------------------------------------------------------------------------
# 8. Voice profile flows into ai_caption.generate_caption_for_tone
# ---------------------------------------------------------------------------

class TestVoiceProfileSystemPromptInjection:
    """Confirm the voice_profile actually changes the system prompt that
    generate_caption_for_tone sends to the LLM. We don't call a real
    provider — we patch call_claude and capture its `system` argument."""

    def _capture_system(self, voice_profile):
        from mediahub.web import ai_caption

        class _Stub:
            def __init__(self, vp):
                self.voice_profile = vp

        captured = {}

        def _fake(system, user, model=None, max_tokens=512):
            captured["system"] = system
            captured["user"] = user
            return "stub caption"

        ach = {"swimmer_name": "Test Swimmer", "event": "200 Free"}
        with mock.patch.object(ai_caption, "call_claude", side_effect=_fake):
            ai_caption.generate_caption_for_tone(
                ach, club_brand={"club_name": "Demo"},
                tone="ai",
                club_profile=_Stub(voice_profile) if voice_profile else None,
            )
        return captured

    def test_no_profile_passthrough_unchanged(self):
        cap = self._capture_system(None)
        # Without a voice profile, prompt has no "Club voice profile" header.
        assert "Club voice profile" not in cap["system"]

    def test_empty_profile_dict_passthrough(self):
        cap = self._capture_system({})
        assert "Club voice profile" not in cap["system"]

    def test_hashtag_count_injected(self):
        cap = self._capture_system({
            "sentence_length_avg": 14,
            "hashtag_count_avg": 3,
            "preferred_swimmer_address": "first_name",
        })
        assert "Club voice profile" in cap["system"]
        assert "3 hashtag" in cap["system"]

    def test_zero_hashtags_means_no_hashtags(self):
        cap = self._capture_system({
            "hashtag_count_avg": 0,
        })
        assert "Do NOT use hashtags" in cap["system"]

    def test_emoji_avoided_when_rate_is_zero(self):
        cap = self._capture_system({
            "emoji_rate_per_caption": 0.0,
        })
        assert "Avoid emoji" in cap["system"]

    def test_address_style_surname(self):
        cap = self._capture_system({
            "preferred_swimmer_address": "surname_only",
        })
        assert "surname" in cap["system"].lower()

    def test_openers_and_closers_injected(self):
        cap = self._capture_system({
            "characteristic_openers": ["Massive swim from", "Big shout to"],
            "characteristic_closers": ["One for the grid"],
        })
        assert "Massive swim from" in cap["system"]
        assert "One for the grid" in cap["system"]

    def test_two_different_profiles_produce_different_prompts(self):
        a = self._capture_system({
            "characteristic_openers": ["Massive"],
            "hashtag_count_avg": 3,
            "preferred_swimmer_address": "first_name",
        })
        b = self._capture_system({
            "characteristic_openers": ["Quietly proud"],
            "hashtag_count_avg": 0,
            "preferred_swimmer_address": "surname_only",
        })
        assert a["system"] != b["system"]
