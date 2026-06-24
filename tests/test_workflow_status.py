"""Tests for `mediahub.workflow.status` — CardStatus and CardWorkflowState
dataclass serialisation.

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


# ---------------------------------------------------------------------------
# CardWorkflowState defaults
# ---------------------------------------------------------------------------


class TestCardWorkflowStateDefaults:
    def test_minimal_construction(self) -> None:
        s = CardWorkflowState(card_id="card:1")
        assert s.card_id == "card:1"
        assert s.status is CardStatus.QUEUE
        assert s.edited_captions is None
        assert s.notes is None
        assert s.posted_at is None
        assert s.last_changed_at == ""


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

    def test_to_dict_keys_complete(self) -> None:
        d = CardWorkflowState(card_id="x").to_dict()
        expected = {
            "card_id",
            "status",
            "edited_captions",
            "notes",
            "posted_at",
            "last_changed_at",
            "translations",  # 1.24 localisation: per-language variants
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
        )
        loaded = CardWorkflowState.from_dict(original.to_dict())
        assert loaded == original

    def test_unknown_status_falls_back_to_queue(self) -> None:
        loaded = CardWorkflowState.from_dict(
            {"card_id": "x", "status": "abandoned-by-previous-version"}
        )
        assert loaded.status is CardStatus.QUEUE

    def test_missing_card_id_defaults_to_empty_string(self) -> None:
        loaded = CardWorkflowState.from_dict({})
        assert loaded.card_id == ""

    def test_missing_optional_fields_default_to_none(self) -> None:
        loaded = CardWorkflowState.from_dict({"card_id": "x"})
        assert loaded.edited_captions is None
        assert loaded.notes is None
        assert loaded.posted_at is None

    def test_legacy_dict_with_obsolete_fields_loads(self) -> None:
        # Older workflow sidecars may carry fields that have since been removed;
        # from_dict must ignore unknown extras and still load.
        legacy = {
            "card_id": "card:99",
            "status": "approved",
            "edited_captions": None,
            "notes": "old card",
            "posted_at": None,
            "last_changed_at": "2023-01-01T00:00:00Z",
            "some_removed_field": "x",
            "another_old_key": 7,
        }
        loaded = CardWorkflowState.from_dict(legacy)
        assert loaded.card_id == "card:99"
        assert loaded.status is CardStatus.APPROVED


# ---------------------------------------------------------------------------
# Review-progress maths (regression: "3/3 = 100%" false-completion bug)
# ---------------------------------------------------------------------------


class TestReviewProgressCalculation:
    """The progress strip must use len(ranked_achs) as the denominator,
    not the workflow-store total.

    When only 3 of 57 cards have been explicitly saved to the workflow store
    (the 3 that were approved), wf_total == 3. Using `wf_total or n_ranked`
    gives grand_total == 3 and pct == 100 — a false completion signal.
    The fix uses `n_ranked or wf_total` so the pipeline total takes
    precedence.
    """

    def _calc(
        self,
        n_approved: int,
        n_rejected: int,
        wf_n_total: int,
        n_ranked: int,
    ) -> tuple[int, int, int]:
        """Mirror the fixed calculation in web.py review route."""
        decided = (n_approved or 0) + (n_rejected or 0)
        grand_total = n_ranked or wf_n_total or 0
        pct = int(round(100 * decided / grand_total)) if grand_total else 0
        return decided, grand_total, pct

    def test_partial_approval_uses_ranked_total(self) -> None:
        """3 approved out of 57 cards → grand_total is 57, pct ≈ 5."""
        decided, grand_total, pct = self._calc(
            n_approved=3, n_rejected=0, wf_n_total=3, n_ranked=57
        )
        assert decided == 3
        assert grand_total == 57, "grand_total must be len(ranked_achs), not the store total"
        assert pct == 5

    def test_all_cards_approved_reaches_100(self) -> None:
        decided, grand_total, pct = self._calc(
            n_approved=57, n_rejected=0, wf_n_total=57, n_ranked=57
        )
        assert grand_total == 57
        assert pct == 100

    def test_zero_cards_gives_zero_pct(self) -> None:
        decided, grand_total, pct = self._calc(n_approved=0, n_rejected=0, wf_n_total=0, n_ranked=0)
        assert grand_total == 0
        assert pct == 0

    def test_ranked_takes_precedence_over_store_total(self) -> None:
        """Even when wf_n_total > 0, n_ranked must win if both are truthy."""
        _, grand_total, _ = self._calc(n_approved=1, n_rejected=1, wf_n_total=2, n_ranked=100)
        assert grand_total == 100
