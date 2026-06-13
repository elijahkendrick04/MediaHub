"""Per-type autonomy publish gate (P2.4).

This is the second layer of the publish chokepoint, sitting alongside (not
replacing) the global kill switch in ``publishing.kill_switch``.

Design:
- Default-off and runtime-inert on the DEFAULT path: if no policy has been
  stored for an org, every type resolves to ``approval_required`` and
  ``assert_type_publishing_allowed`` raises ``TypeGated``, keeping the system
  fully gated — exactly today's behaviour.
- ``fully_autonomous`` is required for autonomous publishing to be allowed,
  AND the global kill switch must be disengaged.
- ``approval_required`` and ``draft_only`` both raise ``TypeGated``.

Callers in autonomous publishing paths (not in the human-approval the scheduler path)
call ``assert_type_publishing_allowed(org_id, content_type_str)`` before
attempting to post.  ``TypeGated`` means "queue for human review" — the same
state the system is in today for every type.
"""

from __future__ import annotations

from mediahub.publishing.kill_switch import assert_publishing_allowed
from mediahub.publishing.per_type_policy import AutonomyLevel, load_policy
from pathlib import Path
from typing import Optional


class TypeGated(RuntimeError):
    """Raised when a content type's autonomy level does not permit autonomous publishing.

    Callers should treat this as "queue for human approval" rather than an
    error — it is the expected default state for every type.
    """


def assert_type_publishing_allowed(
    org_id: str,
    content_type_str: str,
    *,
    data_dir: Optional[Path] = None,
) -> None:
    """Raise if autonomous publishing for ``content_type_str`` is not allowed.

    Checks (in order):
    1. Global kill switch — raises ``PublishingHalted`` if engaged.
    2. Per-type policy — raises ``TypeGated`` unless the type is set to
       ``fully_autonomous`` for this org.

    An org with no stored policy resolves to ``approval_required`` for every
    type, so the default is always gated.  Missing or unknown content type
    strings also resolve to ``approval_required``.
    """
    assert_publishing_allowed()

    from mediahub.club_platform.post_types import canonical_slug

    content_type_str = canonical_slug(content_type_str)
    policy = load_policy(org_id, data_dir=data_dir)
    level_str = policy.get(content_type_str, AutonomyLevel.APPROVAL_REQUIRED.value)
    level = AutonomyLevel.from_str(level_str)
    if not level.can_auto_publish:
        raise TypeGated(
            f"Content type {content_type_str!r} is set to {level.value!r} for org "
            f"{org_id!r} — queued for human approval. "
            f"Set to 'fully_autonomous' in workspace settings to allow autonomous publishing."
        )


def type_gate_status(org_id: str, *, data_dir: Optional[Path] = None) -> dict:
    """Return an informational dict about per-type gate state for ``org_id``.

    Intended for inclusion in ``/healthz/deps`` as a non-ok-affecting summary,
    mirroring ``kill_switch_status()``.
    """
    from mediahub.publishing.per_type_policy import policy_summary

    return policy_summary(org_id, data_dir=data_dir)


__all__ = [
    "TypeGated",
    "assert_type_publishing_allowed",
    "type_gate_status",
]
