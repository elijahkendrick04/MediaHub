"""Tests for `mediahub.recognition.registry` — the sport registry.

The registry holds the active set of registered sports (swim/etc.)
and their detector + history-provider stacks. It uses a module-level
dict so tests must isolate their writes.
"""
from __future__ import annotations

import pytest

from mediahub.recognition import registry as registry_module
from mediahub.recognition.registry import (
    SportConfig,
    get_sport,
    list_sports,
    register_sport,
)


@pytest.fixture(autouse=True)
def isolate_sport_registry():
    """Snapshot the module-level _SPORTS dict and restore after each test."""
    saved = dict(registry_module._SPORTS)
    yield
    registry_module._SPORTS.clear()
    registry_module._SPORTS.update(saved)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegisterSport:
    def test_basic_registration(self) -> None:
        register_sport("rowing", display_name="Rowing")
        cfg = get_sport("rowing")
        assert cfg is not None
        assert cfg.sport == "rowing"
        assert cfg.display_name == "Rowing"

    def test_default_display_name_is_titlecased_sport(self) -> None:
        register_sport("trampolining")
        cfg = get_sport("trampolining")
        assert cfg.display_name == "Trampolining"

    def test_default_detectors_empty(self) -> None:
        register_sport("cycling")
        cfg = get_sport("cycling")
        assert cfg.detectors == []

    def test_detectors_recorded(self) -> None:
        sentinel = [object(), object()]
        register_sport("rowing", detectors=sentinel)
        cfg = get_sport("rowing")
        assert cfg.detectors == sentinel

    def test_history_provider_recorded(self) -> None:
        provider = object()
        register_sport("rowing", history_provider=provider)
        cfg = get_sport("rowing")
        assert cfg.history_provider is provider

    def test_voice_templates_default_empty_dict(self) -> None:
        register_sport("rowing")
        cfg = get_sport("rowing")
        assert cfg.default_voice_templates == {}

    def test_voice_templates_recorded(self) -> None:
        templates = {"pb": "Strong row from {name}!"}
        register_sport("rowing", default_voice_templates=templates)
        assert get_sport("rowing").default_voice_templates == templates

    def test_re_registration_overwrites(self) -> None:
        register_sport("rowing", display_name="First")
        register_sport("rowing", display_name="Second")
        assert get_sport("rowing").display_name == "Second"


# ---------------------------------------------------------------------------
# get_sport
# ---------------------------------------------------------------------------


class TestGetSport:
    def test_unknown_returns_none(self) -> None:
        assert get_sport("nonexistent-sport") is None

    def test_get_returns_sport_config_instance(self) -> None:
        register_sport("rowing")
        assert isinstance(get_sport("rowing"), SportConfig)


# ---------------------------------------------------------------------------
# list_sports
# ---------------------------------------------------------------------------


class TestListSports:
    def test_returns_sorted(self) -> None:
        # Clear and add deliberately in non-sorted order.
        registry_module._SPORTS.clear()
        register_sport("rowing")
        register_sport("athletics")
        register_sport("swimming")
        assert list_sports() == ["athletics", "rowing", "swimming"]

    def test_returns_empty_when_nothing_registered(self) -> None:
        registry_module._SPORTS.clear()
        assert list_sports() == []

    def test_includes_all_keys(self) -> None:
        registry_module._SPORTS.clear()
        register_sport("a")
        register_sport("b")
        register_sport("c")
        assert set(list_sports()) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# SportConfig dataclass
# ---------------------------------------------------------------------------


class TestSportConfigDataclass:
    def test_can_be_constructed_directly(self) -> None:
        cfg = SportConfig(
            sport="rowing",
            display_name="Rowing",
            detectors=[],
        )
        assert cfg.sport == "rowing"
        assert cfg.history_provider is None
        assert cfg.default_voice_templates == {}

    def test_default_voice_templates_independent_per_instance(self) -> None:
        a = SportConfig(sport="a", display_name="A", detectors=[])
        b = SportConfig(sport="b", display_name="B", detectors=[])
        a.default_voice_templates["key"] = "val"
        assert b.default_voice_templates == {}
