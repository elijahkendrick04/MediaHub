"""mediahub/web_research/safe_fetch.py — SSRF-hardened page fetcher.

Capability 3b. The deep-research loop lets an LLM choose which URLs to fetch,
which is a textbook SSRF + prompt-injection surface (the council's #1 blind
spot). This module is the single hardened door for that:

  * **SSRF blocklist** — the destination host is resolved and every resulting IP
    is checked; private (RFC-1918), loopback, link-local (incl. the cloud
    metadata address ``169.254.169.254``), reserved, multicast and unspecified
    addresses are refused. Only ``http``/``https`` is allowed. Redirects are
    followed manually, re-validating the host at every hop (so a public URL
    can't 302 you onto an internal one).
  * **Sanitised + capped output** — pages are reduced to plain text (``<script>``
    / ``<style>`` removed) and truncated to a hard character cap, so a single
    fetched page can neither dominate the model's context nor smuggle markup
    designed to override it.

Returns ``None`` (never raises) on a blocked/failed/unparseable fetch, so the
loop treats it as "this page yielded nothing" rather than crashing.
"""

from __future__ import annotations

import html
import ipaddress
import logging
import re
import socket
from typing import Optional
from urllib.parse import urljoin, urlparse

log = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 8000  # ~2k tokens — the council's per-fetch cap
DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_HOPS = 4

_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>")
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _ip_is_blocked(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return True  # unparseable => refuse
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _host_is_safe(host: str) -> bool:
    """Resolve the host and refuse if ANY resolved IP is internal/reserved."""
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        ip_text = info[4][0]
        if _ip_is_blocked(ip_text):
            return False
    return True


def _html_to_text(raw: str) -> str:
    s = _SCRIPT_STYLE_RE.sub(" ", raw or "")
    s = _TAG_RE.sub(" ", s)
    s = html.unescape(s)
    return _WS_RE.sub(" ", s).strip()


def is_url_safe(url: str) -> bool:
    """True if ``url`` is an http(s) URL whose host resolves to public IPs only."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    return _host_is_safe(parsed.hostname or "")


def safe_fetch(
    url: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    timeout: float = DEFAULT_TIMEOUT,
    max_hops: int = DEFAULT_MAX_HOPS,
) -> Optional[str]:
    """Fetch ``url`` and return sanitised, capped plain text — or ``None``.

    SSRF-safe (host re-validated on every redirect hop), http(s)-only, never
    raises. ``None`` means blocked, failed, non-200, or unparseable.
    """
    try:
        import requests  # noqa: PLC0415
    except Exception:  # pragma: no cover - requests is a hard dependency
        return None

    current = (url or "").strip()
    for _ in range(max(1, max_hops)):
        parsed = urlparse(current)
        if parsed.scheme not in ("http", "https"):
            return None
        if not _host_is_safe(parsed.hostname or ""):
            log.warning("safe_fetch refused a URL (SSRF guard): host=%s", parsed.hostname)
            return None
        try:
            r = requests.get(
                current,
                timeout=timeout,
                allow_redirects=False,  # we follow manually, re-validating each hop
                headers={
                    "User-Agent": "MediaHubResearch/1.0 (+https://github.com/)",
                    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
                    "Accept-Language": "en-GB,en;q=0.9",
                },
            )
        except Exception:
            return None
        if r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("Location")
            if not loc:
                return None
            current = urljoin(current, loc)
            continue
        if r.status_code != 200:
            return None
        text = _html_to_text(r.text)
        if not text:
            return None
        return text[: max(0, int(max_chars))]
    return None  # too many redirects


__all__ = ["safe_fetch", "is_url_safe"]
