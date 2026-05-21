"""Tests for the design-spec contract + validator (creative_brief/design_spec.py).

Coverage:
* a valid spec round-trips (and ``normalise`` is idempotent);
* hallucinated / garbage values normalise to safe defaults;
* every enum field is enforced (in-vocab kept, out-of-vocab → default);
* the injected ``archetypes`` / ``token_roles`` vocabularies are honoured;
* the JSON-schema dict mirrors the validator.

No live LLM is involved — this is the pure contract.
"""
from __future__ import annotations

import pytest

from mediahub.creative_brief.design_spec import (
    ACCENT_TREATMENTS,
    COLOUR_ROLE_SLOTS,
    CROP_INTENTS,
    DEFAULT_ACCENT_TREATMENT,
    DEFAULT_CROP_INTENT,
    DEFAULT_FOCAL_ELEMENT,
    DEFAULT_HERO_STAT,
    DEFAULT_LOGO_LOCKUP,
    DEFAULT_MOOD,
    DEFAULT_MOTION_INTENT,
    FOCAL_ELEMENTS,
    LOGO_LOCKUPS,
    MAX_HOOK_LEN,
    MAX_RATIONALE_LEN,
    MAX_SECONDARY_STATS,
    MOODS,
    MOTION_INTENTS,
    STAT_KEYS,
    ColourRoles,
    DesignSpec,
    design_spec_json_schema,
    normalise,
)

# Sample injected vocabularies (the thesis §5.4 archetypes + role names,
# including hyphenated roles to prove arbitrary role spellings are honoured).
ARCHETYPES = [
    "split_diagonal_hero",
    "full_bleed_photo_lower_third",
    "editorial_numbers_grid",
    "centered_medal_spotlight",
    "magazine_cover",
    "big_number_dominant",
    "minimal_type_poster",
]
TOKEN_ROLES = ["brand", "accent", "accent-strong", "surface", "on-surface", "sponsor-safe"]


def _norm(raw):
    return normalise(raw, archetypes=ARCHETYPES, token_roles=TOKEN_ROLES)


# The verbatim design spec from thesis §5.4 — every value is in vocabulary.
VALID_RAW = {
    "archetype": "split_diagonal_hero",
    "colour_roles": {
        "ground": "brand",
        "surface": "on-surface",
        "headline": "surface",
        "accent": "accent-strong",
    },
    "focal_element": "athlete_cutout",
    "crop_intent": "rule_of_thirds_action",
    "hero_stat": "pb_delta",
    "secondary_stats": ["final_time", "event"],
    "headline_hook": "TWO SECONDS FASTER",
    "accent_treatment": "diagonal_underline",
    "logo_lockup": "mono_light",
    "mood": "explosive",
    "motion_intent": "snap_in_then_settle",
    "rationale": "PB delta is the story; action crop + diagonal energy match the swimmer's drive.",
}


# ── Valid spec round-trips ───────────────────────────────────────────────────


def test_valid_spec_preserves_every_field():
    spec = _norm(VALID_RAW)
    assert spec.archetype == "split_diagonal_hero"
    assert spec.colour_roles == ColourRoles(
        ground="brand", surface="on-surface", headline="surface", accent="accent-strong"
    )
    assert spec.focal_element == "athlete_cutout"
    assert spec.crop_intent == "rule_of_thirds_action"
    assert spec.hero_stat == "pb_delta"
    assert spec.secondary_stats == ("final_time", "event")
    assert spec.headline_hook == "TWO SECONDS FASTER"
    assert spec.accent_treatment == "diagonal_underline"
    assert spec.logo_lockup == "mono_light"
    assert spec.mood == "explosive"
    assert spec.motion_intent == "snap_in_then_settle"
    assert spec.rationale.startswith("PB delta is the story")


def test_to_dict_round_trips_and_is_idempotent():
    spec = _norm(VALID_RAW)
    again = _norm(spec.to_dict())
    assert again == spec
    # Idempotent: normalising the already-normalised dict changes nothing.
    assert again.to_dict() == spec.to_dict()


def test_to_dict_is_json_friendly():
    spec = _norm(VALID_RAW)
    d = spec.to_dict()
    assert isinstance(d["colour_roles"], dict)
    assert isinstance(d["secondary_stats"], list)
    assert set(d["colour_roles"]) == set(COLOUR_ROLE_SLOTS)


def test_design_spec_is_frozen():
    spec = _norm(VALID_RAW)
    with pytest.raises(Exception):
        spec.archetype = "magazine_cover"  # type: ignore[misc]


# ── Hallucinated / garbage values normalise to defaults ──────────────────────


GARBAGE_RAW = {
    "archetype": "a hand-painted watercolour of a swimmer at golden hour",
    "colour_roles": {
        "ground": "#FF0000",
        "surface": "chartreuse",
        "headline": 42,
        "accent": "ultraviolet",
    },
    "focal_element": "fire-breathing dragon",
    "crop_intent": "quantum",
    "hero_stat": "vibes",
    "secondary_stats": ["nonsense", "more nonsense", None, 7],
    "headline_hook": {"not": "a string"},
    "accent_treatment": "supernova",
    "logo_lockup": "hologram",
    "mood": "transcendent",
    "motion_intent": "teleport",
    "rationale": ["lists", "are", "not", "prose"],
}


def test_garbage_values_fall_back_to_documented_defaults():
    spec = _norm(GARBAGE_RAW)
    assert spec.archetype == ARCHETYPES[0]
    assert spec.colour_roles == ColourRoles(
        ground=TOKEN_ROLES[0],
        surface=TOKEN_ROLES[0],
        headline=TOKEN_ROLES[0],
        accent=TOKEN_ROLES[0],
    )
    assert spec.focal_element == DEFAULT_FOCAL_ELEMENT
    assert spec.crop_intent == DEFAULT_CROP_INTENT
    assert spec.hero_stat == DEFAULT_HERO_STAT
    assert spec.secondary_stats == ()
    assert spec.headline_hook == ""  # non-string copy → empty
    assert spec.accent_treatment == DEFAULT_ACCENT_TREATMENT
    assert spec.logo_lockup == DEFAULT_LOGO_LOCKUP
    assert spec.mood == DEFAULT_MOOD
    assert spec.motion_intent == DEFAULT_MOTION_INTENT
    assert spec.rationale == ""


def test_empty_dict_yields_all_defaults():
    spec = _norm({})
    assert spec == DesignSpec(
        archetype=ARCHETYPES[0],
        colour_roles=ColourRoles(*[TOKEN_ROLES[0]] * 4),
        focal_element=DEFAULT_FOCAL_ELEMENT,
        crop_intent=DEFAULT_CROP_INTENT,
        hero_stat=DEFAULT_HERO_STAT,
        secondary_stats=(),
        headline_hook="",
        accent_treatment=DEFAULT_ACCENT_TREATMENT,
        logo_lockup=DEFAULT_LOGO_LOCKUP,
        mood=DEFAULT_MOOD,
        motion_intent=DEFAULT_MOTION_INTENT,
        rationale="",
    )


@pytest.mark.parametrize("raw", [None, "garbage", 123, [], ["a", "b"], 3.14, True])
def test_non_dict_raw_yields_all_defaults(raw):
    # A totally malformed model response must still produce a legal spec.
    spec = _norm(raw)
    assert spec == _norm({})


# ── Enums enforced ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "field,vocab,default",
    [
        ("focal_element", FOCAL_ELEMENTS, DEFAULT_FOCAL_ELEMENT),
        ("crop_intent", CROP_INTENTS, DEFAULT_CROP_INTENT),
        ("hero_stat", STAT_KEYS, DEFAULT_HERO_STAT),
        ("accent_treatment", ACCENT_TREATMENTS, DEFAULT_ACCENT_TREATMENT),
        ("logo_lockup", LOGO_LOCKUPS, DEFAULT_LOGO_LOCKUP),
        ("mood", MOODS, DEFAULT_MOOD),
        ("motion_intent", MOTION_INTENTS, DEFAULT_MOTION_INTENT),
    ],
)
def test_each_enum_field_keeps_valid_and_rejects_invalid(field, vocab, default):
    # Every legal value survives unchanged.
    for value in vocab:
        spec = _norm({field: value})
        assert getattr(spec, field) == value
    # An out-of-vocab value collapses to the documented default.
    spec = _norm({field: "definitely-not-in-the-enum"})
    assert getattr(spec, field) == default


def test_archetype_constrained_to_injected_vocab():
    for value in ARCHETYPES:
        assert _norm({"archetype": value}).archetype == value
    assert _norm({"archetype": "imaginary_layout"}).archetype == ARCHETYPES[0]


def test_colour_roles_constrained_to_injected_token_roles():
    for role in TOKEN_ROLES:
        spec = _norm({"colour_roles": {slot: role for slot in COLOUR_ROLE_SLOTS}})
        assert spec.colour_roles.to_dict() == {slot: role for slot in COLOUR_ROLE_SLOTS}


@pytest.mark.parametrize(
    "raw",
    [
        VALID_RAW,
        GARBAGE_RAW,
        {},
        {"hero_stat": "pb_delta", "secondary_stats": ["pb_delta", "final_time"]},
        {"archetype": "  SPLIT_DIAGONAL_HERO  ", "mood": "EXPLOSIVE"},
        {"colour_roles": {"ground": "BRAND"}},
    ],
)
def test_normalised_spec_is_always_in_vocabulary(raw):
    # The core safety invariant: whatever goes in, the output is always legal.
    spec = _norm(raw)
    assert spec.archetype in ARCHETYPES
    for slot in COLOUR_ROLE_SLOTS:
        assert getattr(spec.colour_roles, slot) in TOKEN_ROLES
    assert spec.focal_element in FOCAL_ELEMENTS
    assert spec.crop_intent in CROP_INTENTS
    assert spec.hero_stat in STAT_KEYS
    assert all(s in STAT_KEYS for s in spec.secondary_stats)
    assert spec.accent_treatment in ACCENT_TREATMENTS
    assert spec.logo_lockup in LOGO_LOCKUPS
    assert spec.mood in MOODS
    assert spec.motion_intent in MOTION_INTENTS


def test_all_defaults_are_in_their_vocabularies():
    # Guards against a maintenance typo making a default illegal.
    assert DEFAULT_FOCAL_ELEMENT in FOCAL_ELEMENTS
    assert DEFAULT_CROP_INTENT in CROP_INTENTS
    assert DEFAULT_HERO_STAT in STAT_KEYS
    assert DEFAULT_ACCENT_TREATMENT in ACCENT_TREATMENTS
    assert DEFAULT_LOGO_LOCKUP in LOGO_LOCKUPS
    assert DEFAULT_MOOD in MOODS
    assert DEFAULT_MOTION_INTENT in MOTION_INTENTS


# ── Case-insensitive / forgiving matching ────────────────────────────────────


def test_enum_matching_is_case_and_whitespace_insensitive():
    spec = _norm(
        {
            "archetype": "  Split_Diagonal_Hero ",
            "focal_element": "ATHLETE_CUTOUT",
            "mood": "Explosive",
            "colour_roles": {"ground": "BRAND", "accent": "Accent-Strong"},
            "hero_stat": " PB_DELTA ",
        }
    )
    assert spec.archetype == "split_diagonal_hero"
    assert spec.focal_element == "athlete_cutout"
    assert spec.mood == "explosive"
    assert spec.colour_roles.ground == "brand"
    assert spec.colour_roles.accent == "accent-strong"
    assert spec.hero_stat == "pb_delta"


# ── Colour-role specifics ────────────────────────────────────────────────────


def test_missing_colour_roles_default_to_first_token_role():
    spec = _norm({"archetype": "magazine_cover"})  # no colour_roles key
    assert spec.colour_roles == ColourRoles(*[TOKEN_ROLES[0]] * 4)


def test_partial_colour_roles_fill_only_invalid_slots():
    spec = _norm({"colour_roles": {"ground": "accent", "surface": "#000000"}})
    assert spec.colour_roles.ground == "accent"  # valid → kept
    assert spec.colour_roles.surface == TOKEN_ROLES[0]  # hex → default
    assert spec.colour_roles.headline == TOKEN_ROLES[0]  # missing → default
    assert spec.colour_roles.accent == TOKEN_ROLES[0]  # missing → default


def test_colour_roles_non_dict_defaults_all_slots():
    spec = _norm({"colour_roles": "brand"})
    assert spec.colour_roles == ColourRoles(*[TOKEN_ROLES[0]] * 4)


# ── secondary_stats specifics ────────────────────────────────────────────────


def test_secondary_stats_drop_invalid_dedupe_and_keep_order():
    spec = _norm(
        {
            "hero_stat": "final_time",
            "secondary_stats": ["event", "garbage", "placing", "event", "points"],
        }
    )
    # "garbage" dropped, duplicate "event" dropped, order preserved.
    assert spec.secondary_stats == ("event", "placing", "points")


def test_secondary_stats_exclude_the_hero_stat():
    spec = _norm({"hero_stat": "pb_delta", "secondary_stats": ["pb_delta", "final_time"]})
    assert "pb_delta" not in spec.secondary_stats
    assert spec.secondary_stats == ("final_time",)


def test_secondary_stats_capped_at_max():
    spec = _norm({"hero_stat": "final_time", "secondary_stats": list(STAT_KEYS)})
    assert len(spec.secondary_stats) == MAX_SECONDARY_STATS


def test_secondary_stats_non_list_becomes_empty():
    assert _norm({"secondary_stats": "final_time"}).secondary_stats == ()
    assert _norm({"secondary_stats": None}).secondary_stats == ()
    assert _norm({"secondary_stats": {"a": 1}}).secondary_stats == ()


# ── Free-text fields ─────────────────────────────────────────────────────────


def test_headline_hook_collapsed_to_single_line_and_capped():
    spec = _norm({"headline_hook": "  TWO\n\tSECONDS   FASTER  "})
    assert spec.headline_hook == "TWO SECONDS FASTER"

    long_hook = "WORD " * 40
    capped = _norm({"headline_hook": long_hook}).headline_hook
    assert len(capped) <= MAX_HOOK_LEN
    assert "  " not in capped  # whitespace collapsed
    assert capped == capped.strip()


def test_rationale_stripped_and_capped():
    spec = _norm({"rationale": "  the action crop matches the drive.  "})
    assert spec.rationale == "the action crop matches the drive."

    long_rationale = "x" * (MAX_RATIONALE_LEN + 200)
    assert len(_norm({"rationale": long_rationale}).rationale) == MAX_RATIONALE_LEN


@pytest.mark.parametrize("bad", [None, 42, ["a"], {"k": "v"}, 3.5])
def test_non_string_copy_fields_become_empty(bad):
    spec = _norm({"headline_hook": bad, "rationale": bad})
    assert spec.headline_hook == ""
    assert spec.rationale == ""


# ── Caller-error guards ──────────────────────────────────────────────────────


def test_empty_archetypes_raises():
    with pytest.raises(ValueError):
        normalise({}, archetypes=[], token_roles=TOKEN_ROLES)


def test_empty_token_roles_raises():
    with pytest.raises(ValueError):
        normalise({}, archetypes=ARCHETYPES, token_roles=[])


# ── JSON schema ──────────────────────────────────────────────────────────────


def test_json_schema_mirrors_the_validator():
    schema = design_spec_json_schema(archetypes=ARCHETYPES, token_roles=TOKEN_ROLES)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False

    props = schema["properties"]
    assert props["archetype"]["enum"] == ARCHETYPES
    assert props["focal_element"]["enum"] == list(FOCAL_ELEMENTS)
    assert props["crop_intent"]["enum"] == list(CROP_INTENTS)
    assert props["hero_stat"]["enum"] == list(STAT_KEYS)
    assert props["secondary_stats"]["items"]["enum"] == list(STAT_KEYS)
    assert props["secondary_stats"]["maxItems"] == MAX_SECONDARY_STATS
    assert props["accent_treatment"]["enum"] == list(ACCENT_TREATMENTS)
    assert props["logo_lockup"]["enum"] == list(LOGO_LOCKUPS)
    assert props["mood"]["enum"] == list(MOODS)
    assert props["motion_intent"]["enum"] == list(MOTION_INTENTS)
    assert props["headline_hook"]["maxLength"] == MAX_HOOK_LEN
    assert props["rationale"]["maxLength"] == MAX_RATIONALE_LEN

    # colour_roles is an object whose every slot is an enum over token_roles.
    cr = props["colour_roles"]
    assert cr["additionalProperties"] is False
    assert set(cr["required"]) == set(COLOUR_ROLE_SLOTS)
    for slot in COLOUR_ROLE_SLOTS:
        assert cr["properties"][slot]["enum"] == TOKEN_ROLES

    # Every spec field is required.
    assert set(schema["required"]) == set(props)


def test_json_schema_enum_objects_are_independent():
    # Defensive: the per-slot/per-stat enum dicts must not be shared references
    # (a consumer mutating one must not affect the others).
    schema = design_spec_json_schema(archetypes=ARCHETYPES, token_roles=TOKEN_ROLES)
    cr = schema["properties"]["colour_roles"]["properties"]
    cr["ground"]["enum"].append("MUTATED")
    assert "MUTATED" not in cr["surface"]["enum"]


def test_json_schema_requires_non_empty_vocab():
    with pytest.raises(ValueError):
        design_spec_json_schema(archetypes=[], token_roles=TOKEN_ROLES)
    with pytest.raises(ValueError):
        design_spec_json_schema(archetypes=ARCHETYPES, token_roles=[])
