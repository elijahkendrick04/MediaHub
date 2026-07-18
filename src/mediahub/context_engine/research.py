"""
context_engine/research.py — Query/cache wrapper around web_research.search.

Provides a thin adapter over WebResearcher that adds:
- Namespace-scoped search caching
- Page fetching via the SSRF-hardened door (web_research.safe_fetch)
- Consistent SearchHit dataclass

Does NOT hardcode any domain names or sources.
"""

from __future__ import annotations

import re
import sys
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
        Fetch a web page and return cleaned, capped plain text — or ``None``.

        Routed through the project's SSRF-hardened door
        (``web_research.safe_fetch``): the host is resolved + validated, the
        connection pinned to that IP, redirects re-validated on every hop,
        http(s)-only, and the body read under a hard byte cap. This URL can be
        seeded from attacker-influenceable uploaded-file text, so a bare
        ``urlopen`` (no IP/redirect/scheme guard) is unsafe here. ``None`` on a
        blocked or failed fetch.
        """
        from mediahub.web_research.safe_fetch import safe_fetch  # noqa: PLC0415

        return safe_fetch(
            url,
            max_chars=max_chars,
            timeout=self._DEFAULT_TIMEOUT,
            max_bytes=200_000,
        )

    def fetch_bytes(self, url: str) -> Optional[bytes]:
        """
        Fetch a URL and return raw bytes (SSRF-hardened) — or ``None``.

        Same hardened door as :meth:`fetch_text` (host/IP validation, per-hop
        redirect re-validation, connection pinning, byte cap). Used when passing
        content to ``interpreter.interpret_document()``.
        """
        from mediahub.web_research.safe_fetch import safe_fetch_bytes  # noqa: PLC0415

        res = safe_fetch_bytes(url, max_bytes=500_000, timeout=self._DEFAULT_TIMEOUT)
        return res[1] if res else None
