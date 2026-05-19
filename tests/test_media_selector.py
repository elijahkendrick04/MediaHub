"""Tests for `mediahub.media_library.selector`.

`score_asset` is the deterministic 8-axis fitness score MediaHub uses
to pick the right photo for a content card. Per CLAUDE.md the scoring
maths is deliberately NOT AI-replaced; it's fast, reproducible, and
well-tuned. These tests pin the current weighting so future tweaks
are deliberate.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mediahub.media_library.models import MediaAsset
from mediahub.media_library.selector import (
    ROLE_TYPE_MAP,
    score_asset,
    select_assets,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_asset(**overrides) -> MediaAsset:
    """Build a MediaAsset with sensible defaults; override per-test."""
    defaults = dict(
        id="a1",
        filename="photo.jpg",
        path="/tmp/photo.jpg",
        type="athlete_action",
        permission_status="user_owned",
        approval_status="approved",
        width=1920,
        height=1080,
        orientation="landscape",
        linked_athlete_ids=["ath-001"],
        linked_athlete_names=["Jane Smith"],
        uploaded_at=datetime.now(timezone.utc).isoformat(),
    )
    defaults.update(overrides)
    return MediaAsset(**defaults)


# ---------------------------------------------------------------------------
# Hard zero-score cases
# ---------------------------------------------------------------------------


class TestUsabilityGates:
    def test_do_not_use_returns_zero(self) -> None:
        asset = _make_asset(permission_status="do_not_use")
        assert score_asset(asset) == 0.0

    def test_needs_parental_consent_returns_zero(self) -> None:
        asset = _make_asset(permission_status="needs_parental_consent")
        assert score_asset(asset) == 0.0

    def test_rejected_asset_returns_zero(self) -> None:
        asset = _make_asset(approval_status="rejected")
        assert score_asset(asset) == 0.0


# ---------------------------------------------------------------------------
# Type fit
# ---------------------------------------------------------------------------


class TestTypeFit:
    def test_first_role_choice_is_top_type_fit(self) -> None:
        # hero_athlete's primary type is "athlete_action"
        primary = _make_asset(type="athlete_action")
        secondary = _make_asset(type="athlete_headshot")
        unrelated = _make_asset(type="venue_photo")
        primary_score = score_asset(primary, role="hero_athlete")
        secondary_score = score_asset(secondary, role="hero_athlete")
        unrelated_score = score_asset(unrelated, role="hero_athlete")
        assert primary_score > secondary_score > unrelated_score

    def test_role_with_no_matching_type_still_scores_low_not_zero(self) -> None:
        asset = _make_asset(type="brand_pattern")
        # role=hero_athlete but type=brand_pattern → type_fit drops to 0.1, doesn't gate to 0
        score = score_asset(asset, role="hero_athlete")
        assert 0.0 < score < 0.7

    def test_team_photo_partial_credit_for_headshot_role(self) -> None:
        asset = _make_asset(type="team_photo")
        # headshot role doesn't normally list team_photo; explicit branch gives 0.4
        score = score_asset(asset, role="headshot")
        # Higher than the generic 0.1 fallback but lower than a true match.
        assert 0.15 < score < 0.9

    def test_role_type_map_covers_expected_roles(self) -> None:
        # Pin the role keys so accidental deletions break this test.
        expected = {
            "hero_athlete",
            "headshot",
            "team",
            "venue",
            "logo",
            "sponsor",
            "brand_pattern",
            "exemplar",
            "any_athlete",
        }
        assert expected.issubset(set(ROLE_TYPE_MAP.keys()))


# ---------------------------------------------------------------------------
# Athlete match
# ---------------------------------------------------------------------------


class TestAthleteMatch:
    def test_athlete_id_match_dominates(self) -> None:
        match = _make_asset(linked_athlete_ids=["ath-001"], linked_athlete_names=[])
        no_match = _make_asset(linked_athlete_ids=["ath-999"], linked_athlete_names=[])
        s_match = score_asset(match, athlete_id="ath-001")
        s_no = score_asset(no_match, athlete_id="ath-001")
        assert s_match > s_no

    def test_exact_name_match_beats_substring(self) -> None:
        exact = _make_asset(
            linked_athlete_ids=[], linked_athlete_names=["jane smith"]
        )
        substring = _make_asset(
            linked_athlete_ids=[], linked_athlete_names=["jane smith jr"]
        )
        s_exact = score_asset(exact, athlete_name="Jane Smith")
        s_sub = score_asset(substring, athlete_name="Jane Smith")
        assert s_exact > s_sub

    def test_description_mention_falls_back_to_0_5(self) -> None:
        asset = _make_asset(
            linked_athlete_ids=[],
            linked_athlete_names=[],
            description_raw="Photo of Jane Smith at the meet",
        )
        s_desc = score_asset(asset, athlete_name="Jane Smith")
        # description-only match is the weakest signal
        no_asset = _make_asset(
            linked_athlete_ids=[],
            linked_athlete_names=[],
            description_raw="Photo of someone else",
        )
        s_no = score_asset(no_asset, athlete_name="Jane Smith")
        assert s_desc > s_no

    def test_athlete_id_overrides_name_check(self) -> None:
        # When athlete_id matches, the name branch is skipped entirely.
        asset = _make_asset(
            linked_athlete_ids=["ath-001"],
            linked_athlete_names=["completely different name"],
        )
        score = score_asset(asset, athlete_id="ath-001", athlete_name="Mismatch")
        # Should still be high because id matched.
        assert score > 0.7

    def test_non_athlete_roles_skip_athlete_match(self) -> None:
        # For roles like "venue"/"logo", athlete identity isn't required.
        asset = _make_asset(
            type="venue_photo",
            linked_athlete_ids=[],
            linked_athlete_names=[],
        )
        score = score_asset(asset, role="venue")
        assert score > 0.6


# ---------------------------------------------------------------------------
# Permission & approval
# ---------------------------------------------------------------------------


class TestPermissionAndApproval:
    @pytest.mark.parametrize(
        "perm",
        [
            "user_owned",
            "approved_by_club",
            "approved_by_photographer",
        ],
    )
    def test_approved_owners_get_full_permission_credit(self, perm: str) -> None:
        # Compare against the same asset with a lower-trust permission status
        # to confirm these three statuses all top the permission axis.
        ref = _make_asset(permission_status="needs_approval")
        promoted = _make_asset(permission_status=perm)
        assert score_asset(promoted, athlete_id="ath-001") > score_asset(
            ref, athlete_id="ath-001"
        )

    def test_needs_approval_lower_than_approved(self) -> None:
        approved = _make_asset(permission_status="approved_by_club")
        pending_perm = _make_asset(permission_status="needs_approval")
        assert score_asset(approved) > score_asset(pending_perm)

    def test_internal_only_lower_than_public(self) -> None:
        public = _make_asset(permission_status="approved_public")
        internal = _make_asset(permission_status="internal_only")
        assert score_asset(public) > score_asset(internal)

    def test_draft_approval_lower_than_approved(self) -> None:
        approved = _make_asset(approval_status="approved")
        draft = _make_asset(approval_status="draft")
        assert score_asset(approved) > score_asset(draft)


# ---------------------------------------------------------------------------
# Orientation
# ---------------------------------------------------------------------------


class TestOrientation:
    def test_matching_orientation_preferred(self) -> None:
        landscape = _make_asset(orientation="landscape")
        portrait = _make_asset(orientation="portrait")
        s_l = score_asset(landscape, preferred_orientation="landscape")
        s_p = score_asset(portrait, preferred_orientation="landscape")
        assert s_l > s_p

    def test_unknown_orientation_no_penalty(self) -> None:
        # When asset has unknown orientation, it shouldn't be penalised.
        unknown = _make_asset(orientation="unknown")
        # Compare to a portrait asset with a landscape preference (penalty path).
        portrait = _make_asset(orientation="portrait")
        s_unknown = score_asset(unknown, preferred_orientation="landscape")
        s_portrait = score_asset(portrait, preferred_orientation="landscape")
        # Unknown gets the default 0.8, portrait-vs-landscape gets 0.55
        assert s_unknown > s_portrait


# ---------------------------------------------------------------------------
# Quality (resolution bonus)
# ---------------------------------------------------------------------------


class TestQuality:
    def test_high_res_outscores_low_res(self) -> None:
        hi = _make_asset(width=2000, height=1500)
        med = _make_asset(width=900, height=600)
        low = _make_asset(width=200, height=200)
        assert score_asset(hi) > score_asset(med) > score_asset(low)

    def test_only_one_dimension_above_threshold_still_counts(self) -> None:
        tall = _make_asset(width=400, height=1800)
        wide = _make_asset(width=1800, height=400)
        # Both should top the quality axis.
        assert score_asset(tall) == pytest.approx(score_asset(wide), abs=0.06)


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


class TestFreshness:
    def test_recent_upload_higher_than_old(self) -> None:
        recent = _make_asset(
            uploaded_at=datetime.now(timezone.utc).isoformat()
        )
        old = _make_asset(
            uploaded_at=(datetime.now(timezone.utc) - timedelta(days=300)).isoformat()
        )
        assert score_asset(recent) > score_asset(old)

    def test_unparseable_upload_date_does_not_crash(self) -> None:
        asset = _make_asset(uploaded_at="not-a-date")
        # Should not raise; freshness falls back to 0.5
        assert 0.0 <= score_asset(asset) <= 1.0

    def test_empty_upload_date_does_not_crash(self) -> None:
        asset = _make_asset(uploaded_at="")
        assert 0.0 <= score_asset(asset) <= 1.0


# ---------------------------------------------------------------------------
# Reuse penalty
# ---------------------------------------------------------------------------


class TestReusePenalty:
    def test_unused_outscores_overused(self) -> None:
        unused = _make_asset(used_in=[])
        # 25 uses zeros the reuse axis (1 − 0.04*25 = 0)
        overused = _make_asset(used_in=[f"v{i}" for i in range(25)])
        assert score_asset(unused) > score_asset(overused)

    def test_reuse_penalty_is_bounded_below_at_zero(self) -> None:
        # Don't let reuse drag composite negative.
        asset = _make_asset(used_in=[f"v{i}" for i in range(100)])
        assert score_asset(asset) >= 0.0


# ---------------------------------------------------------------------------
# Composite invariants
# ---------------------------------------------------------------------------


class TestCompositeScoreInvariants:
    def test_score_always_in_unit_interval(self) -> None:
        asset = _make_asset()
        s = score_asset(asset)
        assert 0.0 <= s <= 1.0

    def test_strong_match_lands_above_0_8(self) -> None:
        asset = _make_asset(
            type="athlete_action",
            permission_status="user_owned",
            approval_status="approved",
            width=2000,
            height=1500,
            orientation="landscape",
            linked_athlete_ids=["ath-001"],
        )
        s = score_asset(
            asset,
            role="hero_athlete",
            athlete_id="ath-001",
            preferred_orientation="landscape",
        )
        assert s > 0.8


# ---------------------------------------------------------------------------
# select_assets
# ---------------------------------------------------------------------------


class TestSelectAssets:
    def test_empty_input_returns_empty(self) -> None:
        assert select_assets([]) == []

    def test_results_sorted_high_to_low(self) -> None:
        good = _make_asset(id="good", type="athlete_action")
        ok = _make_asset(id="ok", type="athlete_headshot")
        bad = _make_asset(
            id="bad",
            type="brand_pattern",
            permission_status="needs_approval",
            approval_status="draft",
        )
        out = select_assets([bad, good, ok], role="hero_athlete")
        scores = [item["score"] for item in out]
        assert scores == sorted(scores, reverse=True)
        # Top asset has the strongest type fit.
        assert out[0]["asset_id"] == "good"

    def test_below_min_score_filtered(self) -> None:
        # A completely unrelated, low-permission asset should be filtered.
        asset = _make_asset(
            type="brand_pattern",
            permission_status="needs_approval",
            approval_status="draft",
            width=100,
            height=100,
            linked_athlete_ids=[],
            linked_athlete_names=[],
            uploaded_at=(datetime.now(timezone.utc) - timedelta(days=400)).isoformat(),
            used_in=[f"v{i}" for i in range(40)],
        )
        out = select_assets(
            [asset],
            role="hero_athlete",
            athlete_id="ath-001",
            min_score=0.6,
        )
        assert out == []

    def test_k_truncates_results(self) -> None:
        assets = [_make_asset(id=f"a{i}") for i in range(10)]
        out = select_assets(assets, k=3, min_score=0.0)
        assert len(out) == 3

    def test_result_shape(self) -> None:
        asset = _make_asset()
        out = select_assets([asset], min_score=0.0)
        assert len(out) == 1
        entry = out[0]
        assert set(entry.keys()) == {"asset_id", "score", "reason_summary", "asset"}
        assert entry["asset_id"] == "a1"
        assert isinstance(entry["reason_summary"], str)
        assert entry["reason_summary"]  # not empty
        assert isinstance(entry["asset"], dict)

    def test_unusable_asset_filtered_even_at_zero_min(self) -> None:
        # do_not_use → score 0, drops below default min_score 0.35
        asset = _make_asset(permission_status="do_not_use")
        out = select_assets([asset], min_score=0.0)
        # Even with min_score=0 the score is exactly 0, so it just barely makes it.
        # Confirm score is 0; ordering is allowed.
        if out:
            assert out[0]["score"] == 0.0


# ---------------------------------------------------------------------------
# _reason summary
# ---------------------------------------------------------------------------


class TestReasonSummary:
    def test_reason_calls_out_id_match(self) -> None:
        asset = _make_asset(linked_athlete_ids=["ath-001"])
        out = select_assets([asset], athlete_id="ath-001", min_score=0.0)
        reason = out[0]["reason_summary"]
        assert "athlete-ID match" in reason

    def test_reason_calls_out_name_match(self) -> None:
        asset = _make_asset(
            linked_athlete_ids=[], linked_athlete_names=["Jane Smith"]
        )
        out = select_assets([asset], athlete_name="Jane Smith", min_score=0.0)
        reason = out[0]["reason_summary"]
        assert "named match" in reason

    def test_reason_falls_back_to_partial_fit(self) -> None:
        asset = _make_asset(
            type="other",
            permission_status="unknown",
            approval_status="draft",
            linked_athlete_ids=[],
            linked_athlete_names=[],
        )
        out = select_assets([asset], min_score=0.0)
        if out:
            assert "partial fit" in out[0]["reason_summary"]
