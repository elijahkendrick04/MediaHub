"""governance/quota.py — per-org / per-feature AI quota policy (1.23).

The raw counting lives in :mod:`mediahub.observability.feature_quota`; this
module is the *decision* layer on top of it. It answers:

  * What is org X's limit for feature Y on plan Z?  (``limit_for``)
  * Where does org X stand against that limit?       (``check``)
  * Should this call be blocked?                      (``enforce``)
  * Record that org X used feature Y.                 (``record``)

Enforcement policy (maintainer decision, 2026-06-24): **meter everything, but
hard-block only where a specific limit is configured.** A feature with no
configured limit returns ``limit == UNLIMITED`` (-1): usage is still counted and
shown (headroom, dashboards) but :func:`enforce` never raises. The moment an
operator sets a positive limit — via the built-in plan table or an env override
or a per-org override — that feature hard-blocks with an honest
:class:`QuotaExceeded` once the org is at or over the limit. Nothing fabricated,
nothing silently dropped: an over-quota call raises and the route surfaces it,
exactly like the generative-imagery quota already does.

Limit resolution order (first hit wins):

  1. explicit ``org_override`` (per-org setting, e.g. from /settings/governance)
  2. env ``MEDIAHUB_QUOTA_<FEATURE>_<PLAN>``     (feature + plan specific)
  3. env ``MEDIAHUB_QUOTA_<FEATURE>``            (feature-wide, all plans)
  4. built-in ``_PLAN_FEATURE_LIMITS[plan][feature]``
  5. UNLIMITED (-1) — meter only, never block

The built-in table ships empty (everything unlimited) so this build cannot
break an existing club's flow; it is the one place real plan-tier numbers get
folded in later (the PC.4 commercial pass).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from ..observability import feature_quota
from . import features

log = logging.getLogger(__name__)

# Sentinel for "no limit configured — meter only, never block".
UNLIMITED = -1

# Fraction of a configured limit at which the dashboard/route starts warning.
WARN_FRACTION = 0.8

# Known plan tiers (mirrors auth.User.plan). Used only to validate env names and
# normalise input; an unknown plan simply finds no built-in/env limit and falls
# through to UNLIMITED.
KNOWN_PLANS = ("free", "club", "federation", "owner")

# Built-in per-plan, per-feature limits (rolling 30-day window). Ships EMPTY so
# nothing hard-blocks until a real limit is set. This is the single place to
# fold in commercial tier numbers later — e.g.
#   "free": {features.FEATURE_CAPTION: 200, features.FEATURE_IMAGINE: 50},
_PLAN_FEATURE_LIMITS: dict[str, dict[str, int]] = {}


class QuotaExceeded(RuntimeError):
    """An org has reached a configured limit for a feature.

    Carries structured fields so a route can render an honest, specific message
    ("AI captions: 200/200 used this month") rather than a generic 429.
    """

    def __init__(self, feature: str, used: int, limit: int):
        self.feature = feature
        self.used = used
        self.limit = limit
        label = features.label_for(feature)
        super().__init__(
            f"{label} quota reached ({used}/{limit} used this month). "
            f"It resets on a rolling 30-day window."
        )


@dataclass
class QuotaStatus:
    """Where an org stands against a feature's quota."""

    feature: str
    ok: bool  # True if under the limit OR the feature is unmetered
    limit: int  # UNLIMITED (-1) = no limit configured
    used: int
    remaining: int  # UNLIMITED (-1) = no limit configured
    enforced: bool  # True only when a real (>=0) limit is configured
    warn: bool = False  # True when enforced and within WARN_FRACTION of the cap
    plan: str = ""


def _norm_plan(plan: object) -> str:
    return str(plan or "").strip().lower()


def _env_int(name: str) -> Optional[int]:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        log.warning("governance.quota: ignoring non-integer %s=%r", name, raw)
        return None


def limit_for(
    plan: object,
    feature: object,
    *,
    org_override: Optional[int] = None,
) -> int:
    """Resolve the configured limit for ``(plan, feature)``.

    Returns ``UNLIMITED`` (-1) when no limit is configured anywhere — the
    common case in this build. A non-negative return means enforcement is on.
    """
    feat = features.normalise(feature)
    pl = _norm_plan(plan)

    # 1. explicit per-org override (a negative value explicitly means unlimited)
    if org_override is not None:
        try:
            return int(org_override)
        except (TypeError, ValueError):
            pass

    # 2 + 3. env overrides (feature+plan, then feature-wide)
    feat_token = feat.upper()
    if pl:
        v = _env_int(f"MEDIAHUB_QUOTA_{feat_token}_{pl.upper()}")
        if v is not None:
            return v
    v = _env_int(f"MEDIAHUB_QUOTA_{feat_token}")
    if v is not None:
        return v

    # 4. built-in plan table
    by_plan = _PLAN_FEATURE_LIMITS.get(pl)
    if by_plan and feat in by_plan:
        return int(by_plan[feat])

    # 5. unlimited — meter only
    return UNLIMITED


def _used(org_id: str, feature: str, window_hours: Optional[int]) -> int:
    if not org_id:
        return 0
    feat = features.normalise(feature)
    # Generative imagery is metered in its own dedicated ledger.
    if feat == features.FEATURE_IMAGINE:
        try:
            from ..observability import imagine_usage

            return imagine_usage.count_for_org(
                org_id, window_hours=window_hours or imagine_usage.MONTHLY_WINDOW_HOURS
            )
        except Exception as exc:  # pragma: no cover - fail open
            log.warning("governance.quota: imagine usage read failed: %s", exc)
            return 0
    return feature_quota.count_for_org(
        org_id,
        feature=feat,
        window_hours=window_hours or feature_quota.MONTHLY_WINDOW_HOURS,
    )


def check(
    org_id: str,
    feature: object,
    *,
    plan: object = None,
    window_hours: Optional[int] = None,
    org_override: Optional[int] = None,
) -> QuotaStatus:
    """Where ``org_id`` stands against its quota for ``feature``.

    Always counts usage (for headroom/dashboards). Sets ``enforced=False`` and
    ``ok=True`` when no limit is configured — the metering-only default.
    """
    feat = features.normalise(feature)
    pl = _norm_plan(plan)
    limit = limit_for(pl, feat, org_override=org_override)
    used = _used(org_id, feat, window_hours)

    if limit < 0:
        return QuotaStatus(
            feature=feat,
            ok=True,
            limit=UNLIMITED,
            used=used,
            remaining=UNLIMITED,
            enforced=False,
            warn=False,
            plan=pl,
        )
    remaining = max(0, limit - used)
    ok = used < limit
    warn = ok and limit > 0 and used >= int(limit * WARN_FRACTION)
    return QuotaStatus(
        feature=feat,
        ok=ok,
        limit=limit,
        used=used,
        remaining=remaining,
        enforced=True,
        warn=warn,
        plan=pl,
    )


def enforce(
    org_id: str,
    feature: object,
    *,
    plan: object = None,
    org_override: Optional[int] = None,
) -> None:
    """Raise :class:`QuotaExceeded` iff a limit is set for the feature and the
    org is at or over it. A no-op for unmetered features (the default)."""
    if not org_id:
        return
    status = check(org_id, feature, plan=plan, org_override=org_override)
    if status.enforced and not status.ok:
        raise QuotaExceeded(status.feature, status.used, status.limit)


def record(
    org_id: str,
    feature: object,
    *,
    ok: bool = True,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    detail: Optional[str] = None,
    error: Optional[BaseException] = None,
) -> None:
    """Record one feature invocation in the shared ledger (best-effort).

    Generative imagery records into its own ledger via ``media_ai.imagine`` and
    is skipped here to avoid double-counting.
    """
    if not org_id:
        return
    feat = features.normalise(feature)
    if feat == features.FEATURE_IMAGINE:
        return
    feature_quota.record_use(
        org_id=org_id,
        feature=feat,
        ok=ok,
        provider=provider,
        model=model,
        detail=detail,
        error_kind=type(error).__name__ if error is not None else None,
        error_message=str(error)[:500] if error is not None else None,
    )


def reserve(
    org_id: str,
    feature: object,
    *,
    plan: object = None,
    org_override: Optional[int] = None,
) -> Optional[int]:
    """Atomically reserve a metered slot BEFORE the work runs (deep-review #95).

    Replaces the check-then-act ``enforce()`` + ``record()`` split for concurrency
    safety: an atomic INSERT-if-under-limit means N concurrent requests at
    ``limit - 1`` can no longer all pass the gate. Raises :class:`QuotaExceeded`
    when the org is at the limit. Returns a reservation id to hand to
    :func:`finalize` when a metered slot was taken, or ``None`` when the feature
    is unmetered (the caller still calls :func:`finalize`, which records normally
    on a ``None`` reservation).

    Fails OPEN on any DB error — a transient hiccup never wrongly blocks a paying
    club (matching ``check()``'s fail-open read).
    """
    if not org_id:
        return None
    feat = features.normalise(feature)
    # Generative imagery is metered in its own ledger (imagine_usage); its own
    # reservation path is out of scope for #95's governance-quota fix.
    if feat == features.FEATURE_IMAGINE:
        return None
    pl = _norm_plan(plan)
    limit = limit_for(pl, feat, org_override=org_override)
    if limit < 0:
        return None  # unmetered — nothing to reserve
    try:
        rid = feature_quota.reserve_use(
            org_id=org_id,
            feature=feat,
            limit=limit,
            window_hours=feature_quota.MONTHLY_WINDOW_HOURS,
        )
    except Exception as exc:  # pragma: no cover - fail open on DB failure
        log.warning("governance.quota: reserve failed (fail-open): %s", exc)
        return None
    if rid is None:
        # At the limit — the atomic insert reserved nothing.
        used = _used(org_id, feat, None)
        raise QuotaExceeded(feat, used, limit)
    return rid


def finalize(
    org_id: str,
    feature: object,
    reservation: Optional[int],
    *,
    ok: bool = True,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    detail: Optional[str] = None,
    error: Optional[BaseException] = None,
) -> None:
    """Finalize a :func:`reserve` outcome (deep-review #95).

    With a reservation id: update the reserved row — attach metadata on success,
    or release it (``ok=0``) on failure so a failed billed call is not charged to
    quota. Without one (unmetered, fail-open, or the imagine ledger): fall back to
    a plain :func:`record` so metering is unchanged. Best-effort.
    """
    if not org_id:
        return
    feat = features.normalise(feature)
    if reservation is None:
        record(org_id, feature, ok=ok, provider=provider, model=model, detail=detail, error=error)
        return
    if feat == features.FEATURE_IMAGINE:
        return
    feature_quota.finalize_use(
        reservation,
        ok=ok,
        provider=provider,
        model=model,
        detail=detail,
        error_kind=type(error).__name__ if error is not None else None,
        error_message=str(error)[:500] if error is not None else None,
    )


__all__ = [
    "UNLIMITED",
    "WARN_FRACTION",
    "KNOWN_PLANS",
    "QuotaExceeded",
    "QuotaStatus",
    "limit_for",
    "check",
    "enforce",
    "record",
    "reserve",
    "finalize",
]
