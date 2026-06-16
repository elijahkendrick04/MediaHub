"""G1.20 — APCA-gated automatic role assignment.

Tests for ``mediahub.theming.roles.assign_brand_roles`` — the engine that
maps N custom club colours onto the brand role slots (primary / secondary /
tertiary), gated by an APCA ink-legibility floor and a CIEDE2000 distinctness
floor, respecting the club's input priority order.

Fixture colours (HCT / gate status verified at authoring time):
    #0E2A47 navy    — brandable, ink gate PASS  (the generic-default primary)
    #C9A227 gold    — brandable, ink gate PASS
    #A30D2D crimson — brandable, ink gate PASS
    #D4FF3A lane    — brandable, ink gate PASS
    #9A7B4F tan     — brandable, ink gate FAIL (mid-luminance, |Lc| 37 < 45)
    #767676 grey    — NOT brandable (chroma 1.8)
    #000000 black   — NOT brandable (tone 0)
    #1E40AF/#1E42B0 — near-identical blues (ΔE2000 ≈ 0.6 < 10)
"""
from __future__ import annotations

import re

import pytest

from mediahub.theming.roles import (
    assign_brand_roles,
    BrandRoleAssignment,
    ColourRole,
    BRAND_ROLE_SLOTS,
    ROLE_INK_FLOOR_APCA,
    ROLE_DISTINCT_DELTA_E,
    BRANDABLE_CHROMA_MIN,
)


_HEX_RE = re.compile(r"#[0-9A-F]{6}")


class TestSlotFilling:
    def test_empty_input_assigns_nothing(self):
        a = assign_brand_roles([])
        assert a.primary is None
        assert a.secondary is None
        assert a.tertiary is None
        assert a.colours == []
        assert a.n_input == 0
        assert a.n_brandable == 0
        assert a.trace  # an explanation is always recorded

    def test_single_colour_fills_primary_only(self):
        a = assign_brand_roles(["#A30D2D"])
        assert a.primary == "#A30D2D"
        assert a.secondary is None
        assert a.tertiary is None
        assert a.n_brandable == 1

    def test_two_distinct_fill_primary_and_secondary(self):
        a = assign_brand_roles(["#0E2A47", "#C9A227"])
        assert a.primary == "#0E2A47"
        assert a.secondary == "#C9A227"
        assert a.tertiary is None

    def test_three_distinct_fill_all_brand_slots(self):
        a = assign_brand_roles(["#0E2A47", "#C9A227", "#A30D2D"])
        assert a.primary == "#0E2A47"
        assert a.secondary == "#C9A227"
        assert a.tertiary == "#A30D2D"
        assert a.n_brandable == 3

    def test_input_priority_order_respected(self):
        """The club's first colour is their primary (when it clears the gate)."""
        a = assign_brand_roles(["#C9A227", "#0E2A47", "#A30D2D"])
        assert a.primary == "#C9A227"
        assert a.secondary == "#0E2A47"
        assert a.tertiary == "#A30D2D"

    def test_more_than_three_brandable_marks_extras(self):
        a = assign_brand_roles(["#0E2A47", "#C9A227", "#A30D2D", "#D4FF3A"])
        assert (a.primary, a.secondary, a.tertiary) == ("#0E2A47", "#C9A227", "#A30D2D")
        extras = [c for c in a.colours if c.role == "extra"]
        assert [c.hex for c in extras] == ["#D4FF3A"]


class TestAPCAInkGate:
    def test_gate_failing_colour_is_not_primary_when_a_passing_one_exists(self):
        """A mid-luminance colour whose best ink is marginal (|Lc| < 45) is
        demoted — a gate-passing colour later in the list is promoted to the
        text-bearing primary fill instead."""
        a = assign_brand_roles(["#9A7B4F", "#0E2A47"])
        assert a.primary == "#0E2A47", "gate-passing navy should be promoted"
        # The tan is still a brand colour — it lands in an accent slot.
        tan = next(c for c in a.colours if c.hex == "#9A7B4F")
        assert tan.role == "secondary"
        assert tan.passes_ink_gate is False

    def test_primary_passes_gate_when_possible(self):
        a = assign_brand_roles(["#9A7B4F", "#C9A227"])
        primary = next(c for c in a.colours if c.hex == a.primary)
        assert primary.passes_ink_gate is True

    def test_all_failing_falls_back_to_first_brandable_with_warning(self):
        """When no brandable colour clears the gate, the first brandable one
        is used anyway — with an explicit warning in the trace."""
        a = assign_brand_roles(["#9A7B4F"])  # only a gate-failer
        assert a.primary == "#9A7B4F"
        assert any("marginal" in line.lower() or "gate" in line.lower() for line in a.trace)


class TestDistinctnessGate:
    def test_near_identical_second_colour_is_redundant(self):
        a = assign_brand_roles(["#1E40AF", "#1E42B0", "#C9A227"])
        assert a.primary == "#1E40AF"
        # The second near-identical blue does NOT take a slot.
        assert a.secondary == "#C9A227"
        dup = next(c for c in a.colours if c.hex == "#1E42B0")
        assert dup.role == "redundant"

    def test_redundant_recorded_in_trace(self):
        a = assign_brand_roles(["#1E40AF", "#1E42B0"])
        assert a.secondary is None
        assert any("redundant" in line.lower() for line in a.trace)

    def test_distinct_colours_all_kept(self):
        a = assign_brand_roles(["#0E2A47", "#C9A227", "#A30D2D"])
        assert not any(c.role == "redundant" for c in a.colours)


class TestBrandabilityFilter:
    @pytest.mark.parametrize("neutral", ["#000000", "#FFFFFF", "#808080", "#767676"])
    def test_neutral_never_takes_a_brand_slot(self, neutral):
        a = assign_brand_roles(["#0E2A47", neutral])
        assert a.primary == "#0E2A47"
        assert a.secondary is None  # the neutral does not become secondary
        nc = next(c for c in a.colours if c.hex == neutral.upper())
        assert nc.brandable is False
        assert nc.role == "neutral"

    def test_all_neutral_still_yields_a_primary_seed(self):
        """If nothing is brandable, the first colour is still used as a
        near-neutral seed (the base engine handles grey seeds)."""
        a = assign_brand_roles(["#808080", "#000000"])
        assert a.primary == "#808080"
        assert a.n_brandable == 0


class TestNormalisation:
    def test_deduplicates_case_insensitively(self):
        a = assign_brand_roles(["#A30D2D", "#a30d2d", "#C9A227"])
        assert a.n_input == 2
        assert a.primary == "#A30D2D"
        assert a.secondary == "#C9A227"

    def test_short_hex_expanded(self):
        a = assign_brand_roles(["#abc"])
        assert a.primary == "#AABBCC"

    def test_non_hex_entries_dropped(self):
        a = assign_brand_roles(["not a colour", "", None, "#C9A227"])  # type: ignore[list-item]
        assert a.n_input == 1
        assert a.primary == "#C9A227"


class TestColourRoleShape:
    def test_every_colour_has_a_role_and_valid_ink(self):
        a = assign_brand_roles(["#0E2A47", "#C9A227", "#9A7B4F", "#000000"])
        valid_roles = set(BRAND_ROLE_SLOTS) | {"neutral", "redundant", "extra"}
        for c in a.colours:
            assert isinstance(c, ColourRole)
            assert c.role in valid_roles, c.role
            assert _HEX_RE.fullmatch(c.best_ink), c.best_ink
            assert isinstance(c.ink_apca, float)
            assert isinstance(c.passes_ink_gate, bool)
            assert c.chroma >= 0

    def test_brandable_flag_tracks_chroma_floor(self):
        a = assign_brand_roles(["#0E2A47", "#767676"])
        navy = next(c for c in a.colours if c.hex == "#0E2A47")
        grey = next(c for c in a.colours if c.hex == "#767676")
        assert navy.chroma >= BRANDABLE_CHROMA_MIN and navy.brandable
        assert grey.chroma < BRANDABLE_CHROMA_MIN and not grey.brandable


class TestSerialisation:
    def test_slots_returns_only_assigned(self):
        a = assign_brand_roles(["#0E2A47", "#C9A227"])
        assert a.slots() == {"primary": "#0E2A47", "secondary": "#C9A227"}

    def test_to_dict_round_trips_key_fields(self):
        a = assign_brand_roles(["#0E2A47", "#C9A227", "#A30D2D"])
        d = a.to_dict()
        assert d["primary"] == "#0E2A47"
        assert d["secondary"] == "#C9A227"
        assert d["tertiary"] == "#A30D2D"
        assert d["n_brandable"] == 3
        assert len(d["colours"]) == 3
        assert isinstance(d["trace"], list) and d["trace"]
        # JSON-serialisable end to end.
        import json

        json.dumps(d)


class TestDeterminism:
    def test_same_input_same_assignment(self):
        args = ["#0E2A47", "#C9A227", "#A30D2D", "#9A7B4F"]
        a = assign_brand_roles(list(args))
        b = assign_brand_roles(list(args))
        assert a.to_dict() == b.to_dict()


class TestConstantsSane:
    def test_gate_floors_are_in_expected_band(self):
        # APCA Bronze non-text floor; ColorBrewer categorical ΔE floor.
        assert 30.0 <= ROLE_INK_FLOOR_APCA <= 60.0
        assert ROLE_DISTINCT_DELTA_E >= 5.0
