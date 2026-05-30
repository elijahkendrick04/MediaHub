"""Tests for the build-loop item rotation (builder._select_item + attempt
tracking).

Regression guard: the autopilot used to call roadmap.next_item() every cycle,
which returns the single highest-priority actionable item — so a hard item the
coder couldn't one-shot was re-picked forever and STARVED every other roadmap
item. _select_item now rotates attempts-first (never-skip): a repeatedly-failed
item sinks below less-tried ones but is always retried later.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from autotest import builder


def _item(id_):
    return SimpleNamespace(id=id_, title=id_, body="", actionable=True)


@pytest.fixture
def tmp_state(tmp_path, monkeypatch):
    """Back the builder state with a real temp file so bump/clear round-trip."""
    monkeypatch.setattr(builder, "STATE_PATH", tmp_path / "builder_state.json")
    return builder.STATE_PATH


# --------------------------------------------------------------------------- #
# attempt tracking
# --------------------------------------------------------------------------- #
def test_bump_and_clear_round_trip(tmp_state):
    assert builder._bump_item_attempt("PAR-2") == 1
    assert builder._bump_item_attempt("PAR-2") == 2
    assert builder._state()["item_attempts"]["PAR-2"] == 2
    builder._clear_item_attempt("PAR-2")
    assert "PAR-2" not in builder._state().get("item_attempts", {})


def test_clear_unknown_item_is_noop(tmp_state):
    builder._clear_item_attempt("nope")  # must not raise
    assert builder._state().get("item_attempts", {}) == {}


# --------------------------------------------------------------------------- #
# selection / rotation
# --------------------------------------------------------------------------- #
def test_select_prefers_priority_when_attempts_equal(tmp_state, monkeypatch):
    # actionable_items returns priority-ordered [A, B]; equal attempts → A wins.
    monkeypatch.setattr(builder.roadmap, "actionable_items", lambda: [_item("A"), _item("B")])
    monkeypatch.delenv("AUTOTEST_BUILD_ITEM", raising=False)
    assert builder._select_item().id == "A"


def test_select_rotates_past_a_repeatedly_failing_item(tmp_state, monkeypatch):
    """The core fix: A is higher priority but has more attempts, so B is built
    next — A sinks instead of starving B."""
    monkeypatch.setattr(builder.roadmap, "actionable_items", lambda: [_item("A"), _item("B")])
    monkeypatch.delenv("AUTOTEST_BUILD_ITEM", raising=False)
    builder._bump_item_attempt("A")
    builder._bump_item_attempt("A")
    builder._bump_item_attempt("B")
    assert builder._select_item().id == "B"


def test_select_never_permanently_skips(tmp_state, monkeypatch):
    """Once B catches up in attempts, the higher-priority A resurfaces — the
    hard item is retried, never abandoned."""
    monkeypatch.setattr(builder.roadmap, "actionable_items", lambda: [_item("A"), _item("B")])
    monkeypatch.delenv("AUTOTEST_BUILD_ITEM", raising=False)
    builder._bump_item_attempt("A")
    builder._bump_item_attempt("B")
    # equal attempts again → priority (A) wins, so A is retried
    assert builder._select_item().id == "A"


def test_forced_item_bypasses_rotation(tmp_state, monkeypatch):
    monkeypatch.setenv("AUTOTEST_BUILD_ITEM", "B")
    monkeypatch.setattr(builder.roadmap, "next_item", lambda: _item("B"))
    # even with A less-tried, the forced id wins
    builder._bump_item_attempt("B")
    assert builder._select_item().id == "B"


def test_select_none_when_nothing_actionable(tmp_state, monkeypatch):
    monkeypatch.setattr(builder.roadmap, "actionable_items", lambda: [])
    monkeypatch.delenv("AUTOTEST_BUILD_ITEM", raising=False)
    assert builder._select_item() is None
