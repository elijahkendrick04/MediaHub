"""mediahub/results_fetch/rendered.py — Tier B (rendered) fetch.

When a static fetch comes back thin, JS-shelled, or result-shapeless, we read the
page the way the Claude Chrome extension would: render it in headless Chromium,
let the JavaScript run, then capture four things —

  1. the rendered DOM (``page.content()``)        — SPA output as real HTML;
  2. the visible text (``innerText`` of ``body``)  — for the shape gate / AI read;
  3. intercepted XHR/fetch JSON/CSV responses      — SPAs usually pull results
     from a JSON API, which is the cleanest data on the site;
  4. a JPEG screenshot                              — the Tier-C AI's "eyes".

Security is enforced at the browser layer, not hoped for:

  * **SSRF** — every request the page makes is checked; private/loopback/metadata
    hosts and non-http(s) schemes are aborted (reusing ``safe_fetch``'s validator).
  * **DNS pinning (anti-rebinding)** — before each navigation the target host is
    resolved to ONE validated public IP (``safe_fetch.resolve_safe_ip``) and
    Chromium's own resolver is pinned to it with ``--host-resolver-rules`` so the
    browser cannot re-resolve the host to an internal address between our check
    and its connection (the DNS-rebinding TOCTOU that Tier A closed at the socket
    layer, closed here at the browser layer). The pin covers the top-level
    navigation, its same-host redirects, and its same-host subresources. See
    ``docs/adr/0030-tier-b-chromium-dns-pinning.md`` for the residual (off-scope
    subresources on *other* public hosts re-resolve and are only re-validated,
    not IP-pinned).
  * **Scope** — top-level/sub-document *navigations* are pinned to the validated
    same-origin path-prefix scope; off-scope asset requests are allowed read-only
    but never recorded as crawl targets.
  * **Budgets** — one browser per crawl, at most ``max_renders`` rendered pages,
    a per-page navigation timeout, a bounded settle, and a total wall-clock
    ceiling. Captured bodies are byte-capped individually and in aggregate.

Reuses the project's Playwright launch convention from
``graphic_renderer/render.py`` (headless chromium, ``--no-sandbox``); that module
is referenced, never modified. Inert: importing this adds no route.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urlparse

from mediahub.web_research.safe_fetch import is_url_safe, resolve_safe_ip

from .fetch import FetchedPage, FetchLimits, _normalise_content_type

log = logging.getLogger(__name__)

__all__ = [
    "Scope",
    "scope_for",
    "in_scope",
    "same_host",
    "CapturedResponse",
    "RenderedPage",
    "RenderedBackend",
]


# ---------------------------------------------------------------------------
# Scope — same host + path-prefix
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scope:
    """The validated crawl scope: a scheme, a host, and a path prefix."""

    scheme: str
    host: str
    path_prefix: str


def scope_for(url: str) -> Scope:
    """Derive the same-host, same-path-prefix scope from an entry URL.

    The prefix is the URL's *directory* (with a trailing slash), so sibling and
    deeper pages are in scope while parents and other sections are not.
    """
    p = urlparse(url)
    path = p.path or "/"
    if not path.endswith("/"):
        head = path.rsplit("/", 1)[0]
        path = (head + "/") if head else "/"
    return Scope(
        scheme=(p.scheme or "https"), host=(p.hostname or "").lower(), path_prefix=path or "/"
    )


def in_scope(url: str, scope: Scope) -> bool:
    """True when ``url`` is an http(s) URL on the same host under the prefix."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return False
    if (p.hostname or "").lower() != scope.host:
        return False
    return (p.path or "/").startswith(scope.path_prefix)


def same_host(url: str, scope: Scope) -> bool:
    """True when ``url`` is on the scope host (path ignored — for API capture)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return False
    return (p.hostname or "").lower() == scope.host


# ---------------------------------------------------------------------------
# Captured network responses (the SPA's data API)
# ---------------------------------------------------------------------------

# Content types worth keeping off the wire: a SPA's results API is almost always
# JSON, occasionally CSV. (``application/<x>+json`` variants count as JSON.)
_CAPTURE_TYPES = frozenset(
    {"application/json", "text/json", "text/csv", "text/tab-separated-values"}
)


def _is_capturable_type(ctype: str) -> bool:
    norm = _normalise_content_type(ctype)
    return norm in _CAPTURE_TYPES or norm.endswith("+json")


@dataclass
class CapturedResponse:
    """One XHR/fetch response kept from the page's own network traffic."""

    url: str
    content_type: str
    body: bytes

    @property
    def byte_len(self) -> int:
        return len(self.body)


@dataclass
class RenderedPage(FetchedPage):
    """A Tier-B read: rendered DOM (``content``) + text + screenshot + captures."""

    screenshot: Optional[bytes] = None
    screenshot_mime: Optional[str] = None
    captures: list[CapturedResponse] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tier B — rendered backend
# ---------------------------------------------------------------------------


class RenderedBackend:
    """Tier B: headless Chromium with scope interception, capture, and budgets.

    One instance == one crawl. Construct it once, ``fetch`` many pages, then
    ``close`` (or use it as a context manager). Reuse keeps a single browser
    alive and lets the render counter enforce a hard per-crawl ceiling.

    ``page_provider`` is the test seam: a zero-arg callable returning a
    page-like object. When supplied, no real browser is launched (so DNS
    pinning is a no-op — there is no resolver to pin), which lets the
    routing/capture/budget logic be unit-tested without Chromium.
    ``host_safe`` (per-request SSRF gate, URL→bool) and ``resolve_ip``
    (per-navigation pin source, host→validated-IP-or-None) both default to the
    production ``safe_fetch`` primitives and are injectable for the same reason.
    """

    tier = "rendered"

    def __init__(
        self,
        limits: Optional[FetchLimits] = None,
        *,
        page_provider: Optional[Callable[[], object]] = None,
        host_safe: Callable[[str], bool] = is_url_safe,
        resolve_ip: Callable[[str], Optional[str]] = resolve_safe_ip,
    ) -> None:
        self.limits = limits or FetchLimits()
        self._page_provider = page_provider
        self._host_safe = host_safe
        self._resolve_ip = resolve_ip
        self._pw = None
        self._browser = None
        self.renders_done = 0
        self.budget_hit = False
        self._deadline: Optional[float] = None
        # The host + validated IP the running browser's resolver is pinned to
        # (``--host-resolver-rules``). Set per navigation from ``resolve_ip``; a
        # change of host tears the browser down so it relaunches re-pinned.
        self._pinned_host: Optional[str] = None
        self._pinned_ip: Optional[str] = None
        # Recycle the headless browser every N renders. A Chromium that has
        # rendered many heavy JS pages on a memory-tight host can wedge so a
        # later new_context/new_page blocks forever (the crawl appears stuck at
        # "Reading the site…"). Relaunching between batches keeps each render on
        # a fresh process. 0/blank disables.
        _raw_recycle = os.environ.get("MEDIAHUB_RESULTS_FETCH_RENDER_RECYCLE", "").strip()
        self._recycle_every = int(_raw_recycle) if _raw_recycle.isdigit() else 15

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> "RenderedBackend":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @staticmethod
    def _host_resolver_rule(host: str, ip: str) -> str:
        """The ``--host-resolver-rules`` arg pinning ``host``'s resolution to
        ``ip``.

        ``MAP <host> <ip>`` remaps *only* ``host`` (every port — the replacement
        carries no port, so Chromium preserves the request's) to the pre-validated
        ``ip``; hosts that match no rule fall through to normal resolution, so a
        page's legit cross-host CDN/subresource fetches are unaffected. IPv6
        replacements are bracketed so the address is not mis-parsed as host:port.
        """
        repl = f"[{ip}]" if ":" in ip else ip
        return f"--host-resolver-rules=MAP {host} {repl}"

    def _launch_args(self) -> list[str]:
        """Chromium launch args: the graphic_renderer convention plus, when a
        navigation host is pinned, the ``--host-resolver-rules`` DNS pin."""
        args = ["--no-sandbox", "--disable-dev-shm-usage"]
        if self._pinned_host and self._pinned_ip:
            args.append(self._host_resolver_rule(self._pinned_host, self._pinned_ip))
        return args

    def _ensure_browser(self) -> None:
        if self._browser is not None or self._page_provider is not None:
            return
        try:
            from playwright.sync_api import sync_playwright  # type: ignore  # noqa: PLC0415
        except Exception as e:  # pragma: no cover - browser absent only off-box
            raise RuntimeError(f"Playwright not installed: {e}")
        self._pw = sync_playwright().start()
        # Same launch convention as graphic_renderer/render.py (headless chromium,
        # --no-sandbox); the bundled-chromium path is resolved via
        # PLAYWRIGHT_BROWSERS_PATH in the deployed image. The DNS pin (if any) for
        # this navigation's host is baked into the args (_launch_args).
        self._browser = self._pw.chromium.launch(args=self._launch_args())

    def _teardown_browser(self) -> None:
        """Close + drop the browser/playwright handles (best-effort). Shared by
        ``close``, the periodic recycle, and the re-pin on a host change."""
        for obj, meth in ((self._browser, "close"), (self._pw, "stop")):
            if obj is not None:
                try:
                    getattr(obj, meth)()
                except Exception:  # pragma: no cover - best-effort teardown
                    pass
        self._browser = None
        self._pw = None

    def close(self) -> None:
        self._teardown_browser()
        self._pinned_host = None
        self._pinned_ip = None

    def _acquire_page(self):
        """Return ``(page, cleanup)``; uses the injected provider in tests."""
        if self._page_provider is not None:
            page = self._page_provider()
            return page, getattr(page, "close", lambda: None)
        self._ensure_browser()
        ctx = self._browser.new_context(  # type: ignore[union-attr]
            viewport={"width": 1366, "height": 2200},
            device_scale_factor=1,
            ignore_https_errors=False,
        )
        page = ctx.new_page()
        return page, ctx.close

    # -- decisions (pure; unit-tested directly) ----------------------------

    def _host_ok(self, url: str) -> bool:
        """SSRF gate for one request the page makes.

        The navigation host is already resolved + IP-pinned for this render
        (``_apply_navigation_pin``), so it is trusted without re-resolving —
        Chromium is locked to the validated IP regardless of what its DNS now
        returns. Every *other* host is re-validated fresh on each call: there is
        deliberately no verdict cache, so a host that flips to internal (DNS
        rebinding) can never ride a stale "safe" verdict (finding #125).
        """
        host = (urlparse(url).hostname or "").lower()
        if host and host == self._pinned_host:
            return True
        return bool(self._host_safe(url))

    def _apply_navigation_pin(self, url: str) -> bool:
        """Resolve ``url``'s host to ONE validated public IP and pin the browser
        to it for this navigation; return ``False`` to refuse the navigation.

        A host already pinned for this backend is accepted immediately: the
        running browser is locked to its validated IP via ``--host-resolver-rules``
        and cannot rebind, so re-resolving it would do no security work — it would
        only risk fail-closing a legitimate same-host page on a transient resolver
        blip. Only a *new* host is resolved: refusal (``False``) then means it is
        unresolvable or *any* current resolution is an internal/reserved IP — a
        rebinding host that now points inward is caught here, before the browser
        connects. A new host tears the running browser down so the next
        ``_acquire_page`` relaunches with ``--host-resolver-rules`` re-pinned to it
        (``_launch_args``).
        """
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return False
        if host == self._pinned_host:
            return True  # already resolved + IP-pinned; the browser cannot rebind
        ip = self._resolve_ip(host)
        if ip is None:
            return False
        self._teardown_browser()  # running browser (if any) is pinned to another host
        self._pinned_host = host
        self._pinned_ip = ip
        return True

    def route_decision(self, url: str, resource_type: str, scope: Scope) -> str:
        """``"continue"`` or ``"abort"`` for one request the page makes.

        Aborts dangerous schemes (``file:``/``ftp:``…), any host that fails SSRF
        validation (internal/loopback/metadata), and off-scope *document*
        navigations. Non-network schemes (``data:``/``blob:``/``about:`` — inline
        images and the like) and off-scope asset requests on public hosts are
        allowed read-only, so the render keeps full fidelity for the AI tier.
        """
        scheme = (urlparse(url).scheme or "").lower()
        if scheme in ("data", "blob", "about"):
            return "continue"
        if scheme not in ("http", "https"):
            return "abort"
        if not self._host_ok(url):
            return "abort"
        if resource_type == "document" and not in_scope(url, scope):
            return "abort"
        return "continue"

    def _maybe_capture(
        self,
        response,
        scope: Scope,
        captures: list[CapturedResponse],
        totals: list[int],
    ) -> None:
        """Append ``response`` to ``captures`` iff it is an in-scope JSON/CSV
        XHR/fetch within the per-body and aggregate byte caps."""
        try:
            request = getattr(response, "request", None)
            rtype = getattr(request, "resource_type", "") if request is not None else ""
            if rtype not in ("xhr", "fetch"):
                return
            url = getattr(response, "url", "")
            if not same_host(url, scope):
                return
            headers = response.headers if hasattr(response, "headers") else {}
            ctype = _normalise_content_type(headers.get("content-type", ""))
            if not _is_capturable_type(ctype):
                return
            body = response.body()
            if not body or len(body) > self.limits.capture_max_bytes:
                return
            if totals[0] + len(body) > self.limits.capture_total_max_bytes:
                return
            totals[0] += len(body)
            captures.append(CapturedResponse(url=url, content_type=ctype, body=bytes(body)))
        except Exception:  # capture is best-effort; never break a render
            return

    # -- the fetch ---------------------------------------------------------

    def _budget_blocks_render(self) -> bool:
        now = time.monotonic()
        if self._deadline is None:
            self._deadline = now + self.limits.render_wall_budget_s
        if self.renders_done >= self.limits.max_renders or now > self._deadline:
            self.budget_hit = True
            return True
        return False

    def _recycle_browser(self) -> None:
        """Close + drop the browser so the next render relaunches a fresh one
        (re-pinned to the current host via ``_launch_args``).

        Frees memory accumulated over a long crawl; no-op under the injected
        test page-provider (no real browser to recycle).
        """
        if self._page_provider is not None or self._browser is None:
            return
        self._teardown_browser()

    def fetch(self, url: str) -> Optional[RenderedPage]:
        if not self._host_ok(url):
            return None
        # Pin Chromium's resolver to this host's validated IP before it connects
        # (anti DNS-rebinding). Only meaningful with a real browser; the injected
        # test page has no resolver, so the pin is skipped there.
        if self._page_provider is None and not self._apply_navigation_pin(url):
            return None
        if self._budget_blocks_render():
            return None
        # Periodic recycle to keep a long crawl off a degrading browser process.
        if (
            self._page_provider is None
            and self._recycle_every > 0
            and self.renders_done > 0
            and self.renders_done % self._recycle_every == 0
        ):
            self._recycle_browser()

        scope = scope_for(url)
        captures: list[CapturedResponse] = []
        totals = [0]

        try:
            page, cleanup = self._acquire_page()
        except Exception:
            return None

        try:

            def _on_route(route):
                request = getattr(route, "request", None)
                req_url = getattr(request, "url", "") if request is not None else ""
                rtype = getattr(request, "resource_type", "") if request is not None else ""
                try:
                    if self.route_decision(req_url, rtype, scope) == "abort":
                        route.abort()
                    else:
                        route.continue_()
                except Exception:  # pragma: no cover - routing must never raise out
                    try:
                        route.continue_()
                    except Exception:
                        pass

            def _on_response(response):
                self._maybe_capture(response, scope, captures, totals)

            try:
                page.route("**/*", _on_route)
            except Exception:
                pass
            try:
                page.on("response", _on_response)
            except Exception:
                pass

            self.renders_done += 1
            try:
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(self.limits.nav_timeout_s * 1000),
                )
            except Exception:
                return None

            # Bounded settle: give XHR-driven content a chance to land, but never
            # block past the budget. Failure here is fine — we read what's there.
            try:
                page.wait_for_load_state(
                    "networkidle", timeout=int(self.limits.settle_timeout_s * 1000)
                )
            except Exception:
                pass

            try:
                dom = page.content() or ""
            except Exception:
                dom = ""
            try:
                text = page.inner_text("body") or ""
            except Exception:
                text = ""
            shot: Optional[bytes] = None
            try:
                shot = page.screenshot(
                    type="jpeg",
                    quality=self.limits.screenshot_quality,
                    full_page=False,
                )
            except Exception:
                shot = None

            final_url = getattr(page, "url", None) or url
            return RenderedPage(
                content=dom.encode("utf-8", "ignore"),
                final_url=final_url,
                content_type="text/html",
                tier="rendered",
                text=text,
                screenshot=shot,
                screenshot_mime="image/jpeg" if shot else None,
                captures=captures,
            )
        finally:
            try:
                cleanup()
            except Exception:  # pragma: no cover - best-effort teardown
                pass
