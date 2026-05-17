"""tests/test_platform_formats.py — per-platform mechanical format
constraints flow through the caption pipeline.

The audit's separation principle was: creative direction → AI;
format constraints → code. Phase 1.2 closes the loop by making the
caption pipeline actually receive and respect both.

Pins:
  1. ``platform_format_for`` returns the right rule block per
     artefact, falls back to generic, and is not profile-aware.
  2. The artefact-key and artefact-intent attached by the Turn-Into
     pipeline both reach the caption LLM's system prompt — previously
     a latent bug where ``_artefact_intent`` was set on the payload
     but never read.
  3. Caller-supplied extra instructions (used by the sponsor variant)
     also reach the system prompt and take precedence at the end.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.brand import derived as bd  # noqa: E402


# ---------------------------------------------------------------------------
# 1. platform_format_for shape
# ---------------------------------------------------------------------------

class TestPlatformFormatFor:
    def test_instagram_long(self):
        rules = bd.platform_format_for("instagram_long")
        assert "Instagram" in rules
        assert "2,200" in rules

    def test_data_thread_post_is_x(self):
        rules = bd.platform_format_for("data_thread_post")
        assert "280" in rules
        # The X label shouldn't include "Instagram"
        assert "Instagram" not in rules

    def test_linkedin_long(self):
        rules = bd.platform_format_for("linkedin_long")
        assert "LinkedIn" in rules
        assert "professional" in rules.lower()

    def test_parent_newsletter_is_email(self):
        rules = bd.platform_format_for("parent_newsletter")
        assert "email" in rules.lower() or "newsletter" in rules.lower()

    def test_unknown_artefact_falls_back_to_generic(self):
        rules = bd.platform_format_for("not_a_real_artefact")
        assert rules == bd.PLATFORM_FORMATS["generic"]

    def test_generic_for_generic_artefacts(self):
        # meet_recap / swimmer_spotlight / etc. aren't platform-locked
        for k in ("meet_recap", "swimmer_spotlight", "sponsor_thank_you",
                  "coach_quote", "next_meet_preview"):
            rules = bd.platform_format_for(k)
            assert rules == bd.PLATFORM_FORMATS["generic"], (
                f"{k} should default to generic format"
            )


# ---------------------------------------------------------------------------
# 2. Caption pipeline now reads _artefact_intent + _artefact_key
# ---------------------------------------------------------------------------

class TestCaptionPipelineReadsArtefactKeys:
    def _capture_system_prompt(self, payload: dict, monkeypatch) -> str:
        """Stub the underlying LLM call and capture what the caption
        pipeline shipped as the system prompt."""
        captured = {}

        def fake_call(system, user, max_tokens=400, **_):
            captured["system"] = system
            return "stubbed caption"

        monkeypatch.setattr(
            "mediahub.web.ai_caption.call_claude", fake_call,
        )
        from mediahub.web.ai_caption import generate_caption_for_tone
        out = generate_caption_for_tone(payload, tone="ai")
        assert out == "stubbed caption"
        return captured.get("system", "")

    def test_artefact_intent_reaches_system_prompt(self, monkeypatch):
        sys_prompt = self._capture_system_prompt(
            {
                "swimmer_name": "Emma", "event": "100 Free",
                "time": "58.21", "type": "pb_confirmed",
                "_artefact_intent": "Lead with the rookie's breakthrough; family-first.",
            },
            monkeypatch,
        )
        assert "Lead with the rookie's breakthrough" in sys_prompt
        assert "Creative intent" in sys_prompt

    def test_artefact_key_pulls_platform_format(self, monkeypatch):
        sys_prompt = self._capture_system_prompt(
            {
                "swimmer_name": "Emma", "event": "100 Free",
                "time": "58.21", "type": "pb_confirmed",
                "_artefact_key": "instagram_long",
            },
            monkeypatch,
        )
        # Instagram rules surface verbatim
        assert "2,200" in sys_prompt
        assert "Instagram" in sys_prompt

    def test_thread_post_pulls_x_format(self, monkeypatch):
        sys_prompt = self._capture_system_prompt(
            {
                "swimmer_name": "Emma", "event": "100 Free",
                "time": "58.21",
                "_artefact_key": "data_thread_post",
            },
            monkeypatch,
        )
        assert "280" in sys_prompt

    def test_extra_instructions_reach_prompt_and_come_last(self, monkeypatch):
        sys_prompt = self._capture_system_prompt(
            {
                "swimmer_name": "Emma", "event": "100 Free",
                "time": "58.21",
                "_extra_instructions": "Acknowledge sponsor Acme Sports.",
            },
            monkeypatch,
        )
        assert "Acknowledge sponsor Acme Sports" in sys_prompt
        # Extra instructions section must appear AFTER the main tone /
        # format blocks so it has precedence in the LLM's reading.
        idx_tone = sys_prompt.find("Tone:")
        idx_extra = sys_prompt.find("Additional requirement")
        assert idx_tone != -1 and idx_extra != -1
        assert idx_extra > idx_tone

    def test_artefact_key_without_intent_still_gets_format(self, monkeypatch):
        """If Turn-Into only set the artefact key (e.g. when the derived
        intent is empty), the platform format rules should still flow."""
        sys_prompt = self._capture_system_prompt(
            {
                "swimmer_name": "Emma", "event": "100 Free",
                "time": "58.21",
                "_artefact_key": "linkedin_long",
            },
            monkeypatch,
        )
        assert "LinkedIn" in sys_prompt
