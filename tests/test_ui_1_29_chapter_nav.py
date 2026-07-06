"""UI 1.29 — Sticky chaptered scroll-spy nav (Linear-inspired).

The long home page carries a side "chapter" rail that lists its sections and
highlights the one currently in view as the reader scrolls. The rail is
server-rendered by ``_layout(chapters=…)``; the active state is driven by an
IntersectionObserver in ``MH.bindChapterNav`` (pure JS, no library); the
positioning is pure CSS ``position: sticky``.

These tests pin:
  - the rail renders on the home page as an accessible ``<nav>`` with an
    ordered list of in-page anchor links, one per page section;
  - integrity: every rail link points at a section ``id`` that actually exists
    on the page, every chaptered section is linked, and the rail order matches
    the section order in the document (no dangling / out-of-order anchors);
  - the scroll-spy JS + sticky CSS ship, gated as a desktop-only progressive
    enhancement (hidden < 1240px, plain anchors with JS off), reduced-motion
    aware, and accessible (aria-current / aria-label / scroll-margin offset);
  - it is opt-in: pages that do not pass ``chapters`` render no rail and keep
    their original ``<main class="wrap">`` (backward compatible);
  - chapter labels are HTML-escaped (no caption/label XSS through the rail).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from mediahub.web import web as webmod

# --- Browser-test plumbing (mirrors tests/test_u12_odometer_stats.py) -------
_SKIP_BROWSER = os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower() in (
    "1",
    "true",
    "yes",
)
from tests._pw_chromium import resolve_prebaked_chromium

_PINNED_CHROMIUM = resolve_prebaked_chromium()


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


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(webmod, "RUNS_DIR", runs, raising=False)
    app = webmod.app
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    with app.test_client() as c:
        yield c


@pytest.fixture
def home_html(client):
    r = client.get("/")
    assert r.status_code == 200
    return r.get_data(as_text=True)


# The chapters the home page is expected to expose, in document order.
EXPECTED_CHAPTERS = [
    ("mh-ch-overview", "Overview"),
    ("mh-ch-how", "How it works"),
    ("mh-ch-engine", "What it does"),
    ("mh-ch-audience", "Who it&#39;s for"),  # apostrophe is HTML-escaped
    ("mh-ch-promise", "Our promise"),
    ("mh-ch-start", "Get started"),
]


def _nav_block(html: str) -> str:
    """The rendered ``<nav class="mh-chapter-nav" …>…</nav>`` element."""
    m = re.search(
        r'<nav class="mh-chapter-nav"[^>]*data-mh-chapnav[^>]*>(.*?)</nav>',
        html,
        re.DOTALL,
    )
    assert m, "chapter-nav element not found on the home page"
    return m.group(0)


# --------------------------------------------------------------------------- #
# The rail renders, accessibly, on the long home page
# --------------------------------------------------------------------------- #
class TestRailRenders:
    def test_nav_element_present_and_labelled(self, home_html):
        nav = _nav_block(home_html)
        assert 'aria-label="On this page"' in nav
        assert "data-mh-chapnav" in nav
        # An ordered list — the chapters have a meaningful sequence.
        assert '<ol class="mh-chapter-nav-list">' in nav
        assert nav.count("<li>") == len(EXPECTED_CHAPTERS)

    def test_eyebrow_label(self, home_html):
        nav = _nav_block(home_html)
        assert "mh-chapter-nav-eyebrow" in nav
        assert "On this page" in nav

    def test_every_expected_chapter_link(self, home_html):
        nav = _nav_block(home_html)
        for anchor, label in EXPECTED_CHAPTERS:
            assert f'href="#{anchor}" data-mh-chap' in nav, anchor
            assert f'<span class="mh-chapter-label">{label}</span>' in nav, label

    def test_chapters_are_numbered(self, home_html):
        nav = _nav_block(home_html)
        # Numbered 01..09, decorative (hidden from assistive tech).
        for i in range(1, len(EXPECTED_CHAPTERS) + 1):
            assert (
                f'<span class="mh-chapter-num" aria-hidden="true">{i:02d}</span>' in nav
            ), i


# --------------------------------------------------------------------------- #
# Integrity: links resolve, sections exist, order matches the document
# --------------------------------------------------------------------------- #
class TestRailIntegrity:
    def test_no_dangling_links(self, home_html):
        nav = _nav_block(home_html)
        hrefs = re.findall(r'href="#(mh-ch-[a-z-]+)"', nav)
        ids = re.findall(r'id="(mh-ch-[a-z-]+)"', home_html)
        assert hrefs, "no chapter links found"
        # Every link target is a real element id somewhere on the page.
        for h in hrefs:
            assert h in ids, f"chapter link #{h} has no matching section id"

    def test_every_chaptered_section_is_linked(self, home_html):
        nav = _nav_block(home_html)
        hrefs = set(re.findall(r'href="#(mh-ch-[a-z-]+)"', nav))
        section_ids = set(re.findall(r'id="(mh-ch-[a-z-]+)"', home_html))
        assert section_ids == hrefs

    def test_rail_order_matches_document_order(self, home_html):
        nav = _nav_block(home_html)
        link_order = re.findall(r'href="#(mh-ch-[a-z-]+)"', nav)
        # Section ids in the order they appear in the body (after the nav).
        body = home_html[home_html.index("</nav>") :]
        section_order = re.findall(r'id="(mh-ch-[a-z-]+)"', body)
        assert link_order == section_order == [c[0] for c in EXPECTED_CHAPTERS]

    def test_section_ids_are_unique(self, home_html):
        body = home_html[home_html.index("</nav>") :]
        ids = re.findall(r'id="(mh-ch-[a-z-]+)"', body)
        assert len(ids) == len(set(ids)), f"duplicate chapter section id: {ids}"


# --------------------------------------------------------------------------- #
# Scroll-spy behaviour (JS) ships and is wired for accessibility
# --------------------------------------------------------------------------- #
class TestScrollSpyJS:
    def test_binding_present(self, home_html):
        assert "MH.bindChapterNav = bindChapterNav;" in home_html
        assert "function bindChapterNav()" in home_html

    def test_uses_intersection_observer(self, home_html):
        # The roadmap item specifies a pure-JS IntersectionObserver spy.
        assert "new IntersectionObserver" in home_html
        assert "data-mh-chapnav" in home_html
        assert "a[data-mh-chap]" in home_html

    def test_sets_aria_current_on_active(self, home_html):
        assert "aria-current" in home_html
        assert "is-active" in home_html

    def test_reduced_motion_aware_scroll(self, home_html):
        # Click smooth-scrolls, but honours prefers-reduced-motion.
        assert "prefersReduced ? 'auto' : 'smooth'" in home_html

    def test_graceful_without_intersection_observer(self, home_html):
        # Falls back to a single static activation when IO is unavailable.
        assert "'IntersectionObserver' in window" in home_html

    def test_bound_on_dom_ready(self, home_html):
        assert "bindChapterNav();" in home_html


# --------------------------------------------------------------------------- #
# Sticky CSS ships and is a desktop-only, reduced-motion-safe enhancement
# --------------------------------------------------------------------------- #
class TestStickyCSS:
    def test_sticky_positioning(self, home_html):
        assert ".mh-chapter-nav {" in home_html
        assert "position: sticky;" in home_html

    def test_hidden_until_wide_desktop(self, home_html):
        # Hidden by default; the grid + rail appear only at >= 1240px.
        assert ".mh-chapter-nav { display: none; }" in home_html
        assert "@media (min-width: 1240px)" in home_html
        assert "main.wrap.mh-has-chapnav {" in home_html

    def test_hidden_attribute_beats_desktop_display_block(self, home_html):
        # The JS guard sets [hidden] when no chapter ids resolve; this rule must
        # win over the >=1240px display:block or an empty rail would still show.
        assert ".mh-chapter-nav[hidden] { display: none; }" in home_html

    def test_active_marker_styling(self, home_html):
        assert ".mh-chapter-nav a.is-active {" in home_html
        # Active link uses the brand "lane" accent.
        assert "border-left-color: var(--lane);" in home_html

    def test_anchor_scroll_offset_clears_masthead(self, home_html):
        # So a #hash jump (even with JS off) lands below the sticky header.
        assert 'main.wrap.mh-has-chapnav [id^="mh-ch-"] { scroll-margin-top: 84px; }' in home_html

    def test_content_wrapped_for_grid(self, home_html):
        assert '<div class="mh-chapnav-content">' in home_html
        assert '<main class="wrap mh-has-chapnav"' in home_html


# --------------------------------------------------------------------------- #
# Opt-in: pages without chapters are untouched (backward compatible)
# --------------------------------------------------------------------------- #
class TestOptIn:
    @pytest.mark.parametrize("path", ["/pricing", "/sign-in", "/terms"])
    def test_other_pages_have_no_rail(self, client, path):
        r = client.get(path)
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        # No rendered rail element and no grid modifier on <main>.
        assert '<nav class="mh-chapter-nav"' not in html
        assert '<main class="wrap mh-has-chapnav"' not in html
        assert '<div class="mh-chapnav-content">' not in html
        # Plain main is preserved.
        assert '<main class="wrap" id="mh-main">' in html

    def test_layout_without_chapters_renders_no_rail(self):
        app = webmod.app
        with app.test_request_context("/"):
            out = webmod._layout("T", "<p>body</p>")
        # No rail element, and <main> keeps its plain wrap class (the grid
        # modifier is never applied).
        assert '<nav class="mh-chapter-nav"' not in out
        assert '<main class="wrap" id="mh-main">' in out
        assert "<p>body</p>" in out

    def test_layout_with_chapters_renders_rail(self):
        app = webmod.app
        with app.test_request_context("/"):
            out = webmod._layout(
                "T", "<p>body</p>", chapters=[("mh-ch-a", "Alpha"), ("mh-ch-b", "Beta")]
            )
        assert '<nav class="mh-chapter-nav" aria-label="On this page"' in out
        assert 'href="#mh-ch-a" data-mh-chap' in out
        assert 'href="#mh-ch-b" data-mh-chap' in out
        assert '<main class="wrap mh-has-chapnav"' in out
        assert '<div class="mh-chapnav-content"><p>body</p></div>' in out


# --------------------------------------------------------------------------- #
# Security: a chapter label cannot inject markup through the rail
# --------------------------------------------------------------------------- #
class TestRailEscaping:
    def test_label_is_html_escaped(self):
        app = webmod.app
        with app.test_request_context("/"):
            out = webmod._layout(
                "T",
                "<p>body</p>",
                chapters=[("mh-ch-x", '<img src=x onerror=alert(1)>Hack & Co')],
            )
        assert "<img src=x onerror=alert(1)>" not in out
        assert "&lt;img src=x onerror=alert(1)&gt;Hack &amp; Co" in out


# --------------------------------------------------------------------------- #
# Browser: the scroll-spy actually lights the right chapter (Playwright)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(_SKIP_BROWSER, reason="browser tests disabled via env")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="pinned Chromium not present")
class TestScrollSpyBrowser:
    def _active(self, page):
        return page.eval_on_selector_all(
            ".mh-chapter-nav a.is-active",
            "els => els.map(e => e.getAttribute('href'))",
        )

    def test_scroll_spy_tracks_sections(self, home_html):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page(viewport={"width": 1340, "height": 900})
            page.set_content(home_html, wait_until="domcontentloaded")
            page.wait_for_timeout(400)

            # Rail is visible on a wide desktop viewport.
            assert (
                page.eval_on_selector(".mh-chapter-nav", "el => getComputedStyle(el).display")
                == "block"
            )
            # At the top, the first chapter is current.
            assert self._active(page) == ["#mh-ch-overview"]

            # Scrolling a mid section to the top makes it current...
            page.eval_on_selector("#mh-ch-engine", "el => el.scrollIntoView()")
            page.wait_for_timeout(350)
            assert self._active(page) == ["#mh-ch-engine"]

            # ...and exactly one chapter is ever active.
            assert len(self._active(page)) == 1

            # The end of the page lights the final chapter (footer-tail guard).
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(350)
            assert self._active(page) == ["#mh-ch-start"]
        finally:
            browser.close()
            pw.stop()

    def test_click_scrolls_and_activates(self, home_html):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page(viewport={"width": 1340, "height": 900})
            page.set_content(home_html, wait_until="domcontentloaded")
            page.wait_for_timeout(400)

            # Clicking a chapter that sits inside a section taller than the
            # viewport must still settle on that chapter — the case a naive
            # top-band observer gets wrong.
            page.click('.mh-chapter-nav a[href="#mh-ch-engine"]')
            page.wait_for_timeout(900)
            assert self._active(page) == ["#mh-ch-engine"]
            # The section is scrolled clear of the sticky masthead, not behind it.
            top = page.eval_on_selector("#mh-ch-engine", "el => el.getBoundingClientRect().top")
            assert 0 <= top <= 130
            # The hash reflects the chapter for shareable deep links.
            assert page.evaluate("location.hash") == "#mh-ch-engine"
        finally:
            browser.close()
            pw.stop()

    def test_rail_hidden_on_narrow_viewport(self, home_html):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page(viewport={"width": 900, "height": 900})
            page.set_content(home_html, wait_until="domcontentloaded")
            page.wait_for_timeout(200)
            assert (
                page.eval_on_selector(".mh-chapter-nav", "el => getComputedStyle(el).display")
                == "none"
            )
        finally:
            browser.close()
            pw.stop()
