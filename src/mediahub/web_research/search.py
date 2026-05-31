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
import re
import subprocess
import time
import urllib.request
import urllib.parse
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


# Cache lives in a .cache dir next to the package root
_CACHE_DIR: Optional[Path] = None
_CACHE_TTL_SECONDS = 30 * 24 * 3600  # 30 days


def _get_cache_dir() -> Path:
    global _CACHE_DIR
    if _CACHE_DIR is None:
        # Try to place it at the repo root
        here = Path(__file__).resolve().parent
        repo_root = here.parent
        candidate = repo_root / ".cache" / "research"
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            _CACHE_DIR = candidate
        except Exception:
            # Fall back to temp dir
            import tempfile

            _CACHE_DIR = Path(tempfile.gettempdir()) / "swim_research_cache"
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def _cache_key(query: str) -> str:
    return hashlib.md5(query.lower().strip().encode()).hexdigest()[:16]


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

        # Try pplx first
        if self._check_pplx():
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

        return results[:num]

    def fetch_url(self, url: str, timeout: int = 10) -> Optional[str]:
        """
        Fetch a URL and return its text content (stripped HTML).
        Returns None on failure.
        """
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; SwimMediaHub/1.0; "
                        "+https://github.com/swim-media-hub)"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml",
                    "Accept-Language": "en-GB,en;q=0.9",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            # Strip HTML tags
            text = re.sub(r"<[^>]+>", " ", raw)
            text = html.unescape(text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:8000]  # Limit length
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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
        Search DuckDuckGo HTML endpoint.
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
