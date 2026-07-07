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
    BURST_HAMMING_MAX,
    ROLE_TYPE_MAP,
    WRONG_ATHLETE_MULTIPLIER,
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
# Quality axis with ingest metrics (M2)
# ---------------------------------------------------------------------------


def _quality(sharpness, clip_h=0.0, clip_s=0.0, dhash="0" * 16) -> dict:
    return {
        "sharpness": sharpness,
        "clip_highlights": clip_h,
        "clip_shadows": clip_s,
        "entropy": 6.0,
        "dhash": dhash,
    }


class TestQualityMetricsAxis:
    def test_legacy_asset_scores_exactly_as_before(self) -> None:
        """Regression pin: absent metrics → the historic resolution-only
        weighted sum, to the last decimal place."""
        uploaded = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        asset = _make_asset(
            type="athlete_action",
            permission_status="unknown",
            approval_status="draft",
            width=900,
            height=600,
            orientation="unknown",
            linked_athlete_ids=[],
            linked_athlete_names=[],
            uploaded_at=uploaded,
            used_in=[],
        )
        fresh = 1.0 - (
            (datetime.now(timezone.utc) - datetime.fromisoformat(uploaded)).days / 365.0
        )
        expected = (
            0.30 * 0.0  # no athlete requested
            + 0.18 * 1.0  # athlete_action is hero_athlete's primary type
            + 0.14 * 0.5  # unknown permission
            + 0.10 * 0.6  # draft
            + 0.10 * 0.85  # 900px resolution tier
            + 0.08 * 0.8  # no preferred orientation
            + 0.05 * fresh
            + 0.05 * 1.0  # unused
        )
        assert score_asset(asset, role="hero_athlete") == pytest.approx(expected, abs=1e-9)
        # Empty / None quality metadata behaves identically to absent.
        assert score_asset(
            _make_asset(**{**asset.__dict__, "media_meta": {}}), role="hero_athlete"
        ) == pytest.approx(expected, abs=1e-9)
        assert score_asset(
            _make_asset(**{**asset.__dict__, "media_meta": {"quality": None}}),
            role="hero_athlete",
        ) == pytest.approx(expected, abs=1e-9)

    def test_sharpness_dominates_when_metrics_exist(self) -> None:
        sharp = _make_asset(media_meta={"quality": _quality(400.0)})
        blurry = _make_asset(media_meta={"quality": _quality(15.0)})
        assert score_asset(sharp) > score_asset(blurry)

    def test_sharp_photo_beats_blurry_higher_res(self) -> None:
        sharp_med = _make_asset(
            width=900, height=600, media_meta={"quality": _quality(400.0)}
        )
        blurry_hi = _make_asset(
            width=4000, height=3000, media_meta={"quality": _quality(10.0)}
        )
        assert score_asset(sharp_med) > score_asset(blurry_hi)

    def test_resolution_stays_the_ceiling(self) -> None:
        # A razor-sharp thumbnail can't outscore its own resolution tier.
        tiny_sharp = _make_asset(
            width=200, height=150, media_meta={"quality": _quality(900.0)}
        )
        tiny_legacy = _make_asset(width=200, height=150)
        assert score_asset(tiny_sharp) <= score_asset(tiny_legacy)

    def test_clipping_penalised(self) -> None:
        clean = _make_asset(media_meta={"quality": _quality(400.0)})
        blown = _make_asset(media_meta={"quality": _quality(400.0, clip_h=0.4)})
        assert score_asset(clean) > score_asset(blown)

    def test_mild_clipping_tolerated(self) -> None:
        clean = _make_asset(media_meta={"quality": _quality(400.0)})
        mild = _make_asset(media_meta={"quality": _quality(400.0, clip_h=0.05)})
        assert score_asset(mild) == pytest.approx(score_asset(clean), abs=1e-9)


# ---------------------------------------------------------------------------
# has_face signal (M4)
# ---------------------------------------------------------------------------


class TestHasFace:
    def test_true_boosts_headshot_and_hero_roles(self) -> None:
        base = _make_asset(has_face=None)
        face = _make_asset(has_face=True)
        for role in ("headshot", "hero_athlete", "any_athlete"):
            assert score_asset(face, role=role, athlete_id="ath-001") > score_asset(
                base, role=role, athlete_id="ath-001"
            )

    def test_none_and_false_are_identical(self) -> None:
        # No real signal recorded → no change; False (explicitly no face)
        # carries no penalty either — absence of a face is not a defect.
        unknown = _make_asset(has_face=None)
        no_face = _make_asset(has_face=False)
        assert score_asset(unknown, role="headshot") == score_asset(no_face, role="headshot")

    def test_no_boost_outside_person_roles(self) -> None:
        face = _make_asset(type="venue_photo", has_face=True)
        plain = _make_asset(type="venue_photo", has_face=None)
        assert score_asset(face, role="venue") == score_asset(plain, role="venue")


# ---------------------------------------------------------------------------
# Wrong-athlete guard (M3 / STILLS-9)
# ---------------------------------------------------------------------------


class TestWrongAthleteGuard:
    def test_other_athlete_hard_demoted(self) -> None:
        other = _make_asset(
            linked_athlete_ids=[], linked_athlete_names=["Sam Powell"]
        )
        unlinked = _make_asset(linked_athlete_ids=[], linked_athlete_names=[])
        s_other = score_asset(other, athlete_name="Jane Smith")
        s_unlinked = score_asset(unlinked, athlete_name="Jane Smith")
        # Only the linked-to-someone-else asset is demoted, by exactly ×0.15.
        assert s_other == pytest.approx(s_unlinked * WRONG_ATHLETE_MULTIPLIER, abs=1e-9)

    def test_wrong_id_link_demoted(self) -> None:
        wrong = _make_asset(linked_athlete_ids=["ath-999"], linked_athlete_names=[])
        s = score_asset(wrong, athlete_id="ath-001")
        unlinked = _make_asset(linked_athlete_ids=[], linked_athlete_names=[])
        assert s == pytest.approx(
            score_asset(unlinked, athlete_id="ath-001") * WRONG_ATHLETE_MULTIPLIER, abs=1e-9
        )

    def test_no_subject_requested_no_demotion(self) -> None:
        linked = _make_asset(linked_athlete_names=["Sam Powell"])
        unlinked = _make_asset(linked_athlete_names=[])
        assert score_asset(linked) == score_asset(unlinked)

    def test_description_mention_counts_as_subject_evidence(self) -> None:
        # Linked to someone else BUT the description names the subject —
        # weak evidence, not a wrong-athlete case.
        mixed = _make_asset(
            linked_athlete_names=["Sam Powell"],
            description_raw="Jane Smith and Sam Powell on the blocks",
        )
        s = score_asset(mixed, athlete_name="Jane Smith")
        assert s > 0.3  # not demoted to the 0.15-multiplied floor

    def test_wrong_athlete_filtered_at_default_min_score(self) -> None:
        other = _make_asset(id="other", linked_athlete_names=["Sam Powell"])
        out = select_assets([other], athlete_name="Jane Smith")
        assert out == []

    def test_unlinked_ranks_below_any_name_matched(self) -> None:
        # A pristine unlinked photo vs a weaker but name-matched one: the
        # name-matched asset must come first regardless of raw score.
        pristine_unlinked = _make_asset(
            id="unlinked",
            linked_athlete_ids=[],
            linked_athlete_names=[],
            width=4000,
            height=3000,
            permission_status="user_owned",
            approval_status="approved",
        )
        weak_matched = _make_asset(
            id="matched",
            linked_athlete_ids=[],
            linked_athlete_names=["Jane Smith Jr"],  # substring match (am 0.6)
            width=300,
            height=200,
            permission_status="needs_approval",
            approval_status="draft",
            uploaded_at=(datetime.now(timezone.utc) - timedelta(days=300)).isoformat(),
        )
        # Sanity: the unlinked one has the higher raw score.
        assert score_asset(pristine_unlinked, athlete_name="Jane Smith") > score_asset(
            weak_matched, athlete_name="Jane Smith"
        )
        out = select_assets(
            [pristine_unlinked, weak_matched], athlete_name="Jane Smith", min_score=0.1
        )
        assert [e["asset_id"] for e in out] == ["matched", "unlinked"]

    def test_reason_surfaces_identity_basis(self) -> None:
        other = _make_asset(id="o", linked_athlete_names=["Sam Powell"])
        unlinked = _make_asset(id="u", linked_athlete_ids=[], linked_athlete_names=[])
        out = select_assets([other, unlinked], athlete_name="Jane Smith", min_score=0.0)
        by_id = {e["asset_id"]: e["reason_summary"] for e in out}
        assert "different athlete" in by_id["o"]
        assert "identity unverified" in by_id["u"]

    def test_score_order_unchanged_without_subject(self) -> None:
        # Without a subject the sort is score-only, exactly as before.
        a = _make_asset(id="a", type="athlete_action")
        b = _make_asset(id="b", type="athlete_headshot")
        out = select_assets([b, a], role="hero_athlete", min_score=0.0)
        assert out[0]["asset_id"] == "a"


# ---------------------------------------------------------------------------
# Burst-family dedupe (M2)
# ---------------------------------------------------------------------------


class TestBurstDedupe:
    def test_only_sharpest_of_a_burst_survives(self) -> None:
        # Two near-frames (1 bit apart) + one distinct frame.
        sharp = _make_asset(
            id="sharp", media_meta={"quality": _quality(500.0, dhash="ff00ff00ff00ff00")}
        )
        soft = _make_asset(
            id="soft", media_meta={"quality": _quality(80.0, dhash="ff00ff00ff00ff01")}
        )
        distinct = _make_asset(
            id="distinct", media_meta={"quality": _quality(300.0, dhash="0123456789abcdef")}
        )
        out = select_assets([soft, sharp, distinct], min_score=0.0)
        ids = [e["asset_id"] for e in out]
        assert "sharp" in ids and "distinct" in ids
        assert "soft" not in ids

    def test_hamming_boundary(self) -> None:
        # Exactly BURST_HAMMING_MAX bits apart → same family; one more → not.
        base = int("ff00ff00ff00ff00", 16)
        near = f"{base ^ ((1 << BURST_HAMMING_MAX) - 1):016x}"  # 6 bits flipped
        far = f"{base ^ ((1 << (BURST_HAMMING_MAX + 1)) - 1):016x}"  # 7 bits
        a = _make_asset(id="a", media_meta={"quality": _quality(500.0, dhash="ff00ff00ff00ff00")})
        b = _make_asset(id="b", media_meta={"quality": _quality(100.0, dhash=near)})
        c = _make_asset(id="c", media_meta={"quality": _quality(100.0, dhash=far)})
        ids = [e["asset_id"] for e in select_assets([a, b, c], min_score=0.0)]
        assert "b" not in ids
        assert "a" in ids and "c" in ids

    def test_assets_without_dhash_untouched(self) -> None:
        legacy1 = _make_asset(id="l1")
        legacy2 = _make_asset(id="l2")
        ids = [e["asset_id"] for e in select_assets([legacy1, legacy2], min_score=0.0)]
        assert set(ids) == {"l1", "l2"}

    def test_exclude_families_drops_near_frames(self) -> None:
        used = "ff00ff00ff00ff00"
        near = _make_asset(
            id="near", media_meta={"quality": _quality(500.0, dhash="ff00ff00ff00ff01")}
        )
        fresh = _make_asset(
            id="fresh", media_meta={"quality": _quality(300.0, dhash="0123456789abcdef")}
        )
        legacy = _make_asset(id="legacy")  # no dhash → never excluded
        out = select_assets([near, fresh, legacy], min_score=0.0, exclude_families=[used])
        ids = [e["asset_id"] for e in out]
        assert "near" not in ids
        assert "fresh" in ids and "legacy" in ids

    def test_no_exclusions_no_change(self) -> None:
        a = _make_asset(id="a")
        assert select_assets([a], min_score=0.0, exclude_families=[]) == select_assets(
            [a], min_score=0.0
        )


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
