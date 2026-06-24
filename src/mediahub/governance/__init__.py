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

The feature registry (:mod:`mediahub.governance.features`) is the shared source
of truth all three concerns key off.
"""

from __future__ import annotations

from . import features, quota, context
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

__all__ = [
    "features",
    "quota",
    "context",
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
]
