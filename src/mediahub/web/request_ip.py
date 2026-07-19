"""Proxy-aware client IP for rate limiters / throttles.

Behind Render's edge exactly ONE trusted reverse proxy APPENDS the real client
address as the LAST ``X-Forwarded-For`` hop; every earlier hop is client-supplied.
Trusting the FIRST hop (or ``request.remote_addr``, which behind a proxy is the
proxy) hands an attacker a fresh rate-limit bucket per request — rotate the header
and dodge the brake. ``MEDIAHUB_TRUSTED_PROXY_HOPS`` (default 1) counts the
proxies in front of the app; 0 means no proxy — use the socket address.

Shared so the web-app throttles and the public-API limiter derive the client the
SAME way (the public API previously keyed on ``remote_addr``, i.e. the proxy).
"""

from __future__ import annotations

import os


def trusted_proxy_hops() -> int:
    try:
        return int(os.environ.get("MEDIAHUB_TRUSTED_PROXY_HOPS", "1"))
    except (TypeError, ValueError):
        return 1


def client_ip(request) -> str:
    """The real client IP for ``request``, honouring the trusted-proxy-hop count."""
    hops = trusted_proxy_hops()
    if hops > 0:
        fwd = [
            p.strip()
            for p in (request.headers.get("X-Forwarded-For") or "").split(",")
            if p.strip()
        ]
        if len(fwd) >= hops:
            return fwd[-hops]
        if fwd:
            return fwd[0]
    return request.remote_addr or "unknown"


__all__ = ["client_ip", "trusted_proxy_hops"]
