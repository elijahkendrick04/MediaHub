"""
Autonomy levels for per-content-type posting control.

``AutonomyLevel`` is the three-state toggle that the roadmap's autonomy model
hangs off (see ``docs/AUTONOMY_MODEL.md``). Each *post type* in a sport profile
carries a default autonomy level; a workspace may later override it per type.

The level decides one thing only: **how much human involvement a post of that
type needs before it can be published.**

  - ``draft_only``         — generate a draft and stop. Never schedules or
                             publishes on its own; a human exports or hand-posts.
  - ``approval_required``  — the product default. Generate a draft, then wait for
                             a human to approve before it can be scheduled/published.
                             This is the QUEUE -> APPROVED step in
                             ``mediahub.workflow.status.CardStatus``.
  - ``fully_autonomous``   — may publish without a human approval step, *provided*
                             every guardrail passes (provenance/trust, brand-safety,
                             rate limit, kill switch). See ``docs/AUTONOMY_MODEL.md``.

This module is deliberately pure and free of any I/O or publishing side effects:
it describes the policy, it does not enforce it. Enforcement is a later roadmap
phase (Phase 2 — autonomy toggles + orchestration). Nothing in the shipped
product imports this yet; it is inert scaffolding.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class AutonomyLevel(str, Enum):
    """How autonomously a single content/post type may be published.

    ``str``-backed so it serialises straight to/from YAML and JSON as the bare
    string value (matching ``mediahub.club_platform.content_types.ContentType``).
    """

    DRAFT_ONLY = "draft_only"
    APPROVAL_REQUIRED = "approval_required"
    FULLY_AUTONOMOUS = "fully_autonomous"

    @classmethod
    def default(cls) -> "AutonomyLevel":
        """The product-wide default: gated behind human approval."""
        return cls.APPROVAL_REQUIRED

    @classmethod
    def from_str(cls, value: object, default: Optional["AutonomyLevel"] = None) -> "AutonomyLevel":
        """Parse a level tolerantly (case/space/hyphen-insensitive).

        Unknown or empty values fall back to ``default`` (or the product default
        when ``default`` is None). This mirrors ``brand.tone.tone_from_str`` —
        config typos degrade to the safe gated level rather than raising.
        """
        fallback = default if default is not None else cls.default()
        if isinstance(value, cls):
            return value
        if value is None:
            return fallback
        key = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        for level in cls:
            if level.value == key:
                return level
        return fallback

    @property
    def requires_human_approval(self) -> bool:
        """True when a human approval step must run before publishing."""
        return self is not AutonomyLevel.FULLY_AUTONOMOUS

    @property
    def can_auto_publish(self) -> bool:
        """True only for the fully-autonomous level (still guardrail-gated)."""
        return self is AutonomyLevel.FULLY_AUTONOMOUS


__all__ = ["AutonomyLevel"]
