"""tests/test_ui_1_28_shortcuts_overlay.py — UI 1.28 global keyboard-shortcuts overlay.

Roadmap **UI 1.28** (Phase 1 product polish, *inspired by GitHub*): press ``?`` on
any page to reveal a modal listing the available shortcuts, with quick keys to
approve / re-queue / navigate in the review flow. Vanilla JS, no new deps,
``prefers-reduced-motion`` respected — but, crucially, this is a *functional*
surface (not decoration), so it must keep working under reduced motion; only the
entrance animation is suppressed there.

This is the GLOBAL, GitHub-style engine. The review page used to ship its own
page-local ``#mh-kbd-overlay`` + ``?`` handler; that was folded into this one
engine (in ``_layout``) so there is a single ``?`` binding app-wide and no
double-toggle collision. The review surface is detected by its ``.ach-row``
cards, which arm the j/k/a/u keys and reveal the "Review" group in the overlay.

Two layers, mirroring tests/test_hud_readout.py and tests/test_spring_microinteractions.py:

  1. **Server-side** (always runs) — the overlay ships in the shared chrome on
     every page with the right dialog a11y shape; the nav rows resolve through
     ``url_for`` (one source of truth for the go-to map); the review group is
     present-but-hidden; ``bindShortcuts`` + the ``MH`` hooks ship globally and do
     NOT early-return under reduced motion; the CSS reduced-motion override
     exists and the component sheet stays brace-balanced; the feature adds no
     backend route; and the page-local review overlay is gone while the review
     page keeps its bulk-approve / expand-all helpers.
  2. **Browser-side** (Playwright, skip-guarded) — ``?`` opens / toggles / Esc
     closes / backdrop + close-button close; typing in a field never opens it;
     focus moves into the dialog and is restored; ``g`` then a key navigates
     (live server); on the review page j/k move the focus ring and a/u
     approve / re-queue the focused card; and the overlay still opens under
     ``prefers-reduced-motion: reduce``.

The Playwright tier skips when Playwright or the pinned Chromium build is absent,
matching tests/test_hud_readout.py.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_SKIP_BROWSER = os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower() in ("1", "true", "yes")
from tests._pw_chromium import resolve_prebaked_chromium

_PINNED_CHROMIUM = resolve_prebaked_chromium()

_OVERLAY = 'id="mh-shortcuts-overlay"'
_RUN_ID = "rev0000001"

# Two ranked cards so the review surface renders real .ach-row cards (an elite
# safe lead + a strong needs-review card), matching the shape /review consumes.
_RANKED = [
    {
        "rank": 1,
        "quality_band": "elite",
        "priority": 0.92,
        "safe_to_post": {"level": "safe", "reason": "High-confidence evidence."},
        "achievement": {
            "swim_id": "s1",
            "swimmer_name": "Tamsin Veldt",
            "event": "200m IM",
            "time": "2:24.61",
            "headline": "Tamsin Veldt takes gold in the 200m IM",
            "type": "medal_gold",
            "confidence": 0.91,
            "confidence_label": "high",
        },
    },
    {
        "rank": 2,
        "quality_band": "strong",
        "priority": 0.61,
        "safe_to_post": {"level": "needs_review", "reason": "Medium confidence — verify."},
        "achievement": {
            "swim_id": "s2",
            "swimmer_name": "Idris Vanterpool",
            "event": "100m Freestyle",
            "time": "53.78",
            "headline": "Idris Vanterpool third in the 100m Free",
            "type": "medal_bronze",
            "confidence": 0.52,
            "confidence_label": "medium",
        },
    },
]


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401

        return True
    except ImportError:
        return False


def _chromium_available() -> bool:
    return _PINNED_CHROMIUM.is_file()


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def world(web_module, tmp_path):
    """Isolated MediaHub app + one ready org + one seeded review run."""
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="riverbend",
            display_name="Riverbend SC",
            brand_voice_summary="Warm, proud, community-first.",
        )
    )
    (tmp_path / "runs_v4" / f"{_RUN_ID}.json").write_text(
        json.dumps(
            {
                "run_id": _RUN_ID,
                "profile_id": "riverbend",
                "meet": {"name": "Riverbend Autumn Sprint"},
                "recognition_report": {"ranked_achievements": _RANKED},
            }
        )
    )

    app = web_module.create_app()
    app.config["TESTING"] = True  # org gate bypassed → every page renders
    return types.SimpleNamespace(app=app, wm=web_module, tmp=tmp_path)


def _get(world, path: str, *, profile: str | None = "riverbend") -> str:
    with world.app.test_client() as c:
        if profile:
            with c.session_transaction() as s:
                s["active_profile_id"] = profile
        r = c.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}"
        return r.get_data(as_text=True)


@pytest.fixture
def home_html(world) -> str:
    return _get(world, "/")


@pytest.fixture
def review_html(world) -> str:
    return _get(world, f"/review/{_RUN_ID}")


@pytest.fixture
def live_server(world):
    """Run the app on a real ephemeral port for genuine navigation tests."""
    from werkzeug.serving import make_server

    srv = make_server("127.0.0.1", 0, world.app, threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_port}"
    finally:
        srv.shutdown()
        thread.join(timeout=5)


def _bind_shortcuts_src(html: str) -> str:
    """Slice the bindShortcuts() function body out of the shipped page."""
    start = html.find("function bindShortcuts()")
    assert start != -1, "bindShortcuts() not shipped"
    end = html.find("MH.bindShortcuts = bindShortcuts;", start)
    assert end != -1, "bindShortcuts registration missing"
    return html[start:end]


def _nav_map(html: str) -> dict[str, str]:
    """Parse the {key: href} go-to map from the server-rendered nav rows."""
    out = {}
    for k, href in re.findall(r'data-mh-go="([a-z])"\s+href="([^"]*)"', html):
        out[k] = href
    return out


# ── Layer 1a: the overlay ships globally with the right shape ────────────────


class TestOverlayShipsGlobally:
    @pytest.mark.parametrize(
        "path", ["/", "/login", "/pricing", "/sign-in", "/status", "/settings"]
    )
    def test_overlay_on_every_layout_page(self, world, path):
        html = _get(world, path)
        assert _OVERLAY in html, f"shortcuts overlay missing on {path}"
        assert "function bindShortcuts()" in html, f"engine missing on {path}"

    def test_dialog_a11y_shape(self, home_html):
        m = re.search(r"<div [^>]*" + re.escape(_OVERLAY) + r"[^>]*>", home_html)
        assert m, "overlay open tag not found"
        tag = m.group(0)
        assert 'role="dialog"' in tag
        assert 'aria-modal="true"' in tag
        # Starts hidden; JS flips aria-hidden to false on open.
        assert 'aria-hidden="true"' in tag
        # Labelled by the heading.
        assert 'aria-labelledby="mh-shortcuts-title"' in tag
        assert 'id="mh-shortcuts-title"' in home_html

    def test_three_groups_present(self, home_html):
        for group in ("nav", "review", "general"):
            assert f'data-mh-shortcuts-group="{group}"' in home_html, f"missing {group} group"

    def test_review_group_hidden_by_default(self, home_html):
        # On a non-review page the review keys do not apply, so the group ships
        # hidden; the JS reveals it only when a review surface is detected.
        m = re.search(r'data-mh-shortcuts-group="review"[^>]*>', home_html)
        assert m and "hidden" in m.group(0), "review group must be hidden off-review"

    def test_general_group_lists_question_and_esc(self, home_html):
        # The two universal keys are always documented.
        block = home_html[home_html.find('data-mh-shortcuts-group="general"') :]
        block = block[: block.find("</section>")]
        assert "<kbd>?</kbd>" in block
        assert "<kbd>Esc</kbd>" in block

    def test_close_button_wired_for_openmodal(self, home_html):
        # MH.openModal wires any [data-mh-modal-close] inside the dialog.
        block = home_html[home_html.find(_OVERLAY) :]
        block = (
            block[: block.find("</div>\n{% if dock %}") + 50]
            if "{% if dock %}" in block
            else block[:4000]
        )
        assert "data-mh-modal-close" in home_html
        assert "mh-kbd-overlay-close" in home_html

    def test_overlay_has_no_user_input_xss_surface(self, home_html):
        # The overlay is fully static chrome — no interpolated user data — so it
        # carries no injection surface. Sanity: its nav hrefs are app paths only.
        for href in _nav_map(home_html).values():
            assert href.startswith("/"), f"nav href is not an internal path: {href!r}"
            assert "<" not in href and '"' not in href


# ── Layer 1b: nav rows resolve through url_for (one source of truth) ─────────


class TestNavRowsResolveViaUrlFor:
    def test_six_distinct_internal_destinations(self, home_html):
        nav = _nav_map(home_html)
        assert set(nav) == {"h", "p", "c", "m", "a", "s"}, nav
        # All distinct, all internal.
        assert len(set(nav.values())) == 6, f"duplicate destinations: {nav}"
        assert all(v.startswith("/") for v in nav.values())

    def test_destinations_match_url_for(self, world, home_html):
        nav = _nav_map(home_html)
        with world.app.test_request_context():
            from flask import url_for

            assert nav["h"] == url_for("home")
            assert nav["p"] == url_for("plan_page")
            assert nav["c"] == url_for("make_page")
            assert nav["m"] == url_for("media_library_page")
            assert nav["a"] == url_for("activity_page")
            assert nav["s"] == url_for("settings_page")

    def test_nav_rows_are_real_links(self, home_html):
        # Progressive enhancement: each nav row is an <a href>, so the overlay
        # doubles as a click menu and works with no JS.
        assert re.search(r'<a class="desc" data-mh-go="h" href="', home_html)


# ── Layer 1c: the engine ships globally + is functional under reduced motion ─


class TestEngineShips:
    def test_engine_and_hooks_exposed(self, home_html):
        assert "function bindShortcuts()" in home_html
        assert "MH.bindShortcuts = bindShortcuts;" in home_html
        assert "MH.openShortcuts = openOverlay;" in home_html
        assert "MH.closeShortcuts = closeOverlay;" in home_html
        assert "MH.toggleShortcuts = toggleOverlay;" in home_html

    def test_reads_navmap_from_dom(self, home_html):
        src = _bind_shortcuts_src(home_html)
        # The go-to map is read back off the server-rendered links — not hardcoded.
        assert "[data-mh-go]" in src
        assert "navMap" in src

    def test_question_and_g_prefix_handled(self, home_html):
        src = _bind_shortcuts_src(home_html)
        assert "e.key === '?'" in src
        assert "gPending" in src  # the GitHub-style 'g then key' sequence
        assert "window.location.href = dest" in src

    def test_reuses_house_focus_trap(self, home_html):
        src = _bind_shortcuts_src(home_html)
        # Opens through the shared MH.openModal helper (focus-trap / Esc / Tab).
        assert "MH.openModal" in src

    def test_review_keys_gated_on_ach_row(self, home_html):
        src = _bind_shortcuts_src(home_html)
        assert "querySelector('.ach-row')" in src  # surface detection
        assert 'data-mh-shortcuts-group="review"' in src  # reveal the group
        for key in ("'j'", "'k'", "'a'", "'u'"):
            assert key in src, f"review key {key} not wired"
        assert "clickWf('approved')" in src and "clickWf('queue')" in src

    def test_typing_guard_present(self, home_html):
        src = _bind_shortcuts_src(home_html)
        assert "isTyping" in src
        assert "isContentEditable" in src

    def test_functional_under_reduced_motion(self, home_html):
        """Unlike the decorative motion layers, the shortcuts engine must NOT
        early-return under reduced motion — the keys still work; only the CSS
        entrance animation is suppressed (and the scroll falls back to instant)."""
        src = _bind_shortcuts_src(home_html)
        assert (
            "if (prefersReduced) return" not in src
        ), "shortcuts must stay functional under reduced motion"
        # It is still motion-aware: the focus-ring scroll honours the flag.
        assert "prefersReduced ? 'auto' : 'smooth'" in src


# ── Layer 1d: CSS contract ───────────────────────────────────────────────────


class TestCssContract:
    @pytest.fixture(scope="class")
    def components_css(self) -> str:
        from mediahub.web.theme_tokens import THEME_COMPONENTS_CSS

        return THEME_COMPONENTS_CSS

    @pytest.mark.parametrize(
        "selector",
        [
            ".mh-kbd-overlay-panel h4",
            ".mh-kbd-overlay-close",
            ".mh-kbd-overlay-foot",
            ".mh-kbd-table a.desc",
            ".mh-kbd-table .mh-kbd-then",
        ],
    )
    def test_rule_present(self, components_css, selector):
        assert selector in components_css, f"missing CSS rule {selector!r}"

    def test_reduced_motion_suppresses_only_animation(self, components_css):
        # A reduced-motion block that turns the overlay animation off (but leaves
        # the dialog fully usable).
        m = re.search(
            r"@media \(prefers-reduced-motion: reduce\)\s*\{[^}]*\.mh-kbd-overlay[^}]*animation:\s*none",
            components_css,
            re.DOTALL,
        )
        assert m, "missing reduced-motion animation:none override for the overlay"

    def test_braces_balanced(self, components_css):
        assert components_css.count("{") == components_css.count(
            "}"
        ), "unbalanced braces in theme-components.css after the UI 1.28 section"

    def test_in_assembled_base_css(self):
        import mediahub.web.web as wm

        assert ".mh-kbd-overlay-close" in wm.BASE_CSS


# ── Layer 1e: the page-local review overlay was subsumed (no collision) ──────


class TestReviewSubsumption:
    def test_review_page_uses_global_overlay(self, review_html):
        assert _OVERLAY in review_html
        # Review cards present → JS arms j/k/a/u + reveals the review group.
        assert 'class="ach-row"' in review_html

    def test_no_page_local_overlay_left(self, review_html):
        # The old page-local '?' handler + modal are gone — exactly one '?'
        # binding now exists (the global engine).
        assert 'id="mh-kbd-overlay"' not in review_html
        assert 'id="mh-kbd-title"' not in review_html
        assert "data-mh-kbd-close" not in review_html
        assert "function toggleHelp" not in review_html

    def test_review_helpers_preserved(self, review_html):
        # Bulk-approve + expand-all were NOT keyboard features — they survive.
        assert "getElementById('mh-bulk-approve')" in review_html
        assert "getElementById('mh-expand-all-why')" in review_html
        # The contextual hint strip + the approve buttons remain.
        assert "mh-kbd-hint" in review_html
        assert 'data-mh-wf="approved"' in review_html


# ── Layer 1f: no new backend surface ─────────────────────────────────────────


class TestNoNewRoute:
    def test_no_shortcut_route_added(self, world):
        rules = [r.rule for r in world.app.url_map.iter_rules()]
        bad = [r for r in rules if "shortcut" in r.lower()]
        assert not bad, f"UI 1.28 must add no backend route: {bad!r}"


# ── Layer 2: live browser behaviour ──────────────────────────────────────────


def _launch_browser():
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        executable_path=str(_PINNED_CHROMIUM),
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    return pw, browser


_DISPATCH = "document.dispatchEvent(new KeyboardEvent('keydown',{key:%r,bubbles:true}))"
_IS_OPEN = "document.getElementById('mh-shortcuts-overlay').classList.contains('is-open')"


@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="prebaked chromium not found")
class TestShortcutsBrowser:
    """The overlay really opens/closes and respects the typing + reduced-motion
    rules — driven against the shipped inline JS via set_content."""

    def test_question_opens_and_moves_focus_then_toggles_closed(self, home_html):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(home_html)
            page.wait_for_timeout(250)
            assert page.evaluate(_IS_OPEN) is False  # starts closed
            page.evaluate(_DISPATCH % "?")
            page.wait_for_timeout(140)
            opened = page.evaluate(
                "({open: " + _IS_OPEN + ", "
                "ah: document.getElementById('mh-shortcuts-overlay').getAttribute('aria-hidden'), "
                "focus: (document.activeElement||{}).className||''})"
            )
            # '?' again toggles it closed.
            page.evaluate(_DISPATCH % "?")
            page.wait_for_timeout(140)
            closed = page.evaluate(_IS_OPEN)
        finally:
            browser.close()
            pw.stop()

        assert opened["open"] is True
        assert opened["ah"] == "false"
        # Focus moved into the dialog (onto the close button via MH.openModal).
        assert "mh-kbd-overlay-close" in opened["focus"]
        assert closed is False

    def test_escape_and_close_button_close(self, home_html):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(home_html)
            page.wait_for_timeout(250)

            # Real Escape closes (MH.openModal owns the capture Esc handler).
            page.evaluate(_DISPATCH % "?")
            page.wait_for_timeout(120)
            assert page.evaluate(_IS_OPEN) is True
            page.keyboard.press("Escape")
            page.wait_for_timeout(120)
            after_esc = page.evaluate(_IS_OPEN)

            # The "Got it" close button closes too.
            page.evaluate(_DISPATCH % "?")
            page.wait_for_timeout(120)
            page.click("#mh-shortcuts-overlay [data-mh-modal-close]")
            page.wait_for_timeout(120)
            after_btn = page.evaluate(_IS_OPEN)
        finally:
            browser.close()
            pw.stop()

        assert after_esc is False
        assert after_btn is False

    def test_backdrop_click_closes(self, home_html):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_viewport_size({"width": 1200, "height": 800})
            page.set_content(home_html)
            page.wait_for_timeout(250)
            page.evaluate(_DISPATCH % "?")
            page.wait_for_timeout(120)
            assert page.evaluate(_IS_OPEN) is True
            # Click far from the centred panel → on the backdrop → closes.
            page.mouse.click(8, 8)
            page.wait_for_timeout(120)
            closed = page.evaluate(_IS_OPEN)
        finally:
            browser.close()
            pw.stop()
        assert closed is False

    def test_typing_in_a_field_does_not_open(self, home_html):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(home_html)
            page.wait_for_timeout(250)
            # Inject + focus an input, then fire '?' from inside it.
            res = page.evaluate(
                """() => {
                    var inp = document.createElement('input');
                    inp.id = '__t'; document.body.appendChild(inp); inp.focus();
                    inp.dispatchEvent(new KeyboardEvent('keydown',{key:'?',bubbles:true}));
                    return document.getElementById('mh-shortcuts-overlay').classList.contains('is-open');
                }"""
            )
        finally:
            browser.close()
            pw.stop()
        assert res is False, "shortcuts opened while typing in a field"

    def test_still_opens_under_reduced_motion(self, home_html):
        pw, browser = _launch_browser()
        try:
            ctx = browser.new_context(reduced_motion="reduce")
            page = ctx.new_page()
            page.set_content(home_html)
            page.wait_for_timeout(250)
            page.evaluate(_DISPATCH % "?")
            page.wait_for_timeout(140)
            opened = page.evaluate(_IS_OPEN)
        finally:
            browser.close()
            pw.stop()
        assert opened is True, "overlay must stay functional under reduced motion"


@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="prebaked chromium not found")
class TestNavBrowser:
    """'g then key' really navigates, against a live server."""

    def test_g_then_key_navigates(self, live_server):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.goto(f"{live_server}/", wait_until="domcontentloaded")
            page.wait_for_timeout(250)
            page.evaluate(_DISPATCH % "g")
            page.evaluate(_DISPATCH % "s")
            page.wait_for_url("**/settings", timeout=5000)
            settings_url = page.url

            page.evaluate(_DISPATCH % "g")
            page.evaluate(_DISPATCH % "h")
            page.wait_for_url(live_server + "/", timeout=5000)
            home_url = page.url
        finally:
            browser.close()
            pw.stop()

        assert settings_url.endswith("/settings")
        assert home_url.rstrip("/") == live_server

    def test_clicking_a_nav_row_navigates(self, live_server):
        """The nav rows work as plain links (no-JS progressive enhancement)."""
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.goto(f"{live_server}/", wait_until="domcontentloaded")
            page.wait_for_timeout(200)
            # Reveal the overlay, then click the Settings row (a destination that
            # renders without a session — Activity 302s to org setup).
            page.evaluate(_DISPATCH % "?")
            page.wait_for_timeout(120)
            page.click('#mh-shortcuts-overlay a[data-mh-go="s"]')
            page.wait_for_url("**/settings", timeout=5000)
            url = page.url
        finally:
            browser.close()
            pw.stop()
        assert url.endswith("/settings")


@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="prebaked chromium not found")
class TestReviewBrowser:
    """On the review surface j/k move the focus ring and a/u act on the focused
    card; the review group is revealed once the engine sees the cards."""

    def _read_focus(self, page):
        return page.evaluate(
            "() => { var f = document.querySelector('.ach-row.mh-kbd-focus'); "
            "return f ? f.getAttribute('data-swimmer') : null; }"
        )

    def test_review_group_revealed(self, review_html):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(review_html)
            page.wait_for_timeout(300)
            hidden = page.evaluate(
                "document.querySelector('[data-mh-shortcuts-group=\"review\"]').hidden"
            )
        finally:
            browser.close()
            pw.stop()
        assert hidden is False, "review group must be revealed on a review surface"

    def test_j_k_move_the_focus_ring(self, review_html):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(review_html)
            page.wait_for_timeout(300)
            count = page.evaluate(
                "Array.prototype.slice.call(document.querySelectorAll('.ach-row'))"
                ".filter(function(e){return e.offsetParent!==null}).length"
            )
            assert count >= 2, f"expected ≥2 visible cards, got {count}"
            page.evaluate(_DISPATCH % "j")
            page.wait_for_timeout(80)
            first = self._read_focus(page)
            page.evaluate(_DISPATCH % "j")
            page.wait_for_timeout(80)
            second = self._read_focus(page)
            page.evaluate(_DISPATCH % "k")
            page.wait_for_timeout(80)
            back = self._read_focus(page)
        finally:
            browser.close()
            pw.stop()

        assert first == "Tamsin Veldt"
        assert second == "Idris Vanterpool"
        assert back == "Tamsin Veldt"

    def test_a_and_u_act_on_the_focused_card(self, review_html):
        """'a' clicks the focused card's Approve button; 'u' clicks Re-queue.
        Spied at the button so the wiring is proven without the network."""
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(review_html)
            page.wait_for_timeout(300)
            result = page.evaluate(
                """() => {
                    document.dispatchEvent(new KeyboardEvent('keydown',{key:'j',bubbles:true}));
                    var foc = document.querySelector('.ach-row.mh-kbd-focus');
                    var hits = {approved: false, queue: false};
                    foc.querySelector('[data-mh-wf="approved"]')
                       .addEventListener('click', function(){ hits.approved = true; });
                    foc.querySelector('[data-mh-wf="queue"]')
                       .addEventListener('click', function(){ hits.queue = true; });
                    document.dispatchEvent(new KeyboardEvent('keydown',{key:'a',bubbles:true}));
                    document.dispatchEvent(new KeyboardEvent('keydown',{key:'u',bubbles:true}));
                    return hits;
                }"""
            )
        finally:
            browser.close()
            pw.stop()

        assert result["approved"] is True, "'a' did not approve the focused card"
        assert result["queue"] is True, "'u' did not re-queue the focused card"

    def test_question_overlay_works_on_review_too(self, review_html):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(review_html)
            page.wait_for_timeout(300)
            page.evaluate(_DISPATCH % "?")
            page.wait_for_timeout(140)
            opened = page.evaluate(_IS_OPEN)
        finally:
            browser.close()
            pw.stop()
        assert opened is True
