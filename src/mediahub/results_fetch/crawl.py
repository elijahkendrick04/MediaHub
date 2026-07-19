"""mediahub/results_fetch/crawl.py — the deterministic structural walker.

Given an entry URL, walk a results site the way the interpreter walks a frameset
mirror on disk: follow structure (frames, links, and the data APIs a rendered
page pulls from), stay inside a validated same-host/path-prefix scope, and keep
every file that looks like competition results — sport-agnostic, by *shape*, with
no vendor or sport hardcoding (mirrors the philosophy at the top of
``interpreter/ingest.py``).

The path-prefix is the primary bound, with one shallow widening for meet *hubs*:
same-host links discovered on the ENTRY page that fall outside the prefix are
followed too (e.g. a ``/meets/<id>/results`` hub whose event pages live at a
sibling ``/events/<id>/results``). Those off-prefix pages are kept only if they
are themselves result-shaped, and they spawn no further off-prefix following —
so a large multi-meet host is never crawled wholesale.

The walker reads each page through :func:`results_fetch.read_page`, so it gets
static-then-rendered escalation for free and shares ONE browser across the whole
crawl. What it produces is a **mirror**: a flat ``{relative_path: bytes}`` map of
kept files (HTML snapshots, PDFs, spreadsheets, captured JSON/CSV APIs) plus
per-file provenance, the entry file, screenshots, honest skip/block/budget
counters, and the pages the AI tier should look at. Step 6 zips that mirror and
hands it to the existing upload pipeline unchanged.

Everything is inert: importing this adds no route and changes no behaviour.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from . import ReadResult, escalate_static
from .fetch import (
    FetchedPage,
    FetchLimits,
    StaticBackend,
    count_result_shaped_tokens,
    visible_text,
)
from .rendered import RenderedBackend, RenderedPage, Scope, in_scope, scope_for

log = logging.getLogger(__name__)

# Cheap, high-value result data files: a static fetch, never a headless render.
# Prioritised in the crawl frontier so a large meet's actual results land before
# the render budget is spent on the JS app's navigation pages.
_DATA_FILE_EXTS = (".pdf", ".csv", ".tsv", ".json", ".xlsx", ".xls", ".zip", ".txt")


def _is_data_file(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(_DATA_FILE_EXTS)


__all__ = [
    "CrawlLimits",
    "CrawlResult",
    "CrawlProgress",
    "FileProvenance",
    "crawl_results_site",
    "shape_gate",
]

_USER_AGENT = "MediaHubResults"

# Data document types that are kept on sight when in scope — they ARE the results
# (a league's spreadsheet, a meet's PDF). HTML/text/JSON still face the shape gate.
_KEEP_ON_SIGHT = frozenset(
    {
        "application/pdf",
        "text/csv",
        "text/tab-separated-values",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    }
)
_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})

# Extensions we never follow as crawl targets (assets, not pages/data).
_ASSET_EXTS = frozenset(
    {
        ".css",
        ".js",
        ".mjs",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".webp",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".mp4",
        ".webm",
        ".mp3",
        ".zip",
    }
)

_HREF_SRC_RE = re.compile(
    rb"""<(?:a|frame|iframe)\b[^>]*?\b(?:href|src)\s*=\s*["']([^"'#]+)["']""",
    re.IGNORECASE,
)
_TABLE_RE = re.compile(rb"<(?:table|tr|pre)\b", re.IGNORECASE)
_MIN_RESULT_TOKENS = 4


# ---------------------------------------------------------------------------
# Limits
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


@dataclass
class CrawlLimits:
    """Bounds for one crawl. Env overrides are read once via :meth:`from_env`."""

    max_pages: int = 400
    max_total_bytes: int = 50 * 1024 * 1024
    timeout_s: float = 180.0
    max_depth: int = 3
    politeness_delay_s: float = 0.3
    respect_robots: bool = True
    max_ai_candidates: int = 60
    # How many static fetches the crawl may have in flight at once. The static
    # tier is independent, read-only I/O, so reading the frontier's upcoming pages
    # concurrently overlaps network latency without changing WHICH pages are kept
    # (the render tier and every keep/discover decision stay single-threaded and
    # in deterministic order). Also bounds simultaneous requests to one host, so
    # it doubles as the politeness ceiling. 1 ⇒ fully serial (legacy behaviour).
    fetch_concurrency: int = 8
    fetch: FetchLimits = field(default_factory=FetchLimits)

    @classmethod
    def from_env(cls) -> "CrawlLimits":
        return cls(
            max_pages=_int_env("MEDIAHUB_RESULTS_FETCH_MAX_PAGES", 400),
            max_total_bytes=_int_env("MEDIAHUB_RESULTS_FETCH_MAX_TOTAL_MB", 50) * 1024 * 1024,
            timeout_s=float(_int_env("MEDIAHUB_RESULTS_FETCH_TIMEOUT_S", 180)),
            fetch_concurrency=_int_env("MEDIAHUB_RESULTS_FETCH_CONCURRENCY", 8),
            fetch=FetchLimits.from_env(),
        )


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class FileProvenance:
    """Where one kept mirror file came from and how it was read."""

    source_url: str
    tier: str  # "static" | "rendered" | "capture"
    trigger: Optional[str]
    content_type: str
    fetched_at: float


@dataclass
class CrawlResult:
    """A crawled mirror: kept files + provenance + screenshots + honest counters.

    ``files`` is what feeds the interpreter (zipped in Step 6). ``ai_candidates``
    are pages that were fetched but yielded nothing machine-readable (a rendered
    SPA that still hid its data, or a results image) — the Tier-C AI reader looks
    at these. Counters never lie: ``skipped``/``blocked``/``render_budget_hit``
    surface in the progress UI.
    """

    files: dict[str, bytes] = field(default_factory=dict)
    provenance: dict[str, FileProvenance] = field(default_factory=dict)
    screenshots: dict[str, bytes] = field(default_factory=dict)
    ai_candidates: list[ReadResult] = field(default_factory=list)
    entry_file: Optional[str] = None
    entry_url: Optional[str] = None
    pages_visited: int = 0
    kept: int = 0
    skipped: int = 0
    blocked: int = 0
    render_budget_hit: bool = False
    total_bytes: int = 0
    # Entry-page diagnostics — populated for the entry page so a "no results"
    # outcome can say *why* honestly (tier, the exact resolved URL, how many
    # links discovery saw, and how many of those survived the scope filter).
    entry_tier: Optional[str] = None
    entry_final_url: Optional[str] = None
    entry_links_found: int = 0
    entry_links_in_scope: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.files


@dataclass(frozen=True)
class CrawlProgress:
    """A live snapshot handed to ``progress_cb`` once per fetched page.

    A crawl has no fixed total up front — the frontier grows as pages are
    discovered — so an honest "how far in" reading combines two signals the
    caller can blend: ``pages_visited`` (work done) against
    ``frontier_remaining`` (in-scope links discovered but not yet read). When the
    frontier drains toward zero the crawl is genuinely near done; while it keeps
    growing the caller can fall back to the elapsed-vs-timeout fraction so the bar
    never stalls. ``kept`` and ``total_bytes`` carry the real counters for the
    status text.
    """

    pages_visited: int
    kept: int
    total_bytes: int
    frontier_remaining: int = 0
    discovered_total: int = 0
    phase: str = "fetching"

    @property
    def fraction(self) -> float:
        """Fraction of *discovered* work done (0..1). 0 when nothing yet found."""
        denom = self.pages_visited + self.frontier_remaining
        if denom <= 0:
            return 0.0
        return min(1.0, self.pages_visited / denom)


# ---------------------------------------------------------------------------
# Shape gate — does this look like competition results? (shape only)
# ---------------------------------------------------------------------------


def _json_has_object_array(obj, depth: int = 0) -> bool:
    """True if ``obj`` contains, anywhere shallowly, a list of ≥1 dicts."""
    if depth > 6:
        return False
    if isinstance(obj, list):
        if any(isinstance(x, dict) for x in obj):
            return True
        return any(_json_has_object_array(x, depth + 1) for x in obj)
    if isinstance(obj, dict):
        return any(_json_has_object_array(v, depth + 1) for v in obj.values())
    return False


def _looks_tabular_text(text: str) -> bool:
    """≥2 lines that split into ≥2 columns on whitespace/tab/comma runs."""
    rows = 0
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        cols = [c for c in re.split(r"\s{2,}|\t|,", s) if c.strip()]
        if len(cols) >= 2:
            rows += 1
            if rows >= 2:
                return True
    return False


def shape_gate(content: bytes, content_type: str, *, text: Optional[str] = None) -> bool:
    """Generalised result-shape check: structure AND ≥4 result-shaped tokens.

    Sport-agnostic and vendor-blind. "Structure" means an HTML table/grid, a
    tabular text block, or an array of homogeneous JSON objects. "Tokens" are the
    numeric shapes competitions emit (times, scores, placings, distances). Both
    must hold, so a prose page with a stray score doesn't pass and a bare numeric
    dump without structure doesn't either.
    """
    norm = (content_type or "").split(";", 1)[0].strip().lower()

    if norm == "application/json" or norm.endswith("+json"):
        try:
            parsed = json.loads(content.decode("utf-8", "ignore"))
        except Exception:
            return False
        if not _json_has_object_array(parsed):
            return False
        return count_result_shaped_tokens(content.decode("utf-8", "ignore")) >= _MIN_RESULT_TOKENS

    if norm in ("text/html", "application/xhtml+xml"):
        has_structure = bool(_TABLE_RE.search(content[:200_000]))
        body_text = text if text is not None else visible_text(content)
        return has_structure and count_result_shaped_tokens(body_text) >= _MIN_RESULT_TOKENS

    # text/plain and friends
    body_text = text if text is not None else content.decode("utf-8", "ignore")
    return _looks_tabular_text(body_text) and (
        count_result_shaped_tokens(body_text) >= _MIN_RESULT_TOKENS
    )


# ---------------------------------------------------------------------------
# Link discovery + mirror paths
# ---------------------------------------------------------------------------


def _discover_links(content: bytes, base_url: str) -> list[str]:
    """Absolute, de-duplicated follow-up URLs from <a>/<frame>/<iframe> in HTML."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in _HREF_SRC_RE.findall(content):
        href = raw.decode("utf-8", "replace").strip()
        if not href or href.lower().startswith(("javascript:", "mailto:", "tel:", "data:")):
            continue
        absolute = urljoin(base_url, href)
        absolute = absolute.split("#", 1)[0]
        ext = os.path.splitext(urlparse(absolute).path)[1].lower()
        if ext in _ASSET_EXTS:
            continue
        if absolute not in seen:
            seen.add(absolute)
            out.append(absolute)
    return out


def _same_host(a: str, b: str) -> bool:
    """True when two URLs share a hostname (case-insensitive; ignores path)."""
    return (urlparse(a).hostname or "").lower() == (urlparse(b).hostname or "").lower()


def _discovery_base(requested_url: str, final_url: str) -> str:
    """The base to resolve a page's relative links against.

    A rendered backend can report ``final_url`` without the requested
    directory's trailing slash — and sometimes with an added ``#fragment`` or
    ``?query``. Resolving relative links against that makes ``urljoin`` drop the
    directory segment, so the links escape the path-prefix scope and a meet hub
    yields "0 kept". When the request was for a directory (it ended in ``/``) and
    the page is the same host, resolve against the slash-terminated URL we
    actually asked for. Requests with no trailing slash are returned unchanged,
    so genuine "page" entries (e.g. ``…/results/639/events``) still resolve their
    relative links against the parent, exactly as before.
    """
    if requested_url.endswith("/") and _same_host(requested_url, final_url):
        return requested_url
    return final_url


_EXT_FOR_TYPE = {
    "text/html": ".html",
    "application/xhtml+xml": ".html",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "text/tab-separated-values": ".tsv",
    "application/json": ".json",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

_UNSAFE_PATH_RE = re.compile(r"[^A-Za-z0-9._/\-]")


def _mirror_path(url: str, content_type: str, used: set[str]) -> str:
    """A safe, unique, correctly-extensioned relative path inside the mirror."""
    p = urlparse(url)
    rel = (p.path or "/").lstrip("/")
    if not rel or rel.endswith("/"):
        rel = rel + "index"
    rel = rel.replace("..", "_")
    rel = _UNSAFE_PATH_RE.sub("_", rel)
    norm = (content_type or "").split(";", 1)[0].strip().lower()
    want_ext = _EXT_FOR_TYPE.get(norm, "")
    cur_ext = os.path.splitext(rel)[1].lower()
    # HTML keeps a sane page extension; data files get the type's extension if absent.
    if norm in ("text/html", "application/xhtml+xml"):
        if cur_ext not in (".html", ".htm"):
            rel = rel + ".html"
    elif want_ext and cur_ext != want_ext:
        rel = rel + want_ext
    if p.query:
        stem, ext = os.path.splitext(rel)
        rel = f"{stem}_{abs(hash(p.query)) % 100000}{ext}"
    candidate = rel
    i = 2
    while candidate in used:
        stem, ext = os.path.splitext(rel)
        candidate = f"{stem}_{i}{ext}"
        i += 1
    used.add(candidate)
    return candidate


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------


def _load_robots(entry_url: str, raw: Optional[str]) -> Optional[RobotFileParser]:
    """Parse robots rules from injected text, or fetch ``/robots.txt`` safely."""
    p = urlparse(entry_url)
    if raw is None:
        try:
            robots_url = f"{p.scheme}://{p.netloc}/robots.txt"
            page = StaticBackend().fetch(robots_url)
            raw = page.content.decode("utf-8", "ignore") if page is not None else ""
        except Exception:
            raw = ""
    rp = RobotFileParser()
    rp.parse(raw.splitlines())
    return rp


# ---------------------------------------------------------------------------
# Concurrent static read-ahead
# ---------------------------------------------------------------------------


class _StaticPrefetcher:
    """Fetch upcoming frontier pages' *static* bytes concurrently, ahead of the
    deterministic consumer.

    Only Tier A (static HTTP, thread-safe ``requests``) runs in parallel — the
    render tier and every keep/discover/enqueue decision stay single-threaded in
    the crawl loop, so WHICH pages are kept is byte-identical to a serial crawl;
    only network wait overlaps. Futures are deduplicated by URL (a page is never
    fetched twice), a per-worker politeness lead-in bounds the request rate, and
    any fetch error is captured in its future and surfaces to the consumer as
    "no page" — exactly the skip a serial failure produces.
    """

    def __init__(
        self,
        static_fetch: Callable[[str], Optional[FetchedPage]],
        *,
        width: int,
        politeness_s: float,
    ) -> None:
        self._static_fetch = static_fetch
        self._politeness_s = max(0.0, politeness_s)
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, width), thread_name_prefix="mh-rf-prefetch"
        )
        self._futures: dict[str, Future] = {}
        self._lock = threading.Lock()

    def _job(self, url: str) -> Optional[FetchedPage]:
        # Politeness rides inside the worker so the delays overlap rather than
        # serialising (the concurrency width is the real per-host ceiling).
        if self._politeness_s > 0:
            time.sleep(self._politeness_s)
        try:
            return self._static_fetch(url)
        except Exception:  # never let a fetch error escape a pool thread
            return None

    def submit(self, url: str) -> None:
        """Start fetching ``url`` if it isn't already in flight (idempotent)."""
        with self._lock:
            if url not in self._futures:
                self._futures[url] = self._pool.submit(self._job, url)

    def get(self, url: str) -> Optional[FetchedPage]:
        """Block for ``url``'s static page, submitting it inline if read-ahead
        never queued it. Returns ``None`` on any failure (consumer skips)."""
        with self._lock:
            fut = self._futures.get(url)
            if fut is None:
                fut = self._pool.submit(self._job, url)
                self._futures[url] = fut
        try:
            return fut.result()
        except Exception:
            return None

    def close(self) -> None:
        try:
            self._pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:  # pragma: no cover - cancel_futures is py3.9+
            self._pool.shutdown(wait=False)


# ---------------------------------------------------------------------------
# The crawl
# ---------------------------------------------------------------------------


def crawl_results_site(
    entry_url: str,
    *,
    limits: Optional[CrawlLimits] = None,
    fetch_page: Optional[Callable[[str], ReadResult]] = None,
    static_fetch: Optional[Callable[[str], Optional[FetchedPage]]] = None,
    rendered: Optional[RenderedBackend] = None,
    robots_txt: Optional[str] = None,
    progress_cb: Optional[Callable[["CrawlProgress"], None]] = None,
) -> CrawlResult:
    """Walk the results site at ``entry_url`` and return a kept-file mirror.

    Two read paths, same deterministic walk:

      * **Production / concurrent (default).** The static tier is fetched with
        read-ahead across ``limits.fetch_concurrency`` threads while the render
        tier and every keep/discover/enqueue decision stay single-threaded and in
        frontier order — so WHICH pages are kept is identical to a serial crawl;
        only network wait overlaps. ``static_fetch`` (a URL → ``FetchedPage``
        callable) and ``rendered`` (a shared :class:`RenderedBackend`) are
        injection seams for testing this path without a network or a browser.
      * **Legacy / serial.** Passing a combined ``fetch_page`` (URL →
        ``ReadResult``) drives the original strictly-sequential walk unchanged —
        the seam the deterministic-walk tests use.

    ``robots_txt`` injects robots rules for tests. ``progress_cb(CrawlProgress)``
    is an optional best-effort hook fired once per fetched page (after discovery,
    so the frontier count is live) — any exception it raises is swallowed so it
    can never affect the crawl.
    """
    limits = limits or CrawlLimits.from_env()
    scope: Scope = scope_for(entry_url)
    result = CrawlResult(entry_url=entry_url)

    rp = _load_robots(entry_url, robots_txt) if limits.respect_robots else None

    def _allowed_by_robots(url: str) -> bool:
        if rp is None:
            return True
        try:
            return rp.can_fetch(_USER_AGENT, url)
        except Exception:
            return True

    # Wire up the read path. ``own_*`` are the backends THIS call created and must
    # therefore tear down; ``render_backend`` is whichever rendered backend
    # escalation uses (injected or own), tracked for the render budget.
    prefetcher: Optional[_StaticPrefetcher] = None
    own_static: Optional[StaticBackend] = None
    own_rendered: Optional[RenderedBackend] = None
    render_backend: Optional[RenderedBackend] = None

    if fetch_page is not None:
        # Legacy serial path — the combined reader is the whole tier stack.
        def _obtain(u: str) -> ReadResult:
            return fetch_page(u)

    else:
        # Concurrent path: one pooled StaticBackend (read-ahead) + one shared
        # RenderedBackend (single browser, render budget).
        if static_fetch is None:
            own_static = StaticBackend(limits.fetch)
            static_fetch = own_static.fetch
        render_backend = rendered
        if render_backend is None:
            own_rendered = RenderedBackend(limits.fetch)
            render_backend = own_rendered
        prefetcher = _StaticPrefetcher(
            static_fetch,
            width=limits.fetch_concurrency,
            politeness_s=limits.politeness_delay_s,
        )

        def _obtain(u: str) -> ReadResult:
            # Static bytes come warm from read-ahead; the render escalation runs
            # here, in the single consumer thread, so the browser is never shared.
            return escalate_static(
                u, prefetcher.get(u), limits=limits.fetch, rendered=render_backend
            )

    used_paths: set[str] = set()
    visited: set[str] = set()
    # Same-host links discovered on the ENTRY page that fall outside the path-
    # prefix scope but are followed anyway (see the discovery block below). This
    # is the only way an off-prefix URL becomes fetchable; a child page never
    # adds to it, so the crawl can never widen past the entry's siblings.
    offprefix_allowed: set[str] = set()
    frontier: list[tuple[str, int]] = [(entry_url, 0)]
    started = time.monotonic()

    def _enqueue(link: str, next_depth: int) -> None:
        """Add a follow-up link to the frontier (data files first so a budget-
        limited crawl gets the real results before navigation HTML) and start its
        static read-ahead, so by the time the consumer pops it the bytes are warm."""
        if _is_data_file(link):
            frontier.insert(0, (link, next_depth))
        else:
            frontier.append((link, next_depth))
        if prefetcher is not None and link not in visited and _allowed_by_robots(link):
            prefetcher.submit(link)

    try:
        while frontier:
            if result.pages_visited >= limits.max_pages:
                break
            if time.monotonic() - started > limits.timeout_s:
                break
            if result.total_bytes >= limits.max_total_bytes:
                break

            url, depth = frontier.pop(0)
            norm_url = url.split("#", 1)[0]
            if norm_url in visited:
                continue
            visited.add(norm_url)

            if not in_scope(norm_url, scope) and norm_url not in offprefix_allowed:
                result.blocked += 1
                continue
            if not _allowed_by_robots(norm_url):
                result.blocked += 1
                continue

            # In the concurrent path politeness rides inside the read-ahead
            # workers (overlapping); only the serial path sleeps in-loop.
            if prefetcher is None and limits.politeness_delay_s > 0:
                time.sleep(limits.politeness_delay_s)

            read = _obtain(norm_url)
            result.pages_visited += 1
            if render_backend is not None and render_backend.budget_hit:
                result.render_budget_hit = True

            page = read.page
            if page is None:
                result.skipped += 1
            else:
                is_entry = norm_url == entry_url
                kept_this_page = _keep_page(result, read, scope, used_paths, limits, is_entry)

                # Captured data APIs (already in hand from the render) → mirror files.
                if isinstance(page, RenderedPage):
                    for cap in page.captures:
                        _keep_capture(result, cap, used_paths, limits)
                    # Screenshots count against the same total-byte budget as
                    # kept files/captures: up to ``max_renders`` viewport JPEGs
                    # (~1-2 MB each) would otherwise pile up in memory on top of
                    # ``max_total_bytes``. Stop storing once the budget is hit.
                    if (
                        page.screenshot
                        and result.total_bytes + len(page.screenshot) <= limits.max_total_bytes
                    ):
                        shot_path = _mirror_path(norm_url, "image/jpeg", used_paths)
                        result.screenshots[shot_path] = page.screenshot
                        result.total_bytes += len(page.screenshot)

                if (
                    not kept_this_page
                    and _is_ai_candidate(page)
                    and (len(result.ai_candidates) < limits.max_ai_candidates)
                ):
                    result.ai_candidates.append(read)

                # Discover follow-ups from the (rendered when available) DOM,
                # unioned with the static HTML's links so a render that drops or
                # rewrites anchors can't zero out discovery.
                if _is_html(page.content_type) and depth < limits.max_depth:
                    discovery_base = _discovery_base(norm_url, page.final_url)
                    discovered = _discover_links(page.content, discovery_base)
                    static_page = read.static_page
                    if (
                        static_page is not None
                        and static_page is not page
                        and _is_html(static_page.content_type)
                    ):
                        seen = set(discovered)
                        for link in _discover_links(static_page.content, discovery_base):
                            if link not in seen:
                                seen.add(link)
                                discovered.append(link)

                    in_scope_links = [link for link in discovered if in_scope(link, scope)]
                    follow = list(in_scope_links)
                    if is_entry:
                        result.entry_tier = page.tier
                        result.entry_final_url = page.final_url
                        result.entry_links_found = len(discovered)
                        result.entry_links_in_scope = len(in_scope_links)
                        # Some meet hubs route each event's results to a SIBLING
                        # path on the same host, outside the entry's path-prefix
                        # (e.g. a /meets/<id>/results hub whose event pages live at
                        # /events/<id>/results — same host, different top-level
                        # path). Follow those same-host, off-prefix links found on
                        # the ENTRY page so the hub can reach its event pages.
                        #
                        # This stays bounded and sport/vendor-agnostic: only entry-
                        # page links qualify (a child page never widens the crawl),
                        # each reached page is kept solely if it is itself result-
                        # shaped (the shape gate decides — no domain/word matching),
                        # the pages they reach enqueue in-scope links only, and every
                        # existing budget (max_pages, max_total_bytes, timeout,
                        # robots, SSRF) still applies. A large multi-meet host is
                        # therefore never crawled wholesale — its off-prefix nav
                        # pages are fetched at most once, fail the shape gate, and
                        # spawn no further off-prefix following.
                        for link in discovered:
                            if (
                                in_scope(link, scope)
                                or not _same_host(link, entry_url)
                                or link in offprefix_allowed
                            ):
                                continue
                            offprefix_allowed.add(link)
                            follow.append(link)
                    for link in follow:
                        if link in visited:
                            continue
                        _enqueue(link, depth + 1)

            # One progress beat per visited page (skips included), fired AFTER
            # discovery so ``frontier_remaining`` reflects this page's new links.
            if progress_cb is not None:
                try:
                    progress_cb(
                        CrawlProgress(
                            pages_visited=result.pages_visited,
                            kept=result.kept,
                            total_bytes=result.total_bytes,
                            frontier_remaining=len(frontier),
                            discovered_total=result.pages_visited + len(frontier),
                        )
                    )
                except Exception:  # noqa: BLE001 — progress is best-effort, never fatal
                    pass
    finally:
        if render_backend is not None and render_backend.budget_hit:
            result.render_budget_hit = True
        if prefetcher is not None:
            prefetcher.close()
        if own_rendered is not None:
            own_rendered.close()
        if own_static is not None:
            own_static.close()

    return result


def _is_html(content_type: str) -> bool:
    return (content_type or "").split(";", 1)[0].strip().lower() in (
        "text/html",
        "application/xhtml+xml",
    )


def _is_ai_candidate(page) -> bool:
    """A rendered HTML page or an image that yielded no machine-readable table."""
    norm = (page.content_type or "").split(";", 1)[0].strip().lower()
    if norm in _IMAGE_TYPES:
        return True
    return page.tier == "rendered" and norm in ("text/html", "application/xhtml+xml")


def _keep_page(
    result: CrawlResult,
    read: ReadResult,
    scope: Scope,
    used: set[str],
    limits: CrawlLimits,
    is_entry: bool,
) -> bool:
    """Keep the page's bytes in the mirror if it is (or contains) results."""
    page = read.page
    assert page is not None
    norm = (page.content_type or "").split(";", 1)[0].strip().lower()

    keep = False
    if norm in _KEEP_ON_SIGHT:
        keep = True
    elif shape_gate(page.content, page.content_type, text=getattr(page, "text", None)):
        keep = True

    if not keep:
        # The entry page is always recorded (even a frameset/landing shell) so the
        # mirror has a root and discovery can proceed; it just may not be results.
        if not is_entry:
            result.skipped += 1
            return False

    rel = _mirror_path(page.final_url, page.content_type, used)
    data = page.content
    result.files[rel] = data
    result.total_bytes += len(data)
    result.kept += 1 if keep else 0
    result.provenance[rel] = FileProvenance(
        source_url=page.final_url,
        tier=page.tier,
        trigger=read.trigger,
        content_type=norm,
        fetched_at=time.time(),
    )
    if is_entry and result.entry_file is None:
        result.entry_file = rel
    return keep


def _keep_capture(result: CrawlResult, cap, used: set[str], limits: CrawlLimits) -> None:
    """Persist a captured JSON/CSV API response as a mirror file."""
    if result.total_bytes + cap.byte_len > limits.max_total_bytes:
        return
    rel = _mirror_path(cap.url, cap.content_type, used)
    result.files[rel] = cap.body
    result.total_bytes += cap.byte_len
    result.kept += 1
    result.provenance[rel] = FileProvenance(
        source_url=cap.url,
        tier="capture",
        trigger=None,
        content_type=(cap.content_type or "").split(";", 1)[0].strip().lower(),
        fetched_at=time.time(),
    )
