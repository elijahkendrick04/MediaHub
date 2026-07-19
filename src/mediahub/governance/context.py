"""governance/context.py — request-scoped org/plan + the feature guard (1.23).

AI surface functions (caption generation, palette resolve, …) live deep below
the Flask request and mostly don't take an ``org_id`` argument. Threading one
through every signature would be invasive and easy to get wrong. Instead the web
layer binds the active org + plan into a :class:`contextvars.ContextVar` once per
request (``set_request_context``), and the governance guard reads it.

:func:`feature_scope` is the packaged guard for wiring a surface:

    with governance.feature_scope(features.FEATURE_CAPTION) as scope:
        scope.provider = "gemini"      # optional annotation
        text = do_the_ai_work()

On enter it enforces the quota (raising :class:`~mediahub.governance.quota.QuotaExceeded`
only when a limit is configured and reached — see quota.py). On exit it records
one usage row (ok on success, failure recorded but not charged to quota). When
no org is bound (e.g. the operator, or a background job), it is a transparent
no-op that still runs the body — governance never blocks unattributed internal
work, it just doesn't meter it.

Honest adoption status: the routes metered so far (captions, translation)
interleave the role/permission gate with route-specific error bodies, so they
call :func:`~mediahub.governance.quota.reserve` /
:func:`~mediahub.governance.quota.finalize` directly rather than this wrapper.
``feature_scope`` is the one-liner for wiring the remaining
registered-but-unmetered surfaces (see the package README's honest-status note).

Pure stdlib (contextvars) — no Flask import — so the package stays importable and
testable standalone.
"""

from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from typing import Iterator, Optional

from . import quota

log = logging.getLogger(__name__)

_ctx_org: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "mediahub_gov_org", default=None
)
_ctx_plan: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "mediahub_gov_plan", default=None
)


def set_request_context(org_id: Optional[str], plan: Optional[str] = None) -> None:
    """Bind the active org + plan for the current context (call per request)."""
    _ctx_org.set((org_id or "").strip() or None)
    _ctx_plan.set((plan or "").strip() or None)


def clear_request_context() -> None:
    """Clear the bound org + plan (call on request teardown)."""
    _ctx_org.set(None)
    _ctx_plan.set(None)


def current_org_id() -> Optional[str]:
    """The org bound to the current context, or None."""
    return _ctx_org.get()


def current_plan() -> Optional[str]:
    """The plan bound to the current context, or None."""
    return _ctx_plan.get()


@contextmanager
def bind(org_id: Optional[str], plan: Optional[str] = None) -> Iterator[None]:
    """Context manager that binds org/plan and restores the prior values on exit.

    Handy in tests and background jobs where teardown hooks don't run.
    """
    org_tok = _ctx_org.set((org_id or "").strip() or None)
    plan_tok = _ctx_plan.set((plan or "").strip() or None)
    try:
        yield
    finally:
        _ctx_org.reset(org_tok)
        _ctx_plan.reset(plan_tok)


class FeatureScope:
    """Mutable handle yielded by :func:`feature_scope` for optional annotation.

    Set ``provider`` / ``model`` / ``detail`` inside the ``with`` block and they
    are written onto the recorded usage row when the block exits.
    """

    __slots__ = ("feature", "org_id", "plan", "provider", "model", "detail")

    def __init__(self, feature: str, org_id: Optional[str], plan: Optional[str]):
        self.feature = feature
        self.org_id = org_id
        self.plan = plan
        self.provider: Optional[str] = None
        self.model: Optional[str] = None
        self.detail: Optional[str] = None


@contextmanager
def feature_scope(
    feature: str,
    *,
    org_id: Optional[str] = None,
    plan: Optional[str] = None,
    enforce: bool = True,
    org_override: Optional[int] = None,
) -> Iterator[FeatureScope]:
    """Meter (and optionally enforce) one AI feature invocation.

    ``org_id`` / ``plan`` default to the request-bound context. With no org
    resolved the block runs un-metered (a no-op guard). Enforcement raises
    :class:`~mediahub.governance.quota.QuotaExceeded` *before* the body runs when
    a limit is configured and reached, so a blocked call records nothing (it
    never happened). A body that raises is recorded as a failure (not charged to
    quota); a body that returns is recorded as a success.
    """
    org = (org_id if org_id is not None else current_org_id()) or None
    pl = (plan if plan is not None else current_plan()) or None

    # Atomic reserve-before-work (deep-review #95): reserve() takes the quota slot
    # up front with an atomic INSERT-if-under-limit, so N concurrent requests at
    # the limit can no longer all pass a read-then-act gate. It raises
    # QuotaExceeded when at the limit, and returns a reservation id (metered) or
    # None (unmetered / metering-only / fail-open). The reservation is finalised
    # in the finally below — guaranteed by the context manager even on early exit,
    # so a reserved slot is never leaked.
    reservation: Optional[int] = None
    if enforce and org:
        reservation = quota.reserve(org, feature, plan=pl, org_override=org_override)

    scope = FeatureScope(feature, org, pl)
    if not org:
        # Unattributed internal work — run it, but don't meter.
        yield scope
        return

    ok = True
    err: Optional[BaseException] = None
    try:
        yield scope
    except BaseException as exc:  # noqa: BLE001 - re-raised after recording
        ok = False
        err = exc
        raise
    finally:
        # finalize() updates the reservation (release on failure) when one was
        # taken, or records a plain usage row when it was not (unmetered /
        # metering-only) — so behaviour is unchanged for those paths.
        quota.finalize(
            org,
            feature,
            reservation,
            ok=ok,
            provider=scope.provider,
            model=scope.model,
            detail=scope.detail,
            error=err,
        )


__all__ = [
    "set_request_context",
    "clear_request_context",
    "current_org_id",
    "current_plan",
    "bind",
    "feature_scope",
    "FeatureScope",
]
