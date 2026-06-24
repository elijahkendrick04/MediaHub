"""governance/permissions.py — which role (and plan) may use which AI feature (1.23).

Layered on :mod:`mediahub.collab.permissions` (the workspace role → capability
matrix). That module answers "can this role edit / approve / manage?"; this one
answers the narrower governance question "can this role *use this AI feature*?"
by mapping each feature to the capability a member needs to invoke it:

  * Content generation (captions, imagery, media tagging, research) needs
    ``edit`` — the seat that drafts content. Reviewers and viewers can look but
    not spend the org's AI on new output.
  * Brand-defining AI (brand interpretation, palette resolution, brand-DNA
    capture) needs ``manage`` — it reshapes the whole org's identity, so it sits
    with the owner alongside the other workspace-admin powers.

A second, optional axis gates a feature behind a minimum plan. It ships EMPTY
(no feature is plan-gated) — the seam for a future commercial pass — so this
build is purely role-based, exactly as the roadmap item asks. Pure data + a
couple of predicates: no I/O, no Flask, trivially testable.
"""

from __future__ import annotations

from ..collab import permissions as caps
from . import features

# AI feature → capability needed to use it (least-privilege on unknowns).
_FEATURE_CAPABILITY: dict[str, str] = {
    features.FEATURE_CAPTION: caps.CAP_EDIT,
    features.FEATURE_IMAGINE: caps.CAP_EDIT,
    features.FEATURE_DESCRIBE: caps.CAP_EDIT,
    features.FEATURE_RESEARCH: caps.CAP_EDIT,
    features.FEATURE_TRANSLATE: caps.CAP_EDIT,
    features.FEATURE_BRAND: caps.CAP_MANAGE,
    features.FEATURE_PALETTE: caps.CAP_MANAGE,
    features.FEATURE_DNA: caps.CAP_MANAGE,
}

# An unknown AI feature needs edit — a safe middle seat: not free-for-all
# (view), not owner-only (manage).
_DEFAULT_CAPABILITY = caps.CAP_EDIT

# Optional commercial gate: feature → minimum plan. Ships EMPTY (no plan gate).
# Mirrors auth.VALID_PLANS ordering: free < club < federation < owner.
_PLAN_RANK: dict[str, int] = {"free": 0, "club": 1, "federation": 2, "owner": 3}
_FEATURE_MIN_PLAN: dict[str, str] = {}


def required_capability(feature: object) -> str:
    """The capability a member needs to use ``feature``."""
    return _FEATURE_CAPABILITY.get(features.normalise(feature), _DEFAULT_CAPABILITY)


def _plan_rank(plan: object) -> int:
    return _PLAN_RANK.get(str(plan or "").strip().lower(), 0)


def plan_allows(feature: object, plan: object) -> bool:
    """True unless ``feature`` is plan-gated above ``plan`` (default: always)."""
    need = _FEATURE_MIN_PLAN.get(features.normalise(feature))
    if not need:
        return True
    return _plan_rank(plan) >= _plan_rank(need)


def role_allows(role: object, feature: object) -> bool:
    """True when ``role`` holds the capability ``feature`` requires."""
    return caps.can(role, required_capability(feature))


def can_use_feature(role: object, feature: object, *, plan: object = None) -> bool:
    """True when ``role`` (on ``plan``) may use ``feature`` — both gates pass."""
    return role_allows(role, feature) and plan_allows(feature, plan)


def features_for_role(role: object, *, plan: object = None) -> list[str]:
    """Every feature ``role`` may use, in registry order (for UI gating)."""
    return [f for f in features.feature_keys() if can_use_feature(role, f, plan=plan)]


def denial_reason(role: object, feature: object, *, plan: object = None) -> str:
    """An honest, specific message for why a use is blocked (empty if allowed)."""
    label = features.label_for(feature)
    if not role_allows(role, feature):
        need = required_capability(feature)
        ask = (
            "Only an owner can use it."
            if need == caps.CAP_MANAGE
            else "Ask an owner for editor access."
        )
        return f"Your role ({caps.role_label(role)}) can't use {label}. {ask}"
    if not plan_allows(feature, plan):
        need = _FEATURE_MIN_PLAN.get(features.normalise(feature), "")
        return f"{label} needs the {need.title()} plan."
    return ""


__all__ = [
    "required_capability",
    "plan_allows",
    "role_allows",
    "can_use_feature",
    "features_for_role",
    "denial_reason",
]
