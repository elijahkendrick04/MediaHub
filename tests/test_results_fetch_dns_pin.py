"""Live-Chromium proof for finding #125 — the Tier-B DNS pin really routes the
browser to the validated IP.

The offline suite (``test_results_fetch_fetch.py``) proves the pin is DERIVED
from ``resolve_safe_ip`` and that a host which re-resolves internal is refused
*before* Chromium launches. This file closes the loop with a real headless
Chromium: it proves ``--host-resolver-rules`` makes the browser connect to
exactly the IP we pinned and do NO DNS of its own for that host — the property
that defeats DNS rebinding. Because the navigated host (``pinned.invalid``) has
no real DNS record, *reaching a server at all* is only possible via the pin.

Skipped cleanly where Playwright or the prebaked Chromium is absent (e.g. the
dev sandbox); it runs in CI, where both are present.
"""

from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from mediahub.results_fetch.fetch import FetchLimits
from mediahub.results_fetch.rendered import RenderedBackend
from tests._pw_chromium import resolve_prebaked_chromium

_SKIP_BROWSER = os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower() in ("1", "true", "yes")
_PINNED_CHROMIUM = resolve_prebaked_chromium()


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401

        return True
    except ImportError:
        return False


def _serve_marker(marker: str) -> HTTPServer:
    """A loopback HTTP server that answers every GET with an HTML page carrying
    ``marker``. Bound to 127.0.0.1 on an ephemeral port; caller shuts it down."""

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

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


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


@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _PINNED_CHROMIUM.is_file(), reason="prebaked chromium not found")
def test_pin_routes_browser_to_the_validated_ip():
    """The pin makes Chromium connect to the IP we validated — for a host with
    no DNS at all, so only the pin could have routed the navigation."""
    marker = "PIN-OK-9f3a2b"
    server = _serve_marker(marker)
    _, port = server.server_address
    try:
        rb = _PinnedChromiumBackend(
            # Up-front gate passes; the pin source hands back the loopback server
            # as the "validated IP" (we are testing the pin mechanism, not the
            # SSRF validator — that is covered offline with the real resolver).
            host_safe=lambda u: True,
            resolve_ip=lambda host: "127.0.0.1",
            limits=FetchLimits(nav_timeout_s=8.0, settle_timeout_s=1.0),
        )
        try:
            pinned_host, pinned_ip = None, None
            page = rb.fetch(f"http://pinned.invalid:{port}/")
            pinned_host, pinned_ip = rb._pinned_host, rb._pinned_ip
        finally:
            rb.close()
    finally:
        server.shutdown()
        server.server_close()

    # Reached the pinned loopback server — `pinned.invalid` has no DNS, so the
    # navigation could ONLY have connected via the --host-resolver-rules pin.
    assert page is not None
    assert marker in (page.text or "")
    assert (pinned_host, pinned_ip) == ("pinned.invalid", "127.0.0.1")
