"""tests/test_caption_ai_tell_guardrail.py — strengthened caption guardrails.

Covers the caption-generator audit improvements:

  1. Expanded AI-tell / hollow-filler ban list, and the single-source-of-truth
     alignment between the ban list and the system-prompt instruction.
  2. Source-fact grounding check (recipe #232 of the generation-engine
     competitor evaluation): a caption naming no swimmer/event/time is generic
     filler and is dropped in favour of a grounded sibling.
  3. Inline caption-assist bounded regenerate-on-tell — the assist surface no
     longer ships a banned cliché the live route would have filtered.
  4. Guardrail parity for the two surfaces that build their own prompt: the
     brief-led content engine and the turn-into long-form writer.

All LLM calls are mocked — no network required.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# 1. Expanded ban list + prompt/filter alignment
# ---------------------------------------------------------------------------


class TestExpandedBanList:
    def test_new_tells_detected(self):
        from mediahub.web.ai_caption import _contains_ai_tell

        for phrase in (
            "This swim is a testament to her hard work.",
            "When it comes to the 200 fly, no one is faster.",
            "Needless to say, the whole squad was proud.",
            "She is the epitome of dedication.",
            "A shining example for the younger swimmers.",
            "The result speaks volumes about the coaching.",
            "It just goes to show what training can do.",
            "The team unleashed everything in the final leg.",
        ):
            assert _contains_ai_tell(phrase) is True, phrase

    def test_original_tells_still_detected(self):
        from mediahub.web.ai_caption import _contains_ai_tell

        assert _contains_ai_tell("Let us delve into the performance") is True
        assert _contains_ai_tell("elevating the club to new heights") is True
        assert _contains_ai_tell("In the world of swimming this matters") is True

    def test_clean_caption_still_passes(self):
        from mediahub.web.ai_caption import _contains_ai_tell

        assert _contains_ai_tell("Alex smashed his 100m PB with a 58.12.") is False
        assert _contains_ai_tell("Gold for Eira in the 200 free — 2:08.41!") is False

    def test_prompt_and_filter_agree(self):
        # The shared anti-slop instruction (ai_core.prompt_guard) and the
        # post-generation filter must not drift: phrases the model is warned
        # about are also the ones the filter strips.
        from mediahub.web.ai_caption import _contains_ai_tell

        for phrase in ("delve", "unleash", "testament to", "when it comes to", "the epitome of"):
            assert _contains_ai_tell(f"a caption that says {phrase} in it") is True, phrase

    def test_instruction_names_representative_tells(self):
        # The instruction is sourced from ai_core.prompt_guard and aliased.
        from mediahub.web.ai_caption import _AI_TELL_SYSTEM_INSTRUCTION

        low = _AI_TELL_SYSTEM_INSTRUCTION.lower()
        for phrase in ("delve", "testament to", "when it comes to", "unleash"):
            assert phrase in low, phrase

    def test_filter_drops_expanded_tell(self):
        from mediahub.web.ai_caption import filter_caption_variants

        tell = "Her swim is a testament to months of early mornings."
        good = "Eira goes 2:08.41 in the 200 free for a new PB."
        assert filter_caption_variants([tell, good]) == [good]


# ---------------------------------------------------------------------------
# 2. Source-fact grounding
# ---------------------------------------------------------------------------

_ACH = {
    "swimmer_name": "Eira Hughes",
    "event": "200m Freestyle (SC)",
    "time": "2:08.41",
    "place": 1,
    "type": "medal_gold",
}


class TestGroundingFacts:
    def test_facts_extracted_from_achievement(self):
        from mediahub.web.ai_caption import _caption_grounding_facts

        facts = _caption_grounding_facts(_ACH)
        assert "eira" in facts
        assert "hughes" in facts
        assert "2:08.41" in facts
        assert "200m" in facts
        assert "freestyle" in facts
        # Course jargon must not become a "fact" to match on.
        assert "sc" not in facts

    def test_no_facts_for_empty_source(self):
        from mediahub.web.ai_caption import _caption_grounding_facts

        assert _caption_grounding_facts({}) == []
        assert _caption_grounding_facts(None) == []

    def test_is_grounded_true_on_any_fact(self):
        from mediahub.web.ai_caption import _caption_grounding_facts, _is_grounded

        facts = _caption_grounding_facts(_ACH)
        assert _is_grounded("Huge swim from Eira tonight!", facts) is True
        assert _is_grounded("A 2:08.41 in the 200 free — brilliant.", facts) is True

    def test_is_grounded_false_on_generic_filler(self):
        from mediahub.web.ai_caption import _caption_grounding_facts, _is_grounded

        facts = _caption_grounding_facts(_ACH)
        assert _is_grounded("What a night for the whole club!", facts) is False

    def test_no_facts_means_grounded(self):
        # Nothing to check against → grounding never fail-closes.
        from mediahub.web.ai_caption import _is_grounded

        assert _is_grounded("Any caption at all.", []) is True


class TestFilterGrounding:
    def test_drops_ungrounded_prefers_grounded(self):
        from mediahub.web.ai_caption import filter_caption_variants

        generic = "What a night for the whole club — everyone did us proud!"
        grounded = "Eira storms to 2:08.41 in the 200 free — a new PB!"
        result = filter_caption_variants([generic, grounded], achievement=_ACH)
        assert result == [grounded]

    def test_no_achievement_keeps_generic(self):
        # Without an achievement, grounding is off — a generic caption survives.
        from mediahub.web.ai_caption import filter_caption_variants

        generic = "What a night for the whole club — everyone did us proud!"
        assert filter_caption_variants([generic]) == [generic]

    def test_fail_open_when_all_ungrounded(self):
        from mediahub.web.ai_caption import filter_caption_variants

        generic = "What a night for the whole club!"
        assert filter_caption_variants([generic], achievement=_ACH) == [generic]


# ---------------------------------------------------------------------------
# 3. Assist bounded regenerate-on-tell
# ---------------------------------------------------------------------------


class TestAssistRegenerateOnTell:
    def test_retries_once_when_first_has_tell(self):
        from mediahub.web import caption_assist

        outputs = iter(
            [
                "Her swim is a testament to her hard work.",  # tell → retry
                "Alice drops a 57.10 PB in the 100 free!",  # clean
            ]
        )

        def fake_gen(*a, **k):
            return next(outputs)

        with mock.patch(
            "mediahub.web.ai_caption.generate_caption_for_tone", side_effect=fake_gen
        ) as m:
            out = caption_assist.assist_caption(
                {"swimmer_name": "Alice"}, "Alice swam a PB", "tidy"
            )
        assert out == "Alice drops a 57.10 PB in the 100 free!"
        assert m.call_count == 2

    def test_no_retry_when_first_is_clean(self):
        from mediahub.web import caption_assist

        with mock.patch(
            "mediahub.web.ai_caption.generate_caption_for_tone",
            return_value="Alice drops a 57.10 PB!",
        ) as m:
            out = caption_assist.assist_caption(
                {"swimmer_name": "Alice"}, "Alice swam a PB", "shorter"
            )
        assert out == "Alice drops a 57.10 PB!"
        assert m.call_count == 1

    def test_keeps_first_if_retry_also_has_tell(self):
        # Fail-open: two banned attempts still return something, not empty.
        from mediahub.web import caption_assist

        with mock.patch(
            "mediahub.web.ai_caption.generate_caption_for_tone",
            side_effect=[
                "A testament to the squad.",
                "Needless to say, a great swim.",
            ],
        ):
            out = caption_assist.assist_caption({}, "cap", "rewrite")
        assert out  # non-empty
        assert out == "A testament to the squad."


# ---------------------------------------------------------------------------
# 4. Guardrail parity: content engine + turn-into long-form
# ---------------------------------------------------------------------------


class TestContentEngineParity:
    def test_brief_led_prompt_carries_ai_tell_ban(self):
        from mediahub.content_engine.engine import _build_system_prompt

        system = _build_system_prompt(
            brand={}, requirements="", directions=[], recent_cards=None, tone="ai"
        )
        assert "delve" in system.lower()
        assert "testament to" in system  # from the shared opener/tone bans


class TestTurnIntoLongformParity:
    def test_longform_prompt_carries_ai_tell_ban(self):
        from mediahub.turn_into import templates

        captured: dict = {}

        def fake_generate(brief, *, system="", max_tokens=1400, **k):
            captured["system"] = system
            return "A long, grounded club report body."

        with mock.patch(
            "mediahub.turn_into.templates._narrate_brief", return_value="Brief facts here."
        ), mock.patch("mediahub.media_ai.llm.generate", side_effect=fake_generate):
            out = templates._gen_longform(
                {"kind": "club_report"},
                {"club_name": "City SC"},
                tone="warm-club",
                intent_key="club_report",
                deterministic=False,
                fallback_text="fallback",
            )
        assert out == "A long, grounded club report body."
        assert "delve" in captured["system"].lower()
