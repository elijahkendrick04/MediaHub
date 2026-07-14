"""Live-Chromium proof for finding #125 — the Tier-B DNS pin routes the browser
to the validated IP and OVERRIDES a conflicting live DNS resolution.

The offline suite (``test_results_fetch_fetch.py``) proves the pin is DERIVED
from ``resolve_safe_ip`` and that a host which re-resolves internal is refused
*before* Chromium launches. This file closes the loop with a real headless
Chromium, driven through ``RenderedBackend.fetch`` (its production route
interception + pin path):

* ``test_pin_beats_a_genuine_conflicting_resolution`` is the load-bearing proof.
  ``localhost`` genuinely resolves to 127.0.0.1, but the backend pins it to
  127.0.0.2; the navigation reaches the 127.0.0.2 server, never the 127.0.0.1
  one. That is the property DNS-rebinding turns on: the pin wins over a
  *successful, conflicting* resolution at connect time, so an attacker who
  flips the host's DNS to an internal address after our check cannot move the
  browser off the validated IP.
* ``test_pin_routes_a_host_with_no_dns`` is a simpler sanity check: a host with
  no DNS record at all is still reachable, so the pin — not the resolver — is
  what routed the navigation.

Skipped cleanly where Playwright or the prebaked Chromium is absent (e.g. the
dev sandbox); both run in CI, where the pinned Chromium is present.
"""

from __future__ import annotations

import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from mediahub.results_fetch.fetch import FetchLimits
from mediahub.results_fetch.rendered import RenderedBackend
from tests._pw_chromium import resolve_prebaked_chromium

_SKIP_BROWSER = os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower() in ("1", "true", "yes")
_PINNED_CHROMIUM = resolve_prebaked_chromium()

pytestmark = [
    pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set"),
    pytest.mark.skipif(not _PINNED_CHROMIUM.is_file(), reason="prebaked chromium not found"),
]


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401

        return True
    except ImportError:
        return False


pytestmark.append(
    pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
)


def _serve_marker(marker: str, *, ip: str = "127.0.0.1", port: int = 0) -> HTTPServer:
    """A loopback HTTP server (on ``ip``:``port``) that answers every GET with an
    HTML page carrying ``marker``. Caller shuts it down. ``port=0`` picks a free
    one; pass an explicit port to co-locate two servers on distinct loopback IPs."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib naming
            body = f"<html><body>{marker}</body></html>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):  # silence the default stderr access log
            return

    server = HTTPServer((ip, port), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


class _PinnedChromiumBackend(RenderedBackend):
    """RenderedBackend that launches the prebaked Chromium explicitly (revision
    parity with the other browser e2e tests) while still building its args —
    crucially the ``--host-resolver-rules`` pin — through the real
    ``_launch_args``. Everything else (the pin decision, routing, capture) is
    inherited, so ``fetch`` exercises the production pin path end-to-end."""

    def _ensure_browser(self) -> None:
        if self._browser is not None or self._page_provider is not None:
            return
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            executable_path=str(_PINNED_CHROMIUM),
            headless=True,
            args=self._launch_args(),
        )


def _fetch_text(backend: RenderedBackend, url: str):
    """Drive one fetch and return (page_text, pinned_host, pinned_ip); always
    closes the backend (which resets the pin, so capture it first)."""
    try:
        page = backend.fetch(url)
        pinned = (backend._pinned_host, backend._pinned_ip)
    finally:
        backend.close()
    return (page.text if page else None), pinned


def test_pin_beats_a_genuine_conflicting_resolution():
    """THE anti-rebinding proof: `localhost` genuinely resolves to 127.0.0.1, but
    the pin sends Chromium to 127.0.0.2 — so a live resolution that conflicts with
    the pinned IP loses. A DNS-rebind that repoints the host after our check
    therefore cannot move the browser off the validated IP."""
    port = _free_port()
    real = _serve_marker(
        "REAL-DNS-A-127-0-0-1", ip="127.0.0.1", port=port
    )  # where localhost resolves
    pinned = _serve_marker("PINNED-B-127-0-0-2", ip="127.0.0.2", port=port)  # where we pin
    try:
        backend = _PinnedChromiumBackend(
            host_safe=lambda u: True,
            resolve_ip=lambda host: "127.0.0.2",  # the "validated IP" we pin to
            limits=FetchLimits(nav_timeout_s=8.0, settle_timeout_s=1.0),
        )
        text, pin = _fetch_text(backend, f"http://localhost:{port}/")
    finally:
        real.shutdown()
        real.server_close()
        pinned.shutdown()
        pinned.server_close()

    assert text is not None
    assert "PINNED-B-127-0-0-2" in text  # reached the pinned IP…
    assert "REAL-DNS-A-127-0-0-1" not in text  # …NOT localhost's genuine resolution
    assert pin == ("localhost", "127.0.0.2")


def test_pin_routes_a_host_with_no_dns():
    """Sanity check: a host with no DNS record (`pinned.invalid`, RFC 2606) is
    still reached, so the pin — not the resolver — routed the navigation."""
    marker = "PIN-OK-9f3a2b"
    server = _serve_marker(marker)
    _, port = server.server_address
    try:
        backend = _PinnedChromiumBackend(
            host_safe=lambda u: True,
            resolve_ip=lambda host: "127.0.0.1",
            limits=FetchLimits(nav_timeout_s=8.0, settle_timeout_s=1.0),
        )
        text, pin = _fetch_text(backend, f"http://pinned.invalid:{port}/")
    finally:
        server.shutdown()
        server.server_close()

    assert text is not None
    assert marker in text
    assert pin == ("pinned.invalid", "127.0.0.1")
