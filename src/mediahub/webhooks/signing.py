"""mediahub/webhooks/signing.py — HMAC-SHA256 request signing.

Every outbound delivery carries an ``X-MediaHub-Signature`` header so the
receiver can prove the request came from MediaHub (and not a forger) and is
fresh (not replayed). The scheme mirrors Stripe's, which integrators already
know:

    X-MediaHub-Signature: t=1718000000,v1=<hex hmac-sha256>

The signed message is ``"{t}.{raw_body}"``; the key is the endpoint's shared
secret. The receiver recomputes the HMAC over the same string and compares in
constant time, rejecting timestamps outside a tolerance window.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Optional

HEADER = "X-MediaHub-Signature"
SCHEME_VERSION = "v1"
DEFAULT_TOLERANCE = 300  # seconds


def compute(secret: str, timestamp: int, body: bytes) -> str:
    """The hex HMAC-SHA256 of ``"{timestamp}.{body}"`` under ``secret``."""
    signed = f"{timestamp}.".encode("utf-8") + (body or b"")
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def signature_header(secret: str, body: bytes, *, timestamp: Optional[int] = None) -> str:
    """Build the full ``X-MediaHub-Signature`` header value for a body."""
    ts = int(timestamp if timestamp is not None else time.time())
    return f"t={ts},{SCHEME_VERSION}={compute(secret, ts, body)}"


def _parse(header_value: str) -> tuple[Optional[int], Optional[str]]:
    ts: Optional[int] = None
    sig: Optional[str] = None
    for part in (header_value or "").split(","):
        k, _, v = part.strip().partition("=")
        if k == "t":
            try:
                ts = int(v)
            except ValueError:
                ts = None
        elif k == SCHEME_VERSION:
            sig = v
    return ts, sig


def verify(
    secret: str,
    header_value: str,
    body: bytes,
    *,
    tolerance: int = DEFAULT_TOLERANCE,
    now: Optional[int] = None,
) -> bool:
    """True iff ``header_value`` is a valid, fresh signature for ``body``.

    Provided for receivers and for our own tests. Constant-time comparison; a
    timestamp older/newer than ``tolerance`` seconds is rejected (replay guard)."""
    ts, sig = _parse(header_value)
    if ts is None or not sig:
        return False
    ref = int(now if now is not None else time.time())
    if tolerance and abs(ref - ts) > tolerance:
        return False
    expected = compute(secret, ts, body)
    return hmac.compare_digest(expected, sig)


__all__ = ["HEADER", "SCHEME_VERSION", "compute", "signature_header", "verify"]
