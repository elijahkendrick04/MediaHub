"""Global publishing kill switch (P2.3).

This module is default-off and runtime-inert on the default path: when
MEDIAHUB_PUBLISH_KILL_SWITCH is unset or blank, publish_kill_switch_engaged()
returns False and assert_publishing_allowed() is a no-op. No running cost is
added; no fake/placeholder success is ever emitted. Setting the env var to
one of the truthy tokens halts all outbound publishing calls at the earliest
possible point, before any token validation or network work occurs.
"""

from __future__ import annotations

import os

KILL_SWITCH_ENV = "MEDIAHUB_PUBLISH_KILL_SWITCH"

_TRUTHY = {"1", "true", "yes", "on", "engaged"}


class PublishingHalted(RuntimeError):
    """Raised by assert_publishing_allowed() when the kill switch is engaged.

    Never swallowed silently — callers must surface an honest error.
    """


def publish_kill_switch_engaged() -> bool:
    """Return True only when the kill switch env var is set to a truthy token."""
    raw = os.environ.get(KILL_SWITCH_ENV, "").strip().lower()
    return raw in _TRUTHY


def assert_publishing_allowed() -> None:
    """Raise PublishingHalted if the kill switch is engaged, else no-op."""
    if publish_kill_switch_engaged():
        raise PublishingHalted(
            "Publishing is halted by the kill switch"
            f" ({KILL_SWITCH_ENV}={os.environ.get(KILL_SWITCH_ENV, '')!r})."
            " No post was sent. Unset the environment variable to resume publishing."
        )


def kill_switch_status() -> dict:
    """Return an informational dict about the current kill switch state."""
    raw = os.environ.get(KILL_SWITCH_ENV, "").strip()
    return {
        "engaged": publish_kill_switch_engaged(),
        "configured": raw,
        "env": KILL_SWITCH_ENV,
    }


__all__ = [
    "KILL_SWITCH_ENV",
    "PublishingHalted",
    "publish_kill_switch_engaged",
    "assert_publishing_allowed",
    "kill_switch_status",
]
