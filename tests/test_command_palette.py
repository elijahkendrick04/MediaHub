"""tests/test_command_palette.py — UI 1.15: command palette (Cmd-K).

A modal "search or jump to…" overlay opened with ⌘K / Ctrl-K (or "/" when the
user is not already typing, or the nav trigger pill). It gives fast keyboard
navigation and quick actions across the app. Pure vanilla JS, no framework.

The command list is **server-rendered** with ``url_for()`` so it is
authoritative and gated exactly like the nav (signed-in orgs get the app
surfaces; signed-out visitors get the public ones). The inline script only
filters and navigates — it never invents a route.

Two layers of assertion, mirroring tests/test_hud_readout.py:

  1. Server-side (no browser, always runs): the palette markup, ids, the
     ARIA combobox/listbox shape, the CSS contract, progressive-enhancement
     placement (hidden until opened; trigger shown only under ``.mh-js``), the
     command gating for each auth state, that every href is a real ``url_for``
     path (never hardcoded / never an unrendered template), and the "no new
     backend route" guarantee.
  2. Browser-side (Playwright, skips when absent): against a real live server —
     ⌘K / Ctrl-K and "/" open it, the trigger opens it, typing filters, the
     empty state shows, ↑/↓ move the highlight with wrap-around,
     aria-activedescendant tracks it, ↵ navigates, Esc / backdrop close and
     restore focus, Tab is trapped, and the body scroll-locks while open.
"""
from __future__ import annotations

import importlib
import os
import re
import sys
import threading
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_SKIP_BROWSER = (
    os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower() in ("1", "true", "yes")
)
_PINNED_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")

# Structural ids the palette and its script depend on.
_CMDK_IDS = (
    "mh-cmdk",
    "mh-cmdk-input",
    "mh-cmdk-results",
    "mh-cmdk-empty",
)


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
def cmdk_app(tmp_path, monkeypatch):
    """Minimal isolated MediaHub app."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    return app


def _signed_out_html(app) -> str:
    with app.test_client() as c:
        return c.get("/").get_data(as_text=True)


def _signed_in_html(app, *, account_email: str = "") -> str:
    """Render the home page with an org pinned (and optionally an account)."""
    import time

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="cmdk-org", display_name="Cmd-K Swim Club"))
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["active_profile_id"] = "cmdk-org"
            s["login_seen_at"] = int(time.time())
            if account_email:
                s["user_email"] = account_email
        return c.get("/").get_data(as_text=True)


@pytest.fixture
def cmdk_html(cmdk_app):
    """Signed-out home-page HTML (the public chrome the palette ships in)."""
    return _signed_out_html(cmdk_app)


@pytest.fixture
def cmdk_html_in(cmdk_app):
    """Signed-in home-page HTML (org pinned — the full app command set)."""
    return _signed_in_html(cmdk_app)


@pytest.fixture
def cmdk_server(cmdk_app):
    """Run the app on a real ephemeral port so the browser can open the palette
    and follow real navigations. Yields the base URL."""
    from werkzeug.serving import make_server

    srv = make_server("127.0.0.1", 0, cmdk_app, threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_port}"
    finally:
        srv.shutdown()
        thread.join(timeout=5)


def _opt_ids(html: str) -> list[str]:
    return re.findall(r'id="mh-cmdk-opt-([\w-]+)"', html)


def _href_for(html: str, opt_id: str) -> str | None:
    m = re.search(
        r'id="mh-cmdk-opt-%s"[^>]*data-href="([^"]+)"' % re.escape(opt_id), html, re.S
    )
    return m.group(1) if m else None


# ── Layer 1: server-side markup / CSS / wiring ───────────────────────────────


class TestCmdkServerMarkup:
    def test_present_on_every_layout_page(self, cmdk_app):
        """The palette is part of the shared chrome — every ``_layout`` page,
        signed-out included."""
        with cmdk_app.test_client() as c:
            for path in ("/", "/pricing", "/sign-in", "/status"):
                html = c.get(path).get_data(as_text=True)
                assert 'id="mh-cmdk"' in html, f"palette missing on {path}"

    @pytest.mark.parametrize("element_id", _CMDK_IDS)
    def test_required_ids_present(self, cmdk_html, element_id):
        assert f'id="{element_id}"' in cmdk_html, f"missing #{element_id}"

    def test_dialog_is_modal_and_hidden_by_default(self, cmdk_html):
        """Closed at rest: a no-JS visitor never sees it, and it doesn't trap a
        keyboard user. It opens (``.is-open``) only via JS."""
        m = re.search(r'<div class="mh-cmdk"[^>]*>', cmdk_html)
        assert m, "palette root not found"
        tag = m.group(0)
        assert 'role="dialog"' in tag
        assert 'aria-modal="true"' in tag
        assert 'aria-hidden="true"' in tag
        assert "is-open" not in tag  # not open in the server HTML

    def test_trigger_present_and_advertises_shortcut(self, cmdk_html):
        """A discoverable nav pill that opens the palette and shows ⌘K."""
        assert "mh-cmdk-trigger" in cmdk_html
        assert "data-cmdk-open" in cmdk_html
        assert 'aria-controls="mh-cmdk"' in cmdk_html
        # The kbd hint the JS rewrites to "Ctrl K" off-Mac.
        assert "data-cmdk-kbd" in cmdk_html

    def test_trigger_is_progressive_enhancement(self, cmdk_html):
        """The trigger is hidden until JS is up (``.mh-js``) so a no-JS user
        never gets a dead button — the nav links still work without it."""
        assert ".mh-cmdk-trigger { display: none; }" in cmdk_html
        assert ".mh-js .mh-cmdk-trigger {" in cmdk_html


class TestCmdkAria:
    """Standard WAI-ARIA combobox-over-listbox so the palette is operable and
    legible to assistive tech."""

    def test_input_is_a_combobox(self, cmdk_html):
        m = re.search(r'<input id="mh-cmdk-input"[^>]*>', cmdk_html)
        assert m, "palette input not found"
        tag = m.group(0)
        assert 'role="combobox"' in tag
        assert 'aria-controls="mh-cmdk-results"' in tag
        assert 'aria-autocomplete="list"' in tag
        # An autocomplete dropdown of suggestions should not autocomplete/spellcheck.
        assert 'autocomplete="off"' in tag
        assert 'spellcheck="false"' in tag

    def test_results_is_a_listbox_of_options(self, cmdk_html):
        m = re.search(r'<div class="mh-cmdk-results"[^>]*>', cmdk_html)
        assert m and 'role="listbox"' in m.group(0)
        # Every command row is an option with a stable id (for aria-activedescendant).
        opts = re.findall(r'<div class="mh-cmdk-item"[^>]*role="option"[^>]*>', cmdk_html)
        assert len(opts) >= 5
        for o in opts:
            assert 'aria-selected="false"' in o  # none active at rest

    def test_group_labels_are_presentational(self, cmdk_html):
        """Group headings are dividers, not selectable options."""
        labels = re.findall(r'<div class="mh-cmdk-group-label"[^>]*>', cmdk_html)
        assert labels, "no group labels rendered"
        for lab in labels:
            assert 'role="presentation"' in lab

    def test_decorative_glyphs_hidden(self, cmdk_html):
        """Icons and the ↵ go-glyph carry no meaning for SR users."""
        assert 'class="mh-cmdk-item-icon" aria-hidden="true"' in cmdk_html
        assert 'class="mh-cmdk-item-go" aria-hidden="true"' in cmdk_html


class TestCmdkCommandGating:
    """The command set adapts to the auth state — exactly like the nav."""

    def test_signed_out_commands(self, cmdk_html):
        ids = set(_opt_ids(cmdk_html))
        # Public destinations only.
        assert {"home", "pricing", "status", "sign-in"}.issubset(ids)
        # No app surfaces when there is no org pinned.
        assert not ({"create", "plan", "library", "settings", "switch-org"} & ids)

    def test_signed_in_commands(self, cmdk_html_in):
        ids = set(_opt_ids(cmdk_html_in))
        assert {
            "home",
            "create",
            "plan",
            "library",
            "activity",
            "brand",
            "settings",
            "status",
            "switch-org",
            "sign-out",
        }.issubset(ids), ids
        # Signed-in chrome drops the prospect-facing entries.
        assert "pricing" not in ids
        assert "sign-in" not in ids

    def test_account_email_adds_billing(self, cmdk_app):
        """An account-level session (PC.1) surfaces Billing + account log-out."""
        html = _signed_in_html(cmdk_app, account_email="coach@club.example")
        ids = set(_opt_ids(html))
        assert "billing" in ids
        assert "log-out" in ids
        # The billing hint shows the signed-in account email.
        assert "coach@club.example" in html

    def test_signed_in_offers_more_than_signed_out(self, cmdk_html, cmdk_html_in):
        assert len(_opt_ids(cmdk_html_in)) > len(_opt_ids(cmdk_html))


class TestCmdkHrefsAreUrlFor:
    """Every destination must be a real resolved path — never hardcoded, never
    an unrendered ``{{ }}`` template, and matching ``url_for`` for that route
    (the CLAUDE.md 'url_for() always' rule)."""

    def test_no_unrendered_templates_in_palette(self, cmdk_html_in):
        # The palette is rendered just before the top nav — slice between those
        # two stable markers and confirm Jinja fully resolved inside it.
        start = cmdk_html_in.find('<div class="mh-cmdk" id="mh-cmdk"')
        end = cmdk_html_in.find('<header class="topnav">', start)
        assert start != -1 and end != -1 and start < end, "could not isolate palette block"
        block = cmdk_html_in[start:end]
        assert "mh-cmdk-results" in block  # sanity: we grabbed the right region
        assert "{{" not in block and "{%" not in block

    def test_every_item_href_is_absolute_path(self, cmdk_html_in):
        hrefs = re.findall(r'data-cmdk-item data-href="([^"]+)"', cmdk_html_in)
        assert hrefs
        for h in hrefs:
            assert h.startswith("/"), h

    def test_hrefs_match_url_for(self, cmdk_app):
        """Tie each command to its endpoint via url_for so a route rename can't
        silently break the palette."""
        html = _signed_in_html(cmdk_app)
        with cmdk_app.test_request_context():
            from flask import url_for

            expected = {
                "home": url_for("home"),
                "create": url_for("make_page"),
                "plan": url_for("plan_page"),
                "library": url_for("media_library_page"),
                "activity": url_for("activity_page"),
                "brand": url_for("organisation_setup"),
                "settings": url_for("settings_page"),
                "status": url_for("status_page"),
                "switch-org": url_for("sign_in_page"),
                "sign-out": url_for("sign_out"),
            }
        for opt_id, want in expected.items():
            assert _href_for(html, opt_id) == want, opt_id

    def test_every_item_has_an_icon_and_haystack(self, cmdk_html_in):
        n = len(_opt_ids(cmdk_html_in))
        # One stroked icon span per row.
        assert cmdk_html_in.count('class="mh-cmdk-item-icon"') == n
        # A lowercased search haystack per row.
        hays = re.findall(r'data-haystack="([^"]+)"', cmdk_html_in)
        assert len(hays) == n
        for h in hays:
            assert h == h.lower(), h


class TestCmdkCss:
    @pytest.mark.parametrize(
        "selector",
        [
            ".mh-cmdk {",
            ".mh-cmdk.is-open {",
            ".mh-cmdk-panel {",
            ".mh-cmdk-search {",
            ".mh-cmdk-input {",
            ".mh-cmdk-results {",
            ".mh-cmdk-item {",
            ".mh-cmdk-item.is-active {",
            ".mh-cmdk-item.is-hidden {",
            ".mh-cmdk-empty {",
            ".mh-cmdk-foot {",
            "body.mh-cmdk-open {",
        ],
    )
    def test_css_rule_present(self, cmdk_html, selector):
        assert selector in cmdk_html, f"missing palette CSS rule {selector!r}"

    def test_reduced_motion_disables_animation(self, cmdk_html):
        """The open animation is gone under prefers-reduced-motion."""
        m = re.search(
            r"@media \(prefers-reduced-motion: reduce\) \{([^@]*?\.mh-cmdk[^@]*?)\}\s*\n",
            cmdk_html,
            re.S,
        )
        # At minimum the panel + overlay animations are overridden somewhere in
        # a reduced-motion block.
        assert ".mh-cmdk-panel { animation: none; }" in cmdk_html
        assert ".mh-cmdk.is-open { animation: none; }" in cmdk_html

    def test_high_z_index_overlay(self, cmdk_html):
        """The modal sits above the page chrome (loader 9999 / toasts 10000)."""
        m = re.search(r"\.mh-cmdk \{(.*?)\}", cmdk_html, re.S)
        assert m
        zi = re.search(r"z-index:\s*(\d+)", m.group(1))
        assert zi and int(zi.group(1)) >= 10000


class TestCmdkJsWiring:
    """The behaviour the inline script must wire — asserted at the source level
    so a refactor that drops a binding is caught even without a browser."""

    def test_keyboard_openers_present(self, cmdk_html):
        # ⌘K / Ctrl-K opener.
        assert "e.metaKey || e.ctrlKey" in cmdk_html
        assert "'k'" in cmdk_html and "'K'" in cmdk_html
        # "/" opener guarded by a not-typing check.
        assert "typingTarget" in cmdk_html
        assert "=== '/'" in cmdk_html

    def test_keyboard_navigation_present(self, cmdk_html):
        for token in ("ArrowDown", "ArrowUp", "Enter", "Escape", "Tab"):
            assert token in cmdk_html, f"missing key handler for {token}"
        assert "moveActive" in cmdk_html  # wrap-around highlight movement

    def test_activedescendant_and_focus_restore(self, cmdk_html):
        assert "aria-activedescendant" in cmdk_html
        assert "lastFocus" in cmdk_html  # focus is restored on close

    def test_public_api_exposed(self, cmdk_html):
        assert "MH.openCommandPalette" in cmdk_html
        assert "MH.closeCommandPalette" in cmdk_html

    def test_no_new_cmdk_route(self, cmdk_app):
        """'No new backend surface' — the palette adds no route of its own."""
        rules = [r.rule for r in cmdk_app.url_map.iter_rules()]
        bad = [r for r in rules if ("cmdk" in r.lower() or "command-palette" in r.lower())]
        assert not bad, "UI 1.15 must add no backend route: " + repr(bad)


class TestCmdkGroupsHelper:
    """Direct unit coverage of the gating helper (fast, no full render)."""

    def test_helper_gating(self, cmdk_app):
        import mediahub.web.web as wm

        with cmdk_app.test_request_context():
            out = wm._command_palette_groups(
                signed_in=False, research_enabled=False, account_email="", dev_operator=False
            )
            ids_out = {it["id"] for g in out for it in g["items"]}
            assert "create" not in ids_out and "pricing" in ids_out

            ins = wm._command_palette_groups(
                signed_in=True, research_enabled=True, account_email="", dev_operator=False
            )
            ids_in = {it["id"] for g in ins for it in g["items"]}
            assert {"create", "research", "switch-org"}.issubset(ids_in)
            # research only when the console is enabled
            no_research = wm._command_palette_groups(
                signed_in=True, research_enabled=False, account_email="", dev_operator=False
            )
            assert "research" not in {it["id"] for g in no_research for it in g["items"]}

    def test_helper_items_well_formed(self, cmdk_app):
        import mediahub.web.web as wm

        with cmdk_app.test_request_context():
            groups = wm._command_palette_groups(
                signed_in=True, research_enabled=False, account_email="", dev_operator=False
            )
        assert groups and all(g["items"] for g in groups)
        for g in groups:
            for it in g["items"]:
                assert it["id"] and it["label"] and it["href"].startswith("/")
                assert it["icon"].startswith("<svg")
                assert it["keywords"]


# ── Layer 2: live browser behaviour ──────────────────────────────────────────


@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="chromium-1194 not at pinned path")
class TestCmdkBrowserBehaviour:
    """End-to-end against a real server on the signed-out chrome (Home, Pricing,
    System status, Sign in, Log in) — enough commands to exercise every path."""

    def _open_state(self, page):
        return page.evaluate(
            """() => ({
                open: document.getElementById('mh-cmdk').classList.contains('is-open'),
                hidden: document.getElementById('mh-cmdk').getAttribute('aria-hidden'),
                focused: document.activeElement && document.activeElement.id,
                bodyLocked: document.body.classList.contains('mh-cmdk-open'),
                active: document.getElementById('mh-cmdk-input').getAttribute('aria-activedescendant'),
            })"""
        )

    def _visible_option_ids(self, page):
        return page.evaluate(
            """() => Array.prototype.slice
                .call(document.querySelectorAll('#mh-cmdk-results [data-cmdk-item]'))
                .filter(el => !el.classList.contains('is-hidden'))
                .map(el => el.id)"""
        )

    def test_cmdk_opens_and_focuses_input(self, cmdk_server):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.goto(f"{cmdk_server}/", wait_until="domcontentloaded")
            assert self._open_state(page)["open"] is False
            page.keyboard.press("Control+k")
            page.wait_for_function(
                "document.getElementById('mh-cmdk').classList.contains('is-open')",
                timeout=4000,
            )
            st = self._open_state(page)
            assert st["open"] is True
            assert st["hidden"] == "false"
            assert st["focused"] == "mh-cmdk-input"  # caret lands in the search box
            assert st["bodyLocked"] is True  # background scroll-locked
            # First row is highlighted for immediate Enter-to-go.
            assert st["active"] and st["active"].startswith("mh-cmdk-opt-")
            # Meta+k toggles it closed (handler accepts either modifier).
            page.keyboard.press("Control+k")
            page.wait_for_function(
                "!document.getElementById('mh-cmdk').classList.contains('is-open')",
                timeout=4000,
            )
            assert self._open_state(page)["open"] is False
        finally:
            browser.close()
            pw.stop()

    def test_slash_opens_when_not_typing(self, cmdk_server):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.goto(f"{cmdk_server}/", wait_until="domcontentloaded")
            page.keyboard.press("/")
            page.wait_for_function(
                "document.getElementById('mh-cmdk').classList.contains('is-open')",
                timeout=4000,
            )
            # The "/" was consumed as the opener, not typed into the box.
            assert page.eval_on_selector("#mh-cmdk-input", "el => el.value") == ""
        finally:
            browser.close()
            pw.stop()

    def test_trigger_click_opens(self, cmdk_server):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.goto(f"{cmdk_server}/", wait_until="domcontentloaded")
            page.click(".mh-cmdk-trigger")
            page.wait_for_function(
                "document.getElementById('mh-cmdk').classList.contains('is-open')",
                timeout=4000,
            )
            # Off-Mac the kbd hint reads "Ctrl K".
            assert "Ctrl" in page.eval_on_selector("[data-cmdk-kbd]", "el => el.textContent")
        finally:
            browser.close()
            pw.stop()

    def test_filter_narrows_and_empty_state(self, cmdk_server):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.goto(f"{cmdk_server}/", wait_until="domcontentloaded")
            page.keyboard.press("Control+k")
            page.wait_for_function(
                "document.getElementById('mh-cmdk').classList.contains('is-open')",
                timeout=4000,
            )
            # Type a query that matches exactly one public command.
            page.fill("#mh-cmdk-input", "pricing")
            page.wait_for_function(
                """() => {
                    const v = Array.prototype.slice
                      .call(document.querySelectorAll('#mh-cmdk-results [data-cmdk-item]'))
                      .filter(el => !el.classList.contains('is-hidden'));
                    return v.length === 1 && v[0].id === 'mh-cmdk-opt-pricing';
                }""",
                timeout=4000,
            )
            assert self._visible_option_ids(page) == ["mh-cmdk-opt-pricing"]
            # The highlight re-anchors to the surviving row.
            assert self._open_state(page)["active"] == "mh-cmdk-opt-pricing"
            # A no-match query shows the empty state and hides every row.
            page.fill("#mh-cmdk-input", "zzzznope")
            page.wait_for_function(
                "!document.getElementById('mh-cmdk-empty').classList.contains('is-hidden')",
                timeout=4000,
            )
            assert self._visible_option_ids(page) == []
        finally:
            browser.close()
            pw.stop()

    def test_arrow_navigation_wraps_and_updates_activedescendant(self, cmdk_server):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.goto(f"{cmdk_server}/", wait_until="domcontentloaded")
            page.keyboard.press("Control+k")
            page.wait_for_function(
                "document.getElementById('mh-cmdk').classList.contains('is-open')",
                timeout=4000,
            )
            first = self._open_state(page)["active"]
            page.keyboard.press("ArrowDown")
            second = self._open_state(page)["active"]
            assert second and second != first
            # ArrowUp from the first row wraps to the last visible row.
            page.keyboard.press("ArrowUp")  # back to first
            page.keyboard.press("ArrowUp")  # wrap to last
            wrapped = self._open_state(page)["active"]
            vis = self._visible_option_ids(page)
            assert wrapped == vis[-1]
        finally:
            browser.close()
            pw.stop()

    def test_enter_navigates_to_command(self, cmdk_server):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.goto(f"{cmdk_server}/", wait_until="domcontentloaded")
            page.keyboard.press("Control+k")
            page.wait_for_function(
                "document.getElementById('mh-cmdk').classList.contains('is-open')",
                timeout=4000,
            )
            page.fill("#mh-cmdk-input", "system status")
            page.wait_for_function(
                """() => {
                    const v = Array.prototype.slice
                      .call(document.querySelectorAll('#mh-cmdk-results [data-cmdk-item]'))
                      .filter(el => !el.classList.contains('is-hidden'));
                    return v.length === 1 && v[0].id === 'mh-cmdk-opt-status';
                }""",
                timeout=4000,
            )
            page.keyboard.press("Enter")
            page.wait_for_url("**/status", timeout=5000)
            assert page.url.rstrip("/").endswith("/status")
        finally:
            browser.close()
            pw.stop()

    def test_escape_closes_and_restores_focus(self, cmdk_server):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.goto(f"{cmdk_server}/", wait_until="domcontentloaded")
            page.click(".mh-cmdk-trigger")
            page.wait_for_function(
                "document.getElementById('mh-cmdk').classList.contains('is-open')",
                timeout=4000,
            )
            page.keyboard.press("Escape")
            page.wait_for_function(
                "!document.getElementById('mh-cmdk').classList.contains('is-open')",
                timeout=4000,
            )
            st = self._open_state(page)
            assert st["open"] is False
            assert st["bodyLocked"] is False
            # Focus returns to the trigger that opened it.
            assert page.evaluate(
                "() => document.activeElement && document.activeElement.classList.contains('mh-cmdk-trigger')"
            )
        finally:
            browser.close()
            pw.stop()

    def test_backdrop_click_closes(self, cmdk_server):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.goto(f"{cmdk_server}/", wait_until="domcontentloaded")
            page.keyboard.press("Control+k")
            page.wait_for_function(
                "document.getElementById('mh-cmdk').classList.contains('is-open')",
                timeout=4000,
            )
            # Click the overlay backdrop, away from the panel (top-left corner).
            page.mouse.click(8, 8)
            page.wait_for_function(
                "!document.getElementById('mh-cmdk').classList.contains('is-open')",
                timeout=4000,
            )
            assert self._open_state(page)["open"] is False
        finally:
            browser.close()
            pw.stop()

    def test_tab_is_trapped_in_input(self, cmdk_server):
        """Tab moves the highlight but keeps focus in the search box (a focus
        trap) — it never leaks to the page behind the modal."""
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.goto(f"{cmdk_server}/", wait_until="domcontentloaded")
            page.keyboard.press("Control+k")
            page.wait_for_function(
                "document.getElementById('mh-cmdk').classList.contains('is-open')",
                timeout=4000,
            )
            first = self._open_state(page)["active"]
            page.keyboard.press("Tab")
            st = self._open_state(page)
            assert st["focused"] == "mh-cmdk-input"  # focus stayed in the box
            assert st["active"] != first  # highlight advanced
        finally:
            browser.close()
            pw.stop()
