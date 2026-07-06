"""
pb_discovery/fetch_profile.py — Generic profile-page fetcher.

Given any URL, fetches the page and returns both cleaned text and
extracted tables (as list of list of strings).

Uses stdlib urllib + BeautifulSoup for HTML parsing.
Does not depend on any hardcoded domain-specific logic.
"""

from __future__ import annotations

import html
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Ensure repo root is on path for web_research import
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@dataclass
class ProfilePage:
    """Result of fetching and parsing a profile page."""

    url: str
    fetched_at: str
    text: str  # Full cleaned text content
    tables: list[list[list[str]]]  # Tables as [row][col] strings
    raw_html_length: int = 0
    fetch_success: bool = True
    error: Optional[str] = None


def _extract_domain(url: str) -> str:
    try:
        s = re.sub(r"^https?://", "", url)
        return s.split("/")[0].split("?")[0].split(":")[0].lower()
    except Exception:
        return ""


_MAX_REDIRECT_HOPS = 5

_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SwimPBDiscovery/7.5; "
        "+https://github.com/swim-media-hub)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse automatic redirects — each hop is re-validated by the caller."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def _fetch_raw(url: str, timeout: int = 12) -> Optional[bytes]:
    """Fetch raw bytes from a URL via urllib.

    SSRF-guarded and FAIL-CLOSED: candidate URLs can come from web search and
    (when enabled) a model, so refuse any URL that resolves to a private /
    loopback / link-local / cloud-metadata address before opening a
    connection — and if the guard itself cannot run, refuse the fetch rather
    than proceeding unchecked. Redirects are never auto-followed: each hop is
    re-validated with the same guard (urllib's default auto-follow would let a
    public host redirect to an internal/metadata address past the initial
    check).
    """
    try:
        from mediahub.web_research.safe_fetch import is_url_safe
    except Exception:
        return None  # guard unavailable — fail closed, never fetch unchecked

    opener = urllib.request.build_opener(_NoRedirectHandler)
    current = url
    for _ in range(_MAX_REDIRECT_HOPS):
        try:
            if not is_url_safe(current):
                return None
        except Exception:
            return None  # guard errored — fail closed
        try:
            req = urllib.request.Request(current, headers=dict(_FETCH_HEADERS))
            with opener.open(req, timeout=timeout) as resp:
                return resp.read(500_000)
        except urllib.error.HTTPError as exc:
            # With auto-redirects disabled, a 3xx surfaces as HTTPError here;
            # loop back so the next hop goes through the SSRF guard too.
            if exc.code in (301, 302, 303, 307, 308):
                loc = (exc.headers.get("Location") if exc.headers else None) or ""
                if not loc:
                    return None
                current = urllib.parse.urljoin(current, loc)
                continue
            return None
        except (urllib.error.URLError, OSError, Exception):
            return None
    return None  # too many redirects


def _parse_html(raw_bytes: bytes, url: str) -> ProfilePage:
    """Parse HTML bytes into ProfilePage using BeautifulSoup."""
    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    raw_html_length = len(raw_bytes)
    raw = raw_bytes.decode("utf-8", errors="replace")

    # Try BeautifulSoup parsing
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw, "lxml")

        # Remove noise elements
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()

        # Extract tables
        tables: list[list[list[str]]] = []
        for table in soup.find_all("table"):
            rows: list[list[str]] = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(cells)
            if rows:
                tables.append(rows)

        # Extract text
        text = soup.get_text(separator=" ")
        text = re.sub(r"\s+", " ", text).strip()

        return ProfilePage(
            url=url,
            fetched_at=fetched_at,
            text=text[:15_000],
            tables=tables,
            raw_html_length=raw_html_length,
            fetch_success=True,
        )
    except ImportError:
        pass

    # Stdlib fallback
    text = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()

    # Simple table extraction fallback (just rows with | separator)
    tables = []
    table_matches = re.findall(r"<table[^>]*>(.*?)</table>", raw, flags=re.DOTALL | re.IGNORECASE)
    for table_html in table_matches:
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.DOTALL | re.IGNORECASE):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.DOTALL | re.IGNORECASE)
            cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in cells]
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)

    return ProfilePage(
        url=url,
        fetched_at=fetched_at,
        text=text[:15_000],
        tables=tables,
        raw_html_length=raw_html_length,
        fetch_success=True,
    )


def fetch_profile_page(url: str, timeout: int = 12) -> ProfilePage:
    """
    Fetch a swimmer profile or results page and return structured content.

    Args:
        url: The URL to fetch.
        timeout: HTTP timeout in seconds.

    Returns:
        ProfilePage with text and tables extracted.
    """
    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    raw_bytes = _fetch_raw(url, timeout=timeout)

    if raw_bytes is None:
        return ProfilePage(
            url=url,
            fetched_at=fetched_at,
            text="",
            tables=[],
            fetch_success=False,
            error="Failed to fetch URL",
        )

    return _parse_html(raw_bytes, url)
