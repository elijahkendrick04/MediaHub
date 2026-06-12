"""mediahub/web_research/searxng_client.py — SearXNG metasearch JSON client.

Capability 3a. A thin ``requests``-based client for a self-hosted, **stock**
SearXNG metasearch daemon (https://searxng.org), queried over HTTP with
``format=json``. SearXNG fans one query out to many upstream engines and returns
aggregated, de-duplicated results — a sturdier, fee-free replacement for the
single-engine DuckDuckGo HTML scraping ``WebResearcher`` uses today.

SearXNG is **AGPL-3.0** and runs as a **separate, unmodified** service: MediaHub
never imports or bundles its code — it only queries it over HTTP — so MediaHub
itself is unaffected by the AGPL network-copyleft. MediaHub does NOT host or
provision SearXNG (that would add running cost) — this is a **bring-your-own,
off-by-default** backend. If you run a stock ``searxng/searxng`` instance
anywhere reachable (for free), point ``MEDIAHUB_SEARCH_ENDPOINT`` at it; we
never fork or bundle it.

Configuration is env-only and **inert when unset**:

    MEDIAHUB_SEARCH_ENDPOINT   base URL of the SearXNG instance (e.g.
                               ``http://searxng:8080``). Unset => this backend is
                               off and WebResearcher behaves exactly as before.
    MEDIAHUB_SEARCH_TIMEOUT    per-request timeout in seconds (default 10).

Note: SearXNG ships with JSON output **disabled** by default; the instance must
set ``search.formats: [html, json]``. If it isn't enabled the instance returns
403/non-JSON, this client raises :class:`SearxngUnavailable`, and WebResearcher
falls back to DuckDuckGo (logged degraded) — never a fabricated result.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # avoid an import cycle at runtime (search.py imports us lazily)
    from mediahub.web_research.search import SearchResult

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0
DEFAULT_BREAKER_COOLDOWN = 300.0  # seconds to skip SearXNG after a failure


class SearxngUnavailable(RuntimeError):
    """Raised when the SearXNG instance can't be reached or errors."""


# --- circuit breaker ---------------------------------------------------------
# When the configured instance is down (e.g. the in-container SearXNG never
# started), every research query would otherwise re-probe the dead endpoint and
# warn — dozens of identical log lines per run. After a failure we skip SearXNG
# for a cooldown window instead; per-process state, no persistence needed.

_breaker_lock = threading.Lock()
_breaker_open_until: float = 0.0
_breaker_reason: str = ""


def breaker_cooldown() -> float:
    """Cooldown seconds after a failure (``MEDIAHUB_SEARCH_BREAKER_COOLDOWN``).

    ``0`` disables the breaker entirely — every query probes SearXNG again,
    matching the pre-breaker behaviour."""
    raw = os.environ.get("MEDIAHUB_SEARCH_BREAKER_COOLDOWN", "").strip()
    if not raw:
        return DEFAULT_BREAKER_COOLDOWN
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_BREAKER_COOLDOWN


def breaker_open() -> bool:
    """True while SearXNG attempts are paused after a recent failure."""
    with _breaker_lock:
        return time.time() < _breaker_open_until


def breaker_reason() -> str:
    """The failure message that opened the breaker ('' when closed)."""
    with _breaker_lock:
        return _breaker_reason if time.time() < _breaker_open_until else ""


def _trip_breaker(reason: str) -> None:
    global _breaker_open_until, _breaker_reason
    cooldown = breaker_cooldown()
    if cooldown <= 0:
        return
    with _breaker_lock:
        _breaker_open_until = time.time() + cooldown
        _breaker_reason = reason


def _reset_breaker() -> None:
    global _breaker_open_until, _breaker_reason
    with _breaker_lock:
        _breaker_open_until = 0.0
        _breaker_reason = ""


def endpoint() -> Optional[str]:
    """Resolve the SearXNG base URL (env first, then secrets_store)."""
    v = os.environ.get("MEDIAHUB_SEARCH_ENDPOINT", "").strip()
    if v:
        return v.rstrip("/")
    try:
        from mediahub.web.secrets_store import get_secret

        s = get_secret("mediahub_search_endpoint")
        return s.rstrip("/") if s and s.strip() else None
    except Exception:
        return None


def is_configured() -> bool:
    """True when a SearXNG endpoint is configured."""
    return bool(endpoint())


def _timeout() -> float:
    raw = os.environ.get("MEDIAHUB_SEARCH_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        return max(1.0, float(raw))
    except ValueError:
        return DEFAULT_TIMEOUT


def search(query: str, num: int = 5) -> "list[SearchResult]":
    """Query SearXNG (``format=json``) and return normalized ``SearchResult``s.

    Raises :class:`SearxngUnavailable` on a transport/HTTP/parse failure so the
    caller can fall back. Returns ``[]`` when SearXNG answers with no results.
    """
    from mediahub.web_research.search import SearchResult  # lazy: avoids cycle

    base = endpoint()
    if not base:
        raise SearxngUnavailable("MEDIAHUB_SEARCH_ENDPOINT is not configured")
    if breaker_open():
        raise SearxngUnavailable(f"skipped — circuit open after earlier failure: {breaker_reason()}")
    try:
        import requests  # noqa: PLC0415
    except Exception as e:  # pragma: no cover - requests is a hard dep
        raise SearxngUnavailable(f"requests unavailable: {e}") from e

    try:
        r = requests.get(
            f"{base}/search",
            params={"q": query, "format": "json"},
            headers={"Accept": "application/json"},
            timeout=_timeout(),
        )
    except Exception as e:
        _trip_breaker(f"SearXNG transport error: {e}")
        raise SearxngUnavailable(f"SearXNG transport error: {e}") from e
    if r.status_code != 200:
        _trip_breaker(f"SearXNG HTTP {r.status_code}")
        raise SearxngUnavailable(f"SearXNG HTTP {r.status_code}")
    try:
        data = r.json()
    except Exception as e:
        _trip_breaker("SearXNG returned non-JSON")
        raise SearxngUnavailable(f"SearXNG returned non-JSON (is json format enabled?): {e}") from e
    _reset_breaker()

    out: "list[SearchResult]" = []
    for item in data.get("results") or []:
        url = (item.get("url") or "").strip()
        title = (item.get("title") or "").strip()
        if not url or not title:
            continue
        out.append(
            SearchResult(
                url=url,
                title=title,
                snippet=(item.get("content") or "").strip(),
                source="searxng",
            )
        )
        if len(out) >= max(1, num):
            break
    return out


def health() -> dict:
    """Report which search backend is actually live, with a lightweight probe.

    Returns a dict describing whether SearXNG is configured and reachable. When
    it isn't reachable, MediaHub falls back to DuckDuckGo, so ``engine`` reflects
    what searches will really use right now. Cheap + safe (short timeout, never
    raises) — suitable for a /healthz endpoint.
    """
    base = endpoint()
    if not base:
        return {
            "engine": "duckduckgo",
            "searxng_configured": False,
            "searxng_reachable": False,
            "breaker_open": False,
            "detail": "MEDIAHUB_SEARCH_ENDPOINT not set",
        }
    reachable = False
    detail = ""
    try:
        import requests  # noqa: PLC0415

        r = requests.get(
            f"{base}/search",
            params={"q": "ping", "format": "json"},
            headers={"Accept": "application/json"},
            timeout=min(5.0, _timeout()),
        )
        reachable = r.status_code == 200
        if not reachable:
            detail = f"HTTP {r.status_code} (is json format enabled?)"
    except Exception as e:
        detail = str(e)[:160]
    # The probe is fresh truth — let it close (or open) the breaker so a
    # recovered SearXNG is picked up immediately rather than after cooldown.
    if reachable:
        _reset_breaker()
    else:
        _trip_breaker(detail or "health probe failed")
    return {
        "engine": "searxng" if reachable else "duckduckgo",
        "searxng_configured": True,
        "searxng_reachable": reachable,
        "breaker_open": breaker_open(),
        "detail": detail or "ok",
    }


__all__ = [
    "SearxngUnavailable",
    "search",
    "is_configured",
    "endpoint",
    "health",
    "breaker_open",
    "breaker_reason",
    "breaker_cooldown",
]
