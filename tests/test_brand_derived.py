"""tests/test_brand_derived.py — AI-derived operating profile.

The audit identified four families of hardcoded judgment that should
be replaced with AI: tone descriptors, achievement priority weights,
achievement-type phrases, and per-artefact creative intents.

`brand.derived.derive_operating_profile` runs one LLM call at
profile-save time and produces a cached dict that every consumer
reads via the lookup helpers. This file pins:

  1. The LLM-driven derivation produces a clean, type-safe operating
     profile and clamps any out-of-band priority weights.
  2. The lookup helpers prefer the derived cache when present and
     fall back to the hardcoded defaults when absent (or when no
     LLM was available at save-time).
  3. Resolution flows end-to-end: a saved profile with a derived
     operating profile produces org-specific tone prose / priority
     weights / type phrases / artefact intents at the consumer
     boundaries (ai_caption, narrate, turn_into).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.brand import derived as bd  # noqa: E402
from mediahub.web.club_profile import ClubProfile  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Derivation produces well-shaped output
# ---------------------------------------------------------------------------


class TestDerivation:
    def test_empty_profile_returns_no_context(self):
        out = bd.derive_operating_profile(ClubProfile(profile_id="x", display_name=""))
        assert out["status"] == "no_context"
        assert out["tone_prose"] == {}

    def test_llm_output_normalised(self, monkeypatch):
        mock_out = {
            "tone_prose": {
                "warm-club": "Like a club volunteer talking to parents at the side of the pool.",
                "data-led": "Numbers-first, sponsor-friendly, no fluff.",
                "invalid_tone": "should be dropped",
            },
            "achievement_priorities": {
                "pb_confirmed": 1.7,
                "medal_gold": 0.8,
                "_default": 1.0,
                "made_up_type": 9.9,  # not in CANONICAL_ACHIEVEMENT_TYPES — drop
                "first_sub_barrier": 99.0,  # out-of-band — clamp to 2.0
            },
            "type_phrases": {
                "pb_confirmed": "a brand-new personal best",
                "medal_gold": "a gold medal swim",
                "garbage": "drop me",
            },
            "artefact_voice": {
                "meet_recap": "Lead with the youngest swimmer's breakthrough.",
                "swimmer_spotlight": "Always include the parent's name.",
                "not_an_artefact": "drop me",
            },
        }
        monkeypatch.setattr(bd, "_call_llm", lambda ctx: mock_out)

        p = ClubProfile(
            profile_id="x",
            display_name="City Aquatics",
            brand_voice_summary="Inclusive community club.",
        )
        out = bd.derive_operating_profile(p)
        assert out["status"] == "ok"
        # Canonical tones only
        assert "warm-club" in out["tone_prose"]
        assert "data-led" in out["tone_prose"]
        assert "invalid_tone" not in out["tone_prose"]
        # Priorities clamped + canonical-only
        assert out["achievement_priorities"]["pb_confirmed"] == 1.7
        assert out["achievement_priorities"]["medal_gold"] == 0.8
        assert out["achievement_priorities"]["first_sub_barrier"] == 2.0  # clamped
        assert "made_up_type" not in out["achievement_priorities"]
        # Type phrases canonical-only
        assert out["type_phrases"]["pb_confirmed"] == "a brand-new personal best"
        assert "garbage" not in out["type_phrases"]
        # Artefact voice canonical-only
        assert "meet_recap" in out["artefact_voice"]
        assert "not_an_artefact" not in out["artefact_voice"]

    def test_no_llm_raises_unavailable(self, monkeypatch):
        """When the cloud LLM is unreachable, derive_operating_profile
        raises ClaudeUnavailableError. Callers (the org-save handler in
        web.py) catch it and persist a status="error" stub; consumer
        lookups then fall back to the canonical product defaults."""
        from mediahub.media_ai.llm import ClaudeUnavailableError
        import pytest

        monkeypatch.setattr(bd, "_call_llm", lambda ctx: None)
        p = ClubProfile(
            profile_id="x",
            display_name="City",
            brand_voice_summary="Warm club.",
        )
        with pytest.raises(ClaudeUnavailableError):
            bd.derive_operating_profile(p)

    def test_llm_returns_garbage_raises_unavailable(self, monkeypatch):
        """If the LLM responds but nothing usable survives normalisation,
        we raise ClaudeUnavailableError instead of returning a stub
        labelled as derived output."""
        from mediahub.media_ai.llm import ClaudeUnavailableError
        import pytest

        monkeypatch.setattr(
            bd,
            "_call_llm",
            lambda ctx: {
                "tone_prose": "not a dict",
                "achievement_priorities": [],
                "type_phrases": None,
                "artefact_voice": "neither",
            },
        )
        p = ClubProfile(
            profile_id="x",
            display_name="X",
            brand_voice_summary="something",
        )
        with pytest.raises(ClaudeUnavailableError):
            bd.derive_operating_profile(p)


# ---------------------------------------------------------------------------
# 2. Lookup helpers
# ---------------------------------------------------------------------------


class TestLookupHelpers:
    def test_tone_descriptor_falls_back_when_no_cache(self):
        p = ClubProfile(profile_id="x", display_name="X")
        assert bd.tone_descriptor_for(p, "warm-club", "DEFAULT") == "DEFAULT"

    def test_tone_descriptor_uses_cache_when_present(self):
        p = ClubProfile(
            profile_id="x",
            display_name="X",
            brand_operating_profile={
                "tone_prose": {"warm-club": "Org-specific warm prose."},
            },
        )
        assert bd.tone_descriptor_for(p, "warm-club", "DEFAULT") == "Org-specific warm prose."
        # Falls back for tones not in the cache
        assert bd.tone_descriptor_for(p, "data-led", "DEFAULT") == "DEFAULT"

    def test_priority_falls_back_to_default(self):
        p = ClubProfile(profile_id="x", display_name="X")
        assert bd.priority_for(p, "pb_confirmed", 1.5) == 1.5

    def test_priority_uses_derived_specific(self):
        p = ClubProfile(
            profile_id="x",
            display_name="X",
            brand_operating_profile={
                "achievement_priorities": {"pb_confirmed": 1.8, "_default": 1.1},
            },
        )
        assert bd.priority_for(p, "pb_confirmed", 1.5) == 1.8
        # Unknown type uses the derived default, not the caller's default
        assert bd.priority_for(p, "unknown_type", 1.5) == 1.1

    def test_priority_caller_default_when_no_derived_default(self):
        p = ClubProfile(
            profile_id="x",
            display_name="X",
            brand_operating_profile={
                "achievement_priorities": {"pb_confirmed": 1.8},
            },
        )
        # No _default in derived dict → fall through to caller default
        assert bd.priority_for(p, "medal_gold", 0.6) == 0.6

    def test_type_phrase_overrides_default(self):
        p = ClubProfile(
            profile_id="x",
            display_name="X",
            brand_operating_profile={
                "type_phrases": {"pb_confirmed": "a brand-new PB"},
            },
        )
        assert bd.type_phrase_for(p, "pb_confirmed", "DEFAULT") == "a brand-new PB"
        assert bd.type_phrase_for(p, "medal_gold", "DEFAULT") == "DEFAULT"

    def test_artefact_intent_overrides_default(self):
        p = ClubProfile(
            profile_id="x",
            display_name="X",
            brand_operating_profile={
                "artefact_voice": {"meet_recap": "Lead with the volunteers."},
            },
        )
        assert bd.artefact_intent_for(p, "meet_recap", "DEFAULT") == "Lead with the volunteers."
        assert bd.artefact_intent_for(p, "coach_quote", "DEFAULT") == "DEFAULT"

    def test_helpers_accept_none_and_dict(self):
        assert bd.tone_descriptor_for(None, "warm-club", "X") == "X"
        assert bd.priority_for(None, "pb_confirmed", 1.2) == 1.2
        assert (
            bd.type_phrase_for(
                {"brand_operating_profile": {"type_phrases": {"pb_confirmed": "Y"}}},
                "pb_confirmed",
                "X",
            )
            == "Y"
        )


# ---------------------------------------------------------------------------
# 3. Resolution at consumer boundaries
# ---------------------------------------------------------------------------


class TestConsumerWiring:
    """The derived cache must reach every consumer the audit named:
    ai_caption tone descriptors, ClubProfile priorities, and the
    narrate achievement kind."""

    def _profile_with_overrides(self) -> ClubProfile:
        return ClubProfile(
            profile_id="x",
            display_name="Test Org",
            achievement_priorities={"pb_confirmed": 1.5, "_default": 1.0},
            brand_operating_profile={
                "tone_prose": {
                    "warm-club": "ORG-SPECIFIC-TONE-PROSE",
                },
                "achievement_priorities": {
                    "pb_confirmed": 1.9,
                    "_default": 1.1,
                },
                "type_phrases": {
                    "pb_confirmed": "ORG-SPECIFIC-PHRASE",
                },
                "artefact_voice": {
                    "meet_recap": "ORG-SPECIFIC-INTENT",
                },
            },
        )

    def test_ai_caption_tone_descriptor_uses_derived(self):
        from mediahub.web.ai_caption import _resolve_tone_descriptor

        p = self._profile_with_overrides()
        assert _resolve_tone_descriptor(p, "warm-club") == "ORG-SPECIFIC-TONE-PROSE"

    def test_ai_caption_falls_back_to_default_when_no_cache(self):
        from mediahub.web.ai_caption import _resolve_tone_descriptor, _TONE_DESCRIPTORS

        p = ClubProfile(profile_id="x", display_name="X")
        assert _resolve_tone_descriptor(p, "warm-club") == _TONE_DESCRIPTORS["warm-club"]

    def test_club_profile_priority_prefers_derived(self):
        p = self._profile_with_overrides()
        # Derived value 1.9 must beat the legacy 1.5
        assert p.get_achievement_priority("pb_confirmed") == 1.9
        # Unknown type falls through to derived _default
        assert p.get_achievement_priority("unknown_type") == 1.1

    def test_club_profile_priority_legacy_when_no_derived(self):
        p = ClubProfile(
            profile_id="x",
            display_name="X",
            achievement_priorities={"pb_confirmed": 1.5},
        )
        assert p.get_achievement_priority("pb_confirmed") == 1.5

    def test_narrate_uses_derived_phrase(self):
        from mediahub.ai_core.narrate import narrate_achievement

        p = self._profile_with_overrides()
        a = {
            "type": "pb_confirmed",
            "swimmer_name": "Emma",
            "event": "100 Free",
            "time": "58.21",
        }
        with_profile = narrate_achievement(a, profile=p)
        without_profile = narrate_achievement(a)
        assert "ORG-SPECIFIC-PHRASE" in with_profile
        assert "a confirmed personal best" in without_profile

    def test_turn_into_uses_derived_intent(self, monkeypatch):
        """Threading: _gen_caption resolves the artefact intent via the
        profile-derived helper before handing it to the caption LLM."""
        from mediahub.turn_into import templates as ti

        # Stub the caption call so we can inspect the enriched payload.
        captured = {}

        def fake_caption(
            payload, club_brand, tone=None, club_profile=None, brief_prose=None, **_kw
        ):
            captured["payload"] = payload
            captured["club_profile"] = club_profile
            captured["brief_prose"] = brief_prose
            return "stubbed"

        monkeypatch.setattr(
            "mediahub.web.ai_caption.generate_caption_for_tone",
            fake_caption,
        )
        p = self._profile_with_overrides()
        out = ti._gen_caption(
            {"kind": "meet_recap"},
            {},
            tone="warm-club",
            intent_key="meet_recap",
            deterministic=False,
            fallback_text="fb",
            profile=p,
        )
        assert out == "stubbed"
        assert captured["payload"]["_artefact_intent"] == "ORG-SPECIFIC-INTENT"
        assert captured["club_profile"] is p
        # Aggregate "kind" payloads are narrated into a brief so the model
        # actually writes them instead of falling back to a template.
        assert captured["brief_prose"] and "recap" in captured["brief_prose"].lower()


# ---------------------------------------------------------------------------
# 4. End-to-end save path triggers derivation
# ---------------------------------------------------------------------------


class TestSavePathTriggersDerivation:
    def test_setup_capture_writes_operating_profile(
        self,
        app,
        monkeypatch,
    ):
        # Stub the social-DNA so it returns a brand context worth deriving from
        from mediahub.brand import social_dna

        monkeypatch.setattr(
            social_dna,
            "capture_from_socials",
            lambda **kw: {
                "brand_voice_summary": "Inclusive community club.",
                "brand_keywords": ["community", "inclusive"],
                "brand_palette_extracted": {},
                "brand_logo_url": "",
                "brand_typography_hint": "",
                "brand_phrases_to_avoid": [],
                "brand_phrases_to_use": ["Big PB"],
                "brand_source_url": kw.get("website_url", ""),
                "brand_captured_at": "2026-05-17T12:00:00+00:00",
                "brand_capture_status": "ok",
                "voice_profile": {},
                "social_links_status": {"website": "ok"},
                "captions_captured": 0,
            },
        )
        # Stub the derivation LLM call
        from mediahub.brand import derived as bd_mod

        monkeypatch.setattr(
            bd_mod,
            "_call_llm",
            lambda ctx: {
                "tone_prose": {"warm-club": "Like a parent at poolside."},
                "achievement_priorities": {"pb_confirmed": 1.7, "_default": 1.0},
                "type_phrases": {"pb_confirmed": "a brand-new PB"},
                "artefact_voice": {"meet_recap": "Lead with the youngest."},
            },
        )

        app.config["ENFORCE_ORG_GATE"] = True
        c = app.test_client()

        resp = c.post(
            "/organisation/setup/capture",
            data={
                "display_name": "Derive Club",
                "website_url": "https://derive.example",
            },
        )
        assert resp.status_code in (301, 302, 303, 307, 308)

        from mediahub.web.club_profile import list_profiles

        profs = [p for p in list_profiles() if p.display_name == "Derive Club"]
        assert len(profs) == 1
        op = profs[0].brand_operating_profile
        assert op["status"] == "ok"
        assert op["tone_prose"]["warm-club"] == "Like a parent at poolside."
        assert op["achievement_priorities"]["pb_confirmed"] == 1.7
        assert op["type_phrases"]["pb_confirmed"] == "a brand-new PB"
        assert op["artefact_voice"]["meet_recap"] == "Lead with the youngest."
