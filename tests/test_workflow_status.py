"""Tests for `mediahub.workflow.status` — CardStatus, ScheduleStatus,
and CardWorkflowState dataclass serialisation.

The workflow status dataclass is persisted to disk as JSON and read
back across deploys. Round-trip stability matters more than feature
coverage; these tests pin the dict shape, enum values, and the
defensive fallbacks for unknown / legacy status strings.
"""
from __future__ import annotations

import pytest

from mediahub.workflow.status import (
    CardStatus,
    CardWorkflowState,
    ScheduleStatus,
)


# ---------------------------------------------------------------------------
# Enum value pinning — disk-format stability
# ---------------------------------------------------------------------------


class TestCardStatusValues:
    @pytest.mark.parametrize(
        "member, value",
        [
            (CardStatus.QUEUE, "queue"),
            (CardStatus.APPROVED, "approved"),
            (CardStatus.REJECTED, "rejected"),
            (CardStatus.POSTED, "posted"),
            (CardStatus.EDITED, "edited"),
        ],
    )
    def test_values_match_disk_strings(self, member: CardStatus, value: str) -> None:
        assert member.value == value
        # str subclass — value should equal direct comparison.
        assert member == value

    def test_constructor_accepts_disk_value(self) -> None:
        assert CardStatus("approved") is CardStatus.APPROVED

    def test_unknown_value_raises(self) -> None:
        with pytest.raises(ValueError):
            CardStatus("totally-made-up")


class TestScheduleStatusValues:
    @pytest.mark.parametrize(
        "member, value",
        [
            (ScheduleStatus.QUEUED, "queued"),
            (ScheduleStatus.SCHEDULED, "scheduled"),
            (ScheduleStatus.PUBLISHED, "published"),
            (ScheduleStatus.FAILED, "failed"),
        ],
    )
    def test_values_match_disk_strings(self, member: ScheduleStatus, value: str) -> None:
        assert member.value == value
        assert member == value


# ---------------------------------------------------------------------------
# CardWorkflowState defaults
# ---------------------------------------------------------------------------


class TestCardWorkflowStateDefaults:
    def test_minimal_construction(self) -> None:
        s = CardWorkflowState(card_id="card:1")
        assert s.card_id == "card:1"
        assert s.status is CardStatus.QUEUE
        assert s.schedule_status is ScheduleStatus.QUEUED
        assert s.edited_captions is None
        assert s.notes is None
        assert s.posted_at is None
        assert s.last_changed_at == ""
        assert s.buffer_update_id is None
        assert s.scheduled_at is None
        assert s.schedule_error is None


# ---------------------------------------------------------------------------
# to_dict — JSON-ready output
# ---------------------------------------------------------------------------


class TestToDict:
    def test_status_serialised_as_string_value(self) -> None:
        s = CardWorkflowState(card_id="x", status=CardStatus.APPROVED)
        d = s.to_dict()
        assert d["status"] == "approved"
        # Must be a plain str, not the Enum instance.
        assert type(d["status"]) is str

    def test_schedule_status_serialised_as_string_value(self) -> None:
        s = CardWorkflowState(
            card_id="x",
            schedule_status=ScheduleStatus.SCHEDULED,
        )
        d = s.to_dict()
        assert d["schedule_status"] == "scheduled"
        assert type(d["schedule_status"]) is str

    def test_to_dict_keys_complete(self) -> None:
        d = CardWorkflowState(card_id="x").to_dict()
        expected = {
            "card_id",
            "status",
            "edited_captions",
            "notes",
            "posted_at",
            "last_changed_at",
            "schedule_status",
            "buffer_update_id",
            "scheduled_at",
            "schedule_error",
        }
        assert set(d.keys()) == expected


# ---------------------------------------------------------------------------
# from_dict — disk reload
# ---------------------------------------------------------------------------


class TestFromDict:
    def test_round_trip_minimal(self) -> None:
        original = CardWorkflowState(card_id="card:1")
        loaded = CardWorkflowState.from_dict(original.to_dict())
        assert loaded == original

    def test_round_trip_fully_populated(self) -> None:
        original = CardWorkflowState(
            card_id="card:2",
            status=CardStatus.APPROVED,
            edited_captions={"clean": "edited"},
            notes="committee approved",
            posted_at="2024-05-01T12:00:00Z",
            last_changed_at="2024-04-30T10:00:00Z",
            schedule_status=ScheduleStatus.PUBLISHED,
            buffer_update_id="buf-1",
            scheduled_at="2024-05-01T11:30:00Z",
            schedule_error=None,
        )
        loaded = CardWorkflowState.from_dict(original.to_dict())
        assert loaded == original

    def test_unknown_status_falls_back_to_queue(self) -> None:
        loaded = CardWorkflowState.from_dict(
            {"card_id": "x", "status": "abandoned-by-previous-version"}
        )
        assert loaded.status is CardStatus.QUEUE

    def test_unknown_schedule_status_falls_back_to_queued(self) -> None:
        loaded = CardWorkflowState.from_dict(
            {"card_id": "x", "schedule_status": "gone-fishing"}
        )
        assert loaded.schedule_status is ScheduleStatus.QUEUED

    def test_missing_card_id_defaults_to_empty_string(self) -> None:
        loaded = CardWorkflowState.from_dict({})
        assert loaded.card_id == ""

    def test_missing_optional_fields_default_to_none(self) -> None:
        loaded = CardWorkflowState.from_dict({"card_id": "x"})
        assert loaded.edited_captions is None
        assert loaded.notes is None
        assert loaded.buffer_update_id is None
        assert loaded.posted_at is None
        assert loaded.scheduled_at is None
        assert loaded.schedule_error is None

    def test_legacy_dict_without_schedule_fields_loads(self) -> None:
        # Older workflow sidecars predate the schedule_* fields; they must
        # still load cleanly.
        legacy = {
            "card_id": "card:99",
            "status": "approved",
            "edited_captions": None,
            "notes": "old card",
            "posted_at": None,
            "last_changed_at": "2023-01-01T00:00:00Z",
        }
        loaded = CardWorkflowState.from_dict(legacy)
        assert loaded.card_id == "card:99"
        assert loaded.status is CardStatus.APPROVED
        assert loaded.schedule_status is ScheduleStatus.QUEUED
