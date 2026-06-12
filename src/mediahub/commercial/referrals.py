"""PC.9 — the in-product referral engine.

Runs PC.6's compounding mechanism (2 named intros per signed club) inside
the product instead of operator ledgers:

- every organisation gets a shareable **referral code** (deterministic
  ledger row, unguessable token);
- `/signup?ref=CODE` records the referred club as a lead in the PC.6
  pipeline with ``source=referral`` and the referrer attributed — zero
  operator typing;
- when the referred club's **first annual payment lands amount-verified**
  in the WTP ledger (the idempotent Stripe webhook hook, or an operator's
  manual attestation), the reward auto-grants: one free month as a Stripe
  coupon on the referrer's subscription, valued at the referrer's own
  verified annual price / 12 — never an invented figure. When the value or
  the Stripe subscription can't be resolved, the reward is recorded
  ``pending_manual`` with the reason, honestly, instead of guessing.

Ledgers (append-only JSONL, last-write-wins, 0600 — the commercial/
convention):

    DATA_DIR/commercial/referral_codes.jsonl    one code per org
    DATA_DIR/commercial/referral_rewards.jsonl  one reward per referred club
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .pipeline import (
    Lead,
    LeadStore,
    SOURCE_REFERRAL,
    STATUS_WON,
)

log = logging.getLogger(__name__)

REWARD_GRANTED = "granted"
REWARD_PENDING_MANUAL = "pending_manual"

_LEDGER_LOCK = threading.Lock()


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _data_dir() -> Path:
    src_root = Path(__file__).resolve().parents[2]
    return Path(os.environ.get("DATA_DIR", str(src_root)))


def _codes_path() -> Path:
    return _data_dir() / "commercial" / "referral_codes.jsonl"


def _rewards_path() -> Path:
    return _data_dir() / "commercial" / "referral_rewards.jsonl"


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Referral codes
# ---------------------------------------------------------------------------


@dataclass
class ReferralCode:
    code: str
    profile_id: str
    club_name: str = ""
    created_at: str = ""

    def to_record(self) -> dict:
        return asdict(self)


class ReferralCodeStore:
    """One shareable code per org, last-write-wins per ``profile_id``."""

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path is not None else _codes_path()

    def _by_profile(self) -> dict[str, ReferralCode]:
        out: dict[str, ReferralCode] = {}
        for rec in _read_jsonl(self._path):
            pid = str(rec.get("profile_id") or "").strip()
            code = str(rec.get("code") or "").strip()
            if pid and code:
                out[pid] = ReferralCode(
                    code=code,
                    profile_id=pid,
                    club_name=str(rec.get("club_name") or "").strip(),
                    created_at=str(rec.get("created_at") or ""),
                )
        return out

    def get_or_create(self, profile_id: str, club_name: str = "") -> ReferralCode:
        pid = (profile_id or "").strip()
        if not pid:
            raise ValueError("profile_id required for a referral code")
        with _LEDGER_LOCK:
            existing = self._by_profile().get(pid)
            if existing is not None:
                # Keep the code stable; refresh a missing club name only.
                if club_name and not existing.club_name:
                    updated = ReferralCode(
                        code=existing.code,
                        profile_id=pid,
                        club_name=club_name.strip(),
                        created_at=existing.created_at,
                    )
                    _append_jsonl(self._path, updated.to_record())
                    return updated
                return existing
            rc = ReferralCode(
                # URL-friendly, case-insensitive-safe, hard to guess, short
                # enough to read out at a gala.
                code=secrets.token_urlsafe(6).replace("-", "x").replace("_", "y"),
                profile_id=pid,
                club_name=(club_name or "").strip(),
                created_at=_utc_now_iso(),
            )
            _append_jsonl(self._path, rc.to_record())
            return rc

    def resolve(self, code: str) -> Optional[ReferralCode]:
        needle = (code or "").strip()
        if not needle:
            return None
        for rc in self._by_profile().values():
            if rc.code == needle:
                return rc
        return None


# ---------------------------------------------------------------------------
# Referred signups → pipeline leads
# ---------------------------------------------------------------------------


def record_referred_signup(
    code: str,
    email: str,
    *,
    code_store: Optional[ReferralCodeStore] = None,
    lead_store: Optional[LeadStore] = None,
) -> Optional[Lead]:
    """A new account arrived through ``/signup?ref=CODE``: record the lead.

    The club's real name isn't known at signup, so the lead is keyed by the
    account email (``contact_email``) and named after it until the operator
    or a quote renames it. Idempotent per email: a second signup with the
    same address doesn't duplicate the lead. Invalid codes record nothing —
    a typo must not corrupt the funnel.
    """
    codes = code_store or ReferralCodeStore()
    leads = lead_store or LeadStore()
    rc = codes.resolve(code)
    norm_email = (email or "").strip().lower()
    if rc is None or not norm_email:
        return None
    for lead in leads.list_all():
        if lead.source == SOURCE_REFERRAL and lead.contact_email == norm_email:
            return lead  # already tracked
    referrer_name = rc.club_name or rc.profile_id
    return leads.create(
        norm_email,  # best name available until the club names itself
        source=SOURCE_REFERRAL,
        referrer_club=referrer_name,
        contact_email=norm_email,
        notes=f"self-served signup via referral code {rc.code}",
    )


# ---------------------------------------------------------------------------
# Rewards
# ---------------------------------------------------------------------------


@dataclass
class ReferralReward:
    reward_id: str
    referrer_profile_id: str
    referrer_club: str
    referred_club: str
    referred_email: str
    quote_id: str
    status: str  # granted | pending_manual
    reason: str = ""  # why pending, when pending
    stripe_coupon_id: str = ""
    amount_off_pence: Optional[int] = None
    currency: str = "gbp"
    created_at: str = ""

    def to_record(self) -> dict:
        return asdict(self)


class ReferralRewardStore:
    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path is not None else _rewards_path()

    def list_all(self) -> list[ReferralReward]:
        out = []
        by_id: dict[str, dict] = {}
        for rec in _read_jsonl(self._path):
            rid = str(rec.get("reward_id") or "")
            if rid:
                by_id[rid] = rec
        for rec in by_id.values():
            def _int_or_none(v):
                try:
                    return int(v) if v is not None else None
                except (TypeError, ValueError):
                    return None

            out.append(
                ReferralReward(
                    reward_id=str(rec.get("reward_id") or ""),
                    referrer_profile_id=str(rec.get("referrer_profile_id") or ""),
                    referrer_club=str(rec.get("referrer_club") or ""),
                    referred_club=str(rec.get("referred_club") or ""),
                    referred_email=str(rec.get("referred_email") or ""),
                    quote_id=str(rec.get("quote_id") or ""),
                    status=str(rec.get("status") or REWARD_PENDING_MANUAL),
                    reason=str(rec.get("reason") or ""),
                    stripe_coupon_id=str(rec.get("stripe_coupon_id") or ""),
                    amount_off_pence=_int_or_none(rec.get("amount_off_pence")),
                    currency=str(rec.get("currency") or "gbp"),
                    created_at=str(rec.get("created_at") or ""),
                )
            )
        return sorted(out, key=lambda r: r.created_at, reverse=True)

    def for_quote(self, quote_id: str) -> Optional[ReferralReward]:
        qid = (quote_id or "").strip()
        if not qid:
            return None
        for r in self.list_all():
            if r.quote_id == qid:
                return r
        return None

    def append(self, reward: ReferralReward) -> ReferralReward:
        _append_jsonl(self._path, reward.to_record())
        return reward


def _referrer_profile_for_club(club_name: str, codes: ReferralCodeStore) -> Optional[ReferralCode]:
    needle = (club_name or "").strip().lower()
    if not needle:
        return None
    for rc in codes._by_profile().values():
        if rc.club_name.strip().lower() == needle or rc.profile_id.strip().lower() == needle:
            return rc
    return None


def _referrer_stripe_customer(profile_id: str) -> str:
    """The referrer org's billing identity: the first active owner (then any
    active member) whose account carries a Stripe customer id."""
    try:
        from mediahub.web.auth import UserStore
        from mediahub.web.tenancy import ROLE_OWNER, MembershipStore

        members = MembershipStore().list_for_profile(profile_id)
        users = UserStore()
        ranked = sorted(members, key=lambda m: 0 if m.role == ROLE_OWNER else 1)
        for m in ranked:
            u = users.get(m.email)
            if u is not None and u.stripe_customer_id:
                return u.stripe_customer_id
    except Exception:
        log.warning("referral: customer lookup failed", exc_info=True)
    return ""


def _referrer_paid_annual_pence(referrer_club: str, currency_out: list) -> Optional[int]:
    """The referrer's own verified annual price (their PAID quote)."""
    try:
        from mediahub.commercial.wtp import STATUS_PAID, QuoteStore

        needle = (referrer_club or "").strip().lower()
        for q in QuoteStore().list_all():
            if (
                q.status == STATUS_PAID
                and q.billing_interval == "year"
                and q.club_name.strip().lower() == needle
            ):
                currency_out.append(q.currency)
                return q.amount_pence
    except Exception:
        log.warning("referral: referrer WTP lookup failed", exc_info=True)
    return None


def on_verified_quote_payment(
    quote,
    *,
    code_store: Optional[ReferralCodeStore] = None,
    lead_store: Optional[LeadStore] = None,
    reward_store: Optional[ReferralRewardStore] = None,
    grant_coupon=None,
) -> Optional[ReferralReward]:
    """The webhook hook: a quote just hit verified-PAID — settle any referral.

    Idempotent per quote (a webhook retry changes nothing). Matching order:
    the referred lead's ``contact_email`` equals the quote's contact email,
    else the lead's club name equals the quote's club name. When matched:
    the lead auto-advances to ``won`` and the reward grants (or records
    ``pending_manual`` with the honest reason). Returns the reward row, or
    None when the payment wasn't a referral.
    """
    from mediahub.commercial.wtp import STATUS_PAID

    if quote is None or quote.status != STATUS_PAID:
        return None
    codes = code_store or ReferralCodeStore()
    leads = lead_store or LeadStore()
    rewards = reward_store or ReferralRewardStore()

    existing = rewards.for_quote(quote.quote_id)
    if existing is not None:
        return existing  # idempotent per quote

    q_email = (quote.contact_email or "").strip().lower()
    q_club = (quote.club_name or "").strip().lower()
    referred = None
    for lead in leads.list_all():
        if lead.source != SOURCE_REFERRAL:
            continue
        if q_email and lead.contact_email == q_email:
            referred = lead
            break
        if q_club and lead.club_name.strip().lower() == q_club:
            referred = lead
            break
    if referred is None:
        return None

    # Zero operator typing: the funnel ledger advances itself.
    try:
        if referred.status != STATUS_WON:
            leads.set_status(referred.lead_id, STATUS_WON)
    except Exception:
        log.warning("referral: lead status advance failed", exc_info=True)

    rc = _referrer_profile_for_club(referred.referrer_club, codes)
    referrer_pid = rc.profile_id if rc else ""
    base = {
        "reward_id": secrets.token_hex(8),
        "referrer_profile_id": referrer_pid,
        "referrer_club": referred.referrer_club,
        "referred_club": quote.club_name,
        "referred_email": q_email or referred.contact_email,
        "quote_id": quote.quote_id,
        "currency": quote.currency,
        "created_at": _utc_now_iso(),
    }

    currency_box: list = []
    annual = _referrer_paid_annual_pence(referred.referrer_club, currency_box)
    if annual is None:
        return rewards.append(
            ReferralReward(
                **base,
                status=REWARD_PENDING_MANUAL,
                reason=(
                    "referrer has no verified paid annual quote in the WTP "
                    "ledger — set the free-month value by hand"
                ),
            )
        )
    amount_off = max(1, round(annual / 12))
    currency = currency_box[0] if currency_box else quote.currency
    base["currency"] = currency

    customer_id = _referrer_stripe_customer(referrer_pid) if referrer_pid else ""
    if not customer_id:
        return rewards.append(
            ReferralReward(
                **base,
                status=REWARD_PENDING_MANUAL,
                reason=(
                    "no Stripe customer found on the referrer org's members — "
                    "grant the free month manually (e.g. BACS payer)"
                ),
                amount_off_pence=amount_off,
            )
        )

    if grant_coupon is None:
        from mediahub.web.billing import grant_referral_reward as grant_coupon  # noqa: PLC0415

    try:
        coupon_id = grant_coupon(
            customer_id,
            amount_off_pence=amount_off,
            currency=currency,
            referred_club=quote.club_name,
        )
    except Exception as exc:
        log.warning("referral: coupon grant failed", exc_info=True)
        return rewards.append(
            ReferralReward(
                **base,
                status=REWARD_PENDING_MANUAL,
                reason=f"Stripe coupon grant failed: {exc}",
                amount_off_pence=amount_off,
            )
        )
    return rewards.append(
        ReferralReward(
            **base,
            status=REWARD_GRANTED,
            stripe_coupon_id=coupon_id,
            amount_off_pence=amount_off,
        )
    )


# ---------------------------------------------------------------------------
# Readouts
# ---------------------------------------------------------------------------


def code_tracked_intros(leads: list[Lead]) -> dict[str, list[Lead]]:
    """Referred signups grouped by referrer club (lower-cased key) — the
    live, code-tracked half of the referral-debt readout."""
    out: dict[str, list[Lead]] = {}
    for lead in leads:
        if lead.source != SOURCE_REFERRAL:
            continue
        key = lead.referrer_club.strip().lower()
        if key:
            out.setdefault(key, []).append(lead)
    return out


__all__ = [
    "REWARD_GRANTED",
    "REWARD_PENDING_MANUAL",
    "ReferralCode",
    "ReferralCodeStore",
    "ReferralReward",
    "ReferralRewardStore",
    "code_tracked_intros",
    "on_verified_quote_payment",
    "record_referred_signup",
]
