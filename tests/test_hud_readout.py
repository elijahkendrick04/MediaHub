"""tests/test_hud_readout.py — UI 1.5: live local-time + system-status HUD readout.

The footer carries a small mono "blueprint/HUD" strip: a live local clock
(+ a UTC reference) on the left, and a deployment/system status line
(reachability · build · UTC) on the right. It is fed by the *existing*
``/healthz`` poll plus a pure client-side clock — there is **no new backend
surface**. Since the header "online" pill was removed, this HUD is now the sole
reachability indicator.

Two layers of assertion:

  1. Server-side (no browser, always runs): the HUD markup, ids, CSS contract,
     accessibility shape (no per-second aria-live spam, decorative bits
     aria-hidden, clocks are <time> elements), the print-hidden placement
     (inside ``.mh-footer``), and the "no new route" guarantee.
  2. Browser-side (Playwright, skips when absent): against a real live server —
     the clocks populate + tick, the timezone label resolves, local ≠ UTC under
     a fixed non-UTC zone, the status/build resolve from the real ``/healthz``
     poll (Online), the offline path flips Online→Offline, and the clock keeps
     ticking with the network down.

Mirrors the skip/launch pattern in tests/test_activity_count_up.py.
"""

from __future__ import annotations

import os
import re
import sys
import threading
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_SKIP_BROWSER = os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower() in ("1", "true", "yes")
from tests._pw_chromium import resolve_prebaked_chromium

_PINNED_CHROMIUM = resolve_prebaked_chromium()

# Every id the HUD strip and its JS depend on.
_HUD_IDS = (
    "mh-hud",
    "mh-hud-clock",
    "mh-hud-utc",
    "mh-hud-tz",
    "mh-hud-status",
    "mh-hud-build",
    "mh-hud-dot",
)

_HHMMSS = re.compile(r"^\d{2}:\d{2}:\d{2}$")


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401

        return True
    except ImportError:
        return False


def _chromium_available() -> bool:
    return _PINNED_CHROMIUM.is_file()


def _launch_browser():
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        executable_path=str(_PINNED_CHROMIUM),
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    return pw, browser


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def hud_app(app):
    """Minimal isolated MediaHub app (no org pinned — the chrome is public)."""
    return app


@pytest.fixture
def hud_html(hud_app):
    """Rendered home-page HTML (the standard chrome the HUD ships in)."""
    with hud_app.test_client() as c:
        return c.get("/").get_data(as_text=True)


@pytest.fixture
def hud_server(hud_app):
    """Run the app on a real ephemeral port so the browser's /healthz fetch
    resolves against a genuine endpoint. Yields the base URL."""
    from werkzeug.serving import make_server

    srv = make_server("127.0.0.1", 0, hud_app, threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_port}"
    finally:
        srv.shutdown()
        thread.join(timeout=5)


# ── Layer 1: server-side markup / CSS / wiring ───────────────────────────────


class TestHudServerMarkup:
    def test_strip_present_on_every_layout_page(self, hud_app):
        """The HUD is part of the shared chrome — it must appear on every
        ``_layout`` page, signed-out included."""
        with hud_app.test_client() as c:
            for path in ("/", "/pricing", "/sign-in", "/status"):
                html = c.get(path).get_data(as_text=True)
                assert 'id="mh-hud"' in html, f"HUD missing on {path}"

    @pytest.mark.parametrize("element_id", _HUD_IDS)
    def test_required_ids_present(self, hud_html, element_id):
        assert f'id="{element_id}"' in hud_html, f"missing #{element_id}"

    def test_clocks_are_time_elements(self, hud_html):
        """Live clocks use <time> so the value is machine-readable and the
        per-second text churn is not announced as prose."""
        assert re.search(r'<time id="mh-hud-clock"', hud_html)
        assert re.search(r'<time id="mh-hud-utc"', hud_html)

    def test_initial_placeholders_before_js(self, hud_html):
        """Server HTML ships honest placeholders the JS later fills — not a
        fabricated time/status."""
        assert "Connecting" in hud_html  # status before first /healthz poll
        # Both clocks start as the dashed placeholder.
        assert hud_html.count("--:--:--") >= 2


class TestHudAccessibility:
    """A clock that repaints every second must not nag a screen reader, and
    the purely-decorative bits must be hidden from the a11y tree."""

    def _hud_block(self, html: str) -> str:
        m = re.search(r'<div id="mh-hud".*?</div>\s*</footer>', html, re.S)
        assert m, "could not isolate the HUD block"
        return m.group(0)

    def test_no_live_region(self, hud_html):
        block = self._hud_block(hud_html)
        assert "aria-live" not in block, "HUD must not be an aria-live region"
        # role=status / role=alert are *implicit* live regions — also banned.
        assert 'role="status"' not in block
        assert 'role="alert"' not in block

    def test_decorative_dot_and_separators_hidden(self, hud_html):
        block = self._hud_block(hud_html)
        # The status dot is decorative — the word Online/Offline carries meaning.
        assert re.search(r'id="mh-hud-dot"[^>]*aria-hidden="true"', block)
        # Every middot separator is aria-hidden.
        assert block.count('class="mh-hud-sep" aria-hidden="true"') >= 2


class TestHudCss:
    @pytest.mark.parametrize(
        "selector",
        [
            ".mh-hud {",
            ".mh-hud-inner {",
            ".mh-hud-group--system",
            ".mh-hud-field {",
            ".mh-hud-clock {",
            ".mh-hud--online",
            ".mh-hud--offline",
        ],
    )
    def test_css_rule_present(self, hud_html, selector):
        assert selector in hud_html, f"missing HUD CSS rule {selector!r}"

    def test_hud_uses_mono_blueprint_type(self, hud_html):
        """The strip is mono (blueprint/HUD aesthetic) and tabular so the
        ticking digits don't jitter."""
        inner = re.search(r"\.mh-hud-inner \{(.*?)\}", hud_html, re.S)
        assert inner and "var(--font-mono)" in inner.group(1)
        assert inner and "text-transform: uppercase" in inner.group(1)
        clock = re.search(r"\.mh-hud-clock \{(.*?)\}", hud_html, re.S)
        assert clock and "tabular-nums" in clock.group(1)

    def test_reachability_colours_present(self, hud_html):
        """The HUD's own online green / offline red. (The header status pill
        was removed; the HUD is the sole reachability indicator, so these
        colours now live only in the HUD's CSS.)"""
        assert "#5EE39A" in hud_html  # online green (HUD)
        assert "#FF6B6B" in hud_html  # offline red (HUD)


class TestHudWiring:
    """The HUD reuses the existing /healthz poll + a client clock. No new
    backend surface — one fetch drives the single status indicator."""

    def test_health_poll_paints_hud(self, hud_html):
        # One paint() drives the HUD from a single /healthz response. (The
        # header pill it used to also paint was removed.)
        assert "function paint(online, version)" in hud_html
        assert "mh-hud--online" in hud_html and "mh-hud--offline" in hud_html

    def test_build_comes_from_health_version(self, hud_html):
        """Build label is the version field of the existing /healthz payload —
        not a new endpoint."""
        assert "mh-hud-build" in hud_html
        # paint() receives o.j.version from the health fetch.
        assert "o.j && o.j.version" in hud_html

    def test_clock_is_pure_client_side(self, hud_html):
        """The live clock must not depend on the network — no extra fetch."""
        assert "setInterval(tick, 1000)" in hud_html
        assert "new Date()" in hud_html
        # The clock IIFE resolves the zone label locally via Intl.
        assert "Intl.DateTimeFormat" in hud_html

    def test_no_new_hud_route(self, hud_app):
        """'No new backend surface' — the app exposes no hud-specific route."""
        rules = [r.rule for r in hud_app.url_map.iter_rules()]
        assert not any("hud" in r.lower() for r in rules), (
            "UI 1.5 must add no backend route: " + repr([r for r in rules if "hud" in r.lower()])
        )

    def test_hud_is_inside_footer_so_print_hides_it(self, hud_html):
        """The strip sits inside .mh-footer, which the print stylesheet already
        hides — so it never bleeds into a printed / saved-as-PDF page."""
        foot = hud_html.find('<footer class="mh-footer">')
        hud = hud_html.find('id="mh-hud"')
        foot_end = hud_html.find("</footer>", foot)
        assert foot != -1 and hud != -1 and foot < hud < foot_end


# ── Layer 2: live browser behaviour ──────────────────────────────────────────


@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="prebaked chromium not found")
class TestHudBrowserBehaviour:
    def _read_hud(self, page):
        return page.evaluate(
            """() => ({
                local: document.getElementById('mh-hud-clock').textContent,
                utc: document.getElementById('mh-hud-utc').textContent,
                tz: document.getElementById('mh-hud-tz').textContent,
                status: document.getElementById('mh-hud-status').textContent,
                build: document.getElementById('mh-hud-build').textContent,
                cls: document.getElementById('mh-hud').className,
                datetime: document.getElementById('mh-hud-clock').getAttribute('datetime'),
            })"""
        )

    def test_clock_and_status_go_live(self, hud_server):
        """Clocks populate + tick, the zone label resolves, and the status/
        build resolve Online from the real /healthz poll."""
        pw, browser = _launch_browser()
        try:
            ctx = browser.new_context(timezone_id="America/New_York")
            page = ctx.new_page()
            page.goto(f"{hud_server}/", wait_until="domcontentloaded")

            page.wait_for_function(
                "document.getElementById('mh-hud-clock').textContent !== '--:--:--'",
                timeout=6000,
            )
            page.wait_for_function(
                "document.getElementById('mh-hud').classList.contains('mh-hud--online')",
                timeout=6000,
            )
            snap1 = self._read_hud(page)
            page.wait_for_timeout(1200)
            snap2 = self._read_hud(page)
        finally:
            browser.close()
            pw.stop()

        assert _HHMMSS.match(snap1["local"]), snap1["local"]
        assert _HHMMSS.match(snap1["utc"]), snap1["utc"]
        assert snap1["tz"].strip(), "timezone label did not resolve"
        # New York is never UTC — proves the LOCAL clock uses the browser zone
        # while the reference clock is genuine UTC.
        assert snap1["local"] != snap1["utc"]
        assert snap1["status"] == "Online"
        assert re.match(r"^v\d", snap1["build"]), snap1["build"]
        assert "mh-hud--online" in snap1["cls"]
        assert snap1["datetime"] and "T" in snap1["datetime"]
        # The clock advanced over ~1.2 s.
        assert snap1["local"] != snap2["local"] or snap1["utc"] != snap2["utc"]

    def test_offline_path_and_clock_survives(self, hud_server):
        """With /healthz unreachable the HUD reads Offline, yet the client
        clock keeps ticking (it never depended on the network)."""
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            # Kill the health probe before the page's first poll fires.
            page.route("**/healthz", lambda route: route.abort())
            page.goto(f"{hud_server}/", wait_until="domcontentloaded")

            page.wait_for_function(
                "document.getElementById('mh-hud').classList.contains('mh-hud--offline')",
                timeout=6000,
            )
            page.wait_for_function(
                "document.getElementById('mh-hud-clock').textContent !== '--:--:--'",
                timeout=6000,
            )
            snap1 = self._read_hud(page)
            page.wait_for_timeout(1200)
            snap2 = self._read_hud(page)
        finally:
            browser.close()
            pw.stop()

        assert snap1["status"] == "Offline"
        assert "mh-hud--offline" in snap1["cls"]
        # Clock is network-independent — it keeps advancing while offline.
        assert _HHMMSS.match(snap1["local"]), snap1["local"]
        assert snap1["local"] != snap2["local"] or snap1["utc"] != snap2["utc"]
