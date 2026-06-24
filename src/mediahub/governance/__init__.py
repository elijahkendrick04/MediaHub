"""mediahub.governance — the AI governance layer (roadmap 1.23).

The control plane over every AI surface. Three concerns, one package:

* **Quotas** — per-org / per-feature metering and enforcement. The raw counts
  live in :mod:`mediahub.observability.feature_quota`; the policy (limits, plan
  tiers, enforce-or-meter) lives in :mod:`mediahub.governance.quota`. Wrap an AI
  call in :func:`mediahub.governance.context.feature_scope` and it is metered,
  and hard-blocked iff a limit is configured and reached.

* **Permissions** — which collaboration role (and plan) may use which AI
  feature, layered on :mod:`mediahub.collab.permissions`
  (:mod:`mediahub.governance.permissions`).

* **Provenance** — an honest manifest stamped on every AI-produced asset, so any
  output can answer "what made me, from what, when"
  (:mod:`mediahub.governance.provenance`).

Generative *content moderation* was deliberately left out of this work package
(maintainer decision, 2026-06-24): MediaHub keeps a human in the loop before any
external publishing, and the existing prompt-injection guard, child-policy
backstop and data-minimisation already cover the safety surface that matters
here.

Import note: ``features``, ``quota``, ``context`` and ``provenance`` are pure
(stdlib + observability) and imported eagerly. ``permissions`` reaches the
collaboration role matrix (and thus the web layer), so it is imported lazily via
``__getattr__`` — ``import mediahub.governance`` and
``from mediahub.governance import provenance`` stay cheap for the rendering and
request paths.
"""

from __future__ import annotations

from . import features, quota, context, provenance
from .quota import QuotaExceeded, QuotaStatus, UNLIMITED, check, enforce, limit_for, record
from .context import (
    FeatureScope,
    bind,
    clear_request_context,
    current_org_id,
    current_plan,
    feature_scope,
    set_request_context,
)

# Lazily-resolved names that live in the web-coupled permissions submodule.
_LAZY_PERMISSION_NAMES = frozenset(
    {
        "permissions",
        "can_use_feature",
        "denial_reason",
        "features_for_role",
        "required_capability",
    }
)


def __getattr__(name: str):
    if name in _LAZY_PERMISSION_NAMES:
        import importlib

        # import_module (not ``from . import``) so this doesn't recurse back
        # through __getattr__ while the submodule is still unbound.
        _permissions = importlib.import_module(f"{__name__}.permissions")
        return _permissions if name == "permissions" else getattr(_permissions, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "features",
    "quota",
    "context",
    "provenance",
    "permissions",
    # quota policy
    "QuotaExceeded",
    "QuotaStatus",
    "UNLIMITED",
    "check",
    "enforce",
    "limit_for",
    "record",
    # request context + guard
    "FeatureScope",
    "feature_scope",
    "bind",
    "set_request_context",
    "clear_request_context",
    "current_org_id",
    "current_plan",
    # feature permissions (lazy)
    "can_use_feature",
    "denial_reason",
    "features_for_role",
    "required_capability",
]
