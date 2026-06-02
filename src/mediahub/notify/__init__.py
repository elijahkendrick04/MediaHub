"""mediahub.notify — provider-agnostic notifications (push / webhook).

Fires short notifications on workflow milestones — chiefly "your content pack is
ready for review" the moment a run finishes — to whatever channels the operator
configured (ntfy push, a generic webhook). **OFF by default:** with no channel
configured, :func:`notify` is a no-op and costs nothing. Delivery is best-effort
and never raises, so a notification failure can never break the run/pipeline that
triggered it; sends run in a background thread so they never delay a request.

No daemon is bundled and no new dependency is added — ntfy/webhook are thin HTTP
POSTs over the existing ``requests`` dependency.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from mediahub.notify.channels import Channel, Notification, all_channels

log = logging.getLogger(__name__)


def configured_channels() -> list[Channel]:
    return [c for c in all_channels() if c.configured()]


def is_enabled() -> bool:
    """True when at least one notification channel is configured."""
    return bool(configured_channels())


def _send_all(channels: list[Channel], n: Notification) -> int:
    sent = 0
    for c in channels:
        try:
            if c.send(n):
                sent += 1
        except Exception as e:  # a channel must never break the others / the caller
            log.warning("notify channel %s errored: %s", getattr(c, "name", "?"), e)
    return sent


def notify(
    title: str,
    message: str,
    *,
    priority: str = "default",
    tags=(),
    click_url: Optional[str] = None,
    background: bool = True,
) -> int:
    """Send a notification to every configured channel.

    Returns the number of channels the send was dispatched to (when
    ``background``) or actually accepted it (when not). A no-op returning 0 when
    nothing is configured. Never raises.
    """
    channels = configured_channels()
    if not channels:
        return 0
    n = Notification(
        title=str(title),
        message=str(message),
        priority=priority,
        tags=tuple(tags),
        click_url=click_url,
    )
    if background:
        threading.Thread(target=_send_all, args=(channels, n), daemon=True, name="notify").start()
        return len(channels)
    return _send_all(channels, n)


def notify_pack_ready(
    run_id: str,
    *,
    count: Optional[int] = None,
    click_url: Optional[str] = None,
    background: bool = True,
) -> int:
    """Convenience: the "content pack is ready for review" ping fired when a run
    finishes. Inert (0) unless a channel is configured."""
    if count is not None:
        message = f"{count} card{'s' if count != 1 else ''} ready for review (run {run_id})."
    else:
        message = f"Your content pack is ready for review (run {run_id})."
    return notify(
        "Pack ready for review",
        message,
        priority="high",
        tags=("white_check_mark",),
        click_url=click_url,
        background=background,
    )


__all__ = ["notify", "notify_pack_ready", "is_enabled", "configured_channels"]
