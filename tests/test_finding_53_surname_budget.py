"""Finding #53 — surname matching tolerates only a single typo (budget 1).

`_close` used a length-scaled edit budget (2 for names longer than 4 chars).
Applied to surnames that let two genuinely different families collapse together:
Wilson/Watson are Levenshtein-2 and were matched as the same surname. Surname
matching now passes `max_budget=1`, so a surname tolerates only ONE typo, while
first names keep the wider length-scaled budget (nickname/spelling tolerance).
"""

from __future__ import annotations

import pytest

from mediahub.swimmingresults import names


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("Wilson", "Watson", False),   # Levenshtein 2 — distinct families now
        ("Smith", "Smyth", True),      # 1 edit — still the same surname
        ("Galagher", "Gallagher", True),  # 1 insert — still matches
        ("Gallahger", "Gallagher", False),  # transposition = Levenshtein 2 now misses
        ("Greenslade", "Greenslade", True),  # exact
        ("Marsh", "Walsh", False),     # 2 edits (m->w, r->l) — distinct
    ],
)
def test_surname_match_budget_is_one(a, b, expected):
    assert names.surname_match(a, b) is expected


def test_name_match_surname_branch_uses_budget_one():
    # Same first name, Levenshtein-2 surnames -> different people now.
    assert names.name_match("Rob", "Wilson", "Rob", "Watson") is False
    # A single-typo surname with matching first name still matches.
    assert names.name_match("Rob", "Smith", "Rob", "Smyth") is True


def test_first_name_tolerance_is_unchanged():
    # First-name spelling / nickname / prefix tolerance keeps the wider budget
    # (these all share an exact surname, so only the first-name branch varies).
    assert names.name_match("Sophie", "Lee", "Sofie", "Lee") is True   # 1-edit spelling
    assert names.name_match("Charlie", "Smith", "Charles", "Smith") is True  # nickname
    assert names.name_match("Ben", "Carter", "Benjamin", "Carter") is True   # prefix


def test_close_max_budget_caps_but_never_raises_budget():
    # max_budget only tightens: a would-be budget-1 pair (short names) stays 1.
    assert names._close("al", "xy", max_budget=1) is False
    # Without the cap, a length-6 pair keeps its budget of 2.
    assert names._close("Wilson", "Watson") is True
    assert names._close("Wilson", "Watson", max_budget=1) is False
