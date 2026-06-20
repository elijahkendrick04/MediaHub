"""
swimmingresults/transport.py — fetch pages from swimmingresults.org.

A single, deliberately boring HTTP GET with a real browser User-Agent. The site
serves a Cloudflare 403 to default urllib/script agents but returns 200 to a
normal browser UA — verified from the production Render egress IP, so no proxy
or third-party fetch API is needed. This keeps the whole PB-lookup chain on
free, first-party HTTP with no rate-limit ceiling.

Network failures never raise out of here as anything other than ``SRFetchError``
so callers can treat "couldn't reach the site" as a clean miss (no PB asserted)
rather than a crashed run.
"""

from __future__ import annotations

import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

SR_BASE = "https://www.swimmingresults.org"

# A current desktop-Chrome UA. The site gates on UA shape, not a specific
# version, but we keep this realistic. Refreshing it occasionally is harmless.
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_DEFAULT_TIMEOUT = 25.0


class SRFetchError(RuntimeError):
    """Raised when a swimmingresults.org page could not be fetched (transport
    error, timeout, or a non-200 status)."""


def _timeout() -> float:
    raw = os.environ.get("MEDIAHUB_SR_TIMEOUT", "").strip()
    if raw:
        try:
            return max(1.0, float(raw))
        except ValueError:
            pass
    return _DEFAULT_TIMEOUT


def fetch(url: str, *, timeout: float | None = None) -> str:
    """GET ``url`` and return the decoded HTML body.

    Raises ``SRFetchError`` on any transport failure or a non-200 status. The
    caller decides what a failure means (almost always: skip this swimmer, no
    PB asserted — a miss, never a wrong PB).
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
            "Referer": SR_BASE + "/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout or _timeout()) as resp:
            status = getattr(resp, "status", 200) or 200
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise SRFetchError(f"HTTP {exc.code} for {url}") from exc
    except Exception as exc:  # URLError, timeout, socket errors, …
        raise SRFetchError(f"{type(exc).__name__} for {url}: {exc}") from exc
    if status != 200:
        raise SRFetchError(f"HTTP {status} for {url}")
    return body
