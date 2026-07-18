"""Direct unit tests for the storyline grouper (``swim_content.grouper``).

``group_claims_into_cards`` turns per-swim ``Claim``s into ``ContentCard``s and
is CLAUDE.md deterministic-engine-adjacent code (it decides which swims become a
spotlight vs. standalone standouts). It previously had no direct test coverage.

These regressions pin two contracts the grouper is responsible for:

  * **F61** — an unknown/raw stroke code (outside the ``FR/BK/BR/FL/IM``
    vocabulary) must not ``KeyError``-crash spotlight headline building; it
    should degrade to its own label the way ``_event_label`` already does.
  * **F28** — the per-swimmer emission contract: a swimmer yields *either* one
    ``athlete_spotlight`` *or* one-per-swim ``standout_swim`` cards, never both.
    Anti-spam is enforced structurally at grouping time, so ``ranker_v3``'s
    spotlight-owner demotion never fires on real grouper output.

The assertions call the real ``group_claims_into_cards`` (and, for the coupling
test, the real ``rank_cards``), not a reimplementation.
"""

from __future__ import annotations

from collections import defaultdict

from swim_content.cards import (
    Claim,
    TYPE_SPOTLIGHT,
    TYPE_STANDOUT,
)
from swim_content.grouper import group_claims_into_cards
from swim_content.ranker_v3 import rank_cards


# --------------------------------------------------------------------------- #
# Builder
# --------------------------------------------------------------------------- #


def _claim(
    kind: str,
    *,
    swimmer: str = "Dana Lee",
    tiref: str | None = "T-DANA",
    stroke: str = "FR",
    distance: int = 100,
    course: str = "LC",
    round_: str = "F",
    place: int | None = None,
    level: str | None = None,
) -> Claim:
    """A fully-populated ``Claim``. ``stroke`` is a stroke *code* (e.g. ``"BK"``),
    matching what the detector feeds the grouper."""
    extra: dict = {}
    if level is not None:
        extra["level"] = level
    if place is None and kind in ("gold", "silver", "bronze"):
        place = {"gold": 1, "silver": 2, "bronze": 3}[kind]
    return Claim(
        kind=kind,
        swimmer_name=swimmer,
        swimmer_tiref=tiref,
        event_label=f"{distance}m {stroke} ({course})",
        distance=distance,
        stroke=stroke,
        course=course,
        time_str="00:58.31",
        time_sec=58.31,
        place=place,
        round=round_,
        swim_date="2026-01-01",
        extra=extra,
    )


def _swimmer_cards(cards, name):
    """Per-swimmer storyline cards (spotlight/standout) for one swimmer."""
    return [
        c
        for c in cards
        if c.card_type in (TYPE_SPOTLIGHT, TYPE_STANDOUT)
        and c.primary_swimmer == name
    ]


# --------------------------------------------------------------------------- #
# F61 — unknown stroke code must not crash spotlight headline building
# --------------------------------------------------------------------------- #


def test_f61_unknown_stroke_double_does_not_crash():
    """A same-stroke gold *double* whose stroke code is outside the 5-code
    vocabulary must build a spotlight rather than raise ``KeyError``."""
    claims = [
        _claim("gold", stroke="Back", distance=100),
        _claim("gold", stroke="Back", distance=200),
    ]
    cards = group_claims_into_cards(claims, meet_name="County Champs")

    spot = _swimmer_cards(cards, "Dana Lee")
    assert len(spot) == 1
    assert spot[0].card_type == TYPE_SPOTLIGHT
    # Unknown code degrades to its own label (matching ``_event_label``'s guard).
    assert spot[0].headline == "Dana Lee doubles up in the back"
    assert spot[0].subhead == "Two golds across the Back events"


def test_f61_unknown_stroke_clean_sweep_does_not_crash():
    """The 3+ gold 'clean sweep' headline branch is also guarded."""
    claims = [
        _claim("gold", stroke="Back", distance=50),
        _claim("gold", stroke="Back", distance=100),
        _claim("gold", stroke="Back", distance=200),
    ]
    cards = group_claims_into_cards(claims, meet_name="County Champs")

    spot = _swimmer_cards(cards, "Dana Lee")
    assert len(spot) == 1
    assert spot[0].card_type == TYPE_SPOTLIGHT
    assert spot[0].headline == "Dana Lee — back clean sweep"
    assert spot[0].subhead == "3 golds in the Back events"


def test_f61_empty_stroke_double_does_not_crash():
    """A degenerate empty-string stroke code is still an 'unknown' code: it must
    degrade to "" rather than crash (an earlier guard converted this into an
    AttributeError on ``None.lower()``)."""
    claims = [
        _claim("gold", stroke="", distance=100),
        _claim("gold", stroke="", distance=200),
    ]
    cards = group_claims_into_cards(claims, meet_name="County Champs")

    spot = _swimmer_cards(cards, "Dana Lee")
    assert len(spot) == 1
    assert spot[0].card_type == TYPE_SPOTLIGHT
    # Empty code degrades to "" (matching ``_event_label``'s ``.get`` tolerance).
    assert spot[0].headline == "Dana Lee doubles up in the "


def test_f61_none_stroke_double_does_not_crash():
    """A ``None`` stroke (a broken-adapter type violation) must also not crash
    headline building."""
    claims = [
        _claim("gold", stroke=None, distance=100),
        _claim("gold", stroke=None, distance=200),
    ]
    # Must not raise KeyError or AttributeError.
    cards = group_claims_into_cards(claims, meet_name="County Champs")

    spot = _swimmer_cards(cards, "Dana Lee")
    assert len(spot) == 1
    assert spot[0].card_type == TYPE_SPOTLIGHT


def test_f61_known_stroke_headline_unchanged():
    """Control: a known stroke code still produces the titled family name, so
    the guard is behaviour-preserving for the supported vocabulary."""
    claims = [
        _claim("gold", stroke="BK", distance=100),
        _claim("gold", stroke="BK", distance=200),
    ]
    cards = group_claims_into_cards(claims, meet_name="County Champs")

    spot = _swimmer_cards(cards, "Dana Lee")
    assert len(spot) == 1
    assert spot[0].headline == "Dana Lee doubles up in the backstroke"
    assert spot[0].subhead == "Two golds across the Backstroke events"


# --------------------------------------------------------------------------- #
# F28 — per-swimmer emission contract: spotlight XOR standouts, never both
# --------------------------------------------------------------------------- #


def test_f28_many_notables_emit_spotlight_only():
    """3+ notable swims → exactly one spotlight and zero standouts."""
    claims = [
        _claim("gold", stroke="FR", distance=100),
        _claim("silver", stroke="FR", distance=200),
        _claim("pb_confirmed", stroke="BK", distance=50, place=None),
    ]
    cards = group_claims_into_cards(claims, meet_name="County Champs")

    per = _swimmer_cards(cards, "Dana Lee")
    assert len(per) == 1
    assert per[0].card_type == TYPE_SPOTLIGHT
    assert not any(c.card_type == TYPE_STANDOUT for c in per)


def test_f28_same_stroke_gold_double_emit_spotlight_only():
    """A same-stroke gold double → spotlight only, even with just 2 swims."""
    claims = [
        _claim("gold", stroke="FL", distance=100),
        _claim("gold", stroke="FL", distance=200),
    ]
    cards = group_claims_into_cards(claims, meet_name="County Champs")

    per = _swimmer_cards(cards, "Dana Lee")
    assert len(per) == 1
    assert per[0].card_type == TYPE_SPOTLIGHT


def test_f28_two_non_double_notables_emit_standouts_only():
    """1-2 notable swims that are not a same-stroke gold double → standouts
    only, no spotlight."""
    claims = [
        _claim("gold", stroke="FR", distance=100),
        _claim("pb_confirmed", stroke="BK", distance=200, place=None),
    ]
    cards = group_claims_into_cards(claims, meet_name="County Champs")

    per = _swimmer_cards(cards, "Dana Lee")
    assert len(per) == 2
    assert all(c.card_type == TYPE_STANDOUT for c in per)


def test_f28_no_swimmer_gets_both_card_types():
    """Across a mixed field, no single swimmer ever produces both a spotlight
    and a standout — the structural anti-spam contract the docstring documents."""
    claims = [
        # Spotlight swimmer (3 notables).
        _claim("gold", swimmer="Nadia Cole", tiref="T-NADIA", stroke="FR", distance=100),
        _claim("silver", swimmer="Nadia Cole", tiref="T-NADIA", stroke="BK", distance=200),
        _claim("pb_confirmed", swimmer="Nadia Cole", tiref="T-NADIA", stroke="BR", distance=50, place=None),
        # Standout swimmer (1 notable).
        _claim("gold", swimmer="Omar Reyes", tiref="T-OMAR", stroke="FR", distance=100),
    ]
    cards = group_claims_into_cards(claims, meet_name="County Champs")

    by_swimmer_types: dict[str, set] = defaultdict(set)
    for c in cards:
        if c.card_type in (TYPE_SPOTLIGHT, TYPE_STANDOUT):
            by_swimmer_types[c.primary_swimmer].add(c.card_type)

    # Guard against a vacuous pass: both swimmers must have produced cards.
    assert by_swimmer_types["Nadia Cole"] == {TYPE_SPOTLIGHT}
    assert by_swimmer_types["Omar Reyes"] == {TYPE_STANDOUT}
    for name, types in by_swimmer_types.items():
        assert not (TYPE_SPOTLIGHT in types and TYPE_STANDOUT in types), (
            f"{name} produced both a spotlight and standouts — violates the "
            f"emission contract"
        )


def test_f28_ranker_demotion_no_op_for_distinct_name_swimmers():
    """Distinct-name swimmers: the grouper emits a spotlight for one and a
    standout for the other, and because their `primary_swimmer` names differ,
    ranker_v3's name-keyed spotlight-owner demotion does not fire — the common
    real-world case the docstring calls out."""
    claims = [
        _claim("gold", swimmer="Nadia Cole", tiref="T-NADIA", stroke="FR", distance=100),
        _claim("silver", swimmer="Nadia Cole", tiref="T-NADIA", stroke="BK", distance=200),
        _claim("pb_confirmed", swimmer="Nadia Cole", tiref="T-NADIA", stroke="BR", distance=50, place=None),
        _claim("gold", swimmer="Omar Reyes", tiref="T-OMAR", stroke="FR", distance=100),
    ]
    cards = group_claims_into_cards(claims, meet_name="County Champs")
    # Guard against a vacuous pass: the coupling only means anything if both a
    # spotlight and a standout are present.
    assert any(c.card_type == TYPE_SPOTLIGHT for c in cards)
    assert any(c.card_type == TYPE_STANDOUT for c in cards)

    ranked = rank_cards(cards)
    assert not any(
        "Demoted: covered by athlete spotlight" in reason
        for c in ranked
        for reason in c.score_reasons
    )


def test_f28_shared_display_name_breaks_primary_swimmer_uniqueness():
    """The documented edge case that makes the grouper's per-swimmer XOR NOT
    translate into a per-``primary_swimmer`` XOR: two DISTINCT athletes (distinct
    tirefs) sharing a display name. The grouper keys swimmers by
    `swimmer_tiref or swimmer_name`, so each gets their own storyline — a
    spotlight for one, a standout for the other — but BOTH cards carry the same
    `primary_swimmer` name. That shared name is exactly what lets ranker_v3's
    name-keyed spotlight-owner demotion fire on this grouper's output (see the
    module docstring). We assert only the grouper's output here; whether/how the
    ranker reacts to it is the ranker_v3 owner's call (F28 hand-off)."""
    claims = [
        # 'John Smith' #1 (distinct tiref) — 3 notables → spotlight.
        _claim("gold", swimmer="John Smith", tiref="T-1", stroke="FR", distance=100),
        _claim("silver", swimmer="John Smith", tiref="T-1", stroke="BK", distance=200),
        _claim("pb_confirmed", swimmer="John Smith", tiref="T-1", stroke="BR", distance=50, place=None),
        # 'John Smith' #2 (distinct tiref) — 1 notable → standout, same name.
        _claim("gold", swimmer="John Smith", tiref="T-2", stroke="FR", distance=100),
    ]
    cards = group_claims_into_cards(claims, meet_name="County Champs")

    # Per swimmer KEY the XOR contract still holds: neither tiref yields both.
    by_key_types: dict[str, set] = defaultdict(set)
    for c in cards:
        if c.card_type in (TYPE_SPOTLIGHT, TYPE_STANDOUT):
            by_key_types[c.primary_tiref].add(c.card_type)
    assert by_key_types["T-1"] == {TYPE_SPOTLIGHT}
    assert by_key_types["T-2"] == {TYPE_STANDOUT}

    # But a spotlight and a standout now share one primary_swimmer name — the
    # precondition the docstring flags. (We deliberately do NOT assert ranker_v3's
    # demotion outcome: that coupling is owned by the ranker_v3 session.)
    spot = next(c for c in cards if c.card_type == TYPE_SPOTLIGHT)
    standout = next(c for c in cards if c.card_type == TYPE_STANDOUT)
    assert spot.primary_swimmer == standout.primary_swimmer == "John Smith"
    assert spot.primary_tiref != standout.primary_tiref
