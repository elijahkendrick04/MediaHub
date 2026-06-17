"""
Content-disposition levels for per-content-type review control.

``AutonomyLevel`` is the per-post-type setting for how a draft of that type
enters review. Each *post type* in a sport profile carries a default level; a
workspace may later override it per type.

The level decides one thing only: **how much human involvement a post of that
type needs before it is ready to use.**

  - ``draft_only``         — generate a draft and stop. A human exports or
                             hand-posts it; it never enters the approval queue.
  - ``approval_required``  — the product default. Generate a draft, then wait
                             for a human to approve it. This is the
                             QUEUE -> APPROVED step in
                             ``mediahub.workflow.status.CardStatus``.

This module is deliberately pure and free of any I/O side effects: it describes
the disposition, it does not enforce it. MediaHub never publishes to a social
channel on its own — approved content is exported or downloaded for manual
posting.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class AutonomyLevel(str, Enum):
    """How a single content/post type enters review.

    ``str``-backed so it serialises straight to/from YAML and JSON as the bare
    string value (matching ``mediahub.club_platform.content_types.ContentType``).
    """

    DRAFT_ONLY = "draft_only"
    APPROVAL_REQUIRED = "approval_required"

    @classmethod
    def default(cls) -> "AutonomyLevel":
        """The product-wide default: a human approves before content is used."""
        return cls.APPROVAL_REQUIRED

    @classmethod
    def from_str(cls, value: object, default: Optional["AutonomyLevel"] = None) -> "AutonomyLevel":
        """Parse a level tolerantly (case/space/hyphen-insensitive).

        Unknown or empty values fall back to ``default`` (or the product default
        when ``default`` is None). This mirrors ``brand.tone.tone_from_str`` —
        config typos degrade to the safe approval-required level rather than raising.
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


__all__ = ["AutonomyLevel"]
