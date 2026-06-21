"""workflow/governance.py — group-approver rule evaluation (roadmap 1.12).

A brand kit can carry a group-approver rule (``BrandKitRef.approver_rule``): how
many distinct people must approve a card, and whether at least one must be a
workspace owner, before it can move to APPROVED. This module is the pure,
deterministic evaluator — no I/O, no Flask — so it is trivially testable and is
the single source of truth the approval route consults.

The rich review UI (who-approved badges, request-changes, etc.) is roadmap 1.18;
1.12 ships only the *enforcement* on the CardStatus transition.

Default-safe: an empty/absent rule means "one approval is enough" (today's
behaviour), so a club that never configures a rule sees no change.
"""

from __future__ import annotations

_MAX_APPROVERS = 10


def normalise_approver_rule(raw) -> dict:
    """Coerce a raw rule dict into the canonical, minimal shape.

    Returns ``{}`` for the trivial "one approval is enough" rule so callers can
    treat falsy as "no rule". ``min_approvers`` is only kept when > 1; an
    out-of-range value is clamped to ``[1, 10]``.
    """
    if not isinstance(raw, dict):
        return {}
    try:
        n = int(raw.get("min_approvers", 1))
    except (TypeError, ValueError):
        n = 1
    n = max(1, min(n, _MAX_APPROVERS))
    require_owner = bool(raw.get("require_owner", False))
    out: dict = {}
    if n > 1:
        out["min_approvers"] = n
    if require_owner:
        out["require_owner"] = True
    return out


def rule_is_active(rule) -> bool:
    """True when the rule asks for more than a single approval."""
    return bool(normalise_approver_rule(rule))


def evaluate(rule, *, approver_emails, owner_emails) -> tuple[bool, int, str]:
    """Decide whether the group-approval rule is satisfied.

    Returns ``(satisfied, still_needed, reason)``. ``still_needed`` is how many
    more distinct approvers are required (0 once the count is met, even if an
    owner is still missing). ``reason`` is a human line for the not-yet case.
    """
    r = normalise_approver_rule(rule)
    if not r:
        return True, 0, ""
    approvers = {(e or "").strip().lower() for e in approver_emails if (e or "").strip()}
    owners = {(e or "").strip().lower() for e in owner_emails if (e or "").strip()}
    min_n = r.get("min_approvers", 1)
    still_needed = max(0, min_n - len(approvers))
    owner_ok = (not r.get("require_owner")) or bool(approvers & owners)
    if still_needed == 0 and owner_ok:
        return True, 0, ""
    bits = []
    if still_needed > 0:
        bits.append(f"{still_needed} more approver(s)")
    if not owner_ok:
        bits.append("an owner's approval")
    return False, still_needed, "Needs " + " and ".join(bits) + " before this card is approved."


__all__ = ["normalise_approver_rule", "rule_is_active", "evaluate"]
