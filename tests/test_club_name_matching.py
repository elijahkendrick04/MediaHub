"""Club-name fuzzy matching (pipeline.interpreter_bridge._name_tokens_match).

Regression for the review page showing swimmers from the WRONG club: the
matcher counted the org-type word "city" (which both "Co" and "City of"
normalise to) as a distinguishing token, so EVERY "Co …" club matched
"City of Cardiff" — e.g. Calvin Fry of "Co B'ton & H" (City of Brighton & Hove)
was pulled into a Cardiff run. Identity must turn on the place name, while
legitimate abbreviations ("Co Manch Aq" == "City of Manchester Aquatics") still
match.
"""

from __future__ import annotations

import pytest

from mediahub.pipeline.interpreter_bridge import _name_tokens_match


def _m(target: str, candidate: str) -> bool:
    return _name_tokens_match(target.lower(), candidate.lower())


@pytest.mark.parametrize(
    "target,candidate",
    [
        ("City of Cardiff", "Co Cardiff"),
        ("City of Cardiff", "Co Cardiff 14"),
        ("City of Manchester Aquatics", "Co Manch Aq"),
        ("City of Birmingham", "Co Birmingham"),
        ("Otter Swimming Club", "Otter SC"),
        ("City of Cardiff", "Cardiff"),
    ],
)
def test_same_club_matches(target: str, candidate: str) -> None:
    assert _m(target, candidate) is True


@pytest.mark.parametrize(
    "target,candidate",
    [
        # The exact false match from the bug report: Brighton & Hove pulled into
        # a Cardiff run because both share the generic "city" token.
        ("City of Cardiff", "Co B'ton & H"),
        ("City of Cardiff", "Co Birmingham"),
        ("City of Cardiff", "Co Bristol"),
        ("City of Cardiff", "City of Bristol"),
        ("City of Cardiff", "Co Manch Aq"),
        ("City of Cardiff", "Millfield"),
    ],
)
def test_different_club_does_not_match(target: str, candidate: str) -> None:
    assert _m(target, candidate) is False
