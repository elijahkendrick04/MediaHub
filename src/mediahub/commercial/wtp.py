"""
PC.4 — revealed willingness-to-pay (WTP) quote ledger.

The pricing decision (ADR-0011, sharpened in ADR-0014) is an **evidence
gate**, not a number: quote a *real* annual price to each hand-sold club,
vary it across clubs, and record what each club actually paid. The public
`/pricing` page stays at "Pricing TBC" until **≥5 clubs have paid an annual
prepay at a tested price**; the Phase C traction gate needs **≥10 clubs
paying annually**. This module is the ledger + gate arithmetic; the Stripe
side lives in `web.billing.create_quote_checkout_session` and the webhook.

Council-mandated hardening (ADR-0014): payment recording is **idempotent per
quote** and a Stripe-reported amount is **verified against the quoted
amount** — a mismatch is recorded honestly (`payment_mismatch`) and never
counts toward either gate, so the WTP evidence cannot be forged by editing a
checkout.

Storage: ``DATA_DIR/commercial/wtp_quotes.jsonl`` — append-only JSON lines,
last-write-wins per ``quote_id`` (the users.jsonl / memberships.jsonl
convention).
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

# Quote lifecycle. "paid" is only ever set by a verified payment (Stripe
# amount-match or an explicit operator attestation of an off-Stripe payment).
STATUS_QUOTED = "quoted"
STATUS_ACCEPTED = "accepted"  # verbal yes, payment not yet received
STATUS_DECLINED = "declined"
STATUS_PAID = "paid"
STATUS_MISMATCH = "payment_mismatch"  # money arrived but not at the quoted price
VALID_STATUSES = frozenset(
    {STATUS_QUOTED, STATUS_ACCEPTED, STATUS_DECLINED, STATUS_PAID, STATUS_MISMATCH}
)

METHOD_STRIPE = "stripe"
METHOD_MANUAL = "manual"  # operator-attested off-Stripe payment (e.g. BACS)

PC4_REQUIRED_PAID_CLUBS = 5  # publish-a-list-price gate (ADR-0011)
TRACTION_REQUIRED_PAYING_CLUBS = 10  # Phase C exit gate

_LEDGER_LOCK = threading.Lock()


class QuoteError(Exception):
    """Expected, operator-facing quote failures (clean error, not a 500)."""


def _coerce_status(status: object) -> str:
    s = str(status or "").strip().lower()
    return s if s in VALID_STATUSES else STATUS_QUOTED


@dataclass
class Quote:
    quote_id: str
    club_name: str
    contact_email: str = ""
    amount_pence: int = 0
    currency: str = "gbp"
    billing_interval: str = "year"  # annual prepay is the decided model
    status: str = STATUS_QUOTED
    method: str = ""  # how it was paid: "stripe" | "manual" | ""
    paid_amount_pence: Optional[int] = None
    paid_at: str = ""
    paid_event_id: str = ""  # Stripe event/session id for idempotency
    last_checkout_url: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_record(self) -> dict:
        return asdict(self)

    @classmethod
    def from_record(cls, d: dict) -> "Quote":
        def _int_or_none(v):
            try:
                return int(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        return cls(
            quote_id=str(d.get("quote_id", "") or "").strip(),
            club_name=str(d.get("club_name", "") or "").strip(),
            contact_email=str(d.get("contact_email", "") or "").strip().lower(),
            amount_pence=int(d.get("amount_pence") or 0),
            currency=str(d.get("currency", "gbp") or "gbp").lower(),
            billing_interval=str(d.get("billing_interval", "year") or "year").lower(),
            status=_coerce_status(d.get("status")),
            method=str(d.get("method", "") or ""),
            paid_amount_pence=_int_or_none(d.get("paid_amount_pence")),
            paid_at=str(d.get("paid_at", "") or ""),
            paid_event_id=str(d.get("paid_event_id", "") or ""),
            last_checkout_url=str(d.get("last_checkout_url", "") or ""),
            notes=str(d.get("notes", "") or ""),
            created_at=str(d.get("created_at", "") or ""),
            updated_at=str(d.get("updated_at", "") or ""),
        )


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _data_dir() -> Path:
    src_root = Path(__file__).resolve().parents[2]
    return Path(os.environ.get("DATA_DIR", str(src_root)))


def _quotes_path() -> Path:
    return _data_dir() / "commercial" / "wtp_quotes.jsonl"


class QuoteStore:
    """Append-only JSONL quote ledger, last-write-wins per ``quote_id``."""

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path is not None else _quotes_path()

    @property
    def path(self) -> Path:
        return self._path

    def _read_all(self) -> dict[str, Quote]:
        out: dict[str, Quote] = {}
        if not self._path.exists():
            return out
        try:
            text = self._path.read_text(encoding="utf-8")
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
            if not isinstance(rec, dict):
                continue
            q = Quote.from_record(rec)
            if q.quote_id:
                out[q.quote_id] = q
        return out

    def _append(self, quote: Quote) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(quote.to_record(), ensure_ascii=False) + "\n")
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass

    # ---- reads ----------------------------------------------------------

    def get(self, quote_id: str) -> Optional[Quote]:
        return self._read_all().get((quote_id or "").strip())

    def list_all(self) -> list[Quote]:
        return sorted(self._read_all().values(), key=lambda q: q.created_at, reverse=True)

    # ---- writes ---------------------------------------------------------

    def create(
        self,
        club_name: str,
        amount_pence: int,
        *,
        contact_email: str = "",
        currency: str = "gbp",
        notes: str = "",
    ) -> Quote:
        club = (club_name or "").strip()
        if not club:
            raise QuoteError("Enter the club's name.")
        try:
            amount = int(amount_pence)
        except (TypeError, ValueError):
            raise QuoteError("Quote amount must be a whole number of pence.")
        if amount <= 0:
            raise QuoteError("Quote a real (positive) annual price.")
        with _LEDGER_LOCK:
            now = _utc_now_iso()
            q = Quote(
                quote_id=secrets.token_hex(8),
                club_name=club,
                contact_email=(contact_email or "").strip().lower(),
                amount_pence=amount,
                currency=(currency or "gbp").lower(),
                status=STATUS_QUOTED,
                notes=(notes or "").strip(),
                created_at=now,
                updated_at=now,
            )
            self._append(q)
        return q

    def _update(self, quote: Quote) -> Quote:
        quote.updated_at = _utc_now_iso()
        self._append(quote)
        return quote

    def set_status(self, quote_id: str, status: str) -> Quote:
        """Operator-recorded accept/decline. Payments go through the
        record_* methods so 'paid' always carries verified evidence."""
        status = (status or "").strip().lower()
        if status not in (STATUS_ACCEPTED, STATUS_DECLINED, STATUS_QUOTED):
            raise QuoteError("Use the payment actions to mark a quote paid.")
        with _LEDGER_LOCK:
            q = self._read_all().get((quote_id or "").strip())
            if q is None:
                raise QuoteError("No such quote.")
            q.status = status
            return self._update(q)

    def set_checkout_url(self, quote_id: str, url: str) -> Quote:
        with _LEDGER_LOCK:
            q = self._read_all().get((quote_id or "").strip())
            if q is None:
                raise QuoteError("No such quote.")
            q.last_checkout_url = (url or "").strip()
            return self._update(q)

    def record_stripe_payment(
        self,
        quote_id: str,
        *,
        amount_total_pence: Optional[int],
        currency: str = "",
        event_id: str = "",
    ) -> Optional[Quote]:
        """Record a verified-signature Stripe payment against a quote.

        Idempotent per quote/event: a webhook retry (same event, or an
        already-paid quote at the same amount) changes nothing. The paid
        amount must equal the quoted amount (and currency) exactly —
        otherwise the quote is marked ``payment_mismatch`` and excluded
        from both gates. Unknown quote ids return None (acknowledge the
        webhook; nothing to corrupt).
        """
        with _LEDGER_LOCK:
            q = self._read_all().get((quote_id or "").strip())
            if q is None:
                return None
            if event_id and q.paid_event_id == event_id:
                return q  # exact retry — already recorded
            amount = amount_total_pence if amount_total_pence is not None else -1
            cur = (currency or q.currency).lower()
            verified = amount == q.amount_pence and cur == q.currency
            if q.status == STATUS_PAID and q.paid_amount_pence == amount:
                return q  # already paid at this amount — idempotent
            q.status = STATUS_PAID if verified else STATUS_MISMATCH
            q.method = METHOD_STRIPE
            q.paid_amount_pence = amount if amount >= 0 else None
            q.paid_at = _utc_now_iso()
            q.paid_event_id = event_id or q.paid_event_id
            return self._update(q)

    def record_manual_payment(self, quote_id: str, *, amount_pence: int) -> Quote:
        """Operator attests an off-Stripe annual payment (e.g. bank transfer).

        The same amount-verification rule applies — attesting a different
        figure than quoted records a mismatch, not a paid quote: revealed
        WTP is the price that actually cleared.
        """
        with _LEDGER_LOCK:
            q = self._read_all().get((quote_id or "").strip())
            if q is None:
                raise QuoteError("No such quote.")
            try:
                amount = int(amount_pence)
            except (TypeError, ValueError):
                raise QuoteError("Paid amount must be a whole number of pence.")
            verified = amount == q.amount_pence
            q.status = STATUS_PAID if verified else STATUS_MISMATCH
            q.method = METHOD_MANUAL
            q.paid_amount_pence = amount
            q.paid_at = _utc_now_iso()
            return self._update(q)


# ---- gate arithmetic (deterministic, no judgement) -----------------------


def _paid_annual_quotes(quotes: list[Quote]) -> list[Quote]:
    return [
        q
        for q in quotes
        if q.status == STATUS_PAID and q.billing_interval == "year" and q.amount_pence > 0
    ]


def _distinct_clubs(quotes: list[Quote]) -> list[str]:
    seen: dict[str, str] = {}
    for q in quotes:
        key = q.club_name.strip().lower()
        if key and key not in seen:
            seen[key] = q.club_name.strip()
    return sorted(seen.values(), key=str.lower)


def pc4_pricing_gate(quotes: list[Quote]) -> dict:
    """May a public list price be committed? (≥5 clubs paid annual, tested.)"""
    paid = _paid_annual_quotes(quotes)
    clubs = _distinct_clubs(paid)
    return {
        "paid_clubs": len(clubs),
        "required": PC4_REQUIRED_PAID_CLUBS,
        "met": len(clubs) >= PC4_REQUIRED_PAID_CLUBS,
        "clubs": clubs,
        "tested_prices_pence": sorted({q.amount_pence for q in paid}),
    }


def traction_gate(quotes: list[Quote]) -> dict:
    """Phase C exit gate: ≥10 clubs paying annually (gates P3/P4/P5)."""
    clubs = _distinct_clubs(_paid_annual_quotes(quotes))
    return {
        "paying_clubs": len(clubs),
        "required": TRACTION_REQUIRED_PAYING_CLUBS,
        "met": len(clubs) >= TRACTION_REQUIRED_PAYING_CLUBS,
        "clubs": clubs,
    }
