"""elements.stock — MediaHub's own licence-clean stock pool (roadmap 1.10, build 3).

Canva/Express bundle vendor stock integrations (Adobe Stock's 200M+, Pexels,
Pixabay). MediaHub instead **curates its own pool seeded from open collections**:
Openverse and Wikimedia Commons are *sources we harvest*, not in-product vendor
pickers. Every result carries its licence + attribution as a shared
:class:`~mediahub.audio.library.Licence` value (the same rights vocabulary the
1.8 audio pool uses), and only commercially-usable, attributable results are
surfaced by default — an honest ``commercial_ok=False`` keeps a risky asset out
rather than inviting a takedown.

Paid sources (Pexels, Pixabay) are an **optional, flag-gated seam**: they feed the
same pool only when an operator sets their key, and honest-error otherwise — they
are never a bundled dependency (rule 11: in-house first; an external service is
only ever a swappable slot behind our own interface).

The photo path reuses the shipped ``venue_search`` crawler (Wikimedia → Openverse,
CC-only); the video path adds a Wikimedia Commons media adapter (feeds the 1.6
video suite). Imports are recorded in a small rights ledger so attribution is
preserved per asset and `commercial_ok` is auditable per platform.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

from mediahub.audio.library import Licence  # shared rights vocabulary (1.8 ↔ 1.10)

log = logging.getLogger(__name__)

WIKI_API = "https://commons.wikimedia.org/w/api.php"

# Source ids. The first two are always-on, licence-clean, first-party-harvested.
# The paid ones are flag-gated seams (honest-error without a key).
SOURCE_OPENVERSE = "openverse"
SOURCE_WIKIMEDIA = "wikimedia"
SOURCE_PEXELS = "pexels"
SOURCE_PIXABAY = "pixabay"

_FREE_SOURCES = (SOURCE_WIKIMEDIA, SOURCE_OPENVERSE)
_PAID_SOURCES = (SOURCE_PEXELS, SOURCE_PIXABAY)


# --------------------------------------------------------------------------- #
# result model
# --------------------------------------------------------------------------- #
@dataclass
class StockResult:
    """One licence-clean stock asset (photo or video)."""

    title: str
    thumb_url: str
    direct_url: str
    source_url: str
    source_site: str = SOURCE_WIKIMEDIA
    kind: str = "photo"  # "photo" | "video"
    width: int = 0
    height: int = 0
    licence: Licence = field(default_factory=Licence)
    permission_status: str = "approved_public"
    description: str = ""
    confidence: float = 0.5

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "thumb_url": self.thumb_url,
            "direct_url": self.direct_url,
            "source_url": self.source_url,
            "source_site": self.source_site,
            "kind": self.kind,
            "width": self.width,
            "height": self.height,
            "licence": self.licence.to_dict(),
            "permission_status": self.permission_status,
            "description": self.description,
            "confidence": self.confidence,
        }


# --------------------------------------------------------------------------- #
# licence parsing (CC string → shared Licence + commercial_ok gate)
# --------------------------------------------------------------------------- #
# SPDX best-effort for the common Creative Commons / public-domain strings.
_SPDX_MAP = {
    "cc0": "CC0-1.0",
    "publicdomain": "CC0-1.0",
    "public domain": "CC0-1.0",
    "pdm": "CC0-1.0",
    "ccby4.0": "CC-BY-4.0",
    "ccbysa4.0": "CC-BY-SA-4.0",
    "ccby3.0": "CC-BY-3.0",
    "ccbysa3.0": "CC-BY-SA-3.0",
    "ccby2.0": "CC-BY-2.0",
    "ccbysa2.0": "CC-BY-SA-2.0",
}


def parse_licence(
    licence_str: str, *, url: str = "", attribution: str = "", source: str = ""
) -> Licence:
    """Map a free-text licence string to a shared :class:`Licence`.

    ``commercial_ok`` is conservative: only positively-recognised commercially-
    usable CC/public-domain licences are True. Anything non-commercial (NC) or
    unrecognised is False — we'd rather hold an asset back than ship a takedown.
    """
    raw = (licence_str or "").strip()
    norm = raw.lower().replace("-", "").replace(" ", "")

    # Non-commercial or no-derivatives → not safe for automated commercial use.
    if "nc" in norm or "noncommercial" in norm:
        commercial_ok = False
    elif any(tok in norm for tok in ("cc0", "publicdomain", "pdm", "ccby")):
        commercial_ok = True
    elif "publicdomain" in raw.lower():
        commercial_ok = True
    else:
        commercial_ok = False  # unrecognised → honest no

    spdx = ""
    for key, val in _SPDX_MAP.items():
        if key in norm:
            spdx = val
            break

    return Licence(
        name=raw or "unknown",
        spdx=spdx,
        url=url or "",
        attribution=attribution or "",
        source=source or "",
        commercial_ok=commercial_ok,
    )


# --------------------------------------------------------------------------- #
# source availability (paid sources gated on env keys)
# --------------------------------------------------------------------------- #
def _pexels_key() -> str:
    return (os.environ.get("PEXELS_API_KEY") or "").strip()


def _pixabay_key() -> str:
    return (os.environ.get("PIXABAY_API_KEY") or "").strip()


def available_sources() -> dict[str, bool]:
    """Which stock sources are active right now (paid ones need a key)."""
    return {
        SOURCE_WIKIMEDIA: True,
        SOURCE_OPENVERSE: True,
        SOURCE_PEXELS: bool(_pexels_key()),
        SOURCE_PIXABAY: bool(_pixabay_key()),
    }


# --------------------------------------------------------------------------- #
# search
# --------------------------------------------------------------------------- #
def search(
    query: str,
    *,
    kind: str = "photo",
    limit: int = 12,
    sources: Optional[list[str]] = None,
    commercial_only: bool = True,
    timeout: int = 8,
) -> list[StockResult]:
    """Search the licence-clean stock pool. Always returns a list (never raises).

    ``kind`` is "photo" (Openverse/Wikimedia, + flag-gated paid) or "video"
    (Wikimedia Commons media). ``commercial_only`` (default) drops any result
    whose licence isn't safe for a club's commercial content.
    """
    query = (query or "").strip()
    if not query:
        return []
    want = set(sources or (list(_FREE_SOURCES) + list(_PAID_SOURCES)))
    results: list[StockResult] = []

    if kind == "video":
        try:
            results.extend(_search_wikimedia_video(query, limit=limit, timeout=timeout))
        except Exception as e:  # pragma: no cover - network
            log.debug("wikimedia video search failed: %s", e)
    else:
        if want & set(_FREE_SOURCES):
            try:
                results.extend(_search_free_photos(query, limit=limit, timeout=timeout))
            except Exception as e:  # pragma: no cover - venue_search already no-raises
                log.debug("free photo search failed: %s", e)
        if SOURCE_PEXELS in want and _pexels_key():
            try:
                results.extend(_search_pexels(query, limit=limit, timeout=timeout))
            except Exception as e:  # pragma: no cover - network
                log.debug("pexels search failed: %s", e)
        if SOURCE_PIXABAY in want and _pixabay_key():
            try:
                results.extend(_search_pixabay(query, limit=limit, timeout=timeout))
            except Exception as e:  # pragma: no cover - network
                log.debug("pixabay search failed: %s", e)

    if commercial_only:
        results = [r for r in results if r.licence.commercial_ok]
    return results[:limit]


def _search_free_photos(query: str, *, limit: int, timeout: int) -> list[StockResult]:
    """Reuse the shipped venue_search crawler (Wikimedia → Openverse, CC-only)."""
    try:
        from mediahub.venue_search.search import search as _venue_search
    except Exception:  # pragma: no cover - import guard
        return []
    out: list[StockResult] = []
    for r in _venue_search(query, limit=limit, timeout=timeout):
        lic = parse_licence(
            r.licence or "",
            url=r.licence_url or "",
            attribution=r.attribution or "",
            source=r.source_site,
        )
        out.append(
            StockResult(
                title=r.title,
                thumb_url=r.thumb_url,
                direct_url=r.direct_url,
                source_url=r.source_url,
                source_site=r.source_site,
                kind="photo",
                width=r.width,
                height=r.height,
                licence=lic,
                permission_status=r.permission_status,
                description=r.description,
                confidence=r.confidence,
            )
        )
    return out


def _search_wikimedia_video(query: str, *, limit: int, timeout: int) -> list[StockResult]:
    """Wikimedia Commons video (webm/ogv) — CC-licensed, feeds the 1.6 suite."""
    import requests

    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{query} filetype:video",
        "gsrnamespace": "6",
        "gsrlimit": str(max(1, min(limit, 20))),
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata|mime",
        "iiurlwidth": "480",
    }
    headers = {"User-Agent": "MediaHub/1.0 (stock pool)"}
    resp = requests.get(WIKI_API, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    pages = ((resp.json() or {}).get("query") or {}).get("pages") or {}
    out: list[StockResult] = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        if not (info.get("mime") or "").startswith("video/"):
            continue
        meta = info.get("extmetadata") or {}
        lic_short = (meta.get("LicenseShortName") or {}).get("value", "")
        lic_url = (meta.get("LicenseUrl") or {}).get("value", "")
        artist = (meta.get("Artist") or {}).get("value", "")
        out.append(
            StockResult(
                title=page.get("title", "").replace("File:", ""),
                thumb_url=info.get("thumburl", ""),
                direct_url=info.get("url", ""),
                source_url=info.get("descriptionurl", ""),
                source_site=SOURCE_WIKIMEDIA,
                kind="video",
                width=int(info.get("width") or 0),
                height=int(info.get("height") or 0),
                licence=parse_licence(
                    lic_short, url=lic_url, attribution=_strip_html(artist), source=SOURCE_WIKIMEDIA
                ),
                description=query,
                confidence=0.6,
            )
        )
    return out


def _search_pexels(
    query: str, *, limit: int, timeout: int
) -> list[StockResult]:  # pragma: no cover - keyed
    """Flag-gated paid source. Only called when PEXELS_API_KEY is set."""
    import requests

    headers = {"Authorization": _pexels_key(), "User-Agent": "MediaHub/1.0"}
    resp = requests.get(
        "https://api.pexels.com/v1/search",
        params={"query": query, "per_page": str(max(1, min(limit, 20)))},
        headers=headers,
        timeout=timeout,
    )
    resp.raise_for_status()
    out: list[StockResult] = []
    for ph in (resp.json() or {}).get("photos", []):
        src = ph.get("src") or {}
        out.append(
            StockResult(
                title=ph.get("alt") or query,
                thumb_url=src.get("medium", ""),
                direct_url=src.get("large2x") or src.get("original", ""),
                source_url=ph.get("url", ""),
                source_site=SOURCE_PEXELS,
                kind="photo",
                width=int(ph.get("width") or 0),
                height=int(ph.get("height") or 0),
                # Pexels licence is free for commercial use, attribution appreciated.
                licence=Licence(
                    name="Pexels License",
                    url="https://www.pexels.com/license/",
                    attribution=str(ph.get("photographer") or ""),
                    source=SOURCE_PEXELS,
                    commercial_ok=True,
                ),
                confidence=0.7,
            )
        )
    return out


def _search_pixabay(
    query: str, *, limit: int, timeout: int
) -> list[StockResult]:  # pragma: no cover - keyed
    """Flag-gated paid source. Only called when PIXABAY_API_KEY is set."""
    import requests

    resp = requests.get(
        "https://pixabay.com/api/",
        params={
            "key": _pixabay_key(),
            "q": query,
            "per_page": str(max(3, min(limit, 20))),
            "safesearch": "true",
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    out: list[StockResult] = []
    for hit in (resp.json() or {}).get("hits", []):
        out.append(
            StockResult(
                title=hit.get("tags") or query,
                thumb_url=hit.get("webformatURL", ""),
                direct_url=hit.get("largeImageURL") or hit.get("webformatURL", ""),
                source_url=hit.get("pageURL", ""),
                source_site=SOURCE_PIXABAY,
                kind="photo",
                width=int(hit.get("imageWidth") or 0),
                height=int(hit.get("imageHeight") or 0),
                licence=Licence(
                    name="Pixabay Content License",
                    url="https://pixabay.com/service/license-summary/",
                    attribution=str(hit.get("user") or ""),
                    source=SOURCE_PIXABAY,
                    commercial_ok=True,
                ),
                confidence=0.7,
            )
        )
    return out


def _strip_html(text: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", text or "").strip()


# --------------------------------------------------------------------------- #
# first-party thumbnail proxy (CSP img-src 'self')
# --------------------------------------------------------------------------- #
# The stock browser surfaces thumbnails whose URLs are cross-origin (Wikimedia /
# Openverse / flag-gated paid CDNs). The app CSP pins ``img-src 'self'``, so the
# browser blocks those <img> loads and the grid shows blank tiles. Rather than
# loosen the CSP for the whole app (the same reason brand logos are mirrored
# first-party — see ``brand.logos.mirror_external_logo``), we stream the bytes
# through our own origin. To keep this from being an open image relay it is
# pinned to the known stock CDNs *and* SSRF-checked (a public host can't 302 the
# fetch onto an internal address), size-capped, and image/video-only.
_PROXY_HOST_SUFFIXES = (
    "wikimedia.org",  # upload.wikimedia.org, commons.wikimedia.org
    "wikipedia.org",
    "openverse.org",  # api.openverse.org thumbnails
    "pexels.com",  # images.pexels.com
    "pixabay.com",  # pixabay.com, cdn.pixabay.com
)
_THUMB_MAX_BYTES = 12 * 1024 * 1024  # a thumbnail/poster is far smaller
_THUMB_TIMEOUT = 12  # seconds
_THUMB_MAX_HOPS = 3
_THUMB_UA = "MediaHub/1.0 (stock thumbnail proxy)"
_THUMB_OK_CT_PREFIXES = ("image/", "video/")


def is_proxy_host(host: str) -> bool:
    """True if ``host`` is one of the allow-listed stock CDNs we will proxy."""
    h = (host or "").lower().strip().rstrip(".")
    return any(h == s or h.endswith("." + s) for s in _PROXY_HOST_SUFFIXES)


def fetch_thumb(url: str, *, timeout: int = _THUMB_TIMEOUT) -> tuple[Optional[bytes], str]:
    """Fetch a stock thumbnail's bytes for first-party serving under the CSP.

    Host-allow-listed to the known stock CDNs, SSRF-checked on every redirect
    hop, size-capped, and image/video-only. Returns ``(data, content_type)`` —
    or ``(None, "")`` on any refusal/failure. Never raises.
    """
    url = (url or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return None, ""
    try:
        import requests

        from mediahub.web_research.safe_fetch import is_url_safe
    except Exception:  # pragma: no cover - both are core deps
        return None, ""

    current = url
    for _ in range(_THUMB_MAX_HOPS):
        host = urlparse(current).hostname or ""
        # Allow-list first (cheap), then SSRF-resolve the host (re-checked every
        # hop so a redirect can't smuggle the fetch onto a private address).
        if not is_proxy_host(host) or not is_url_safe(current):
            log.debug("stock thumb proxy refused host: %s", host)
            return None, ""
        try:
            r = requests.get(
                current,
                headers={"User-Agent": _THUMB_UA, "Accept": "image/*,video/*;q=0.8,*/*;q=0.5"},
                timeout=timeout,
                allow_redirects=False,
                stream=True,
            )
        except Exception as e:  # pragma: no cover - network
            log.debug("stock thumb proxy fetch failed for %s: %s", current, e)
            return None, ""
        if r.status_code in (301, 302, 303, 307, 308):
            nxt = r.headers.get("Location", "")
            if not nxt:
                return None, ""
            current = urljoin(current, nxt)
            continue
        if r.status_code != 200:
            return None, ""
        ctype = (r.headers.get("Content-Type", "") or "").split(";")[0].strip().lower()
        if not any(ctype.startswith(p) for p in _THUMB_OK_CT_PREFIXES):
            log.debug("stock thumb proxy refused non-media content (%r)", ctype)
            return None, ""
        chunks: list[bytes] = []
        total = 0
        try:
            for chunk in r.iter_content(64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > _THUMB_MAX_BYTES:
                    log.debug("stock thumb proxy exceeded %d-byte cap", _THUMB_MAX_BYTES)
                    return None, ""
                chunks.append(chunk)
        except Exception as e:  # pragma: no cover - network
            log.debug("stock thumb proxy read failed for %s: %s", current, e)
            return None, ""
        data = b"".join(chunks)
        if not data:
            return None, ""
        return data, ctype
    return None, ""  # too many redirects


# --------------------------------------------------------------------------- #
# rights ledger (shared Licence vocabulary, persisted, auditable)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class StockRightsRecord:
    asset_id: str
    profile_id: str
    source: str
    source_url: str
    kind: str
    licence: Licence
    imported_at: str = ""

    def safe_for_commercial(self) -> bool:
        return bool(self.licence.commercial_ok)

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "profile_id": self.profile_id,
            "source": self.source,
            "source_url": self.source_url,
            "kind": self.kind,
            "licence": self.licence.to_dict(),
            "imported_at": self.imported_at,
        }


class StockRightsLedger:
    """Per-asset licence/attribution ledger for imported stock.

    Shares ``data.db`` and the :class:`Licence` vocabulary with the 1.8 audio
    rights ledger; the table is image/video-specific (no acoustic fingerprint).
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or (
            Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[2]))) / "data.db"
        )
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(str(self._db_path))

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stock_rights (
                    asset_id TEXT PRIMARY KEY,
                    profile_id TEXT,
                    source TEXT,
                    source_url TEXT,
                    kind TEXT,
                    licence_name TEXT,
                    licence_spdx TEXT,
                    licence_url TEXT,
                    attribution TEXT,
                    commercial_ok INTEGER,
                    imported_at TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_stock_rights_profile ON stock_rights(profile_id)"
            )

    def record(self, rec: StockRightsRecord) -> StockRightsRecord:
        imported = rec.imported_at or datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO stock_rights
                (asset_id, profile_id, source, source_url, kind,
                 licence_name, licence_spdx, licence_url, attribution, commercial_ok, imported_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    rec.asset_id,
                    rec.profile_id,
                    rec.source,
                    rec.source_url,
                    rec.kind,
                    rec.licence.name,
                    rec.licence.spdx,
                    rec.licence.url,
                    rec.licence.attribution,
                    1 if rec.licence.commercial_ok else 0,
                    imported,
                ),
            )
        return StockRightsRecord(
            asset_id=rec.asset_id,
            profile_id=rec.profile_id,
            source=rec.source,
            source_url=rec.source_url,
            kind=rec.kind,
            licence=rec.licence,
            imported_at=imported,
        )

    def get(self, asset_id: str) -> Optional[StockRightsRecord]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM stock_rights WHERE asset_id=?", (asset_id,)
            ).fetchone()
        return _row_to_record(row)

    def list_for_profile(self, profile_id: str) -> list[StockRightsRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM stock_rights WHERE profile_id=? ORDER BY imported_at DESC",
                (profile_id,),
            ).fetchall()
        return [r for r in (_row_to_record(row) for row in rows) if r is not None]

    def delete(self, asset_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM stock_rights WHERE asset_id=?", (asset_id,))
            return cur.rowcount > 0


def _row_to_record(row) -> Optional[StockRightsRecord]:
    if not row:
        return None
    (
        asset_id,
        profile_id,
        source,
        source_url,
        kind,
        licence_name,
        licence_spdx,
        licence_url,
        attribution,
        commercial_ok,
        imported_at,
    ) = row
    return StockRightsRecord(
        asset_id=asset_id,
        profile_id=profile_id,
        source=source,
        source_url=source_url,
        kind=kind,
        licence=Licence(
            name=licence_name or "",
            spdx=licence_spdx or "",
            url=licence_url or "",
            attribution=attribution or "",
            source=source or "",
            commercial_ok=bool(commercial_ok),
        ),
        imported_at=imported_at or "",
    )


_default_ledger: Optional[StockRightsLedger] = None


def get_ledger() -> StockRightsLedger:
    global _default_ledger
    if _default_ledger is None:
        _default_ledger = StockRightsLedger()
    return _default_ledger


__all__ = [
    "StockResult",
    "Licence",
    "parse_licence",
    "search",
    "available_sources",
    "fetch_thumb",
    "is_proxy_host",
    "StockRightsRecord",
    "StockRightsLedger",
    "get_ledger",
]
