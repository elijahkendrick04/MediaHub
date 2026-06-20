"""AI font pairing (roadmap 1.9).

The judgement ("which face fits this club") goes through the cloud LLM with an
honest error when no provider is configured; the *options* are bounded by the
deterministic catalogue, so the result is always a renderable, on-brand pairing.
Tests mock the provider so they are deterministic and offline.
"""
from __future__ import annotations

import pytest

from mediahub.brand import type_pairing as tp
from mediahub.media_ai.llm import ClaudeUnavailableError


def _patch_llm(monkeypatch, payload):
    """Make the lazily-imported generate_json return ``payload``."""
    import mediahub.media_ai.llm as llm

    monkeypatch.setattr(llm, "generate_json", lambda *a, **k: payload)


# --------------------------------------------------------------------------- #
# Honest error
# --------------------------------------------------------------------------- #
class TestHonestError:
    def test_no_provider_raises(self, monkeypatch):
        import mediahub.media_ai.llm as llm

        def _boom(*a, **k):
            raise ClaudeUnavailableError("no provider")

        monkeypatch.setattr(llm, "generate_json", _boom)
        with pytest.raises(ClaudeUnavailableError):
            tp.suggest_pairing(tp.PairingContext(club_name="Cardiff"))


# --------------------------------------------------------------------------- #
# Catalogue-bound proposals
# --------------------------------------------------------------------------- #
class TestProposal:
    def test_valid_model_answer_passes_through(self, monkeypatch):
        _patch_llm(
            monkeypatch,
            {"headline": "bebas-neue", "body": "space-grotesk", "numeral": "jetbrains-mono",
             "reason": "Condensed energy with a clean technical body."},
        )
        p = tp.suggest_pairing(tp.PairingContext(mood="bold"))
        assert (p.headline, p.body, p.numeral) == ("bebas-neue", "space-grotesk", "jetbrains-mono")
        assert not p.corrected and p.reason

    def test_invalid_slug_is_corrected_into_catalogue(self, monkeypatch):
        _patch_llm(
            monkeypatch,
            {"headline": "comic-sans", "body": "papyrus", "numeral": "wingdings", "reason": ""},
        )
        p = tp.suggest_pairing(tp.PairingContext())
        assert p.corrected
        # every face is a real catalogue slug with the right role
        assert tp._is_headline(p.headline) and tp._is_body(p.body) and tp._is_numeral(p.numeral)
        assert p.reason  # a reason is always present (synthesised if missing)

    def test_upload_slug_is_never_accepted(self, monkeypatch):
        _patch_llm(monkeypatch, {"headline": "upload:club-700-normal", "body": "inter",
                                 "numeral": "jetbrains-mono", "reason": "x"})
        p = tp.suggest_pairing(tp.PairingContext())
        assert p.headline != "upload:club-700-normal" and p.corrected

    def test_garbage_response_still_renderable(self, monkeypatch):
        _patch_llm(monkeypatch, {"nonsense": True})
        p = tp.suggest_pairing(tp.PairingContext())
        assert tp._is_headline(p.headline) and tp._is_body(p.body) and tp._is_numeral(p.numeral)


# --------------------------------------------------------------------------- #
# Pairing helpers
# --------------------------------------------------------------------------- #
class TestPairing:
    def test_typography_pair_mapping(self):
        assert tp.Pairing("bebas-neue", "inter", "jetbrains-mono", "x").typography_pair() == "bebas-grotesk"
        assert tp.Pairing("bowlby-one", "inter", "jetbrains-mono", "x").typography_pair() == "bowlby-inter"
        assert tp.Pairing("anton", "inter", "jetbrains-mono", "x").typography_pair() == "anton-inter"

    def test_families_are_real_names(self):
        fams = tp.Pairing("anton", "inter", "jetbrains-mono", "x").families()
        assert fams == {
            "headline_family": "Anton",
            "body_family": "Inter",
            "numeral_family": "JetBrains Mono",
        }

    def test_to_dict_shape(self):
        d = tp.Pairing("anton", "inter", "jetbrains-mono", "x").to_dict()
        assert d["typography_pair"] == "anton-inter" and d["families"]["headline_family"] == "Anton"

    def test_catalogue_brief_lists_slugs(self):
        brief = tp._catalogue_brief()
        assert "anton:" in brief and "jetbrains-mono:" in brief and "[good for numbers]" in brief


# --------------------------------------------------------------------------- #
# design_tokens consumer
# --------------------------------------------------------------------------- #
class TestDesignTokensConsumer:
    def test_ai_type_pairing_shape(self, monkeypatch):
        from mediahub.brand import design_tokens as dt

        monkeypatch.setattr(
            tp, "suggest_pairing",
            lambda ctx: tp.Pairing("anton", "inter", "jetbrains-mono", "Clean and bold."),
        )
        out = dt.ai_type_pairing(tp.PairingContext(club_name="X"))
        assert out["pairing"] == "anton-inter"
        assert out["headline_family"] == "Anton" and out["source"] == "ai"
        assert out["reason"] == "Clean and bold."

    def test_ai_type_pairing_propagates_honest_error(self, monkeypatch):
        from mediahub.brand import design_tokens as dt

        def _boom(ctx):
            raise ClaudeUnavailableError("no provider")

        monkeypatch.setattr(tp, "suggest_pairing", _boom)
        with pytest.raises(ClaudeUnavailableError):
            dt.ai_type_pairing(tp.PairingContext())
