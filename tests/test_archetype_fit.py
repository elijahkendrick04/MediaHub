"""F4 (systemic floor) — content-fit eligibility in front of the seeded picker.

``archetypes.score_archetype`` / ``eligible_archetypes`` filter the pick pool to
the layouts that can comfortably hold a card's content shape (surname width,
stat count), so hostile content is routed to a fitting archetype BEFORE the
seeded modulo picks within it. The filter is a strict no-op for ordinary content
— every archetype stays eligible, so the pool (and the rendered card) is
byte-identical — and it degrades to the full pool rather than emptying it.
"""

from __future__ import annotations

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate as gen_brief
from mediahub.graphic_renderer import archetypes as A
from mediahub.media_requirements.evaluator import EvaluationResult

ALL = A.list_archetypes()


def _card(surname="Cox", n_stats=0, has_photo=False):
    return {"surname": surname, "n_stats": n_stats, "has_photo": has_photo}


# ---- pure scoring -------------------------------------------------------


def test_ordinary_content_fits_every_archetype():
    card = _card("Hughes", n_stats=1)
    for name in ALL:
        assert A.score_archetype(name, card) >= A.FIT_THRESHOLD, name
    # …so the eligible pool is the whole (sorted) library — byte-identical pick.
    assert A.eligible_archetypes(card) == A.list_archetypes()


def test_long_surname_excludes_tight_archetypes_keeps_bleed():
    card = _card("Vandenberg-Whitmore", n_stats=0)  # 19 chars
    elig = set(A.eligible_archetypes(card))
    # tight, centred heroes are ruled out …
    for tight in ("centered_medal_spotlight", "spotlight_disc", "scoreline_versus"):
        assert tight not in elig, tight
    # … while the big-type / bleed heroes built for long names remain.
    for roomy in ("mega_surname_bleed", "poster_name_behind", "minimal_type_poster"):
        assert roomy in elig, roomy


def test_many_stats_excludes_low_capacity_keeps_stat_forward():
    card = _card("Cox", n_stats=5)
    elig = set(A.eligible_archetypes(card))
    for low in ("big_number_dominant", "mega_surname_bleed", "minimal_type_poster"):
        assert low not in elig, low
    for stat in ("editorial_numbers_grid", "stat_stack_sidebar", "vertical_stat_tower"):
        assert stat in elig, stat


def test_never_returns_empty_for_pathological_content():
    card = _card("Aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", n_stats=99)
    elig = A.eligible_archetypes(card)
    assert elig  # degrades to the full pool rather than nothing
    assert elig == A.list_archetypes()


def test_filter_respects_restricted_pool():
    pool = ["centered_medal_spotlight", "mega_surname_bleed"]
    elig = A.eligible_archetypes(_card("Vandenberg-Whitmore"), pool)
    assert elig == ["mega_surname_bleed"]


def test_kill_switch_disables_filter(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_ARCHETYPE_FIT", "0")
    assert not A.fit_enabled()
    card = _card("Vandenberg-Whitmore", n_stats=9)
    # disabled → the input pool is returned untouched (pure legacy picker).
    assert A.eligible_archetypes(card) == A.list_archetypes()


def test_score_is_deterministic():
    card = _card("Vandenberg-Whitmore", n_stats=3)
    a = [A.score_archetype(n, card) for n in ALL]
    b = [A.score_archetype(n, card) for n in ALL]
    assert a == b


# ---- integration: pick is byte-identical for ordinary content -----------


def _brand():
    return BrandKit(
        profile_id="fit",
        display_name="Riverside Swimming Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="RSC",
    )


def _eval():
    return EvaluationResult(
        content_item_id="ci-1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout="individual_hero",
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label="NEW PB",
        explain="ok",
    )


def _pick(swimmer, seed, monkeypatch, fit="1"):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    monkeypatch.setenv("MEDIAHUB_ARCHETYPE_FIT", fit)
    item = {
        "id": "ci-1",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": swimmer,
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
        },
    }
    b = gen_brief(
        item,
        _eval(),
        _brand(),
        profile_id="fit",
        meet_name="Manchester Open",
        variation_seed=seed,
    )
    return b.layout_template


@pytest.mark.parametrize("seed", [0, 1, 3, 7, 12, 23])
def test_ordinary_pick_byte_identical_fit_on_vs_off(seed, monkeypatch):
    # A short surname with a single hero stat is eligible everywhere, so the
    # seeded pick is identical whether the fit filter is on or off.
    on = _pick("Mia Cox", seed, monkeypatch, fit="1")
    off = _pick("Mia Cox", seed, monkeypatch, fit="0")
    assert on == off


@pytest.mark.parametrize("seed", [0, 1, 3, 7, 12, 23])
def test_hostile_surname_never_lands_on_a_tight_archetype(seed, monkeypatch):
    landed = _pick("Anastasia Vandenberg-Whitmore", seed, monkeypatch, fit="1")
    tight = {"centered_medal_spotlight", "spotlight_disc", "scoreline_versus", "broadcast_scorebug"}
    assert landed not in tight, f"seed {seed} routed a 19-char surname to {landed}"
