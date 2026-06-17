"""Unit tests for the (inert) mediahub.sport_profiles scaffolding.

These assert the typed loader/schema and the AutonomyLevel enum behave, and that
the two shipped YAML profiles (swimming, football) parse and honour the
"gated by default" safety invariant. Nothing here wires the package into runtime.
"""

from __future__ import annotations

import textwrap

import pytest

from mediahub.sport_profiles import (
    AutonomyLevel,
    PostTypeConfig,
    SportProfile,
    list_sport_profiles,
    load_sport_profile,
)


# --- AutonomyLevel ----------------------------------------------------------


def test_autonomy_values_are_bare_strings():
    assert AutonomyLevel.DRAFT_ONLY.value == "draft_only"
    assert AutonomyLevel.APPROVAL_REQUIRED.value == "approval_required"
    # str-backed: usable directly as its string value
    assert AutonomyLevel.APPROVAL_REQUIRED == "approval_required"


def test_autonomy_default_is_gated():
    assert AutonomyLevel.default() is AutonomyLevel.APPROVAL_REQUIRED


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("draft_only", AutonomyLevel.DRAFT_ONLY),
        ("Draft-Only", AutonomyLevel.DRAFT_ONLY),
        ("  APPROVAL REQUIRED ", AutonomyLevel.APPROVAL_REQUIRED),
        ("approval_required", AutonomyLevel.APPROVAL_REQUIRED),
        (AutonomyLevel.DRAFT_ONLY, AutonomyLevel.DRAFT_ONLY),
    ],
)
def test_autonomy_from_str_tolerant(raw, expected):
    assert AutonomyLevel.from_str(raw) is expected


def test_autonomy_from_str_unknown_falls_back_to_gated():
    assert AutonomyLevel.from_str("banana") is AutonomyLevel.APPROVAL_REQUIRED
    assert AutonomyLevel.from_str(None) is AutonomyLevel.APPROVAL_REQUIRED
    assert (
        AutonomyLevel.from_str("banana", default=AutonomyLevel.DRAFT_ONLY)
        is AutonomyLevel.DRAFT_ONLY
    )


# --- PostTypeConfig / SportProfile ------------------------------------------


def test_post_type_config_defaults_to_gated_when_autonomy_absent():
    cfg = PostTypeConfig.from_dict("meet_recap", {"enabled": True})
    assert cfg.default_autonomy is AutonomyLevel.APPROVAL_REQUIRED
    assert cfg.data_inputs == []
    assert cfg.template_namespace == ""


def test_sport_profile_requires_sport():
    with pytest.raises(ValueError):
        SportProfile.from_dict({"display_name": "No Sport"})


def test_engine_sport_defaults_to_sport():
    prof = SportProfile.from_dict({"sport": "swimming"})
    assert prof.engine_sport == "swimming"
    explicit = SportProfile.from_dict({"sport": "football", "engine_sport": "soccer"})
    assert explicit.engine_sport == "soccer"


def test_from_dict_ignores_unknown_keys():
    # Forward/backward compatibility: an unknown top-level key must not break load.
    prof = SportProfile.from_dict({"sport": "swimming", "future_field": {"x": 1}, "post_types": {}})
    assert prof.sport == "swimming"


def test_round_trip_to_from_dict():
    prof = SportProfile.from_dict(
        {
            "sport": "swimming",
            "display_name": "Swimming",
            "post_types": {
                "meet_recap": {
                    "enabled": True,
                    "data_inputs": ["hytek_hy3"],
                    "template_namespace": "swim/meet_recap",
                    "default_autonomy": "approval_required",
                },
                "sponsor_activation": {
                    "enabled": False,
                    "default_autonomy": "draft_only",
                },
            },
        }
    )
    again = SportProfile.from_dict(prof.to_dict())
    assert again == prof
    assert again.post_types["sponsor_activation"].default_autonomy is AutonomyLevel.DRAFT_ONLY


def test_enabled_post_types_excludes_disabled():
    prof = SportProfile.from_dict(
        {
            "sport": "x",
            "post_types": {
                "a": {"enabled": True},
                "b": {"enabled": False},
                "c": {"enabled": True},
            },
        }
    )
    assert prof.enabled_post_types() == ["a", "c"]


def test_autonomy_for_unknown_post_type_is_gated():
    prof = SportProfile.from_dict({"sport": "x", "post_types": {}})
    assert prof.autonomy_for("nonexistent") is AutonomyLevel.APPROVAL_REQUIRED


# --- Loader against the shipped YAML files -----------------------------------


@pytest.mark.parametrize("sport", ["swimming", "football"])
def test_shipped_profiles_load(sport):
    prof = load_sport_profile(sport)
    assert prof.sport == sport
    assert prof.display_name
    assert prof.post_types, "a shipped profile must declare post types"


def test_list_sport_profiles_finds_at_least_two():
    profs = {p.sport for p in list_sport_profiles()}
    assert {"swimming", "football"}.issubset(profs)


def test_shipped_profiles_have_valid_disposition():
    # Every shipped post type carries a real disposition level; the default is
    # approval-required (a human approves before content is used).
    for prof in list_sport_profiles():
        for key, cfg in prof.post_types.items():
            assert isinstance(cfg.default_autonomy, AutonomyLevel)


def test_load_missing_profile_raises():
    with pytest.raises(FileNotFoundError):
        load_sport_profile("quidditch")


def test_loader_respects_base_dir(tmp_path):
    (tmp_path / "tennis.yaml").write_text(
        textwrap.dedent(
            """
            sport: tennis
            display_name: Tennis
            post_types:
              match_recap:
                enabled: true
                default_autonomy: approval_required
            """
        ),
        encoding="utf-8",
    )
    prof = load_sport_profile("tennis", base_dir=tmp_path)
    assert prof.sport == "tennis"
    assert prof.autonomy_for("match_recap") is AutonomyLevel.APPROVAL_REQUIRED


def test_loader_respects_env_override(tmp_path, monkeypatch):
    (tmp_path / "rowing.yaml").write_text(
        "sport: rowing\ndisplay_name: Rowing\npost_types: {}\n", encoding="utf-8"
    )
    monkeypatch.setenv("MEDIAHUB_SPORT_PROFILES_DIR", str(tmp_path))
    assert load_sport_profile("rowing").sport == "rowing"
    assert {p.sport for p in list_sport_profiles()} == {"rowing"}
