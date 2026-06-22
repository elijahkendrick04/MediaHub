"""The print fulfilment slot — optional, flag-gated, off by default (roadmap 1.20).

*Fulfilment* (the factory that actually prints and posts a product) is the one
part of the print pipeline that can't be first-party — it ends at someone else's
press. So it ships as an **optional slot behind our own interface**, not a wired
integration. The default product is always the **print-ready file download**
(`print_ready.engine`); this module only exists so a real provider can be slotted
in later without reshaping anything.

Standing rules it keeps:
- **Off by default.** With no ``MEDIAHUB_FULFILMENT_PROVIDER`` set, the active
  provider is the :class:`NullProvider`, which honest-errors
  (:class:`FulfilmentUnavailable`) on every call — it never pretends an order was
  placed (the honest-error rule).
- **In-house first (rule 11).** The order schema and the provider *interface* are
  ours; an external print company is a swappable adapter behind it, never
  hardwired, and surfaces its own guarantees / eco options honestly as
  attributes rather than us inventing them.
- **Human approval before anything leaves.** Like the rest of MediaHub, a person
  approves a design before it could ever be sent to a printer; nothing here
  publishes autonomously.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

DEFAULT_PROVIDER = "none"
_ENV_PROVIDER = "MEDIAHUB_FULFILMENT_PROVIDER"


class FulfilmentUnavailable(RuntimeError):
    """No fulfilment provider is enabled (or the call can't be served).

    Honest by design: the club still has the print-ready file to take to any
    print shop. We never fake an order id, a quote, or a tracking link.
    """


# ---------------------------------------------------------------------------
# Order schema (provider-agnostic)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShipTo:
    name: str
    line1: str
    city: str
    postcode: str
    country: str = "GB"
    line2: str = ""


@dataclass(frozen=True)
class OrderLine:
    """One product to print, with the artwork file per placement."""

    product_slug: str
    artwork: dict = field(default_factory=dict)  # placement slug → file path / ref
    quantity: int = 1
    options: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "product_slug": self.product_slug,
            "artwork": dict(self.artwork),
            "quantity": self.quantity,
            "options": dict(self.options),
        }


@dataclass(frozen=True)
class FulfilmentOrder:
    org_id: str
    lines: tuple[OrderLine, ...]
    ship_to: ShipTo
    reference: str = ""

    def to_dict(self) -> dict:
        return {
            "org_id": self.org_id,
            "reference": self.reference,
            "ship_to": {
                "name": self.ship_to.name,
                "line1": self.ship_to.line1,
                "line2": self.ship_to.line2,
                "city": self.ship_to.city,
                "postcode": self.ship_to.postcode,
                "country": self.ship_to.country,
            },
            "lines": [ln.to_dict() for ln in self.lines],
        }


@dataclass(frozen=True)
class Quote:
    provider: str
    currency: str
    subtotal_pence: int
    shipping_pence: int
    lead_time_days: int
    attributes: dict = field(default_factory=dict)  # guarantees / eco, provider-supplied

    @property
    def total_pence(self) -> int:
        return self.subtotal_pence + self.shipping_pence


@dataclass(frozen=True)
class OrderAck:
    provider: str
    order_id: str
    status: str
    tracking_url: str = ""


# ---------------------------------------------------------------------------
# Provider interface + the honest null default
# ---------------------------------------------------------------------------


@runtime_checkable
class FulfilmentProvider(Protocol):
    """What any print-fulfilment adapter must offer behind our own interface."""

    slug: str
    enabled: bool

    def quote(self, order: FulfilmentOrder) -> Quote: ...

    def submit(self, order: FulfilmentOrder) -> OrderAck: ...

    def order_status(self, order_id: str) -> str: ...


class NullProvider:
    """The default — no provider configured; every call honest-errors."""

    slug = "none"
    enabled = False

    _MSG = (
        "Print fulfilment isn't enabled. Download the print-ready file and order "
        "from any print shop — that's always the default."
    )

    def quote(self, order: FulfilmentOrder) -> Quote:
        raise FulfilmentUnavailable(self._MSG)

    def submit(self, order: FulfilmentOrder) -> OrderAck:
        raise FulfilmentUnavailable(self._MSG)

    def order_status(self, order_id: str) -> str:
        raise FulfilmentUnavailable(self._MSG)


# The provider registry. Only the null provider exists today; a real adapter
# (e.g. a print-on-demand API) would register here behind the same interface,
# flag-gated by MEDIAHUB_FULFILMENT_PROVIDER per the P0.3 swappable-slot pattern.
_PROVIDERS: dict[str, FulfilmentProvider] = {"none": NullProvider()}


def register_provider(provider: FulfilmentProvider) -> None:
    """Register a fulfilment adapter under its ``slug`` (kept for the future slot)."""
    _PROVIDERS[provider.slug] = provider


def available_providers() -> list[str]:
    return sorted(_PROVIDERS)


def current_provider() -> FulfilmentProvider:
    """The active provider from ``MEDIAHUB_FULFILMENT_PROVIDER`` (default: null)."""
    name = os.environ.get(_ENV_PROVIDER, DEFAULT_PROVIDER).strip().lower()
    return _PROVIDERS.get(name, _PROVIDERS["none"])


def fulfilment_enabled() -> bool:
    """True only when a real, enabled provider is configured."""
    return bool(getattr(current_provider(), "enabled", False))


def status() -> dict:
    """An honest status surface for the UI / API."""
    p = current_provider()
    enabled = bool(getattr(p, "enabled", False))
    return {
        "enabled": enabled,
        "provider": getattr(p, "slug", "none"),
        "message": (
            "Fulfilment is enabled."
            if enabled
            else "Download-first: no print-fulfilment provider is configured."
        ),
    }


__all__ = [
    "DEFAULT_PROVIDER",
    "FulfilmentUnavailable",
    "ShipTo",
    "OrderLine",
    "FulfilmentOrder",
    "Quote",
    "OrderAck",
    "FulfilmentProvider",
    "NullProvider",
    "register_provider",
    "available_providers",
    "current_provider",
    "fulfilment_enabled",
    "status",
]
