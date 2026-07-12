"""
web_research/search.py — V7.4

WebResearcher: works in the published sandbox and dev environment.

Strategy:
  1. Try `pplx search web` via subprocess (works in dev/local env)
  2. Fall back to DuckDuckGo HTML endpoint (works everywhere, no API key)
  3. Cache to .cache/research/<key>.json for 30 days

The DuckDuckGo HTML endpoint is:
  https://html.duckduckgo.com/html/?q=<query>
It returns an HTML page with result links that can be parsed with stdlib only.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import random
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
import urllib.parse
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# Cache lives under the writable data root (DATA_DIR on a deployment —
# the persistent disk; the src/mediahub dev default otherwise).
_CACHE_DIR: Optional[Path] = None
_CACHE_TTL_SECONDS = 30 * 24 * 3600  # 30 days


def _get_cache_dir() -> Path:
    global _CACHE_DIR
    if _CACHE_DIR is None:
        env = os.environ.get("DATA_DIR")
        base = Path(env) if env else Path(__file__).resolve().parent.parent
        candidate = base / ".cache" / "research"
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            _CACHE_DIR = candidate
        except Exception:
            # Fall back to temp dir
            import tempfile

            _CACHE_DIR = Path(tempfile.gettempdir()) / "swim_research_cache"
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


# ---------------------------------------------------------------------------
# DuckDuckGo politeness.
#
# PB discovery fans swimmer lookups across a thread pool; without a cap that
# meant 6 concurrent DDG searches from one IP — exactly the burst pattern DDG
# rate-limits (403/CAPTCHA), which silently emptied every lookup of a run.
# A small semaphore keeps the burst polite, a single jittered retry absorbs a
# transient throttle, and a short global cooldown makes the rest of the run
# fail fast (and honestly) instead of hammering a server that already said no.
# ---------------------------------------------------------------------------


def _ddg_max_concurrency() -> int:
    raw = os.environ.get("MEDIAHUB_SEARCH_DDG_CONCURRENCY", "").strip()
    try:
        return max(1, min(6, int(raw))) if raw else 2
    except ValueError:
        return 2


_DDG_SEMAPHORE = threading.BoundedSemaphore(_ddg_max_concurrency())
_DDG_STATE_LOCK = threading.Lock()
_DDG_COOLDOWN_S = 60.0
_ddg_cooldown_until = 0.0


def _ddg_in_cooldown() -> bool:
    with _DDG_STATE_LOCK:
        return time.time() < _ddg_cooldown_until


def _ddg_start_cooldown() -> None:
    global _ddg_cooldown_until
    with _DDG_STATE_LOCK:
        _ddg_cooldown_until = time.time() + _DDG_COOLDOWN_S


def _tinyfish_key() -> Optional[str]:
    """The operator's TinyFish API key, or None when the backend is off.

    Read from the environment only (never hard-coded), like every other key.
    TinyFish offers a free tier (no credit card), so this stays inside the
    no-paid-API rule while giving the cold-start PB bootstrap a reliable backend.
    """
    k = (os.environ.get("TINYFISH_API_KEY") or "").strip()
    return k or None


def _tinyfish_timeout() -> int:
    raw = (os.environ.get("MEDIAHUB_TINYFISH_TIMEOUT") or "").strip()
    try:
        return max(2, min(30, int(raw))) if raw else 12
    except ValueError:
        return 12


def _cache_key(query: str) -> str:
    return hashlib.md5(query.lower().strip().encode(), usedforsecurity=False).hexdigest()[:16]


def _load_cache(key: str) -> Optional[list[dict]]:
    p = _get_cache_dir() / f"{key}.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        if time.time() - data.get("_ts", 0) > _CACHE_TTL_SECONDS:
            return None
        return data.get("results", [])
    except Exception:
        return None


def _save_cache(key: str, results: list[dict]) -> None:
    try:
        p = _get_cache_dir() / f"{key}.json"
        p.write_text(json.dumps({"_ts": time.time(), "results": results}, indent=2))
    except Exception:
        pass


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str
    source: str  # "pplx" | "duckduckgo"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SearchResult":
        return cls(
            url=d.get("url", ""),
            title=d.get("title", ""),
            snippet=d.get("snippet", ""),
            source=d.get("source", "duckduckgo"),
        )


class WebResearcher:
    """
    Research helper that works in any environment.

    Tries pplx CLI first (dev/local only), falls back to DuckDuckGo HTML
    scraping (works everywhere, no API key required, low volume).
    """

    def __init__(self, cache_ttl: int = _CACHE_TTL_SECONDS):
        self._cache_ttl = cache_ttl
        self._pplx_available: Optional[bool] = None

    def _check_pplx(self) -> bool:
        """Check if pplx CLI is available."""
        if self._pplx_available is not None:
            return self._pplx_available
        try:
            result = subprocess.run(
                ["pplx", "search", "web", "--help"],
                capture_output=True,
                timeout=5,
            )
            self._pplx_available = result.returncode == 0 or len(result.stdout) > 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            self._pplx_available = False
        return self._pplx_available

    def search(self, query: str, num: int = 5) -> list[SearchResult]:
        """
        Search for a query. Returns up to `num` SearchResult objects.

        Tries pplx CLI first, then DuckDuckGo HTML fallback.
        Results are cached for 30 days.
        """
        cache_key = _cache_key(query)
        cached = _load_cache(cache_key)
        if cached:
            return [SearchResult.from_dict(r) for r in cached[:num]]

        results: list[SearchResult] = []

        # TinyFish web search is the PREFERRED backend when a key is configured:
        # a free tier (no credit card), fast, and returns clean title/snippet/URL
        # JSON that drops straight into the candidate-URL pipeline. Off by default
        # (no TINYFISH_API_KEY => skipped, behaviour unchanged). Any failure falls
        # through to SearXNG/DDG below, so search never just stops. No paid API.
        if not results and _tinyfish_key():
            try:
                results = self._search_tinyfish(query, num)
                log.info("tinyfish search: %d result(s) for %r", len(results), query)
            except Exception:
                # Never silent: a swallowed error here is exactly why "is TinyFish
                # even running?" was impossible to answer. Log it (with traceback)
                # and fall through to the next backend.
                log.warning("tinyfish search failed for %r", query, exc_info=True)

        # Cap 3: SearXNG metasearch is the PREFERRED backend when configured
        # (multi-engine, free, far sturdier than DDG HTML scraping). On any
        # failure we fall back to the existing pplx/DDG path (logged degraded)
        # so research never just stops. Off-by-default: with
        # MEDIAHUB_SEARCH_ENDPOINT unset this block is skipped and behaviour is
        # byte-for-byte unchanged — and MediaHub never provisions or hosts
        # SearXNG, so it adds no running cost.
        #
        # A failure opens the client's circuit breaker: SearXNG is skipped
        # (silently, debug-level) for a cooldown window instead of re-probing a
        # dead endpoint and warning on every single query. One warning per
        # window, with the operator pointer, is the whole story in the logs.
        try:
            from mediahub.web_research import searxng_client

            if searxng_client.is_configured():
                if searxng_client.breaker_open():
                    log.debug(
                        "SearXNG circuit open, using fallback engines: %s",
                        searxng_client.breaker_reason(),
                    )
                else:
                    try:
                        results = searxng_client.search(query, num)
                    except searxng_client.SearxngUnavailable as e:
                        log.warning(
                            "SearXNG unavailable, falling back to DuckDuckGo "
                            "(pausing SearXNG attempts for ~%ds; check /healthz/search): %s",
                            int(searxng_client.breaker_cooldown()),
                            e,
                        )
        except Exception:
            pass

        # Try pplx (dev/local only)
        if not results and self._check_pplx():
            try:
                results = self._search_pplx(query, num)
            except Exception:
                pass

        # Fall back to DuckDuckGo HTML
        if not results:
            try:
                results = self._search_duckduckgo(query, num)
            except Exception:
                pass

        # Cache and return
        if results:
            _save_cache(cache_key, [r.to_dict() for r in results])
            log.info("search %r -> %d result(s) via %s", query, len(results), results[0].source)
        else:
            log.info("search %r -> 0 results (every backend empty/unavailable)", query)

        return results[:num]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _search_tinyfish(self, query: str, num: int) -> list[SearchResult]:
        """Query the TinyFish Search API (free tier) for web results.

        Returns up to ``num`` SearchResult URLs. Tolerant of the JSON shape —
        reads the common ``results``/``organic``/``data`` arrays and the usual
        url/title/snippet fields. Raises on transport error so the caller falls
        back to the next backend.
        """
        key = _tinyfish_key()
        if not key:
            return []
        # GET https://api.search.tinyfish.ai?query=... with an X-API-Key header;
        # response is {"results": [{"url","title","snippet",…}], …}. No location
        # hint — MediaHub clubs span the UK/US/AUS, so a neutral global search
        # beats geo-targeting to the wrong country. (Free tier: 30 req/min; the
        # PB-history baseline keeps actual call volume to first-seen swimmers.)
        encoded = urllib.parse.quote_plus(query)
        url = f"https://api.search.tinyfish.ai?query={encoded}&language=en"
        req = urllib.request.Request(
            url,
            headers={"X-API-Key": key, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_tinyfish_timeout()) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))

        items = []
        if isinstance(data, dict):
            for field in ("results", "organic", "organic_results", "data", "items"):
                if isinstance(data.get(field), list):
                    items = data[field]
                    break
        elif isinstance(data, list):
            items = data

        out: list[SearchResult] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            link = (it.get("url") or it.get("link") or it.get("href") or "").strip()
            if not link.startswith("http"):
                continue
            title = html.unescape(str(it.get("title") or it.get("name") or "").strip())
            snippet = html.unescape(
                str(it.get("snippet") or it.get("description") or it.get("content") or "").strip()
            )
            out.append(SearchResult(url=link, title=title, snippet=snippet, source="tinyfish"))
            if len(out) >= num:
                break
        return out

    def _search_pplx(self, query: str, num: int) -> list[SearchResult]:
        """Use pplx CLI to search."""
        result = subprocess.run(
            ["pplx", "search", "web", query],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            return []
        try:
            data = json.loads(result.stdout)
            hits = data.get("hits", [])
            out = []
            for h in hits[:num]:
                out.append(
                    SearchResult(
                        url=h.get("url", ""),
                        title=h.get("title", ""),
                        snippet=h.get("snippet", "") or h.get("summary", ""),
                        source="pplx",
                    )
                )
            return out
        except (json.JSONDecodeError, KeyError):
            return []

    def _search_duckduckgo(self, query: str, num: int) -> list[SearchResult]:
        """
        Search DuckDuckGo HTML endpoint, politely.

        Concurrency is capped by a module-wide semaphore; an HTTP 403/429 gets
        one jittered retry, and a second throttle starts a global cooldown so
        the rest of the run skips DDG instead of hammering it. During cooldown
        this returns [] (an honest "search unavailable right now").
        """
        if _ddg_in_cooldown():
            return []
        with _DDG_SEMAPHORE:
            try:
                return self._ddg_request(query, num)
            except urllib.error.HTTPError as e:
                if e.code not in (403, 429):
                    raise
            # Throttled — back off briefly with jitter and retry once.
            time.sleep(1.5 + random.random() * 2.0)
            try:
                return self._ddg_request(query, num)
            except urllib.error.HTTPError as e:
                if e.code in (403, 429):
                    _ddg_start_cooldown()
                    log.warning(
                        "DuckDuckGo throttled search (HTTP %s) — cooling down for %.0fs",
                        e.code,
                        _DDG_COOLDOWN_S,
                    )
                    return []
                raise

    def _ddg_request(self, query: str, num: int) -> list[SearchResult]:
        """One raw DuckDuckGo HTML request + parse.
        DDG uses redirect URLs: //duckduckgo.com/l/?uddg=<encoded-real-url>
        """
        encoded = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-GB,en;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")

        # Extract result__a links (DDG redirects via uddg= param)
        links = re.findall(r'class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', raw, re.DOTALL)
        snippets_raw = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', raw, re.DOTALL)

        results = []
        for i, (href_raw, title_raw) in enumerate(links[:num]):
            href_decoded = html.unescape(href_raw).strip()
            # Extract real URL from DDG redirect
            m_uddg = re.search(r"uddg=([^&]+)", href_decoded)
            if m_uddg:
                url_clean = urllib.parse.unquote(m_uddg.group(1))
            else:
                url_clean = href_decoded
                if url_clean.startswith("//"):
                    url_clean = "https:" + url_clean
            if not url_clean.startswith("http"):
                continue
            title_clean = html.unescape(re.sub(r"<[^>]+>", "", title_raw)).strip()
            snippet_clean = ""
            if i < len(snippets_raw):
                snippet_clean = html.unescape(re.sub(r"<[^>]+>", "", snippets_raw[i])).strip()
            if url_clean and title_clean:
                results.append(
                    SearchResult(
                        url=url_clean,
                        title=title_clean,
                        snippet=snippet_clean,
                        source="duckduckgo",
                    )
                )
        return results[:num]

    def _parse_ddg_fallback(self, html_text: str, num: int) -> list[SearchResult]:
        """Alternative DDG HTML parser for edge cases."""
        results = []
        # Extract all result__a links with their text
        links = re.findall(
            r'<a\s+class="result__a"[^>]+href="([^"]*)"[^>]*>(.*?)</a>', html_text, re.DOTALL
        )
        snippets = re.findall(r'<a\s+class="result__snippet"[^>]*>(.*?)</a>', html_text, re.DOTALL)
        for i, (href, title_html) in enumerate(links[:num]):
            url_clean = html.unescape(href).strip()
            title_clean = html.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
            snippet_clean = ""
            if i < len(snippets):
                snippet_clean = html.unescape(re.sub(r"<[^>]+>", "", snippets[i])).strip()
            if url_clean.startswith("//"):
                url_clean = "https:" + url_clean
            if url_clean and title_clean and not url_clean.startswith("/?"):
                results.append(
                    SearchResult(
                        url=url_clean,
                        title=title_clean,
                        snippet=snippet_clean,
                        source="duckduckgo",
                    )
                )
        return results
