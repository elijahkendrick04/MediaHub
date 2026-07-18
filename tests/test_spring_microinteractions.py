"""tests/test_spring_microinteractions.py — UI 1.4 tactile spring-physics layer.

UI 1.4 (roadmap, Phase 1 — Product polish, *inspired by Family*) adds a
restrained spring-physics micro-interaction layer to the surfaces a club
actually presses — primary buttons, selectable cards, and toggles — as a
subtle magnetic pull toward the cursor on hover plus a bouncy release on
press. It is vanilla JS driving CSS custom properties, must respect
``prefers-reduced-motion``, and must stay understated to preserve the
editorial tone.

Three layers of assertion, mirroring tests/test_theme_cascade.py (CSS
contract), tests/test_responsive_meta.py (server render) and
tests/test_activity_count_up.py (Playwright behaviour):

  1. CSS contract — the ``.mh-spring`` composition lives in
     THEME_COMPONENTS_CSS, is built from the three custom properties,
     is gated behind ``prefers-reduced-motion: no-preference``, and never
     transitions ``transform`` (the JS spring owns it).
  2. Server render — every page ships the ``bindSpring()`` engine inline,
     gated on the shared ``prefersReduced`` flag + PointerEvent/rAF, with
     the magnetic, press, keyboard and toggle handlers and the documented
     target selector.
  3. Browser behaviour — under a fine pointer with motion allowed, primary
     buttons / template cards / toggle labels actually get ``.mh-spring``;
     pressing dips the rendered scale and releasing springs it back; a
     magnetic move shifts the rendered translation toward the cursor and
     leaving returns it. Under ``prefers-reduced-motion: reduce`` nothing
     binds at all.

The Playwright class skips when Playwright or a usable Chromium build is
absent, matching tests/test_activity_count_up.py.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def components_css() -> str:
    from mediahub.web.theme_tokens import THEME_COMPONENTS_CSS

    return THEME_COMPONENTS_CSS


@pytest.fixture(scope="module")
def spring_css(components_css: str) -> str:
    """Just the UI 1.4 spring section, sliced from its banner to EOF."""
    marker = "UI 1.4 — TACTILE SPRING-PHYSICS MICRO-INTERACTIONS"
    idx = components_css.find(marker)
    assert idx != -1, "UI 1.4 spring banner missing from theme-components.css"
    return components_css[idx:]


# Public, always-reachable HTML routes (no org gate). The spring engine lives
# in the shared _layout, so it must ship on every one of them.
_PUBLIC_HTML_ROUTES = ["/", "/login", "/pricing", "/try", "/status"]


# ---------------------------------------------------------------------------
# 1 — CSS contract (THEME_COMPONENTS_CSS)
# ---------------------------------------------------------------------------


class TestSpringCssContract:
    def test_section_present(self, spring_css):
        assert ".mh-spring" in spring_css

    def test_seeds_all_three_custom_properties(self, spring_css):
        # Defaults so the composition resolves on the first frame.
        for prop in ("--mh-press:", "--mh-mag-x:", "--mh-mag-y:"):
            assert prop in spring_css, f"missing default for {prop}"

    def test_declares_magnetic_pull_ceiling(self, spring_css):
        assert "--mh-mag-pull:" in spring_css, "missing the restrained pull cap token"

    def test_composed_transform(self, spring_css):
        # One transform owner: magnetic translate + press scale.
        assert "translate3d(var(--mh-mag-x" in spring_css
        assert "scale(var(--mh-press" in spring_css

    def test_gated_behind_no_preference(self, spring_css):
        # The whole composition is OFF under reduced motion.
        assert "@media (prefers-reduced-motion: no-preference)" in spring_css

    def test_transform_rule_inside_no_preference_block(self, spring_css):
        # The transform: composition must sit *inside* the no-preference media
        # block, not leak out of it.
        pattern = re.compile(
            r"@media\s*\(prefers-reduced-motion:\s*no-preference\)\s*\{"
            r".*?transform:\s*\n?\s*translate3d\(var\(--mh-mag-x",
            re.DOTALL,
        )
        assert pattern.search(
            spring_css
        ), "composed transform is not inside the no-preference media block"

    def test_hover_active_specificity_variants(self, spring_css):
        # :hover / :active variants raise specificity so the JS keeps ownership
        # of the transform over .btn:hover / .btn:active / .mh-template:hover.
        assert ".mh-js .mh-spring:hover" in spring_css
        assert ".mh-js .mh-spring:active" in spring_css

    def test_transform_is_not_transitioned(self, spring_css):
        # The JS spring is the animation; a CSS transform transition would
        # fight the per-frame writes. The spring rule's transition list must
        # therefore exclude `transform`.
        m = re.search(r"transition:\s*([^;]+);", spring_css, re.DOTALL)
        assert m, "spring rule declares no transition list"
        transition = m.group(1)
        assert "background" in transition, "expected colour/shadow feedback to transition"
        assert (
            "transform" not in transition
        ), "transform must NOT be transitioned — the JS spring owns it"

    def test_components_css_braces_balanced(self, components_css):
        assert components_css.count("{") == components_css.count(
            "}"
        ), "unbalanced braces in theme-components.css after the spring section"

    def test_in_assembled_cascade_before_guardrails(self):
        """The spring CSS must be inside the assembled BASE_CSS, ahead of the
        responsive guardrails (which must remain the final layer)."""
        import mediahub.web.web as wm
        from mediahub.web.responsive_guardrails import RESPONSIVE_GUARDRAILS_CSS

        assert ".mh-spring" in wm.BASE_CSS
        spring_at = wm.BASE_CSS.find("UI 1.4 — TACTILE SPRING-PHYSICS")
        guardrails_at = wm.BASE_CSS.find(RESPONSIVE_GUARDRAILS_CSS[:200])
        assert spring_at != -1 and guardrails_at != -1
        assert spring_at < guardrails_at, "spring layer must precede the guardrails"


# ---------------------------------------------------------------------------
# 2 — Server render contract (inline JS ships on every page)
# ---------------------------------------------------------------------------


class TestSpringJsShips:
    @pytest.mark.parametrize("route", _PUBLIC_HTML_ROUTES)
    def test_engine_present(self, client, route):
        body = client.get(route).get_data(as_text=True)
        assert "function bindSpring()" in body, f"bindSpring missing on {route}"
        assert "MH.bindSpring = bindSpring;" in body, f"not exposed on {route}"

    def test_reduced_motion_early_return(self, client):
        body = client.get("/").get_data(as_text=True)
        # Reuses the shared prefersReduced flag the reveals/counters use.
        assert "if (prefersReduced) return;" in body

    def test_capability_guards(self, client):
        body = client.get("/").get_data(as_text=True)
        assert "'PointerEvent' in window" in body
        assert "'requestAnimationFrame' in window" in body

    def test_fine_pointer_only_magnetic(self, client):
        body = client.get("/").get_data(as_text=True)
        assert "(hover: hover) and (pointer: fine)" in body

    def test_writes_all_three_custom_properties(self, client):
        body = client.get("/").get_data(as_text=True)
        for prop in ("'--mh-press'", "'--mh-mag-x'", "'--mh-mag-y'"):
            assert prop in body, f"JS never writes {prop}"

    def test_magnetic_tracks_pointer(self, client):
        body = client.get("/").get_data(as_text=True)
        assert "pointermove" in body
        assert "getBoundingClientRect" in body
        assert "pointerleave" in body

    def test_press_and_release_handlers(self, client):
        body = client.get("/").get_data(as_text=True)
        assert "pointerdown" in body
        assert "pointerup" in body
        assert "pointercancel" in body

    def test_keyboard_parity(self, client):
        body = client.get("/").get_data(as_text=True)
        assert "keydown" in body and "keyup" in body
        assert "'Enter'" in body and "'Spacebar'" in body

    def test_toggle_pop_and_has_fallback(self, client):
        body = client.get("/").get_data(as_text=True)
        # Toggles bind the label and "pop" on change; :has() is wrapped so old
        # engines fall back to the explicit .mh-choice labels.
        assert "label:has(> input[type=checkbox])" in body
        assert "'change'" in body

    def test_target_selector_covers_named_surfaces(self, client):
        body = client.get("/").get_data(as_text=True)
        # primary buttons (not secondary/ghost/danger), template cards, opt-in,
        # and toggle labels — the three surfaces the roadmap names.
        assert ".btn:not(.secondary):not(.ghost):not(.danger)" in body
        assert ".mh-template" in body
        assert "[data-mh-spring]" in body
        assert "label.mh-choice" in body

    def test_progressive_enhancement_gate_present(self, client):
        body = client.get("/").get_data(as_text=True)
        # The .mh-spring CSS is gated on html.mh-js — set by the early script.
        assert "classList.add('mh-js')" in body


# ---------------------------------------------------------------------------
# 3 — Browser behaviour (Playwright, skip-guarded)
# ---------------------------------------------------------------------------

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


def _browser_available() -> bool:
    if _SKIP_BROWSER or not _playwright_available():
        return False
    if _PINNED_CHROMIUM.is_file():
        return True
    # Fall back to whatever Chromium Playwright resolves (no launch needed).
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            ep = p.chromium.executable_path
        return bool(ep) and Path(ep).is_file()
    except Exception:
        return False


def _launch(pw):
    kw = dict(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    if _PINNED_CHROMIUM.is_file():
        return pw.chromium.launch(executable_path=str(_PINNED_CHROMIUM), **kw)
    return pw.chromium.launch(**kw)


# The primary-button selector the engine binds (mirrors SEL_FULL in web.py).
_PRIMARY_BTN = ".btn:not(.secondary):not(.ghost):not(.danger):not(.mh-wf-approve):not(.loading)"

# Reads the *rendered* transform (proves JS prop -> CSS composition end to end):
# DOMMatrix.a = scaleX, .e = translateX(px), .f = translateY(px). Works for both
# matrix() and matrix3d() forms.
_READ_MATRIX = """(sel) => {
  var el = document.querySelector(sel);
  if (!el) return null;
  var m = new DOMMatrix(getComputedStyle(el).transform);
  return { a: m.a, e: m.e, f: m.f, cls: el.className };
}"""


@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _browser_available(), reason="no usable Chromium build")
class TestSpringBrowser:
    def _home_html(self, client) -> str:
        resp = client.get("/")
        assert resp.status_code == 200
        return resp.get_data(as_text=True)

    def test_primary_surfaces_get_bound(self, client):
        """Under a fine pointer with motion allowed, the engine adds .mh-spring
        to a primary button and a template card."""
        from playwright.sync_api import sync_playwright

        html = self._home_html(client)
        pw = sync_playwright().start()
        browser = _launch(pw)
        try:
            page = browser.new_page()
            page.emulate_media(reduced_motion="no-preference")
            page.set_content(html)
            page.wait_for_timeout(250)  # let DOMContentLoaded + bindSpring run
            btn = page.evaluate(_READ_MATRIX, _PRIMARY_BTN)
            tpl = page.evaluate(_READ_MATRIX, ".mh-template")
            assert btn is not None, "no primary .btn on the page"
            assert "mh-spring" in btn["cls"], "primary button was not spring-bound"
            if tpl is not None:
                assert "mh-spring" in tpl["cls"], "template card was not spring-bound"
        finally:
            browser.close()
            pw.stop()

    def test_press_dips_then_springs_back(self, client):
        """pointerdown dips the rendered scale below 1; pointerup returns it."""
        from playwright.sync_api import sync_playwright

        html = self._home_html(client)
        pw = sync_playwright().start()
        browser = _launch(pw)
        try:
            page = browser.new_page()
            page.emulate_media(reduced_motion="no-preference")
            page.set_content(html)
            page.wait_for_timeout(250)

            # Press and hold — the scale target is 0.94, so it must dip < 1.
            page.evaluate(
                """(sel) => {
                    var el = document.querySelector(sel);
                    el.dispatchEvent(new PointerEvent('pointerdown',
                        {bubbles: true, pointerType: 'mouse'}));
                }""",
                _PRIMARY_BTN,
            )
            page.wait_for_timeout(140)
            pressed = page.evaluate(_READ_MATRIX, _PRIMARY_BTN)

            # Release — the underdamped spring returns toward scale 1.
            page.evaluate(
                """(sel) => {
                    var el = document.querySelector(sel);
                    el.dispatchEvent(new PointerEvent('pointerup',
                        {bubbles: true, pointerType: 'mouse'}));
                }""",
                _PRIMARY_BTN,
            )
            page.wait_for_timeout(600)
            settled = page.evaluate(_READ_MATRIX, _PRIMARY_BTN)
        finally:
            browser.close()
            pw.stop()

        assert pressed["a"] < 0.999, f"press did not dip the scale (a={pressed['a']})"
        assert pressed["a"] > 0.85, f"press dip is a squash, not restrained (a={pressed['a']})"
        assert settled["a"] > 0.99, f"scale did not spring back (a={settled['a']})"

    def test_magnetic_pull_tracks_then_releases(self, client):
        """A pointermove offset to the right pulls the element right (bounded by
        the restrained cap); pointerleave returns it to centre."""
        from playwright.sync_api import sync_playwright

        html = self._home_html(client)
        pw = sync_playwright().start()
        browser = _launch(pw)
        try:
            page = browser.new_page()
            page.emulate_media(reduced_motion="no-preference")
            page.set_content(html)
            page.wait_for_timeout(250)

            page.evaluate(
                """(sel) => {
                    var el = document.querySelector(sel);
                    var r = el.getBoundingClientRect();
                    // Cursor at the far right edge -> pull toward +x.
                    el.dispatchEvent(new PointerEvent('pointermove', {
                        bubbles: true, pointerType: 'mouse',
                        clientX: r.right, clientY: r.top + r.height / 2,
                    }));
                }""",
                _PRIMARY_BTN,
            )
            page.wait_for_timeout(220)
            pulled = page.evaluate(_READ_MATRIX, _PRIMARY_BTN)

            page.evaluate(
                """(sel) => {
                    var el = document.querySelector(sel);
                    el.dispatchEvent(new PointerEvent('pointerleave',
                        {bubbles: true, pointerType: 'mouse'}));
                }""",
                _PRIMARY_BTN,
            )
            page.wait_for_timeout(600)
            released = page.evaluate(_READ_MATRIX, _PRIMARY_BTN)
        finally:
            browser.close()
            pw.stop()

        assert pulled["e"] > 0.5, f"no magnetic pull toward cursor (e={pulled['e']})"
        # Restrained: the pull never exceeds the ~5px ceiling (+ a little slack).
        assert pulled["e"] <= 6.5, f"magnetic pull exceeds the restrained cap (e={pulled['e']})"
        assert abs(released["e"]) < 0.6, f"did not return to centre (e={released['e']})"

    def test_reduced_motion_binds_nothing(self, client):
        """Under prefers-reduced-motion: reduce, bindSpring() returns early and
        no surface gets .mh-spring — the press/magnetic layer is fully off."""
        from playwright.sync_api import sync_playwright

        html = self._home_html(client)
        pw = sync_playwright().start()
        browser = _launch(pw)
        try:
            page = browser.new_page()
            page.emulate_media(reduced_motion="reduce")
            page.set_content(html)
            page.wait_for_timeout(250)
            btn = page.evaluate(_READ_MATRIX, _PRIMARY_BTN)
        finally:
            browser.close()
            pw.stop()

        assert btn is not None, "no primary .btn on the page"
        assert "mh-spring" not in btn["cls"], "spring bound despite prefers-reduced-motion: reduce"

    def test_toggle_label_is_bound(self, client):
        """A toggle (label wrapping a checkbox / radio, or .mh-choice) is
        spring-bound for the press-pop, when one is present on the page."""
        from playwright.sync_api import sync_playwright

        html = self._home_html(client)
        pw = sync_playwright().start()
        browser = _launch(pw)
        try:
            page = browser.new_page()
            page.emulate_media(reduced_motion="no-preference")
            page.set_content(html)
            page.wait_for_timeout(250)
            info = page.evaluate(
                """() => {
                    var el = document.querySelector(
                        'label.mh-choice, label:has(> input[type=checkbox]), '
                        + 'label:has(> input[type=radio])');
                    return el ? { found: true, bound: el.classList.contains('mh-spring') }
                              : { found: false };
                }"""
            )
        finally:
            browser.close()
            pw.stop()

        if info.get("found"):
            assert info["bound"], "toggle label present but not spring-bound"
