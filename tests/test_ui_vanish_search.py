"""tests/test_ui_vanish_search.py — UI2.6 Vanish search.

Roadmap **UI2.6** (UI2 design-system-uplift follow-on): the /activity (global
run) search is wired to the design-kit **Vanish input** (``.mh-vanish``) — a
rotating *overlay-placeholder element* (``.mh-vanish__ph``) that swap-fades
through real example queries, aligned past the search icon, with the **native
placeholder removed**. This supersedes the UI 1.1 typewriter-through-the-native-
placeholder cycle on that one field (its coverage moved here from
tests/test_ui_cycle_placeholder.py).

Three layers, mirroring tests/test_ui_cycle_placeholder.py and
tests/test_u12_odometer_stats.py:

  1. **Server-side** — the search renders as a ``.mh-search.mh-vanish`` container
     carrying a parseable, HTML-safe ``data-mh-placeholders`` pipe list; the
     overlay element ships the first phrase (the no-JS hint); the native
     ``placeholder`` is emptied; an ``aria-label`` keeps the accessible name; the
     icon + ``id`` (the existing filter JS hook) survive; and the old cycle
     attribute / constants are gone.
  2. **Static assets** — ``ui-kit.js`` ships ``bindVanish`` and binds it; the kit
     CSS ships the overlay + the ``:placeholder-shown`` no-JS fallback; the
     alignment rule (``--mh-vanish-pad``) ships co-located with ``.mh-search``.
  3. **Browser (Playwright)** — the overlay really rotates; typing hides it (the
     ``is-typing`` JS path); reduced motion freezes it on the first phrase; the
     CSS-only ``:placeholder-shown`` rule hides it with the kit JS absent; and the
     overlay aligns past the search icon. Skips when Playwright / the pinned
     Chromium build is absent, matching tests/test_browser_cascade.py.
"""

from __future__ import annotations

import html as _html
import os
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_SKIP_BROWSER = os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower() in ("1", "true", "yes")
from tests._pw_chromium import resolve_prebaked_chromium

_PINNED_CHROMIUM = resolve_prebaked_chromium()

_WEB_STATIC = _ROOT / "src" / "mediahub" / "web" / "static"
_THEME_COMPONENTS = _WEB_STATIC / "theme" / "theme-components.css"
_THEME_MOTION = _WEB_STATIC / "theme" / "theme-motion.css"
_UI_KIT_JS = _WEB_STATIC / "js" / "ui-kit.js"


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


# ── HTML helpers (mirror the client's own parsing where relevant) ──────────────


def _vanish_placeholders(html: str) -> list[str]:
    """The pipe-list the kit's bindVanish() would parse from the container."""
    m = re.search(r'data-mh-placeholders="([^"]*)"', html)
    assert m, "no data-mh-placeholders attribute rendered on the search"
    raw = _html.unescape(m.group(1))
    return [p.strip() for p in raw.split("|") if p.strip()]


def _overlay_text(html: str) -> str:
    m = re.search(r'<span class="mh-vanish__ph"[^>]*>([^<]*)</span>', html)
    assert m, "no .mh-vanish__ph overlay element rendered"
    return _html.unescape(m.group(1))


def _input_attr(html: str, attr: str):
    """Read one attribute off the #mh-activity-search input (either tag order)."""
    after = re.search(r'id="mh-activity-search"[^>]*?\s%s="([^"]*)"' % re.escape(attr), html)
    before = re.search(r'\s%s="([^"]*)"[^>]*?\sid="mh-activity-search"' % re.escape(attr), html)
    m = after or before
    return _html.unescape(m.group(1)) if m else None


# ── fixture ────────────────────────────────────────────────────────────────────


@pytest.fixture
def app_mod(app, web_module):
    """Isolated Flask app + one ready profile with one run (so /activity renders
    its search toolbar)."""
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="test-org",
            display_name="Test Org",
            brand_voice_summary="Testing.",
        )
    )

    # The /activity search toolbar only renders once the org has ≥1 run.
    conn = web_module._db()
    conn.execute(
        "INSERT INTO runs (id, created_at, finished_at, status, profile_id, "
        "meet_name, file_name, our_swims, n_cards, n_queue, n_achievements, error) "
        "VALUES ('run-1', datetime('now'), datetime('now'), 'done', 'test-org', "
        "'Spring Gala', 'spring.pdf', 3, 2, 1, 2, NULL)"
    )
    conn.commit()
    conn.close()
    return app, web_module


def _get(app, path: str) -> str:
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["active_profile_id"] = "test-org"
        r = c.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}"
        return r.get_data(as_text=True)


# ── server-side: the rendered search markup ────────────────────────────────────


class TestVanishSearchMarkup:
    def test_search_is_a_vanish_container(self, app_mod):
        """The box carries both .mh-search (icon/layout) and .mh-vanish (kit)."""
        app, _ = app_mod
        html = _get(app, "/activity")
        assert 'class="grow mh-search mh-vanish"' in html
        # The kit hook must sit on the SAME element that carries the list.
        assert re.search(
            r'class="grow mh-search mh-vanish"\s+data-mh-placeholders="', html
        ), "data-mh-placeholders not on the .mh-vanish container"

    def test_placeholders_parse_to_real_list(self, app_mod):
        app, _ = app_mod
        phrases = _vanish_placeholders(_get(app, "/activity"))
        assert len(phrases) >= 3, f"want ≥3 rotating phrases, got {phrases}"
        assert all(phrases), "an empty phrase slipped through"
        # The list genuinely guides the run search (meet / file / run-id facets).
        joined = " | ".join(phrases).lower()
        assert "run id" in joined
        assert any(".hy3" in p.lower() for p in phrases)

    def test_overlay_element_carries_first_phrase(self, app_mod):
        """The overlay ships the first phrase so the hint reads with no JS, and
        it matches list[0] so bindVanish()'s init causes no flash."""
        app, _ = app_mod
        html = _get(app, "/activity")
        phrases = _vanish_placeholders(html)
        assert _overlay_text(html) == phrases[0]
        # Decorative: the accessible name comes from aria-label, not this span.
        assert re.search(r'<span class="mh-vanish__ph" aria-hidden="true">', html)

    def test_native_placeholder_removed(self, app_mod):
        """UI2.6: the native placeholder shows no visible text (the overlay
        carries the real hint). A single space is used rather than "" so
        WebKit's :placeholder-shown still matches and hides the overlay on
        Safari — so accept whitespace-only, not strictly empty."""
        app, _ = app_mod
        html = _get(app, "/activity")
        assert _input_attr(html, "placeholder").strip() == "", "native placeholder not removed"

    def test_input_keeps_accessible_name(self, app_mod):
        """With the placeholder gone, an aria-label preserves the input's name."""
        app, _ = app_mod
        label = _input_attr(_get(app, "/activity"), "aria-label")
        assert label and label.strip(), "search input lost its accessible name"
        assert "search" in label.lower()

    def test_icon_and_filter_hook_preserved(self, app_mod):
        """The search icon and the #mh-activity-search id (the in-place filter
        JS binds to it) both survive the rewrite."""
        app, _ = app_mod
        html = _get(app, "/activity")
        assert '<circle cx="11" cy="11" r="7"/>' in html  # the search-glass icon
        assert 'id="mh-activity-search"' in html
        assert "document.getElementById('mh-activity-search')" in html  # filter JS

    def test_old_cycle_attribute_is_gone(self, app_mod):
        """The migrated field no longer carries the UI 1.1 cycle attribute, and
        the now-dead search-cycle constants were removed from the module. (The
        global cycle *binder* JS still ships in the layout for the other fields,
        so we check the attribute is gone from the search element itself, not
        that the selector string never appears anywhere on the page.)"""
        app, wm = app_mod
        html = _get(app, "/activity")
        assert _input_attr(html, "data-mh-cycle-placeholder") is None
        assert not hasattr(wm, "_CYCLE_PH_SEARCH")
        assert not hasattr(wm, "_CYCLE_PH_ATTR_SEARCH")


class TestVanishAttributeIntegrity:
    def test_attribute_is_xss_safe(self, app_mod):
        app, _ = app_mod
        html = _get(app, "/activity")
        m = re.search(r'data-mh-placeholders="([^"]*)"', html)
        assert m
        raw = m.group(1)
        # No literal double-quote / angle brackets that would break the tag.
        assert '"' not in raw and "<" not in raw and ">" not in raw

    def test_helper_round_trips(self, app_mod):
        _, wm = app_mod
        attr = wm._vanish_ph_attr(["A's pick", "B & C", "plain"])
        m = re.match(r'data-mh-placeholders="(.*)"$', attr)
        assert m, attr
        raw = m.group(1)
        assert "&" in raw  # the literal & got escaped
        phrases = [p.strip() for p in _html.unescape(raw).split("|") if p.strip()]
        assert phrases == ["A's pick", "B & C", "plain"]

    def test_constants_well_formed(self, app_mod):
        _, wm = app_mod
        const = wm._VANISH_PH_SEARCH
        assert len(const) >= 3
        assert all(isinstance(p, str) and p.strip() for p in const)
        assert all("|" not in p for p in const)  # the pipe is the delimiter


# ── static assets: JS + CSS ────────────────────────────────────────────────────


class TestVanishAssetsPresent:
    def test_kit_js_ships_and_binds(self, app_mod):
        """ui-kit.js loads in the shared shell, defines bindVanish, binds
        .mh-vanish, and reads the data-mh-placeholders list."""
        app, _ = app_mod
        page = _get(app, "/activity")
        assert "js/ui-kit.js" in page  # the loader tag is in the layout
        js = _UI_KIT_JS.read_text(encoding="utf-8")
        assert "function bindVanish" in js
        assert 'each(root, ".mh-vanish", bindVanish)' in js
        assert "data-mh-placeholders" in js
        assert ".mh-vanish__ph" in js

    def test_kit_css_ships_overlay_and_no_js_fallback(self):
        css = _THEME_MOTION.read_text(encoding="utf-8")
        assert ".mh-vanish__ph" in css
        assert ".mh-vanish.is-typing .mh-vanish__ph" in css
        # The no-JS / pre-init CSS fallback hides the overlay once the box holds
        # text, even if .is-typing never gets toggled.
        assert ":not(:placeholder-shown) ~ .mh-vanish__ph" in css

    def test_alignment_rule_clears_the_icon(self):
        """The overlay pad lines up with the input text (past the 36px icon
        gutter) — co-located with the .mh-search icon padding."""
        css = _THEME_COMPONENTS.read_text(encoding="utf-8")
        assert ".mh-toolbar .mh-search.mh-vanish" in css
        assert "--mh-vanish-pad: 36px" in css
        # The input's own padding-left is the gutter the pad must match.
        assert "padding-left: 36px" in css


# ── browser-side: real behaviour ───────────────────────────────────────────────


def _activity_page_assets(app):
    body = _get(app, "/activity")
    css = (
        _THEME_COMPONENTS.read_text(encoding="utf-8")
        + "\n"
        + _THEME_MOTION.read_text(encoding="utf-8")
    )
    js = _UI_KIT_JS.read_text(encoding="utf-8")
    return body, css, js


@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="prebaked chromium not found")
class TestVanishSearchBrowser:
    def test_overlay_rotates_through_phrases(self, app_mod):
        app, _ = app_mod
        body, css, js = _activity_page_assets(app)
        expected = set(app_mod[1]._VANISH_PH_SEARCH)

        pw, browser = _launch_browser()
        try:
            ctx = browser.new_context(reduced_motion="no-preference")
            page = ctx.new_page()
            page.set_content(body)
            page.add_style_tag(content=css)
            page.add_script_tag(content=js)  # runs bindVanish (readyState complete)
            # Sample the overlay text page-side (no round-trip lag) across two
            # rotation intervals (kit rotates every ~2.8s + 0.2s swap).
            page.evaluate(
                """() => {
                    window.__caps = [];
                    var ph = document.querySelector('.mh-vanish__ph');
                    window.__t = setInterval(function(){ window.__caps.push(ph.textContent); }, 150);
                }"""
            )
            page.wait_for_timeout(6500)
            caps = page.evaluate("() => { clearInterval(window.__t); return window.__caps; }")
        finally:
            browser.close()
            pw.stop()

        assert caps, "no overlay samples captured"
        distinct = {c for c in caps if c}
        assert len(distinct) >= 2, f"overlay did not rotate: {sorted(distinct)}"
        # Every value shown is a real, whole phrase from the list (never partial).
        assert distinct <= expected, f"unexpected overlay text: {distinct - expected}"

    def test_typing_hides_then_restores_overlay(self, app_mod):
        app, _ = app_mod
        body, css, js = _activity_page_assets(app)

        pw, browser = _launch_browser()
        try:
            ctx = browser.new_context(reduced_motion="no-preference")
            page = ctx.new_page()
            page.set_content(body)
            page.add_style_tag(content=css)
            page.add_script_tag(content=js)
            page.wait_for_timeout(80)
            before = page.eval_on_selector(".mh-vanish__ph", "el => getComputedStyle(el).opacity")
            page.fill("#mh-activity-search", "county finals")
            page.wait_for_timeout(350)  # let the opacity transition settle
            typing = page.eval_on_selector(".mh-vanish", "el => el.classList.contains('is-typing')")
            during = page.eval_on_selector(".mh-vanish__ph", "el => getComputedStyle(el).opacity")
            page.fill("#mh-activity-search", "")
            page.wait_for_timeout(350)
            after = page.eval_on_selector(".mh-vanish__ph", "el => getComputedStyle(el).opacity")
        finally:
            browser.close()
            pw.stop()

        assert float(before) > 0.5, "overlay should be visible when the box is empty"
        assert typing is True, "the .is-typing JS state was not set on input"
        assert float(during) < 0.05, "overlay should hide while typing"
        assert float(after) > 0.5, "overlay should return when the box is cleared"

    def test_reduced_motion_freezes_first_phrase(self, app_mod):
        app, _ = app_mod
        body, css, js = _activity_page_assets(app)
        first = app_mod[1]._VANISH_PH_SEARCH[0]

        pw, browser = _launch_browser()
        try:
            ctx = browser.new_context(reduced_motion="reduce")
            page = ctx.new_page()
            page.set_content(body)
            page.add_style_tag(content=css)
            page.add_script_tag(content=js)
            page.wait_for_timeout(3500)  # longer than a rotation interval
            text = page.eval_on_selector(".mh-vanish__ph", "el => el.textContent")
            opacity = page.eval_on_selector(".mh-vanish__ph", "el => getComputedStyle(el).opacity")
        finally:
            browser.close()
            pw.stop()

        assert text == first, f"reduced-motion overlay rotated: {text!r}"
        assert float(opacity) > 0.5, "overlay should still show its hint statically"

    def test_no_kit_js_css_fallback_hides_overlay(self, app_mod):
        """With the kit JS absent (load failure / pre-init), the CSS-only
        :placeholder-shown rule still hides the overlay the moment the box holds
        text — proven by .is-typing staying *off* throughout."""
        app, _ = app_mod
        body, css, _js = _activity_page_assets(app)

        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(body)
            page.add_style_tag(content=css)  # CSS only — bindVanish never injected
            page.wait_for_timeout(80)
            before = page.eval_on_selector(".mh-vanish__ph", "el => getComputedStyle(el).opacity")
            typing_before = page.eval_on_selector(
                ".mh-vanish", "el => el.classList.contains('is-typing')"
            )
            page.fill("#mh-activity-search", "county finals")
            page.wait_for_timeout(350)
            after = page.eval_on_selector(".mh-vanish__ph", "el => getComputedStyle(el).opacity")
            typing_after = page.eval_on_selector(
                ".mh-vanish", "el => el.classList.contains('is-typing')"
            )
        finally:
            browser.close()
            pw.stop()

        assert float(before) > 0.5, "overlay should show when empty (no-JS path)"
        assert typing_before is False, "no kit JS, so .is-typing must not be set"
        assert float(after) < 0.05, "CSS :placeholder-shown fallback did not hide it"
        assert typing_after is False, "fallback must be CSS-only, not the JS class"

    def test_overlay_aligns_past_search_icon(self, app_mod):
        app, _ = app_mod
        body, css, js = _activity_page_assets(app)

        pw, browser = _launch_browser()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.set_content(body)
            page.add_style_tag(content=css)
            page.add_script_tag(content=js)
            page.wait_for_timeout(80)
            geo = page.evaluate(
                """() => {
                    var ph = document.querySelector('.mh-vanish__ph');
                    var icon = document.querySelector('.mh-search.mh-vanish svg');
                    return {
                        ph: ph.getBoundingClientRect().left,
                        iconRight: icon.getBoundingClientRect().right,
                    };
                }"""
            )
        finally:
            browser.close()
            pw.stop()

        # The rotating placeholder starts to the right of the search icon, so the
        # two never overlap.
        assert (
            geo["ph"] >= geo["iconRight"]
        ), f"overlay (left={geo['ph']}) overlaps the icon (right={geo['iconRight']})"
