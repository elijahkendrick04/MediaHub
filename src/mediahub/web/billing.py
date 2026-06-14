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
            "Auto scheduling",
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


@dataclass(frozen=True)
class FeatureRow:
    """One row of the ``/pricing`` feature-comparison matrix (UI 1.20).

    A cell is ``True`` (included → ✓), ``False`` (not included → ✗), or a
    short string (a specific value/limit, e.g. ``"Unlimited"`` / ``"3 / month"``
    — which implies *included*). The cell attribute names are deliberately the
    plan ids (``free`` / ``club`` / ``federation``) so the web layer can read a
    cell with ``getattr(row, plan)`` / :func:`cell_for`.

    ``card`` flags the high-signal rows that also render as the per-tier
    check/cross list on the plan cards. This matrix is the **single source of
    truth** for both the cards' check/cross lists and the full comparison
    table; like ``TIERS`` it carries **no price** — the figure is still the
    evidence-gated annual list price resolved at render time.
    """

    group: str
    label: str
    free: "bool | str"
    club: "bool | str"
    federation: "bool | str"
    card: bool = False


# The pricing comparison matrix. Derived from (and kept consistent with) the
# ``TIERS`` copy above — that is the marketing summary, this is the row-by-row
# grid. Order here is the render order; rows sharing a ``group`` are emitted
# under one group heading (see :func:`comparison_groups`).
COMPARISON_ROWS: tuple[FeatureRow, ...] = (
    FeatureRow(
        "Content & generation",
        "Content runs",
        "3 / month",
        "Unlimited",
        "Unlimited",
        card=True,
    ),
    FeatureRow(
        "Content & generation",
        "On-brand captions, graphics & motion",
        True,
        True,
        True,
    ),
    FeatureRow(
        "Content & generation",
        "Priority rendering",
        False,
        True,
        True,
        card=True,
    ),
    FeatureRow(
        "Content & generation",
        "Manual export — copy & download",
        True,
        True,
        True,
    ),
    FeatureRow(
        "Branding",
        "Brand profiles",
        "1",
        "1",
        "Multi-club",
        card=True,
    ),
    FeatureRow(
        "Scheduling & scale",
        "Auto scheduling",
        False,
        True,
        True,
        card=True,
    ),
    FeatureRow(
        "Scheduling & scale",
        "Multi-club workspaces",
        False,
        False,
        True,
        card=True,
    ),
    FeatureRow(
        "Scheduling & scale",
        "Enterprise tools",
        False,
        False,
        True,
    ),
    FeatureRow(
        "Support",
        "Support",
        "Community",
        "Email",
        "Onboarding & priority",
        card=True,
    ),
)


def cell_for(row: FeatureRow, plan: str) -> "bool | str":
    """Read a plan's cell from a comparison row.

    Plan ids map straight onto the :class:`FeatureRow` attributes; an unknown
    plan (e.g. the operator-only ``owner`` tier, never shown on /pricing) reads
    as ``False`` rather than raising.
    """
    return getattr(row, plan, False)


def comparison_groups() -> list[tuple[str, list[FeatureRow]]]:
    """``COMPARISON_ROWS`` as ordered ``(group_name, rows)`` pairs.

    Preserves declaration order and coalesces consecutive rows that share a
    group — the render order is the data order.
    """
    groups: list[tuple[str, list[FeatureRow]]] = []
    for row in COMPARISON_ROWS:
        if not groups or groups[-1][0] != row.group:
            groups.append((row.group, []))
        groups[-1][1].append(row)
    return groups


def card_rows() -> tuple[FeatureRow, ...]:
    """The high-signal rows shown as the per-tier check/cross list on cards."""
    return tuple(r for r in COMPARISON_ROWS if r.card)


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


def create_quote_checkout_session(
    *,
    quote_id: str,
    club_name: str,
    amount_pence: int,
    currency: str,
    customer_email: str,
    success_url: str,
    cancel_url: str,
) -> str:
    """Create a Checkout Session at an operator-quoted ANNUAL price (PC.4).

    Price discovery quotes a *real, varying* annual figure per club before any
    public list price exists, so this uses ad-hoc ``price_data`` (annual
    recurring) rather than a configured Price ID. ``mediahub_quote_id`` rides
    the session + subscription metadata; the signed webhook uses it — together
    with the Stripe-reported amount — to record verified revealed-WTP evidence
    against the quote ledger. The buyer lands on the Club plan like any other
    checkout (``plan`` metadata is honoured by the existing webhook path).
    """
    stripe = _stripe()
    try:
        amount = int(amount_pence)
    except (TypeError, ValueError):
        raise BillingError("quote amount must be an integer number of pence")
    if amount <= 0:
        raise BillingError("quote amount must be positive")
    if not (quote_id or "").strip():
        raise BillingError("missing quote id")
    metadata = {
        "plan": PLAN_CLUB,
        "mediahub_email": customer_email or "",
        "mediahub_quote_id": quote_id,
    }
    kwargs: dict = {
        "mode": "subscription",
        "line_items": [
            {
                "price_data": {
                    "currency": (currency or "gbp").lower(),
                    "unit_amount": amount,
                    "recurring": {"interval": "year"},
                    "product_data": {
                        "name": f"MediaHub Club — {club_name} (annual)",
                    },
                },
                "quantity": 1,
            }
        ],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": customer_email or quote_id,
        "subscription_data": {"metadata": metadata},
        "metadata": metadata,
    }
    if customer_email:
        kwargs["customer_email"] = customer_email
    try:
        sess = stripe.checkout.Session.create(**kwargs)
    except Exception as exc:
        raise BillingError(f"could not start quote checkout: {exc}") from exc
    url = getattr(sess, "url", None) or (sess.get("url") if isinstance(sess, dict) else None)
    if not url:
        raise BillingError("Stripe did not return a checkout URL")
    return url


def grant_referral_reward(
    customer_id: str,
    *,
    amount_off_pence: int,
    currency: str = "gbp",
    referred_club: str = "",
) -> str:
    """Grant the PC.9 referral reward: one free month off the referrer's
    next renewal, as a single-use Stripe coupon. Returns the coupon id.

    The amount is the referrer's own verified annual price / 12, computed by
    the caller from the WTP ledger — this function never invents a figure.
    Applied to the referrer's active subscription when one exists, else as a
    customer-level discount (consumed by their next invoice).
    """
    stripe = _stripe()
    cid = (customer_id or "").strip()
    if not cid:
        raise BillingError("missing referrer customer id")
    try:
        amount = int(amount_off_pence)
    except (TypeError, ValueError):
        raise BillingError("reward amount must be an integer number of pence")
    if amount <= 0:
        raise BillingError("reward amount must be positive")
    # Stripe caps coupon names at 40 chars.
    name = f"Referral reward — {referred_club}".strip()[:40] or "Referral reward"
    try:
        coupon = stripe.Coupon.create(
            amount_off=amount,
            currency=(currency or "gbp").lower(),
            duration="once",
            name=name,
            metadata={"mediahub_referred_club": referred_club or ""},
        )
        coupon_id = getattr(coupon, "id", None) or (
            coupon.get("id") if isinstance(coupon, dict) else None
        )
        if not coupon_id:
            raise BillingError("Stripe did not return a coupon id")
        subs = stripe.Subscription.list(customer=cid, status="active", limit=1)
        data = getattr(subs, "data", None) or (subs.get("data") if isinstance(subs, dict) else [])
        if data:
            sub_id = getattr(data[0], "id", None) or data[0].get("id")
            stripe.Subscription.modify(sub_id, coupon=coupon_id)
        else:
            stripe.Customer.modify(cid, coupon=coupon_id)
    except BillingError:
        raise
    except Exception as exc:
        raise BillingError(f"could not grant referral reward: {exc}") from exc
    return coupon_id


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
    find the user; ``plan`` is the plan the account should now hold. When the
    checkout originated from a PC.4 price-discovery quote, ``quote_id`` plus
    the Stripe-reported ``amount_total_pence``/``currency``/``event_id`` let
    the web layer record verified revealed-WTP evidence (idempotently).
    """

    plan: str
    email: str = ""
    customer_id: str = ""
    event_type: str = ""
    quote_id: str = ""
    amount_total_pence: Optional[int] = None
    currency: str = ""
    event_id: str = ""


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
        amount_total = field("amount_total", None)
        try:
            amount_total = int(amount_total) if amount_total is not None else None
        except (TypeError, ValueError):
            amount_total = None
        return SubscriptionUpdate(
            plan=plan or PLAN_CLUB,
            email=str(email or ""),
            customer_id=str(customer_id or ""),
            event_type=etype,
            quote_id=str(_meta_get(metadata, "mediahub_quote_id") or ""),
            amount_total_pence=amount_total,
            currency=str(field("currency", "") or "").lower(),
            event_id=str(_get(event, "id", "") or ""),
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
