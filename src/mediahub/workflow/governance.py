"""workflow/governance.py — group-approver rule evaluation (roadmap 1.12, 1.18).

A brand kit can carry a group-approver rule (``BrandKitRef.approver_rule``): how
many distinct people must approve a card, and whether at least one must be a
workspace owner, before it can move to APPROVED. This module is the pure,
deterministic evaluator — no I/O, no Flask — so it is trivially testable and is
the single source of truth the approval route consults.

1.12 shipped the base rule + its enforcement on the CardStatus transition.
1.18 adds **per-content-type overrides** (``by_type``): a kit can demand a
stricter rule for the sensitive types the roadmap names — e.g. an extra
approver, an owner among them, for ``sponsor_activation`` or
``safeguarding``-flagged cards — while ordinary cards keep the base rule. A type
with no override inherits the base. The rich review UI (who-approved badges,
request-changes) also lands in 1.18 on top of this engine.

Default-safe: an empty/absent rule means "one approval is enough" (today's
behaviour), so a club that never configures a rule sees no change.
"""

from __future__ import annotations

_MAX_APPROVERS = 10


def _normalise_base(raw) -> dict:
    """Normalise a single base rule ``{min_approvers?, require_owner?}``.

    Returns ``{}`` for the trivial "one approval is enough" rule. ``min_approvers``
    is only kept when > 1; an out-of-range value is clamped to ``[1, 10]``.
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


def normalise_approver_rule(raw) -> dict:
    """Coerce a raw rule dict into the canonical, minimal shape.

    Carries an optional ``by_type`` map of ``{content_type: base_rule}``; each
    sub-rule is normalised and empty ones are dropped, so the map only survives
    when it holds at least one real override. Returns ``{}`` when neither the
    base nor any type override is active, so callers can treat falsy as "no
    rule".
    """
    if not isinstance(raw, dict):
        return {}
    out = _normalise_base(raw)
    by_type = raw.get("by_type")
    if isinstance(by_type, dict):
        norm_types: dict[str, dict] = {}
        for k, v in by_type.items():
            key = str(k or "").strip().lower()
            if not key:
                continue
            sub = _normalise_base(v)
            if sub:
                norm_types[key] = sub
        if norm_types:
            out = dict(out)
            out["by_type"] = norm_types
    return out


def rule_for_type(rule, content_type) -> dict:
    """The effective base-shape rule for ``content_type``.

    A type with its own ``by_type`` override uses it outright; everything else
    inherits the base rule (the ``by_type`` map stripped off). Returns ``{}``
    when nothing applies, which :func:`evaluate` treats as "one approval is
    enough".
    """
    norm = normalise_approver_rule(rule)
    ct = str(content_type or "").strip().lower()
    by_type = norm.get("by_type") or {}
    if ct and ct in by_type:
        return dict(by_type[ct])
    return {k: v for k, v in norm.items() if k != "by_type"}


def rule_is_active(rule) -> bool:
    """True when the kit carries any rule at all (base or a type override)."""
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


def evaluate_for_type(
    rule, content_type, *, approver_emails, owner_emails
) -> tuple[bool, int, str]:
    """Evaluate the rule that applies to ``content_type`` (1.18).

    Thin sugar over :func:`rule_for_type` + :func:`evaluate` so the approval
    route asks one question and the per-type override is honoured.
    """
    return evaluate(
        rule_for_type(rule, content_type),
        approver_emails=approver_emails,
        owner_emails=owner_emails,
    )


__all__ = [
    "normalise_approver_rule",
    "rule_for_type",
    "rule_is_active",
    "evaluate",
    "evaluate_for_type",
]
