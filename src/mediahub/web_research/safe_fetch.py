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
  * **DNS pinning** — the connection is made to the exact IP that passed
    validation (``Host`` header + TLS SNI carry the original hostname), so a
    rebinding resolver cannot pass the check with a public IP and then point
    the actual connection at an internal one.
  * **Sanitised + capped output** — the body is read as a bounded byte stream
    (never materialised unbounded), reduced to plain text (``<script>`` /
    ``<style>`` removed) and truncated to a hard character cap, so a single
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
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

log = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 8000  # ~2k tokens — the council's per-fetch cap
DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_HOPS = 4
DEFAULT_MAX_BYTES = 2 * 1024 * 1024  # hard cap on bytes read off the wire
_CHUNK_BYTES = 65536

_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>")
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_WS_RE = re.compile(r"\s+")
_CHARSET_RE = re.compile(r"(?i)charset=[\"']?([\w.-]+)")


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


def _resolved_ips(host: str) -> list[str]:
    """Every IP the host currently resolves to (deduped); [] on failure."""
    if not host:
        return []
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except Exception:
        return []
    ips: list[str] = []
    for info in infos:
        ip_text = info[4][0]
        if ip_text not in ips:
            ips.append(ip_text)
    return ips


def resolve_safe_ip(host: str) -> Optional[str]:
    """Resolve ``host`` once and return ONE validated IP to pin the connection
    to — or ``None`` if the host is unresolvable or ANY resolved IP is
    internal/reserved.

    Connecting to the returned IP (rather than re-resolving the hostname at
    connect time) is what defeats DNS-rebinding TOCTOU. Shared by every
    outbound door that pre-validates hosts (deep research, webhooks).
    """
    ips = _resolved_ips(host)
    if not ips:
        return None
    for ip_text in ips:
        if _ip_is_blocked(ip_text):
            return None
    for ip_text in ips:  # prefer IPv4 — simplest to pin
        if ":" not in ip_text:
            return ip_text
    return ips[0]


def _host_is_safe(host: str) -> bool:
    """Resolve the host and refuse if ANY resolved IP is internal/reserved."""
    return resolve_safe_ip(host) is not None


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


def _decode_body(body: bytes, content_type: str) -> str:
    m = _CHARSET_RE.search(content_type or "")
    if m:
        try:
            return body.decode(m.group(1), errors="replace")
        except LookupError:
            pass
    return body.decode("utf-8", errors="replace")


def _pinned_get(url: str, *, timeout: float, max_bytes: int) -> Optional[tuple[int, dict, bytes]]:
    """GET ``url`` connecting directly to a pre-validated IP (DNS pinning).

    The TCP connection goes to the IP that passed the SSRF check; the original
    hostname rides along as the ``Host`` header and TLS SNI/verification name,
    so virtual hosts and certificates still work. Redirects are NOT followed
    (the caller re-validates each hop). The body is streamed and capped at
    ``max_bytes``. Returns ``(status, headers, body)`` or ``None``.
    """
    try:
        import urllib3  # noqa: PLC0415
    except Exception:  # pragma: no cover - urllib3 ships with requests
        return None

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    host = parsed.hostname or ""
    ip_text = resolve_safe_ip(host)
    if ip_text is None:
        log.warning("safe_fetch refused a URL (SSRF guard): host=%s", host)
        return None
    default_port = 443 if parsed.scheme == "https" else 80
    port = parsed.port or default_port
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    host_hdr = f"[{host}]" if ":" in host else host
    if port != default_port:
        host_hdr += f":{port}"
    headers = {
        "Host": host_hdr,
        "User-Agent": "MediaHubResearch/1.0 (+https://github.com/)",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
        "Accept-Language": "en-GB,en;q=0.9",
    }
    pool = None
    try:
        pool_timeout = urllib3.Timeout(connect=timeout, read=timeout)
        if parsed.scheme == "https":
            pool = urllib3.HTTPSConnectionPool(
                ip_text,
                port=port,
                timeout=pool_timeout,
                server_hostname=host,  # SNI + certificate name for the real host
                assert_hostname=host,
                retries=False,
            )
        else:
            # Cleartext pool is reached ONLY when the caller's validated URL is
            # http:// (the https branch above uses HTTPSConnectionPool with SNI +
            # cert checks). We never downgrade an https target — the scheme is
            # preserved from the SSRF-validated URL; we only pin the resolved IP.
            # nosemgrep: python.lang.security.audit.network.http-not-https-connection.http-not-https-connection
            pool = urllib3.HTTPConnectionPool(
                ip_text, port=port, timeout=pool_timeout, retries=False
            )
        r = pool.urlopen(
            "GET",
            path,
            headers=headers,
            redirect=False,
            retries=False,
            preload_content=False,
        )
        try:
            deadline = time.monotonic() + max(timeout * 3.0, timeout + 5.0)
            chunks: list[bytes] = []
            total = 0
            for chunk in r.stream(_CHUNK_BYTES):
                chunks.append(chunk)
                total += len(chunk)
                if total >= max_bytes or time.monotonic() > deadline:
                    break  # bounded read — never materialise an unbounded body
            body = b"".join(chunks)[:max_bytes]
            return int(r.status), dict(r.headers), body
        finally:
            try:
                r.close()
            except Exception:
                pass
    except Exception:
        return None
    finally:
        if pool is not None:
            try:
                pool.close()
            except Exception:
                pass


def safe_fetch(
    url: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    timeout: float = DEFAULT_TIMEOUT,
    max_hops: int = DEFAULT_MAX_HOPS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> Optional[str]:
    """Fetch ``url`` and return sanitised, capped plain text — or ``None``.

    SSRF-safe (host re-validated on every redirect hop, connection pinned to
    the validated IP), http(s)-only, byte-capped streaming read, never raises.
    ``None`` means blocked, failed, non-200, or unparseable.
    """
    current = (url or "").strip()
    for _ in range(max(1, max_hops)):
        res = _pinned_get(current, timeout=timeout, max_bytes=max(1, int(max_bytes)))
        if res is None:
            return None
        status, headers, body = res
        if status in (301, 302, 303, 307, 308):
            loc = headers.get("Location") or headers.get("location")
            if not loc:
                return None
            current = urljoin(current, loc)
            continue
        if status != 200:
            return None
        text = _html_to_text(_decode_body(body, headers.get("Content-Type", "")))
        if not text:
            return None
        return text[: max(0, int(max_chars))]
    return None  # too many redirects


__all__ = ["safe_fetch", "is_url_safe", "resolve_safe_ip"]
