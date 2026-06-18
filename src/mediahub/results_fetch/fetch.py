"""mediahub/results_fetch/fetch.py — Tier A (static) fetch + shared primitives.

"Results from a link" reads a competition's results site the way a person with a
browser would, escalating only as far as needed:

    Tier A — static HTTP GET      (this module)
    Tier B — headless Chromium    (rendered.py)
    Tier C — AI looks at the page (ai_read.py, a later step)

This module owns Tier A and the primitives the whole package shares:

  * ``FetchLimits``  — resource budgets (byte caps, timeouts, render budget),
    overridable from the environment.
  * ``FetchedPage``  — the immutable result of one fetch (bytes + provenance).
  * ``FetchBackend`` — the protocol both backends satisfy.
  * ``StaticBackend``— an SSRF-validated GET with a content-type allowlist and a
    hard per-page byte cap, reusing the hardened door in
    ``web_research/safe_fetch.py`` (host/IP + per-hop redirect re-validation).
  * the *shape-based* signals that decide when Tier A is not enough and the
    deterministic result-shape vocabulary (times, scores, placings, distances)
    — sport-agnostic by construction, with no vendor or sport hardcoding.

Everything here is inert: importing it adds no route and changes no behaviour.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable
from urllib.parse import urljoin, urlparse

# Reuse the project's single hardened outbound door. ``is_url_safe`` resolves the
# host and refuses private/loopback/link-local/metadata IPs and non-http(s)
# schemes; we call it on every redirect hop so a public URL can't 302 us onto an
# internal one. Imported read-only — safe_fetch is never modified.
from mediahub.web_research.safe_fetch import is_url_safe

__all__ = [
    "FetchLimits",
    "FetchedPage",
    "FetchBackend",
    "StaticBackend",
    "ALLOWED_CONTENT_TYPES",
    "count_result_shaped_tokens",
    "looks_like_html",
    "render_trigger",
    "visible_text",
]


# ---------------------------------------------------------------------------
# Content-type allowlist + lightweight binary sniffing
# ---------------------------------------------------------------------------

# Only these may be kept. Everything a competition publishes lives here: rendered
# pages, PDFs, plain text, CSV/TSV, JSON APIs, ZIP exports, spreadsheets, and the
# image formats that "results posted as a picture" arrive as.
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "application/pdf",
        "text/plain",
        "text/csv",
        "text/tab-separated-values",
        "application/json",
        "application/zip",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
        "application/vnd.ms-excel",  # .xls
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
    }
)

_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})

# Magic-byte sniffing for downloads that arrive mislabelled (octet-stream / no
# content-type). We only promote bytes to an *already allowed* binary type — a
# tightening, never a way around the allowlist.
_MAGIC_SNIFFS: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),  # also xlsx; the interpreter disambiguates
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

# URL-extension fallback when both the header and the magic bytes are unhelpful.
_EXT_TYPES: dict[str, str] = {
    ".html": "text/html",
    ".htm": "text/html",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".zip": "application/zip",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _normalise_content_type(raw: str) -> str:
    """Lower-cased media type with parameters (``; charset=...``) stripped."""
    return (raw or "").split(";", 1)[0].strip().lower()


def _sniff_content_type(declared: str, body: bytes, url: str) -> Optional[str]:
    """Resolve a trustworthy, *allowed* content type — or ``None`` to reject.

    Order: an allowed declared type wins; otherwise magic bytes; otherwise the
    URL extension. Anything that lands outside :data:`ALLOWED_CONTENT_TYPES` is
    refused (returns ``None``).
    """
    ct = _normalise_content_type(declared)
    if ct in ALLOWED_CONTENT_TYPES:
        return ct
    head = body[:16]
    for magic, sniffed in _MAGIC_SNIFFS:
        if head.startswith(magic):
            return sniffed
    # WEBP is a RIFF container with the 'WEBP' tag at offset 8 (a bare RIFF, e.g.
    # a WAV, is not something we keep).
    if head.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "image/webp"
    path = (urlparse(url).path or "").lower()
    for ext, mapped in _EXT_TYPES.items():
        if path.endswith(ext):
            return mapped
    return None


# ---------------------------------------------------------------------------
# Shape-based result vocabulary (sport-agnostic) + JS-shell detection
# ---------------------------------------------------------------------------

# A page "looks like results" when it carries enough numeric tokens of the shapes
# competitions emit, for ANY sport. We match *shapes*, never vendors or sports:
#   times      1:23.45  / 58.21        scores     3 - 1 / 21:19
#   placings   1st 2nd 3rd 14th        distances  6.42 m / 5.3 km / 980 pts
_RESULT_SHAPE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\d{1,2}[:.]\d{2}(?:\.\d{1,2})?\b"),  # times
    re.compile(r"\b\d{1,3}\s*[-–:]\s*\d{1,3}\b"),  # scores / aggregates
    re.compile(r"\b\d{1,3}(?:st|nd|rd|th)\b", re.IGNORECASE),  # placings
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:m|km|cm|pts?|points)\b", re.IGNORECASE),  # distances/points
)

_SHAPE_SCAN_CAP = 200_000  # tokens past this point add cost without changing the verdict


def count_result_shaped_tokens(text: str) -> int:
    """How many result-shaped numeric tokens appear in ``text`` (capped scan)."""
    if not text:
        return 0
    window = text[:_SHAPE_SCAN_CAP]
    return sum(len(p.findall(window)) for p in _RESULT_SHAPE_PATTERNS)


_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style|noscript|template)[^>]*>.*?</\1>")
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_WS_RE = re.compile(r"\s+")

# Empty SPA mount points: <div id="root"></div>, <div id="app"></div>, Next/Nuxt.
_EMPTY_MOUNT_RE = re.compile(
    r"<(?:div|main)[^>]+id=[\"'](?:root|app|__next|__nuxt|application)[\"'][^>]*>\s*</(?:div|main)>",
    re.IGNORECASE,
)
_ENABLE_JS_RE = re.compile(r"enable\s+javascript|requires\s+javascript", re.IGNORECASE)


def looks_like_html(content_type: str) -> bool:
    """True for ``text/html`` / ``application/xhtml+xml`` (Tier A→B candidates)."""
    return _normalise_content_type(content_type) in _HTML_TYPES


def visible_text(content: bytes | str) -> str:
    """Strip scripts/styles/markup → collapsed visible text. Best-effort, cheap."""
    if isinstance(content, bytes):
        raw = content.decode("utf-8", "ignore")
    else:
        raw = content or ""
    s = _SCRIPT_STYLE_RE.sub(" ", raw)
    s = _TAG_RE.sub(" ", s)
    return _WS_RE.sub(" ", s).strip()


def _is_js_shell(html: str) -> bool:
    """True when the static HTML is a JavaScript shell with no real content yet."""
    if _ENABLE_JS_RE.search(html):
        return True
    if _EMPTY_MOUNT_RE.search(html):
        return True
    return False


def render_trigger(page: "FetchedPage", limits: "FetchLimits") -> Optional[str]:
    """Deterministic Tier A→B escalation decision.

    Returns the name of the trigger that fired, or ``None`` when the static fetch
    is sufficient. Only HTML escalates — PDFs, JSON, CSV, spreadsheets and images
    are already data and are kept as-is. The triggers, in order:

      * ``"thin_body"``       — fewer than ``thin_text_chars`` of visible text;
      * ``"js_shell"``        — an empty ``#root``/``#app`` mount or an "enable
        JavaScript" notice (a client-rendered SPA);
      * ``"no_result_shape"`` — rendered to text but with zero result-shaped
        numeric tokens, so the data (if any) is arriving via JS/XHR.
    """
    if not looks_like_html(page.content_type):
        return None
    text = page.text if page.text is not None else visible_text(page.content)
    if len(text) < limits.thin_text_chars:
        return "thin_body"
    html = page.content.decode("utf-8", "ignore")
    if _is_js_shell(html):
        return "js_shell"
    if count_result_shaped_tokens(text) == 0:
        return "no_result_shape"
    return None


# ---------------------------------------------------------------------------
# Limits + page model
# ---------------------------------------------------------------------------


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        val = int(raw.strip())
    except (TypeError, ValueError):
        return default
    return val if val > 0 else default


@dataclass(frozen=True)
class FetchLimits:
    """Resource budgets for a single crawl's worth of fetching.

    Defaults are deliberately generous for a real championship mirror yet hard
    enough that a hostile or runaway site cannot exhaust the worker. The
    environment overrides (``MEDIAHUB_RESULTS_FETCH_*``) are read once via
    :meth:`from_env`; the full set is documented with the route hardening.
    """

    max_page_bytes: int = 25 * 1024 * 1024
    static_timeout_s: float = 15.0
    static_max_hops: int = 5
    nav_timeout_s: float = 25.0
    settle_timeout_s: float = 6.0
    thin_text_chars: int = 200
    max_renders: int = 60
    render_wall_budget_s: float = 240.0
    screenshot_quality: int = 60
    capture_max_bytes: int = 4 * 1024 * 1024
    capture_total_max_bytes: int = 16 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "FetchLimits":
        return cls(
            max_page_bytes=_int_env("MEDIAHUB_RESULTS_FETCH_MAX_PAGE_MB", 25) * 1024 * 1024,
            max_renders=_int_env("MEDIAHUB_RESULTS_FETCH_MAX_RENDERS", 60),
            render_wall_budget_s=float(_int_env("MEDIAHUB_RESULTS_FETCH_RENDER_BUDGET_S", 240)),
        )


@dataclass
class FetchedPage:
    """One fetched resource: its bytes plus the provenance the mirror records.

    ``text`` is the page's visible text when cheaply known (HTML) and ``None``
    for opaque binaries (PDF/ZIP/XLSX/image). ``tier`` records how it was read.
    """

    content: bytes
    final_url: str
    content_type: str
    tier: str = "static"
    text: Optional[str] = None

    @property
    def byte_len(self) -> int:
        return len(self.content)


@runtime_checkable
class FetchBackend(Protocol):
    """A read tier: turn a URL into a :class:`FetchedPage`, or ``None``."""

    tier: str

    def fetch(self, url: str) -> Optional[FetchedPage]:  # pragma: no cover - protocol
        ...


# ---------------------------------------------------------------------------
# Tier A — static backend
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": "MediaHubResults/1.0 (+https://github.com/)",
    "Accept": (
        "text/html,application/xhtml+xml,application/pdf,application/json,"
        "text/csv,text/plain,application/zip,*/*;q=0.5"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})

# Keep-alive connection-pool size. A results crawl hits one host many times, so a
# pooled session reuses TCP+TLS connections (a fresh ``requests.get`` per page
# pays a full handshake every time). Sized comfortably above the crawl's default
# static-fetch concurrency so parallel read-ahead never starves on connections.
_POOL_MAXSIZE = 24


def _read_capped(response, cap: int) -> Optional[bytes]:
    """Stream up to ``cap`` bytes; ``None`` if the body exceeds the cap."""
    out = bytearray()
    try:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            out.extend(chunk)
            if len(out) > cap:
                return None
    except Exception:
        return None
    return bytes(out)


@dataclass
class StaticBackend:
    """Tier A: SSRF-validated HTTP GET, allowlisted, byte-capped. Never raises.

    Mirrors ``safe_fetch``'s philosophy — manual redirect following with the host
    re-validated at every hop — but returns raw *bytes* (not stripped text) so a
    PDF/CSV/JSON/XLSX/image download survives intact for the interpreter.

    One backend == one crawl: a single pooled, keep-alive ``requests.Session`` is
    shared across every page (and across the crawl's parallel read-ahead threads —
    a Session is safe for concurrent requests), so repeated hits on the same host
    reuse connections instead of re-handshaking TCP+TLS each time. ``fetch`` itself
    is unchanged in behaviour: same SSRF re-validation, same allowlist, same byte
    cap — only the transport is pooled.
    """

    limits: FetchLimits = field(default_factory=FetchLimits)
    tier: str = "static"
    _session: object = field(default=None, init=False, repr=False, compare=False)
    _session_lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

    def _get_session(self):
        """The shared keep-alive session, built once (thread-safe), or ``None``
        when ``requests`` is unavailable so the caller falls back gracefully."""
        sess = self._session
        if sess is not None:
            return sess
        with self._session_lock:
            if self._session is None:
                try:
                    import requests  # noqa: PLC0415
                    from requests.adapters import HTTPAdapter  # noqa: PLC0415
                except Exception:  # pragma: no cover - requests is a hard dependency
                    return None
                s = requests.Session()
                adapter = HTTPAdapter(
                    pool_connections=4, pool_maxsize=_POOL_MAXSIZE, max_retries=0
                )
                s.mount("http://", adapter)
                s.mount("https://", adapter)
                s.headers.update(_HEADERS)
                self._session = s
            return self._session

    def close(self) -> None:
        """Release the pooled connections. Idempotent; safe to call once a crawl
        finishes. A new ``fetch`` after close lazily rebuilds the session."""
        sess = self._session
        self._session = None
        if sess is not None:
            try:
                sess.close()
            except Exception:  # pragma: no cover - best-effort teardown
                pass

    def fetch(self, url: str) -> Optional[FetchedPage]:
        session = self._get_session()
        if session is None:  # pragma: no cover - requests is a hard dependency
            return None

        current = (url or "").strip()
        for _ in range(max(1, self.limits.static_max_hops)):
            if not is_url_safe(current):
                return None
            try:
                resp = session.get(
                    current,
                    timeout=self.limits.static_timeout_s,
                    allow_redirects=False,  # follow manually, re-validating each hop
                    stream=True,
                )
            except Exception:
                return None
            try:
                if resp.status_code in _REDIRECT_CODES:
                    loc = resp.headers.get("Location")
                    if not loc:
                        return None
                    current = urljoin(current, loc)
                    continue
                if resp.status_code != 200:
                    return None
                body = _read_capped(resp, self.limits.max_page_bytes)
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
            if body is None or not body:
                return None
            ctype = _sniff_content_type(resp.headers.get("Content-Type", ""), body, current)
            if ctype is None:
                return None
            text = visible_text(body) if ctype in _HTML_TYPES else None
            return FetchedPage(
                content=body,
                final_url=current,
                content_type=ctype,
                tier="static",
                text=text,
            )
        return None  # too many redirects
