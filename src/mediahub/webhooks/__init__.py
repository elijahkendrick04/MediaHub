"""mediahub.webhooks — outbound signed webhooks (roadmap 1.21).

MediaHub's own webhooks: a club or federation registers a URL, picks the events
it cares about (`run.finished`, `card.approved`, `pack.exported`,
`form.submitted`), and MediaHub POSTs a signed JSON payload when they happen.
This is how clubs wire MediaHub into anything — including, via *their* own
Zapier/Make accounts, the long tail (we publish recipes; we don't embed their
runtimes).

Every delivery is **HMAC-SHA256 signed** (`signing.py`, Stripe-style header) so
a receiver can prove authenticity and freshness. Deliveries are durable and
**retried with exponential backoff** (`delivery.py`); the scheduler runs the
retry sweep. Endpoints are per-organisation and tenant-isolated (`registry.py`).

Public entry point: ``emit(event, profile_id, payload)`` — best-effort, never
raises, fired from the engine's event chokepoints in ``web.py``.
"""

from __future__ import annotations

from .delivery import DeliveryStore, deliver_now, deliver_pending, emit
from .events import ALL_EVENTS, EVENTS, validate_events
from .registry import EndpointStore, WebhookEndpoint

__all__ = [
    "emit",
    "deliver_now",
    "deliver_pending",
    "DeliveryStore",
    "EndpointStore",
    "WebhookEndpoint",
    "EVENTS",
    "ALL_EVENTS",
    "validate_events",
]
