"""
context_engine/research.py — Query/cache wrapper around web_research.search.

Provides a thin adapter over WebResearcher that adds:
- Namespace-scoped search caching
- Page fetching with light HTML cleaning (BeautifulSoup or stdlib fallback)
- Consistent SearchHit dataclass

Does NOT hardcode any domain names or sources.
"""

from __future__ import annotations

import html
import re
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

# Locate the web_research package (sibling directory)
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mediahub.web_research.search import WebResearcher, SearchResult


@dataclass
class SearchHit:
    """A single search result with enriched metadata."""

    url: str
    title: str
    snippet: str
    domain: str
    source: str = "duckduckgo"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_search_result(cls, r: SearchResult) -> "SearchHit":
        domain = _extract_domain(r.url)
        return cls(
            url=r.url,
            title=r.title,
            snippet=r.snippet,
            domain=domain,
            source=r.source,
        )


def _extract_domain(url: str) -> str:
    """Extract the registered domain from a URL without external libs."""
    try:
        # Remove scheme
        s = re.sub(r"^https?://", "", url)
        # Remove path/query
        s = s.split("/")[0].split("?")[0].split("#")[0]
        # Remove port
        s = s.split(":")[0]
        return s.lower()
    except Exception:
        return ""


def _clean_html(raw: str) -> str:
    """
    Strip HTML tags and decode entities.
    Tries BeautifulSoup first (better quality), falls back to regex.
    """
    # Try BeautifulSoup
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw, "lxml")
        # Remove script and style elements
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ")
        text = re.sub(r"\s+", " ", text).strip()
        return text
    except ImportError:
        pass

    # Stdlib fallback
    text = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class ResearchClient:
    """
    Wrapper around WebResearcher with page-fetch capability.

    Usage:
        client = ResearchClient()
        hits = client.search("query about a swimming meet")
        text = client.fetch_text("https://example.com/page")
    """

    _DEFAULT_TIMEOUT = 12

    def __init__(self, num_results: int = 5):
        self._researcher = WebResearcher()
        self._num_results = num_results

    def search(self, query: str, num: int | None = None) -> list[SearchHit]:
        """
        Search the web and return SearchHit objects.
        Results come from WebResearcher (DDG fallback + cache).
        """
        n = num if num is not None else self._num_results
        raw = self._researcher.search(query, num=n)
        return [SearchHit.from_search_result(r) for r in raw]

    def fetch_text(self, url: str, max_chars: int = 12_000) -> Optional[str]:
        """
        Fetch a web page and return cleaned text content.

        Uses urllib + BeautifulSoup (stdlib fallback available).
        Returns None on failure.
        """
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; SwimContextEngine/7.5; "
                        "+https://github.com/swim-media-hub)"
                    ),
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-GB,en;q=0.9",
                },
            )
            with urllib.request.urlopen(req, timeout=self._DEFAULT_TIMEOUT) as resp:
                raw_bytes = resp.read(200_000)
            raw = raw_bytes.decode("utf-8", errors="replace")
            return _clean_html(raw)[:max_chars]
        except (urllib.error.URLError, OSError, Exception):
            return None

    def fetch_bytes(self, url: str) -> Optional[bytes]:
        """
        Fetch a URL and return raw bytes.
        Used when passing content to interpreter.interpret_document().
        """
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; SwimContextEngine/7.5; "
                        "+https://github.com/swim-media-hub)"
                    ),
                },
            )
            with urllib.request.urlopen(req, timeout=self._DEFAULT_TIMEOUT) as resp:
                return resp.read(500_000)
        except Exception:
            return None
