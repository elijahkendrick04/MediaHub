"""
PC.2 — Stripe billing: Checkout, the Customer Portal, and a signed webhook.

This is the billing half of Phase C (Appendix B Step 7). It is the **only**
module that reads Stripe secrets, and it reads every one of them from the
process environment — never a literal in source (CLAUDE.md secrets rule):

  - ``STRIPE_SECRET_KEY``     — the API key (``sk_test_…`` / ``sk_live_…``).
  - ``STRIPE_WEBHOOK_SECRET`` — the endpoint signing secret (``whsec_…``).
  - ``STRIPE_PRICE_CLUB``     — the Stripe Price id for the Club tier.
  - ``STRIPE_PRICE_FEDERATION`` — the Stripe Price id for the Federation tier.

**No price amount is hardcoded anywhere.** Pricing is unvalidated and being
decided in parallel (ADR-0011 / PC.4); the tier → Stripe-price mapping is the
``STRIPE_PRICE_*`` env vars and nothing else. That is precisely what lets this
build ship in parallel with the pricing decision.

**Honest-error / self-host-safe.** With ``STRIPE_SECRET_KEY`` unset,
``billing_configured()`` is ``False``, no Stripe network call is ever made,
and the web layer turns every billing route into a clean
``503 "billing is not configured for this deployment"``. There is no fake or
stubbed billing path — a deployment without Stripe simply has no billing, and
every existing route stays open.

``stripe`` is imported lazily so the package is only required when billing is
actually configured; a self-host install without the dependency still boots.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .auth import PLAN_CLUB, PLAN_FEDERATION, PLAN_FREE

# Public, non-secret message reused by the web layer for every billing route
# when Stripe is not configured.
NOT_CONFIGURED_MESSAGE = "billing is not configured for this deployment"


class BillingNotConfigured(Exception):
    """Raised when a billing action is attempted with no Stripe config."""


class BillingError(Exception):
    """A billing operation failed (Stripe API / signature / bad input)."""


@dataclass(frozen=True)
class TierInfo:
    plan: str
    name: str
    blurb: str
    features: tuple[str, ...]


# Tier catalogue — copy + feature lists only. **Deliberately no price** here;
# the displayed price is whatever the Stripe Price (resolved from the env id)
# says, so the unvalidated number lives in Stripe + env, never in the repo.
TIERS: tuple[TierInfo, ...] = (
    TierInfo(
        plan=PLAN_FREE,
        name="Free",
        blurb="Get a feel for MediaHub on one club.",
        features=(
            "3 content runs / month",
            "1 brand profile",
            "On-brand captions, graphics & motion",
            "Manual export (copy / download)",
            "Community support",
        ),
    ),
    TierInfo(
        plan=PLAN_CLUB,
        name="Club",
        blurb="For a single club posting regularly.",
        features=(
            "Unlimited content runs",
            "1 brand profile",
            "Buffer scheduling",
            "Priority rendering",
            "Email support",
        ),
    ),
    TierInfo(
        plan=PLAN_FEDERATION,
        name="Federation",
        blurb="For governing bodies and multi-club operators.",
        features=(
            "Everything in Club",
            "Multi-club workspaces",
            "Enterprise tools",
            "Onboarding & priority support",
        ),
    ),
)

# Map a paid plan to the env var holding its Stripe Price id.
_PLAN_PRICE_ENV = {
    PLAN_CLUB: "STRIPE_PRICE_CLUB",
    PLAN_FEDERATION: "STRIPE_PRICE_FEDERATION",
}


def _secret_key() -> str:
    return os.environ.get("STRIPE_SECRET_KEY", "").strip()


def _webhook_secret() -> str:
    return os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()


def billing_configured() -> bool:
    """True only when a Stripe secret key is present in the environment.

    This is the single gate the web layer checks before serving any billing
    action. No key → no billing → honest 503; the rest of the app is unaffected.
    """
    return bool(_secret_key())


def price_id_for_plan(plan: str) -> str:
    """Return the configured Stripe Price id for a paid plan ('' if unset)."""
    env_name = _PLAN_PRICE_ENV.get(plan)
    if not env_name:
        return ""
    return os.environ.get(env_name, "").strip()


def plan_purchasable(plan: str) -> bool:
    """True when billing is configured *and* this plan has a price id wired."""
    return billing_configured() and bool(price_id_for_plan(plan))


def _stripe():
    """Lazily import + configure the Stripe SDK. Raises if not configured."""
    key = _secret_key()
    if not key:
        raise BillingNotConfigured(NOT_CONFIGURED_MESSAGE)
    try:
        import stripe  # imported lazily so self-host without the dep still boots
    except ImportError as exc:  # pragma: no cover - dependency always present here
        raise BillingError("the stripe package is not installed") from exc
    stripe.api_key = key
    return stripe


def create_checkout_session(
    *,
    plan: str,
    customer_email: str,
    success_url: str,
    cancel_url: str,
    client_reference_id: Optional[str] = None,
    customer_id: Optional[str] = None,
) -> str:
    """Create a Stripe Checkout Session for ``plan`` and return its URL.

    ``client_reference_id`` (the user's email) is echoed back on the
    ``checkout.session.completed`` webhook so we can attribute the new
    subscription to the right account.
    """
    # Not-configured takes precedence so callers get the honest
    # BillingNotConfigured (→ 503) rather than a generic price error.
    stripe = _stripe()
    if plan not in _PLAN_PRICE_ENV:
        raise BillingError(f"'{plan}' is not a purchasable plan")
    price_id = price_id_for_plan(plan)
    if not price_id:
        raise BillingError(f"no Stripe price configured for the {plan} plan")
    kwargs: dict = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": client_reference_id or customer_email,
        # Carry the plan + account on the subscription so webhook events that
        # don't echo the checkout session can still be reconciled.
        "subscription_data": {
            "metadata": {"plan": plan, "mediahub_email": customer_email},
        },
        "metadata": {"plan": plan, "mediahub_email": customer_email},
    }
    # Reuse an existing customer when we have one, else let Stripe create one
    # keyed to the email.
    if customer_id:
        kwargs["customer"] = customer_id
    elif customer_email:
        kwargs["customer_email"] = customer_email
    try:
        sess = stripe.checkout.Session.create(**kwargs)
    except Exception as exc:  # Stripe raises a family of errors; surface cleanly
        raise BillingError(f"could not start checkout: {exc}") from exc
    url = getattr(sess, "url", None) or (sess.get("url") if isinstance(sess, dict) else None)
    if not url:
        raise BillingError("Stripe did not return a checkout URL")
    return url


def create_customer_portal_session(*, customer_id: str, return_url: str) -> str:
    """Create a Stripe Customer Portal session and return its URL."""
    stripe = _stripe()
    if not customer_id:
        raise BillingError("no Stripe customer on this account yet")
    try:
        sess = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
    except Exception as exc:
        raise BillingError(f"could not open the billing portal: {exc}") from exc
    url = getattr(sess, "url", None) or (sess.get("url") if isinstance(sess, dict) else None)
    if not url:
        raise BillingError("Stripe did not return a portal URL")
    return url


@dataclass
class SubscriptionUpdate:
    """Normalised result of a billing webhook the web layer can act on.

    Exactly one identity field (``email`` or ``customer_id``) is enough to
    find the user; ``plan`` is the plan the account should now hold.
    """

    plan: str
    email: str = ""
    customer_id: str = ""
    event_type: str = ""


def verify_and_parse_webhook(
    payload: bytes,
    signature_header: str,
) -> Optional[SubscriptionUpdate]:
    """Verify a Stripe webhook signature and map it to a plan change.

    Returns a ``SubscriptionUpdate`` for events that change a subscription's
    state, or ``None`` for events we don't act on. Raises ``BillingError`` on a
    bad/forged signature so the route can answer ``400`` — an unverified
    payload is never trusted.
    """
    secret = _webhook_secret()
    stripe = _stripe()
    if not secret:
        raise BillingError("STRIPE_WEBHOOK_SECRET is not configured")
    try:
        event = stripe.Webhook.construct_event(payload, signature_header, secret)
    except stripe.error.SignatureVerificationError as exc:  # type: ignore[attr-defined]
        raise BillingError("invalid webhook signature") from exc
    except ValueError as exc:  # malformed JSON
        raise BillingError("invalid webhook payload") from exc
    except Exception as exc:  # any other construct/shape error → don't trust it
        raise BillingError("could not parse webhook event") from exc
    return _interpret_event(event)


def _get(obj, key, default=None):
    """Read ``key`` from a Stripe ``StripeObject`` or a plain dict, uniformly.

    Both support ``.get``; ``StripeObject`` additionally exposes attributes,
    but ``.get`` is the safe path that never raises on a missing key (attribute
    access on a ``StripeObject`` raises ``AttributeError``). Falls back to
    ``getattr`` for any other object shape (defensive).
    """
    if obj is None:
        return default
    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except Exception:
            pass
    return getattr(obj, key, default)


def _meta_get(metadata, key, default=""):
    """Read a metadata value tolerating dict / StripeObject / None."""
    return _get(metadata, key, default) if metadata is not None else default


def _interpret_event(event) -> Optional[SubscriptionUpdate]:
    """Translate a verified Stripe event into a plan change, or ``None``."""
    etype = _get(event, "type", "") or ""
    data = _get(event, "data", {}) or {}
    obj = _get(data, "object", {}) or {}

    def field(name, default=""):
        return _get(obj, name, default)

    metadata = field("metadata", {}) or {}
    email = (
        _meta_get(metadata, "mediahub_email")
        or field("client_reference_id")
        or field("customer_email")
        or ""
    )
    customer_id = field("customer", "") or ""

    if etype == "checkout.session.completed":
        plan = _meta_get(metadata, "plan") or _plan_from_subscription_items(field("line_items"))
        return SubscriptionUpdate(
            plan=plan or PLAN_CLUB,
            email=str(email or ""),
            customer_id=str(customer_id or ""),
            event_type=etype,
        )

    if etype in ("customer.subscription.created", "customer.subscription.updated"):
        status = field("status", "")
        if status in ("canceled", "unpaid", "incomplete_expired"):
            return SubscriptionUpdate(
                plan=PLAN_FREE,
                email=str(email or ""),
                customer_id=str(customer_id or ""),
                event_type=etype,
            )
        plan = _meta_get(metadata, "plan") or _plan_from_subscription_items(field("items"))
        return SubscriptionUpdate(
            plan=plan or PLAN_CLUB,
            email=str(email or ""),
            customer_id=str(customer_id or ""),
            event_type=etype,
        )

    if etype == "customer.subscription.deleted":
        return SubscriptionUpdate(
            plan=PLAN_FREE,
            email=str(email or ""),
            customer_id=str(customer_id or ""),
            event_type=etype,
        )

    # Any other event type: nothing to do.
    return None


def _plan_from_subscription_items(items) -> str:
    """Best-effort: map the price id on a subscription's items back to a plan.

    Used when an event carries no plan metadata (e.g. a portal-driven change).
    Compares against the configured ``STRIPE_PRICE_*`` ids so the mapping stays
    env-driven.
    """
    price_ids = _collect_price_ids(items)
    if not price_ids:
        return ""
    club = price_id_for_plan(PLAN_CLUB)
    fed = price_id_for_plan(PLAN_FEDERATION)
    if fed and fed in price_ids:
        return PLAN_FEDERATION
    if club and club in price_ids:
        return PLAN_CLUB
    return ""


def _collect_price_ids(items) -> set[str]:
    """Pull price ids out of a Stripe items collection or a plain list/dict."""
    out: set[str] = set()
    if not items:
        return out
    data = _get(items, "data", items)
    if not data:
        return out
    for line in data:
        price = _get(line, "price")
        pid = _get(price, "id") if price is not None else None
        if pid:
            out.add(str(pid))
    return out
