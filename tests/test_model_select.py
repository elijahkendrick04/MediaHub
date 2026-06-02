"""Tests for media_ai.model_select — pure per-content-type model routing.

No network, no env (except the explicit models_from_env cases). Verifies the
deterministic "which model for which surface" policy: hero surfaces earn the
premium model, bulk steps take the cheap one, overrides win, and a half-
configured deployment still resolves something usable.
"""
from __future__ import annotations

from mediahub.media_ai import model_select as ms


def test_hero_type_uses_premium():
    c = ms.select_model("caption", cheap="cheap-m", premium="prem-m")
    assert c.model == "prem-m"
    assert c.premium is True


def test_non_hero_uses_cheap():
    c = ms.select_model("tagging", cheap="cheap-m", premium="prem-m")
    assert c.model == "cheap-m"
    assert c.premium is False


def test_override_beats_default():
    c = ms.select_model(
        "tagging", cheap="cheap-m", premium="prem-m",
        overrides={"tagging": "special-m"},
    )
    assert c.model == "special-m"


def test_hero_falls_back_to_cheap_when_premium_unset():
    c = ms.select_model("caption", cheap="cheap-m", premium=None)
    assert c.model == "cheap-m"
    assert c.premium is False


def test_only_premium_configured_is_premium():
    c = ms.select_model("tagging", cheap=None, premium="prem-m")
    assert c.model == "prem-m"
    assert c.premium is True


def test_unknown_type_defaults_cheap():
    c = ms.select_model("some_random_type", cheap="cheap-m", premium="prem-m")
    assert c.model == "cheap-m"
    assert c.premium is False


def test_empty_when_nothing_configured():
    c = ms.select_model("caption", cheap=None, premium=None)
    assert c.model == ""
    assert c.premium is False


def test_premium_fallback_for_cheap_choice():
    c = ms.select_model("tagging", cheap="cheap-m", premium="prem-m")
    fb = ms.premium_fallback(c, cheap="cheap-m", premium="prem-m")
    assert fb is not None
    assert fb.model == "prem-m"
    assert fb.premium is True


def test_no_premium_fallback_when_already_premium():
    c = ms.select_model("caption", cheap="cheap-m", premium="prem-m")
    assert c.premium is True
    assert ms.premium_fallback(c, cheap="cheap-m", premium="prem-m") is None


def test_no_premium_fallback_when_premium_unset():
    c = ms.select_model("tagging", cheap="cheap-m", premium=None)
    assert ms.premium_fallback(c, cheap="cheap-m", premium=None) is None


def test_no_premium_fallback_when_premium_equals_choice():
    # premium == the model already chosen => nothing distinct to escalate to.
    c = ms.select_model("tagging", cheap="same-m", premium="same-m")
    assert ms.premium_fallback(c, cheap="same-m", premium="same-m") is None


def test_models_from_env(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_LLM_MODEL_CHEAP", "c-model")
    monkeypatch.setenv("MEDIAHUB_LLM_MODEL_PREMIUM", "p-model")
    monkeypatch.setenv(
        "MEDIAHUB_LLM_MODEL_OVERRIDES", "caption=x, spotlight=y ,bad,=z,k="
    )
    cheap, premium, overrides = ms.models_from_env()
    assert cheap == "c-model"
    assert premium == "p-model"
    # Malformed pairs (no '=', empty key, empty value) are dropped.
    assert overrides == {"caption": "x", "spotlight": "y"}


def test_models_from_env_unset(monkeypatch):
    for k in ("MEDIAHUB_LLM_MODEL_CHEAP", "MEDIAHUB_LLM_MODEL_PREMIUM",
              "MEDIAHUB_LLM_MODEL_OVERRIDES"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("mediahub.web.secrets_store.get_secret", lambda k: None)
    cheap, premium, overrides = ms.models_from_env()
    assert cheap is None
    assert premium is None
    assert overrides == {}
