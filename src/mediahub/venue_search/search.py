"""Search the public web for venue images.

Primary source: Wikimedia Commons (CC-licensed public-domain results).
Each result includes:
  - thumb_url
  - source_url (the Commons file page)
  - direct_url (the image file URL)
  - title / description
  - dimensions
  - licence  (e.g. 'CC BY-SA 4.0', 'public domain')
  - attribution_required (bool)
  - permission_status ('approved_public' for CC; 'needs_approval' otherwise)

Falls back to Openverse if Wikimedia returns nothing.
Network failures return [] — never raises.
"""
from __future__ import annotations

import logging
import urllib.parse
from dataclasses import dataclass, asdict, field
from typing import Optional

import requests

log = logging.getLogger(__name__)

WIKI_API = "https://commons.wikimedia.org/w/api.php"
OPENVERSE_API = "https://api.openverse.org/v1/images/"


@dataclass
class VenueImageResult:
    title: str
    thumb_url: str
    direct_url: str
    source_url: str
    source_site: str = "wikimedia"
    width: int = 0
    height: int = 0
    licence: str = ""
    licence_url: Optional[str] = None
    attribution: Optional[str] = None
    attribution_required: bool = True
    permission_status: str = "approved_public"
    description: str = ""
    confidence: float = 0.5     # how likely this is the right venue

    def to_dict(self) -> dict:
        return asdict(self)


def search(query: str, *, limit: int = 8, timeout: int = 8) -> list[VenueImageResult]:
    """Search for venue images. Always returns a list (never raises)."""
    query = (query or "").strip()
    if not query:
        return []
    results: list[VenueImageResult] = []
    try:
        results.extend(_search_wikimedia(query, limit=limit, timeout=timeout))
    except Exception as e:
        log.warning("wikimedia search failed: %s", e)
    if len(results) < 3:
        try:
            results.extend(_search_openverse(query, limit=limit - len(results), timeout=timeout))
        except Exception as e:
            log.debug("openverse search failed: %s", e)
    # Score-rank
    needle = query.lower()
    for r in results:
        if needle in (r.title or "").lower():
            r.confidence = max(r.confidence, 0.85)
        elif any(w in (r.title or "").lower() for w in needle.split() if len(w) > 3):
            r.confidence = max(r.confidence, 0.6)
    results.sort(key=lambda x: -x.confidence)
    return results[:limit]


# ---------------------------------------------------------------------------
# Wikimedia Commons
# ---------------------------------------------------------------------------

def _search_wikimedia(query: str, *, limit: int, timeout: int) -> list[VenueImageResult]:
    # Step 1: search for files matching query
    params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "srsearch": f"{query} filetype:bitmap",
        "srnamespace": 6,         # File namespace
        "srlimit": str(limit * 2),
    }
    r = requests.get(WIKI_API, params=params,
                     headers={"User-Agent": "MediaHub/0.8 (venue_search)"},
                     timeout=timeout)
    r.raise_for_status()
    data = r.json()
    titles = [hit["title"] for hit in data.get("query", {}).get("search", [])]
    if not titles:
        return []

    # Step 2: fetch image info + license for each
    info_params = {
        "action": "query",
        "format": "json",
        "titles": "|".join(titles[:limit * 2]),
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata|user",
        "iiurlwidth": "800",
    }
    r2 = requests.get(WIKI_API, params=info_params,
                      headers={"User-Agent": "MediaHub/0.8"},
                      timeout=timeout)
    r2.raise_for_status()
    pages = r2.json().get("query", {}).get("pages", {}) or {}

    results: list[VenueImageResult] = []
    for page in pages.values():
        try:
            info = (page.get("imageinfo") or [{}])[0]
            if not info:
                continue
            ext = info.get("extmetadata") or {}
            licence = ext.get("LicenseShortName", {}).get("value", "") or ext.get("UsageTerms", {}).get("value", "")
            licence_url = ext.get("LicenseUrl", {}).get("value")
            attribution = ext.get("Artist", {}).get("value") or info.get("user")
            description = ext.get("ImageDescription", {}).get("value", "") or ""
            # Strip simple HTML
            import re as _re
            description = _re.sub(r"<[^>]+>", "", description).strip()
            attribution = _re.sub(r"<[^>]+>", "", attribution or "").strip() or None
            file_page = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(page.get("title", ""))

            licence_lower = (licence or "").lower()
            attribution_required = bool(licence) and "public domain" not in licence_lower
            # Map to permission status
            if "public domain" in licence_lower:
                perm = "approved_public"
            elif licence_lower.startswith("cc"):
                perm = "approved_public"
            else:
                perm = "needs_approval"

            results.append(VenueImageResult(
                title=page.get("title", "").replace("File:", ""),
                thumb_url=info.get("thumburl") or info.get("url", ""),
                direct_url=info.get("url", ""),
                source_url=file_page,
                source_site="wikimedia",
                width=info.get("width", 0) or 0,
                height=info.get("height", 0) or 0,
                licence=licence,
                licence_url=licence_url,
                attribution=attribution,
                attribution_required=attribution_required,
                permission_status=perm,
                description=description[:400],
                confidence=0.55,
            ))
        except Exception as e:
            log.debug("wiki entry parse failed: %s", e)
            continue
    return results


# ---------------------------------------------------------------------------
# Openverse fallback (also CC-licensed)
# ---------------------------------------------------------------------------

def _search_openverse(query: str, *, limit: int, timeout: int) -> list[VenueImageResult]:
    if limit <= 0:
        return []
    params = {"q": query, "page_size": str(min(limit, 20))}
    r = requests.get(OPENVERSE_API, params=params,
                     headers={"User-Agent": "MediaHub/0.8"}, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    out: list[VenueImageResult] = []
    for item in data.get("results", []):
        try:
            licence = (item.get("license") or "") + (
                f" {item.get('license_version','')}" if item.get("license_version") else ""
            )
            attribution = item.get("creator")
            licence_lower = (licence or "").lower()
            if "cc0" in licence_lower or "public" in licence_lower:
                perm = "approved_public"
                attribution_required = False
            elif licence_lower.startswith("cc") or licence_lower.startswith(" cc"):
                perm = "approved_public"
                attribution_required = True
            else:
                perm = "needs_approval"
                attribution_required = True
            out.append(VenueImageResult(
                title=item.get("title") or "",
                thumb_url=item.get("thumbnail") or item.get("url", ""),
                direct_url=item.get("url", ""),
                source_url=item.get("foreign_landing_url") or item.get("url", ""),
                source_site=(item.get("source") or "openverse"),
                width=item.get("width", 0) or 0,
                height=item.get("height", 0) or 0,
                licence=licence.strip(),
                licence_url=item.get("license_url"),
                attribution=attribution,
                attribution_required=attribution_required,
                permission_status=perm,
                description=item.get("description", "") or "",
                confidence=0.5,
            ))
        except Exception:
            continue
    return out


__all__ = ["search", "VenueImageResult"]
