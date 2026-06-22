"""Roadmap 1.18 build 1 — per-content-type group-approver overrides.

The 1.12 base rule is unchanged; 1.18 adds a ``by_type`` overlay so a kit can
demand a stricter sign-off for the sensitive types the roadmap names
(``safeguarding``, ``sponsor_activation``) while ordinary cards inherit the base.
Pure evaluator tests — no I/O.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.workflow import governance as gov


def test_base_rule_unchanged_when_no_by_type():
    assert gov.normalise_approver_rule({"min_approvers": 2}) == {"min_approvers": 2}
    assert gov.normalise_approver_rule({}) == {}


def test_by_type_keeps_only_real_overrides():
    # A trivial sub-rule (1 approver, no owner) is dropped — it would just
    # inherit the base anyway, so it never bloats the stored rule.
    r = gov.normalise_approver_rule(
        {
            "min_approvers": 1,
            "by_type": {
                "safeguarding": {"min_approvers": 2, "require_owner": True},
                "sponsor_activation": {"min_approvers": 1},  # trivial → dropped
                "": {"min_approvers": 5},  # blank key → dropped
            },
        }
    )
    assert r == {"by_type": {"safeguarding": {"min_approvers": 2, "require_owner": True}}}


def test_rule_for_type_override_vs_inherit():
    r = {
        "min_approvers": 2,
        "by_type": {"safeguarding": {"min_approvers": 3, "require_owner": True}},
    }
    assert gov.rule_for_type(r, "safeguarding") == {"min_approvers": 3, "require_owner": True}
    # An un-overridden type inherits the base (with by_type stripped off).
    assert gov.rule_for_type(r, "meet_recap") == {"min_approvers": 2}
    assert gov.rule_for_type(r, "") == {"min_approvers": 2}


def test_rule_for_type_with_no_rule_is_empty():
    assert gov.rule_for_type({}, "safeguarding") == {}
    assert gov.rule_for_type(None, "anything") == {}


def test_evaluate_for_type_applies_the_stricter_rule():
    r = {
        "min_approvers": 1,
        "by_type": {"safeguarding": {"min_approvers": 2, "require_owner": True}},
    }
    # Ordinary card: one approval suffices (inherits trivial base).
    ok, need, _ = gov.evaluate_for_type(
        r, "meet_recap", approver_emails=["vol@x"], owner_emails=["boss@x"]
    )
    assert ok is True and need == 0
    # Safeguarding card: needs 2 distinct approvers AND an owner.
    ok2, need2, reason = gov.evaluate_for_type(
        r, "safeguarding", approver_emails=["vol@x"], owner_emails=["boss@x"]
    )
    assert ok2 is False and need2 == 1
    assert "owner" in reason.lower()
    # Same card, now satisfied: an owner plus another approver.
    ok3, need3, _ = gov.evaluate_for_type(
        r, "safeguarding", approver_emails=["vol@x", "boss@x"], owner_emails=["boss@x"]
    )
    assert ok3 is True and need3 == 0


def test_rule_is_active_true_when_only_a_type_override_exists():
    r = {"by_type": {"safeguarding": {"min_approvers": 2}}}
    assert gov.rule_is_active(r) is True
    # …but the base (no override) for an ordinary type is trivially satisfied.
    ok, _, _ = gov.evaluate_for_type(r, "meet_recap", approver_emails=[], owner_emails=[])
    assert ok is True
