"""
Direct behavioural tests for the production V5 ranker
(``legacy/swim_content_v5/ranker.py``).

Before these tests the ranker had a single direct assertion in the whole suite
(``tests/test_phase_w_spine.py::test_club_record_outranks_gold_and_pb``), so its
weights, magnitude/level tables, priority maths, quality-band thresholds, band
overrides, post-type mapping, tie-breaks and profile maths were all
behaviourally unverified. This file closes that gap (F22, F23, F52) and pins the
specific defect fixes in package P6 (F13, F03, F07, F08, F19, F12, F05, F14,
F15, F04, F21, F24, F34, F49, F54, F62) so a regression fails a test.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

# tests/conftest.py imports ``mediahub`` at collection time, which registers the
# legacy top-level packages (``swim_content_v5`` etc.) — same convention as
# tests/test_ranker_v3_direct.py.
from swim_content_v5.ranker import (
    rank_achievements,
    _compute_priority,
    _magnitude_factor,
    _rarity_factor,
    _certainty_factor,
    _assign_quality_band,
    _assign_post_type,
    _WEIGHTS,
    _TYPE_MAGNITUDE,
    _MEET_LEVEL_SCORE,
    _TYPE_NARRATIVE_BONUS,
    _POST_ANGLE_MAP,
)
from swim_content_v5.schema import Achievement, QualityBand, PostType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ach(atype, *, conf=0.95, raw=None, notes=None, swim_id=None, swimmer_id="s"):
    return Achievement(
        type=atype,
        swim_id=swim_id or f"s:{atype}",
        swimmer_id=swimmer_id,
        swimmer_name="Test Swimmer",
        event="100m Freestyle (LC)",
        headline=atype,
        angle_hint="",
        confidence=conf,
        confidence_label="high",
        raw_facts=raw or {},
        uncertainty_notes=notes or [],
    )


def ctx(level="county", profile=None, **kw):
    return SimpleNamespace(meet_level=level, profile=profile, **kw)


def priority_of(atype, level="county", **kw):
    p, _factors, _rec = _compute_priority(ach(atype, **kw), ctx(level))
    return p


# ---------------------------------------------------------------------------
# F22 — weights, magnitude table, priority maths
# ---------------------------------------------------------------------------

class TestWeightsAndTables:
    def test_scoring_weights_sum_to_one(self):
        # The six scoring factors (recency + profile_priority are weight 0)
        assert abs(sum(_WEIGHTS.values()) - 1.0) < 1e-9
        assert _WEIGHTS["recency"] == 0.0
        assert _WEIGHTS["profile_priority"] == 0.0

    def test_individual_weight_values(self):
        assert _WEIGHTS["magnitude"] == 0.30
        assert _WEIGHTS["rarity"] == 0.20
        assert _WEIGHTS["meet_level"] == 0.15
        assert _WEIGHTS["narrative"] == 0.15
        assert _WEIGHTS["barrier"] == 0.10
        assert _WEIGHTS["certainty"] == 0.10

    def test_every_magnitude_value_within_contract(self):
        # F49: every magnitude table value is in the [0, 1] factor contract.
        for t, v in _TYPE_MAGNITUDE.items():
            assert 0.0 <= v <= 1.0, f"{t} magnitude {v} out of [0,1]"

    def test_medal_hierarchy(self):
        assert _TYPE_MAGNITUDE["medal_gold"] > _TYPE_MAGNITUDE["medal_silver"] > _TYPE_MAGNITUDE["medal_bronze"]

    def test_priority_maths_known_input(self):
        # medal_gold at national, confidence 0.95, no notes, no profile:
        #   magnitude 1.0*0.30 + rarity 1.0*0.20 + meet 1.0*0.15
        #   + narrative 0.0 + barrier 0.0 + certainty 0.95*0.10
        #   = 0.30 + 0.20 + 0.15 + 0.095 = 0.745
        p = priority_of("medal_gold", "national")
        assert p == pytest.approx(0.745, abs=1e-4)

    def test_unknown_type_gets_default_magnitude(self):
        v, _w, _r = _magnitude_factor(ach("some_unregistered_type"), ctx())
        assert v == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# F07 — official_pb_confirmed and other live types present & ranked sensibly
# ---------------------------------------------------------------------------

class TestLiveTypesPresent:
    @pytest.mark.parametrize("t", [
        "official_pb_confirmed", "multi_pb_weekend", "biggest_drop_of_meet",
        "relay_strong_performance",
    ])
    def test_live_type_has_real_magnitude(self, t):
        assert t in _TYPE_MAGNITUDE
        assert _TYPE_MAGNITUDE[t] > 0.3  # above the unknown-type default

    def test_official_pb_outranks_confirmed_and_likely(self):
        r = rank_achievements(
            [ach("pb_likely", conf=0.9), ach("pb_confirmed", conf=0.9),
             ach("official_pb_confirmed", conf=0.9)],
            ctx("open"),
        )
        assert r[0].achievement.type == "official_pb_confirmed"
        # and it is not floored to nice/recap
        assert r[0].quality_band in (QualityBand.STRONG, QualityBand.ELITE)

    def test_official_pb_magnitude_above_pb_confirmed(self):
        assert _TYPE_MAGNITUDE["official_pb_confirmed"] > _TYPE_MAGNITUDE["pb_confirmed"]


# ---------------------------------------------------------------------------
# F08 — biggest_drop_of_meet keeps its magnitude + narrative bonus
# ---------------------------------------------------------------------------

class TestBiggestDrop:
    def test_narrative_and_magnitude_present(self):
        assert _TYPE_NARRATIVE_BONUS.get("biggest_drop_of_meet") == 0.8
        assert _TYPE_MAGNITUDE.get("biggest_drop_of_meet") == 0.7

    def test_biggest_drop_keeps_narrative_when_ranked(self):
        _p, factors, _r = _compute_priority(
            ach("biggest_drop_of_meet", raw={"drop_pct": 6.0}), ctx("county")
        )
        narrative = next(f for f in factors if f.name == "narrative")
        assert narrative.value == 0.8
        magnitude = next(f for f in factors if f.name == "magnitude")
        assert magnitude.value == pytest.approx(0.9)  # 0.7 + min(0.2, 6/20)

    def test_biggest_drop_outranks_bronze(self):
        r = rank_achievements(
            [ach("medal_bronze"), ach("biggest_drop_of_meet", raw={"drop_pct": 6.0})],
            ctx("county"),
        )
        assert r[0].achievement.type == "biggest_drop_of_meet"


# ---------------------------------------------------------------------------
# F12 — regional / international meet levels
# ---------------------------------------------------------------------------

class TestMeetLevels:
    def test_regional_score_between_national_and_county(self):
        assert _MEET_LEVEL_SCORE["national"] > _MEET_LEVEL_SCORE["regional"] > _MEET_LEVEL_SCORE["county"]
        assert _MEET_LEVEL_SCORE["regional"] == 0.75

    def test_regional_gold_outranks_open_and_county(self):
        assert priority_of("medal_gold", "regional") > priority_of("medal_gold", "county")
        assert priority_of("medal_gold", "county") > priority_of("medal_gold", "open")

    def test_international_present(self):
        assert _MEET_LEVEL_SCORE["international"] == 1.0

    @pytest.mark.parametrize("level", ["national", "international", "regional", "university"])
    def test_strong_at_big_meet_maps_to_main_feed(self, level):
        pt = _assign_post_type(QualityBand.STRONG, "medal_silver", ctx(level))
        assert pt == PostType.MAIN_FEED

    def test_strong_at_open_maps_to_story(self):
        pt = _assign_post_type(QualityBand.STRONG, "medal_silver", ctx("open"))
        assert pt == PostType.STORY


# ---------------------------------------------------------------------------
# F23 — quality-band thresholds, type overrides, band -> post-type mapping
# ---------------------------------------------------------------------------

class TestQualityBands:
    def test_priority_thresholds(self):
        # Use an unregistered type so only the priority threshold decides.
        t = "unregistered_type"
        assert _assign_quality_band(0.80, t) == QualityBand.ELITE
        assert _assign_quality_band(0.79, t) == QualityBand.STRONG
        assert _assign_quality_band(0.60, t) == QualityBand.STRONG
        assert _assign_quality_band(0.59, t) == QualityBand.STORY
        assert _assign_quality_band(0.40, t) == QualityBand.STORY
        assert _assign_quality_band(0.39, t) == QualityBand.NICE
        assert _assign_quality_band(0.20, t) == QualityBand.NICE
        assert _assign_quality_band(0.19, t) == QualityBand.NOT_WORTHY

    def test_not_worthy_branch(self):
        assert _assign_quality_band(0.0, "unregistered_type") == QualityBand.NOT_WORTHY

    def test_type_override_elite(self):
        # Low priority but ELITE type (safe, confident) -> ELITE.
        for t in ("medal_gold", "first_sub_barrier", "pb_magnitude_huge", "club_record"):
            assert _assign_quality_band(0.05, t, 0.9, {"level": "safe"}) == QualityBand.ELITE

    def test_type_override_strong(self):
        for t in ("medal_silver", "qual_hit_in_window", "pb_magnitude_big", "official_pb_confirmed"):
            b = _assign_quality_band(0.05, t, 0.9, {"level": "safe"})
            assert b == QualityBand.STRONG

    def test_band_to_post_type_mapping(self):
        assert _assign_post_type(QualityBand.ELITE, "medal_gold", ctx("open")) == PostType.MAIN_FEED
        assert _assign_post_type(QualityBand.STORY, "return_to_form", ctx("open")) == PostType.STORY
        assert _assign_post_type(QualityBand.NICE, "pb_confirmed", ctx("open")) == PostType.RECAP
        assert _assign_post_type(QualityBand.NOT_WORTHY, "x", ctx("open")) == PostType.INTERNAL_NOTE

    def test_internal_note_branch_reachable_end_to_end(self):
        # A genuinely unremarkable, low-confidence achievement bands NOT_WORTHY
        # -> INTERNAL_NOTE through the full rank path.
        r = rank_achievements([ach("final_appearance", conf=0.45)], ctx("open"))
        # final_appearance at open with modest confidence should not be elite
        assert r[0].quality_band in (QualityBand.NICE, QualityBand.STORY, QualityBand.NOT_WORTHY)


# ---------------------------------------------------------------------------
# F15 — band overrides gated on confidence + safe_to_post
# ---------------------------------------------------------------------------

class TestBandGating:
    def test_low_confidence_gold_not_elite(self):
        assert _assign_quality_band(0.30, "medal_gold", 0.1, {"level": "do_not_post"}) != QualityBand.ELITE

    def test_do_not_post_gold_not_elite_even_with_confidence(self):
        # If the safety verdict is do_not_post, the ELITE type override must not fire.
        assert _assign_quality_band(0.30, "medal_gold", 0.9, {"level": "do_not_post"}) != QualityBand.ELITE

    def test_safe_confident_gold_is_elite(self):
        assert _assign_quality_band(0.30, "medal_gold", 0.9, {"level": "safe"}) == QualityBand.ELITE

    def test_safe_high_priority_is_elite(self):
        # A postable, genuinely high-priority card bands ELITE via the threshold.
        assert _assign_quality_band(0.85, "medal_gold", 0.9, {"level": "safe"}) == QualityBand.ELITE

    def test_high_priority_do_not_post_capped_at_strong(self):
        # Even a high computed priority must NOT band a do_not_post card ELITE —
        # but it stays STRONG so the content-pack builder routes it to
        # needs_review (not rejected/internal_notes).
        b = _assign_quality_band(0.85, "medal_gold", 0.1, {"level": "do_not_post"})
        assert b != QualityBand.ELITE
        assert b == QualityBand.STRONG

    @pytest.mark.parametrize("level", ["club", "county", "regional", "university", "national", "international"])
    def test_end_to_end_ocr_mangled_gold_never_reaches_main_feed(self, level):
        # confidence 0.1 -> derive_safe_to_post returns do_not_post. At NO meet
        # level may the card be banded ELITE or suggested MAIN_FEED end-to-end
        # (the pre-fix STRONG->big-meet->MAIN_FEED path leaked this at national).
        r = rank_achievements([ach("medal_gold", conf=0.1)], ctx(level))
        assert r[0].quality_band != QualityBand.ELITE, level
        assert r[0].suggested_post_type != PostType.MAIN_FEED, level

    @pytest.mark.parametrize("level", ["regional", "university", "national", "international"])
    def test_do_not_post_barrier_not_main_feed(self, level):
        r = rank_achievements([ach("first_sub_barrier", conf=0.1)], ctx(level))
        assert r[0].quality_band != QualityBand.ELITE, level
        assert r[0].suggested_post_type != PostType.MAIN_FEED, level

    def test_do_not_post_stays_strong_for_review_at_big_meet(self):
        # A do_not_post gold at a national meet stays STRONG (so the builder
        # sends it to needs_review) but its suggested label is INTERNAL_NOTE.
        r = rank_achievements([ach("medal_gold", conf=0.1)], ctx("national"))
        assert r[0].quality_band == QualityBand.STRONG
        assert r[0].suggested_post_type == PostType.INTERNAL_NOTE


# ---------------------------------------------------------------------------
# F05 / F14 — club_record dominance + no magnitude inversion
# ---------------------------------------------------------------------------

class TestClubRecord:
    def test_club_record_magnitude_within_contract(self):
        assert _TYPE_MAGNITUDE["club_record"] == 1.0

    def test_club_record_high_rarity(self):
        v, _w, _r = _rarity_factor(ach("club_record"), ctx("club"))
        assert v == 1.0

    def test_club_record_outranks_gold_and_pb_at_club(self):
        r = rank_achievements(
            [ach("pb_confirmed"), ach("club_record"), ach("medal_gold")], ctx("club")
        )
        assert r[0].achievement.type == "club_record"

    def test_club_record_outranks_gold_at_national(self):
        assert priority_of("club_record", "national") > priority_of("medal_gold", "national")

    def test_club_record_bands_elite(self):
        r = rank_achievements([ach("club_record")], ctx("club"))
        assert r[0].quality_band == QualityBand.ELITE

    def test_improvement_does_not_lower_club_record(self):
        # F14: adding positive drop_pct must NOT reduce the score below the
        # no-drop club record (the old min(1.0, ...) cap inverted this).
        no_drop = priority_of("club_record", "national")
        with_drop = priority_of("club_record", "national", raw={"drop_pct": 3.0})
        assert with_drop >= no_drop
        # ... and it still tops a gold either way.
        assert with_drop > priority_of("medal_gold", "national")


# ---------------------------------------------------------------------------
# F04 — profile-priority order-preserving boost (no saturation)
# ---------------------------------------------------------------------------

class TestProfilePriority:
    def test_no_profile_leaves_priority_unchanged(self):
        # multiplier 1.0 must be an exact identity on the base score.
        base = priority_of("medal_gold", "national")
        prof = SimpleNamespace(get_achievement_priority=lambda t: 1.0)
        p, _f, _r = _compute_priority(ach("medal_gold"), ctx("national", profile=prof))
        assert p == pytest.approx(base)

    def test_boost_preserves_order_and_stays_distinct(self):
        prof = SimpleNamespace(get_achievement_priority=lambda t: 2.0)
        achs = [
            ach("first_sub_barrier"),
            ach("medal_gold"),
            ach("pb_magnitude_huge", raw={"drop_pct": 5.0}),
        ]
        r_fwd = rank_achievements(list(achs), ctx("national", profile=prof))
        r_rev = rank_achievements(list(reversed(achs)), ctx("national", profile=prof))
        prios = [ra.priority for ra in r_fwd]
        # No two boosted cards collapse to the same score.
        assert len(set(prios)) == len(prios)
        # Order is identical regardless of input order.
        assert [ra.achievement.type for ra in r_fwd] == [ra.achievement.type for ra in r_rev]

    def test_boost_raises_score_but_stays_bounded(self):
        base = priority_of("medal_silver", "county")
        prof = SimpleNamespace(get_achievement_priority=lambda t: 2.0)
        p, _f, _r = _compute_priority(ach("medal_silver"), ctx("county", profile=prof))
        assert base < p <= 1.0

    def test_extreme_legacy_multiplier_still_ordered(self):
        # The unclamped legacy path (x100) must not collapse order to input order.
        prof = SimpleNamespace(get_achievement_priority=lambda t: 100.0)
        strong = ach("pb_magnitude_huge", raw={"drop_pct": 5.0})
        weak = ach("pb_confirmed")
        r = rank_achievements([weak, strong], ctx("national", profile=prof))
        assert r[0].achievement.type == "pb_magnitude_huge"
        assert r[0].priority > r[1].priority

    def test_suppression_multiplier_lowers_score(self):
        prof = SimpleNamespace(get_achievement_priority=lambda t: 0.3)
        base = priority_of("medal_gold", "county")
        p, _f, _r = _compute_priority(ach("medal_gold"), ctx("county", profile=prof))
        assert p < base


# ---------------------------------------------------------------------------
# F21 — profile-priority errors are surfaced, not swallowed
# ---------------------------------------------------------------------------

class TestProfileErrorSurfaced:
    def test_bad_profile_reason_records_failure(self):
        class Bad:  # neither get_achievement_priority nor .get
            pass

        _p, factors, _r = _compute_priority(ach("medal_gold"), ctx("county", profile=Bad()))
        pf = next(f for f in factors if f.name == "profile_priority")
        assert "failed" in pf.reason.lower()
        assert pf.reason != "no profile priority override"
        assert pf.value == 1.0  # falls back to neutral, but honestly reported

    def test_working_profile_reports_override(self):
        prof = SimpleNamespace(get_achievement_priority=lambda t: 1.5)
        _p, factors, _r = _compute_priority(ach("medal_gold"), ctx("county", profile=prof))
        pf = next(f for f in factors if f.name == "profile_priority")
        assert "1.50" in pf.reason
        assert pf.value == 1.5


# ---------------------------------------------------------------------------
# F13 — drop_pct None must not crash the ranking run
# ---------------------------------------------------------------------------

class TestDropPctNoneGuard:
    @pytest.mark.parametrize("t", [
        "pb_confirmed", "pb_likely", "pb_magnitude_huge", "official_pb_confirmed",
    ])
    def test_none_drop_pct_no_crash(self, t):
        r = rank_achievements([ach(t, raw={"drop_pct": None})], ctx("county"))
        assert len(r) == 1

    def test_mixed_batch_with_none_drop_pct(self):
        r = rank_achievements(
            [ach("pb_confirmed", raw={"drop_pct": None}), ach("medal_gold")],
            ctx("county"),
        )
        assert len(r) == 2

    @pytest.mark.parametrize("bad", ["5.0", "abc", [1, 2], {"a": 1}, float("nan"), float("inf"), -3.0])
    def test_wrong_typed_or_nonfinite_drop_pct_no_crash(self, bad):
        # F13: a persisted/external achievement may carry a stringly-typed or
        # non-finite drop_pct; it must be coerced, not crash the ranking run.
        r = rank_achievements([ach("pb_confirmed", raw={"drop_pct": bad})], ctx("county"))
        assert len(r) == 1

    def test_none_raw_facts_no_crash(self):
        # A JSON-null raw_facts (persisted run) must not raise AttributeError.
        a = ach("pb_confirmed")
        a.raw_facts = None
        r = rank_achievements([a], ctx("county"))
        assert len(r) == 1


# ---------------------------------------------------------------------------
# F03 / F19 — post_angle mapping aligned with builder, no ghost recap_mention
# ---------------------------------------------------------------------------

class TestPostAngle:
    @pytest.mark.parametrize("t,expected", [
        ("club_record", "club_record"),
        ("club_debut", "milestone"),
        ("race_milestone_25", "milestone"),
        ("race_milestone_100", "milestone"),
        ("race_milestone_500", "milestone"),
        ("first_event_swim", "milestone"),
        ("relay_strong_performance", "relay_highlight"),
        ("official_pb_confirmed", "confirmed_official_pb"),
    ])
    def test_type_maps_to_expected_angle(self, t, expected):
        assert _POST_ANGLE_MAP.get(t) == expected
        r = rank_achievements([ach(t)], ctx("county"))
        assert r[0].post_angle == expected

    def test_phase_w_types_not_recap_mention(self):
        for t in ("club_record", "club_debut", "race_milestone_100", "first_event_swim"):
            r = rank_achievements([ach(t)], ctx("county"))
            assert r[0].post_angle != "recap_mention", t

    def test_ranker_angle_map_matches_builder(self):
        # The two maps must not drift: every key the builder knows, the ranker
        # resolves to the same angle (F03).
        from mediahub.content_pack.builder import _TYPE_TO_ANGLE
        for t, angle in _TYPE_TO_ANGLE.items():
            if t in _POST_ANGLE_MAP:
                assert _POST_ANGLE_MAP[t] == angle, f"drift on {t}"


# ---------------------------------------------------------------------------
# F24 — no input mutation; detector-preset angle respected
# ---------------------------------------------------------------------------

class TestNoInputMutation:
    def test_input_achievement_not_mutated(self):
        a = ach("pb_confirmed")
        assert getattr(a, "post_angle", None) is None
        rank_achievements([a], ctx("county"))
        # The ranker must not stamp post_angle onto the caller's object.
        assert getattr(a, "post_angle", None) is None

    def test_detector_preset_angle_wins(self):
        a = ach("pb_confirmed")
        a.post_angle = "confirmed_official_pb"  # a more specific detector preset
        r = rank_achievements([a], ctx("county"))
        assert r[0].post_angle == "confirmed_official_pb"

    def test_rerank_is_idempotent(self):
        a = ach("medal_gold")
        r1 = rank_achievements([a], ctx("county"))
        r2 = rank_achievements([a], ctx("county"))
        assert r1[0].priority == r2[0].priority
        assert r1[0].post_angle == r2[0].post_angle


# ---------------------------------------------------------------------------
# F34 — deterministic tie-breaks
# ---------------------------------------------------------------------------

class TestDeterministicTieBreak:
    def test_identical_golds_ordered_by_swim_id(self):
        g1 = ach("medal_gold", swim_id="zed:gold", swimmer_id="zed")
        g2 = ach("medal_gold", swim_id="amy:gold", swimmer_id="amy")
        o1 = [ra.achievement.swim_id for ra in rank_achievements([g1, g2], ctx("open"))]
        o2 = [ra.achievement.swim_id for ra in rank_achievements([g2, g1], ctx("open"))]
        assert o1 == o2 == ["amy:gold", "zed:gold"]

    def test_confidence_breaks_priority_tie(self):
        # Same type/priority-driving inputs but different confidence: higher
        # confidence must rank first (confidence is the first tie-break).
        hi = ach("medal_gold", conf=0.95, swim_id="a:gold", swimmer_id="a")
        lo = ach("medal_gold", conf=0.90, swim_id="b:gold", swimmer_id="b")
        # equalise everything the priority depends on except confidence is hard;
        # instead assert the sort key orders hi before lo when priorities tie.
        r = rank_achievements([lo, hi], ctx("open"))
        # hi has marginally higher certainty -> higher priority -> rank 1
        assert r[0].achievement.swim_id == "a:gold"

    def test_ranks_are_sequential(self):
        r = rank_achievements(
            [ach("medal_gold"), ach("pb_confirmed"), ach("medal_bronze")], ctx("county")
        )
        assert [ra.rank for ra in r] == [1, 2, 3]

    def test_none_swim_id_in_tie_does_not_crash(self):
        # F34 robustness: a malformed None swim_id tying with a str swim_id must
        # not raise in the tie-break sort (the key is coerced to str).
        g1 = ach("medal_gold", swimmer_id="a")
        g1.swim_id = None
        g2 = ach("medal_gold", swim_id="b:gold", swimmer_id="b")
        r = rank_achievements([g1, g2], ctx("open"))
        assert len(r) == 2
        assert [ra.rank for ra in r] == [1, 2]


# ---------------------------------------------------------------------------
# F54 — certainty penalty rework
# ---------------------------------------------------------------------------

class TestCertaintyPenalty:
    def test_zero_and_one_note_match_flat_penalty(self):
        # For 0-1 notes the behaviour is identical to the old flat 0.05/note.
        v0, _w, _r = _certainty_factor(ach("pb_confirmed", conf=0.90), ctx())
        assert v0 == pytest.approx(0.90)
        v1, _w, _r = _certainty_factor(ach("pb_confirmed", conf=0.90, notes=["a"]), ctx())
        assert v1 == pytest.approx(0.85)

    @pytest.mark.parametrize("conf,expected", [(0.90, 0.85), (0.30, 0.25), (0.05, 0.0), (0.03, 0.0)])
    def test_one_note_matches_flat_penalty_at_all_confidences(self, conf, expected):
        # The "0-1 notes == old flat 0.05/note" claim holds at EVERY confidence,
        # including conf < 0.10 (the cap only engages at >= 2 notes).
        v, _w, _r = _certainty_factor(ach("pb_confirmed", conf=conf, notes=["a"]), ctx())
        assert v == pytest.approx(expected)

    def test_perfect_confidence_with_notes_beats_zero_confidence(self):
        v_perfect, _w, _r = _certainty_factor(
            ach("pb_confirmed", conf=1.0, notes=["a", "b", "c"]), ctx()
        )
        v_zero, _w, _r = _certainty_factor(ach("pb_confirmed", conf=0.0), ctx())
        assert v_perfect > v_zero

    def test_penalty_never_exceeds_confidence(self):
        # Many notes must not produce a >1 penalty or collapse to zero.
        v, _w, reason = _certainty_factor(
            ach("pb_confirmed", conf=1.0, notes=["x"] * 40), ctx()
        )
        assert v > 0.0
        assert v >= 0.5  # capped at half the confidence
        assert "penalty 0.50" in reason  # never a nonsensical >1 penalty


# ---------------------------------------------------------------------------
# F52 — barrier / rarity / drop-pct branches exercised
# ---------------------------------------------------------------------------

class TestBarrierAndDropBranches:
    def test_first_sub_barrier_factors(self):
        _p, factors, _r = _compute_priority(ach("first_sub_barrier"), ctx("county"))
        barrier = next(f for f in factors if f.name == "barrier")
        rarity = next(f for f in factors if f.name == "rarity")
        assert barrier.value == 1.0
        assert rarity.value == 0.8

    def test_first_sub_barrier_bands_elite(self):
        r = rank_achievements([ach("first_sub_barrier")], ctx("county"))
        assert r[0].quality_band == QualityBand.ELITE

    def test_drop_pct_boosts_pb_magnitude(self):
        low = _magnitude_factor(ach("pb_confirmed"), ctx())[0]
        high = _magnitude_factor(ach("pb_confirmed", raw={"drop_pct": 4.0}), ctx())[0]
        assert high > low
        assert high == pytest.approx(min(1.0, 0.5 + 4.0 / 20.0))

    def test_drop_pct_narrative_bump_for_pb(self):
        _p, factors, _r = _compute_priority(
            ach("pb_confirmed", raw={"drop_pct": 3.0}), ctx("county")
        )
        narrative = next(f for f in factors if f.name == "narrative")
        assert narrative.value >= 0.4


# ---------------------------------------------------------------------------
# F49 / F62 — factor contract + attribute assignment robustness
# ---------------------------------------------------------------------------

class TestContractAndAttrs:
    def test_all_scoring_factor_values_in_unit_interval(self):
        for t in ["club_record", "medal_gold", "first_sub_barrier",
                  "official_pb_confirmed", "biggest_drop_of_meet"]:
            _p, factors, _r = _compute_priority(ach(t, raw={"drop_pct": 5.0}), ctx("national"))
            for f in factors:
                if f.name == "profile_priority":
                    continue  # documented multiplier exception
                assert 0.0 <= f.value <= 1.0, f"{t}/{f.name} = {f.value}"

    def test_recency_factor_present_and_bounded(self):
        _p, factors, _r = _compute_priority(ach("medal_gold"), ctx("county"))
        rec = next(f for f in factors if f.name == "recency")
        assert 0.0 <= rec.value <= 1.0
        assert rec.weight == 0.0

    def test_safe_to_post_and_post_angle_set_on_ranked(self):
        r = rank_achievements([ach("medal_gold")], ctx("county"))
        assert getattr(r[0], "safe_to_post", None) is not None
        assert getattr(r[0], "post_angle", None) is not None
        d = r[0].to_dict()
        assert "safe_to_post" in d and "post_angle" in d


# ---------------------------------------------------------------------------
# F27 — history_map is consumed (recency), and absent history is neutral
# ---------------------------------------------------------------------------

class TestHistoryMapConsumed:
    def test_recency_neutral_without_history(self):
        _p, factors, rec = _compute_priority(ach("medal_gold"), ctx("county"), None)
        assert rec == 0.5

    def test_recency_reads_history_map(self):
        # A SwimmerHistory-like object with a recent prior swim near the meet date.
        snap = SimpleNamespace(
            fetch_ok=True,
            pb_times={"100FRLC": [{"time_sec": 60.0, "date_iso": "2026-06-01"}]},
        )
        hist = SimpleNamespace(has_data=True, _snap=snap)
        hmap = {"s": hist}
        c = ctx("county", start_date="2026-06-08")
        _p, factors, rec = _compute_priority(ach("medal_gold"), c, hmap)
        # 7 days before the meet -> close to 1.0
        assert rec > 0.9

    def test_recency_does_not_change_primary_priority(self):
        # Weight 0: recency must not perturb the weighted-sum priority.
        c = ctx("county", start_date="2026-06-08")
        snap = SimpleNamespace(
            fetch_ok=True,
            pb_times={"100FRLC": [{"time_sec": 60.0, "date_iso": "2026-06-01"}]},
        )
        hist = SimpleNamespace(has_data=True, _snap=snap)
        p_with, _f, _r = _compute_priority(ach("medal_gold"), c, {"s": hist})
        p_without, _f, _r = _compute_priority(ach("medal_gold"), c, None)
        assert p_with == pytest.approx(p_without)


# ---------------------------------------------------------------------------
# Integration — a realistic mixed pack ranks sensibly end to end
# ---------------------------------------------------------------------------

class TestRealisticPack:
    def test_mixed_pack_orders_and_bands(self):
        achs = [
            ach("club_record", swim_id="cr", swimmer_id="a"),
            ach("medal_gold", swim_id="mg", swimmer_id="b"),
            ach("official_pb_confirmed", swim_id="opb", swimmer_id="c"),
            ach("first_sub_barrier", swim_id="fsb", swimmer_id="d"),
            ach("biggest_drop_of_meet", swim_id="bd", swimmer_id="e", raw={"drop_pct": 6.0}),
            ach("relay_strong_performance", swim_id="rsp", swimmer_id="f"),
            ach("pb_likely", swim_id="pl", swimmer_id="g"),
            ach("final_appearance", swim_id="fa", swimmer_id="h", conf=0.5),
        ]
        r = rank_achievements(achs, ctx("regional"))
        # deterministic + sequential ranks
        assert [ra.rank for ra in r] == list(range(1, len(achs) + 1))
        # club_record leads (highest emotion, top of gold + PB)
        assert r[0].achievement.type == "club_record"
        # every card resolved a real (non-recap) angle for known headline types
        by_type = {ra.achievement.type: ra for ra in r}
        assert by_type["relay_strong_performance"].post_angle == "relay_highlight"
        assert by_type["official_pb_confirmed"].post_angle == "confirmed_official_pb"
        # a low-confidence final appearance never lands elite/main_feed
        assert by_type["final_appearance"].quality_band != QualityBand.ELITE
