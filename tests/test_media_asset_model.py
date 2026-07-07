"""Tests for `mediahub.media_library.models.MediaAsset`.

MediaAsset.from_dict is the deserialisation seam for assets loaded
back from the JSON sidecar (and from SQLite rows that store list /
dict fields as JSON strings). It tolerates partial dicts, legacy
formats, and string-encoded lists; these tests pin those guarantees.
"""
from __future__ import annotations

import json

import pytest

from mediahub.media_library.models import (
    APPROVAL_STATUSES,
    ASSET_TYPES,
    LEGACY_TYPE_ALIASES,
    ORIENTATIONS,
    PERMISSION_STATUSES,
    MediaAsset,
    canonical_asset_type,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_asset_types_contains_core_types(self) -> None:
        for t in (
            "athlete_headshot",
            "athlete_action",
            "team_photo",
            "venue_photo",
            "logo",
            "sponsor_logo",
        ):
            assert t in ASSET_TYPES

    def test_permission_statuses_contains_core_values(self) -> None:
        for p in ("user_owned", "do_not_use", "unknown"):
            assert p in PERMISSION_STATUSES

    def test_approval_statuses(self) -> None:
        assert set(APPROVAL_STATUSES) == {"approved", "draft", "rejected", "pending"}

    def test_orientations(self) -> None:
        assert set(ORIENTATIONS) == {"portrait", "landscape", "square", "unknown"}


# ---------------------------------------------------------------------------
# is_usable_for_post
# ---------------------------------------------------------------------------


class TestIsUsable:
    def test_default_usable(self) -> None:
        a = MediaAsset(id="x", filename="f.jpg", path="/p")
        assert a.is_usable_for_post() is True

    @pytest.mark.parametrize(
        "perm", ["do_not_use", "needs_parental_consent"],
    )
    def test_unusable_permission_blocks(self, perm: str) -> None:
        a = MediaAsset(id="x", filename="f.jpg", path="/p", permission_status=perm)
        assert a.is_usable_for_post() is False

    def test_rejected_approval_blocks(self) -> None:
        a = MediaAsset(
            id="x", filename="f.jpg", path="/p", approval_status="rejected"
        )
        assert a.is_usable_for_post() is False

    def test_draft_is_still_usable(self) -> None:
        a = MediaAsset(
            id="x", filename="f.jpg", path="/p", approval_status="draft"
        )
        # Draft is allowed; only rejected blocks.
        assert a.is_usable_for_post() is True


# ---------------------------------------------------------------------------
# to_dict / from_dict round trips
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_minimal_round_trip(self) -> None:
        original = MediaAsset(id="x", filename="f.jpg", path="/p")
        loaded = MediaAsset.from_dict(original.to_dict())
        assert loaded == original

    def test_fully_populated_round_trip(self) -> None:
        original = MediaAsset(
            id="ast-001",
            filename="jane.jpg",
            path="/data/library/jane.jpg",
            type="athlete_action",
            description_raw="Jane mid-stroke",
            description_parsed={"colours": ["#003366"], "subject": "athlete"},
            linked_athlete_ids=["ath-001"],
            linked_athlete_names=["Jane Smith"],
            linked_meet_ids=["meet-2024"],
            linked_venue="London Aquatics Centre",
            permission_status="user_owned",
            approval_status="approved",
            width=2400,
            height=1600,
            orientation="landscape",
            dominant_colours=["#003366", "#FFFFFF"],
            uploaded_at="2024-04-01T08:00:00Z",
            used_in=["card-1", "card-2"],
            tags=["championship", "freestyle"],
        )
        loaded = MediaAsset.from_dict(original.to_dict())
        assert loaded == original


# ---------------------------------------------------------------------------
# from_dict — defensive parsing
# ---------------------------------------------------------------------------


class TestFromDictDefensive:
    def test_unknown_keys_silently_dropped(self) -> None:
        a = MediaAsset.from_dict({
            "id": "x",
            "filename": "f.jpg",
            "path": "/p",
            "unknown_field": "ignored",
            "another_unknown": 42,
        })
        assert a.id == "x"
        assert not hasattr(a, "unknown_field")

    def test_missing_required_fields_default_to_empty(self) -> None:
        a = MediaAsset.from_dict({})
        # The dataclass requires id/filename/path; from_dict supplies blanks.
        assert a.id == ""
        assert a.filename == ""
        assert a.path == ""

    def test_string_encoded_list_parsed_as_json(self) -> None:
        a = MediaAsset.from_dict({
            "id": "x",
            "filename": "f.jpg",
            "path": "/p",
            "linked_athlete_ids": json.dumps(["a", "b"]),
            "tags": json.dumps(["t1", "t2", "t3"]),
        })
        assert a.linked_athlete_ids == ["a", "b"]
        assert a.tags == ["t1", "t2", "t3"]

    def test_comma_separated_string_falls_back_to_split(self) -> None:
        a = MediaAsset.from_dict({
            "id": "x",
            "filename": "f.jpg",
            "path": "/p",
            "linked_athlete_names": "Jane Smith, John Doe, Eve Adams",
        })
        # Non-JSON string is split by comma.
        assert a.linked_athlete_names == ["Jane Smith", "John Doe", "Eve Adams"]

    def test_empty_string_list_field_becomes_empty_list(self) -> None:
        a = MediaAsset.from_dict({
            "id": "x", "filename": "f.jpg", "path": "/p",
            "linked_athlete_ids": "",
        })
        assert a.linked_athlete_ids == []

    def test_description_parsed_string_decoded_as_json(self) -> None:
        a = MediaAsset.from_dict({
            "id": "x",
            "filename": "f.jpg",
            "path": "/p",
            "description_parsed": json.dumps({"subject": "athlete"}),
        })
        assert a.description_parsed == {"subject": "athlete"}

    def test_description_parsed_empty_string_becomes_empty_dict(self) -> None:
        a = MediaAsset.from_dict({
            "id": "x", "filename": "f.jpg", "path": "/p",
            "description_parsed": "",
        })
        assert a.description_parsed == {}

    def test_description_parsed_malformed_string_falls_back_empty(self) -> None:
        a = MediaAsset.from_dict({
            "id": "x", "filename": "f.jpg", "path": "/p",
            "description_parsed": "not-json-at-all",
        })
        assert a.description_parsed == {}


# ---------------------------------------------------------------------------
# Legacy asset-type aliases (M1) — normalised at deserialise
# ---------------------------------------------------------------------------


class TestLegacyTypeAliases:
    @pytest.mark.parametrize(
        "legacy,canonical",
        [
            ("athlete_photo", "athlete_action"),
            ("venue", "venue_photo"),
            ("podium", "athlete_action"),
            ("team", "team_photo"),
            ("action", "athlete_action"),
        ],
    )
    def test_from_dict_maps_legacy_value(self, legacy: str, canonical: str) -> None:
        a = MediaAsset.from_dict({"id": "x", "filename": "f.jpg", "path": "/p", "type": legacy})
        assert a.type == canonical

    def test_every_alias_targets_a_canonical_type(self) -> None:
        for target in LEGACY_TYPE_ALIASES.values():
            assert target in ASSET_TYPES

    def test_canonical_values_pass_through(self) -> None:
        for t in ASSET_TYPES:
            assert canonical_asset_type(t) == t
            a = MediaAsset.from_dict({"id": "x", "filename": "f", "path": "/p", "type": t})
            assert a.type == t

    def test_unknown_type_kept_as_is(self) -> None:
        # from_dict has always tolerated arbitrary strings; only the known
        # legacy aliases are rewritten.
        a = MediaAsset.from_dict(
            {"id": "x", "filename": "f", "path": "/p", "type": "something_custom"}
        )
        assert a.type == "something_custom"

    def test_missing_type_keeps_default(self) -> None:
        a = MediaAsset.from_dict({"id": "x", "filename": "f", "path": "/p"})
        assert a.type == "other"


# ---------------------------------------------------------------------------
# to_dict shape — JSON-stable surface
# ---------------------------------------------------------------------------


class TestToDictShape:
    def test_to_dict_keys_include_all_dataclass_fields(self) -> None:
        a = MediaAsset(id="x", filename="f.jpg", path="/p")
        d = a.to_dict()
        # A spot of representative fields — pin so a rename doesn't slip through.
        for k in (
            "id",
            "filename",
            "path",
            "type",
            "description_raw",
            "description_parsed",
            "linked_athlete_ids",
            "linked_athlete_names",
            "permission_status",
            "approval_status",
            "width",
            "height",
            "orientation",
            "uploaded_at",
            "used_in",
            "tags",
        ):
            assert k in d, f"missing key {k}"

    def test_to_dict_returns_plain_dict_for_nested_dataclass_free_fields(self) -> None:
        # description_parsed is a dict; to_dict shouldn't introduce dataclass artefacts.
        a = MediaAsset(
            id="x",
            filename="f.jpg",
            path="/p",
            description_parsed={"foo": "bar", "nested": {"k": 1}},
        )
        d = a.to_dict()
        assert isinstance(d["description_parsed"], dict)
        assert d["description_parsed"]["nested"]["k"] == 1
