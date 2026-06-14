"""tests/test_u16_card_tilt.py — U.16 subtle 3D tilt on the sample output cards.

Roadmap U.16 (Phase 1, product polish): a premium parallax/tilt-on-hover for the
landing-page sample output cards, inspired by atlascard.com — CSS perspective +
JS pointer-tracking, respecting ``prefers-reduced-motion``. Presentation-only:
the deterministic engine, the AI surfaces and the explainability logic are all
untouched.

The effect is split deliberately so it can never get "stuck":
  * the tilt + lift transform is written by JS as an *inline* style, so it wins
    over the reveal-group's own ``transform`` without a specificity fight;
  * CSS owns the cursor-tracked sheen (``.mh-sample::before``), the lifted
    stacking order, and the reduced-motion / no-hover no-op;
  * the JS never binds under ``prefers-reduced-motion`` or on touch / no-hover
    pointers, so those visitors keep the flat, static card.

Four layers of assertion:
  1. CSS contract (``theme-components.css``).
  2. JS contract (``web.py`` source — the ``MH.bindCardTilt`` binder).
  3. Rendered home page (the three sample cards + the tilt CSS/JS ship inline).
  4. Browser behaviour (Playwright + the pinned Chromium build; skips when
     absent) — the tilt really tracks the pointer and settles, and never
     engages under ``prefers-reduced-motion``.

The Playwright layer mirrors the gating/launch pattern of
``tests/test_activity_count_up.py`` (the U.12 count-up sibling).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from mediahub.web import web as webmod
from mediahub.web.theme_tokens import THEME_COMPONENTS_CSS


# --------------------------------------------------------------------------- #
# Browser-test gating (mirrors tests/test_activity_count_up.py)
# --------------------------------------------------------------------------- #
_SKIP_BROWSER = (
    os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower()
    in ("1", "true", "yes")
)
_PINNED_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")


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


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(webmod, "RUNS_DIR", runs, raising=False)
    app = webmod.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(scope="module")
def components_css() -> str:
    return THEME_COMPONENTS_CSS


@pytest.fixture(scope="module")
def web_src() -> str:
    return Path(webmod.__file__).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def tilt_js(web_src) -> str:
    """The body of the MH.bindCardTilt binder — sliced so each assertion is
    scoped to the new code, not an unrelated coincidence elsewhere in web.py."""
    start = web_src.index("function bindCardTilt()")
    end = web_src.index("MH.bindCardTilt = bindCardTilt;", start)
    return web_src[start:end]


def _home(client) -> str:
    resp = client.get("/")
    assert resp.status_code == 200, f"/ → {resp.status_code}"
    return resp.get_data(as_text=True)


# =========================================================================== #
# Layer 1 — CSS contract (theme-components.css)
# =========================================================================== #
class TestTiltCss:
    def test_sheen_pseudo_element_exists(self, components_css):
        assert ".mh-sample::before" in components_css

    def test_sheen_follows_pointer_via_custom_props(self, components_css):
        # The sheen centre rides --mh-gx/--mh-gy (set inline by the binder).
        assert "radial-gradient(circle at var(--mh-gx" in components_css
        assert "var(--mh-gy" in components_css

    def test_sheen_is_inert_and_hidden_at_rest(self, components_css):
        # Pull the ::before block out and check it's non-interactive + invisible
        # until the card is being tilted.
        block = re.search(
            r"\.mh-sample::before\s*\{(.*?)\}", components_css, re.DOTALL
        )
        assert block, "no .mh-sample::before rule"
        body = block.group(1)
        assert "pointer-events: none" in body      # never eats clicks
        assert "opacity: 0" in body                 # hidden at rest
        assert "transition: opacity" in body        # fades, not pops

    def test_sheen_lights_only_while_tilting(self, components_css):
        assert ".mh-sample.is-tilting::before" in components_css
        m = re.search(
            r"\.mh-sample\.is-tilting::before\s*\{([^}]*)\}", components_css
        )
        assert m and "opacity: 1" in m.group(1)

    def test_tilting_card_lifts_stacking_and_hints_compositor(self, components_css):
        m = re.search(
            r"\.mh-sample\.is-tilting\s*\{([^}]*)\}", components_css
        )
        assert m, "no .mh-sample.is-tilting rule"
        body = m.group(1)
        assert "z-index" in body                    # rises above its neighbours
        assert "will-change: transform" in body     # promoted while active

    def test_reduced_motion_kills_the_sheen(self, components_css):
        # There must be a reduced-motion block that disables the sheen entirely.
        assert "prefers-reduced-motion: reduce" in components_css
        blocks = re.findall(
            r"@media \(prefers-reduced-motion: reduce\)\s*\{(.*?\.mh-sample.*?)\}\s*\}",
            components_css,
            re.DOTALL,
        )
        joined = "\n".join(blocks)
        assert ".mh-sample::before" in joined and "display: none" in joined, (
            "reduced-motion must hide .mh-sample::before"
        )

    def test_corner_mark_stays_above_the_sheen(self, components_css):
        # The lane corner-mark (::after) must sit above the sheen (::before) so
        # the brand accent stays crisp; both are inside the same card.
        after = re.search(r"\.mh-sample::after\s*\{([^}]*)\}", components_css)
        assert after and "z-index: 3" in after.group(1)

    def test_components_css_braces_balanced(self, components_css):
        assert components_css.count("{") == components_css.count("}")


# =========================================================================== #
# Layer 2 — JS contract (web.py: MH.bindCardTilt)
# =========================================================================== #
class TestTiltJs:
    def test_binder_is_defined_and_exported(self, web_src):
        assert "function bindCardTilt()" in web_src
        assert "MH.bindCardTilt = bindCardTilt;" in web_src

    def test_binder_runs_on_dom_ready(self, web_src):
        assert "document.addEventListener('DOMContentLoaded', bindCardTilt)" in web_src

    def test_reduced_motion_short_circuits(self, tilt_js):
        # First statement of the binder is the reduced-motion bail-out.
        assert "if (prefersReduced) return;" in tilt_js

    def test_gated_to_fine_hover_pointers(self, tilt_js):
        assert "(hover: hover) and (pointer: fine)" in tilt_js

    def test_touch_pointer_is_ignored(self, tilt_js):
        # Touch never tilts even if a hybrid device slips past the media gate.
        assert "pointerType === 'touch'" in tilt_js

    def test_targets_sample_cards_and_generic_opt_in(self, tilt_js):
        assert ".mh-sample, [data-mh-tilt]" in tilt_js

    def test_uses_css_perspective_tilt(self, tilt_js):
        assert "perspective(900px)" in tilt_js
        assert "rotateX(" in tilt_js
        assert "rotateY(" in tilt_js
        assert "scale(1.02)" in tilt_js     # the subtle premium lift-scale

    def test_pointer_tracking_is_raf_throttled(self, tilt_js):
        assert "requestAnimationFrame(apply)" in tilt_js
        assert "cancelAnimationFrame" in tilt_js

    def test_binds_pointer_lifecycle(self, tilt_js):
        for ev in ("pointerenter", "pointermove", "pointerleave"):
            assert f"addEventListener('{ev}'" in tilt_js, f"missing {ev} handler"

    def test_toggles_is_tilting_class(self, tilt_js):
        assert "classList.add('is-tilting')" in tilt_js
        assert "classList.remove('is-tilting')" in tilt_js

    def test_drives_the_sheen_position(self, tilt_js):
        assert "setProperty('--mh-gx'" in tilt_js
        assert "setProperty('--mh-gy'" in tilt_js

    def test_settles_back_to_rest_on_leave(self, tilt_js):
        # Leaving the card hands it back a defined rest transform (never stuck
        # askew) and clears the sheen vars.
        assert "TILT_REST" in tilt_js
        assert "removeProperty('--mh-gx')" in tilt_js
        assert "removeProperty('--mh-gy')" in tilt_js


# =========================================================================== #
# Layer 3 — rendered home page ships the cards + the inline CSS/JS
# =========================================================================== #
class TestHomePageWiring:
    def test_three_sample_cards_render(self, client):
        body = _home(client)
        assert "mh-sample story" in body
        assert "mh-sample feed" in body
        assert "mh-sample reel" in body

    def test_tilt_css_is_inlined(self, client):
        body = _home(client)
        # The component CSS rides BASE_CSS into the inline <style> block.
        assert ".mh-sample::before" in body
        assert ".mh-sample.is-tilting" in body
        assert "radial-gradient(circle at var(--mh-gx" in body

    def test_tilt_js_is_inlined(self, client):
        body = _home(client)
        assert "function bindCardTilt()" in body
        assert "MH.bindCardTilt = bindCardTilt;" in body
        assert "(hover: hover) and (pointer: fine)" in body

    def test_reduced_motion_guard_ships_on_page(self, client):
        body = _home(client)
        assert "prefers-reduced-motion: reduce" in body
        assert "if (prefersReduced) return;" in body


# =========================================================================== #
# Layer 4 — real browser behaviour (Playwright + pinned Chromium)
# =========================================================================== #
@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="chromium-1194 not at pinned path")
class TestTiltBrowserBehaviour:
    """Drive the inline tilt JS in a real Chromium and prove it tracks the
    pointer, settles to rest, and stands down under prefers-reduced-motion."""

    # JS injected once per page: dispatches mouse-type pointer events at a
    # fractional position inside the first sample card and exposes helpers.
    _SETUP = """() => {
      var card = document.querySelector('.mh-sample');
      if (!card) return {error: 'no .mh-sample'};
      window.__card = card;
      window.__move = function(fx, fy) {
        var r = card.getBoundingClientRect();
        card.dispatchEvent(new PointerEvent('pointerenter', {pointerType:'mouse', bubbles:true}));
        card.dispatchEvent(new PointerEvent('pointermove', {
          pointerType:'mouse', bubbles:true,
          clientX: r.left + r.width * fx, clientY: r.top + r.height * fy
        }));
      };
      window.__leave = function() {
        card.dispatchEvent(new PointerEvent('pointerleave', {pointerType:'mouse', bubbles:true}));
      };
      var r = card.getBoundingClientRect();
      return {w: r.width, h: r.height, hasBinder: typeof window.MH.bindCardTilt === 'function'};
    }"""

    @staticmethod
    def _rot(transform: str, axis: str) -> float:
        m = re.search(rf"rotate{axis}\(([-\d.]+)deg\)", transform)
        assert m, f"no rotate{axis} in {transform!r}"
        return float(m.group(1))

    def test_tilt_tracks_pointer_and_settles(self, client):
        body = _home(client)
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(body)
            page.wait_for_load_state("domcontentloaded")

            info = page.evaluate(self._SETUP)
            assert "error" not in info, info
            assert info["w"] > 0 and info["h"] > 0
            assert info["hasBinder"], "MH.bindCardTilt never defined (IIFE threw?)"

            # --- Pointer near the TOP-LEFT: top edge tilts back (rotateX > 0),
            #     left edge tilts toward us (rotateY < 0). ---------------------
            page.evaluate("() => window.__move(0.15, 0.15)")
            page.wait_for_function(
                "() => window.__card.style.transform.indexOf('perspective(') !== -1"
            )
            t1 = page.evaluate("() => window.__card.style.transform")
            assert "perspective(900px)" in t1
            assert "scale(1.02)" in t1                      # lifted + scaled
            assert self._rot(t1, "X") > 0.5, t1
            assert self._rot(t1, "Y") < -0.5, t1

            # The card is marked active, the sheen is live + positioned.
            state = page.evaluate(r"""() => {
              var c = window.__card;
              return {
                tilting: c.classList.contains('is-tilting'),
                gx: c.style.getPropertyValue('--mh-gx'),
                gy: c.style.getPropertyValue('--mh-gy'),
                sheen: getComputedStyle(c, '::before').display
              };
            }""")
            assert state["tilting"] is True
            assert state["gx"] and state["gy"], state    # sheen centre set inline
            assert state["sheen"] != "none"              # sheen is rendered

            # --- Pointer near the BOTTOM-RIGHT: both rotations flip sign. ----
            page.evaluate("() => window.__move(0.85, 0.85)")
            page.wait_for_function(
                r"() => { var m = window.__card.style.transform.match(/rotateY\(([-\d.]+)deg\)/);"
                r" return m && parseFloat(m[1]) > 0; }"
            )
            t2 = page.evaluate("() => window.__card.style.transform")
            assert self._rot(t2, "X") < -0.5, t2
            assert self._rot(t2, "Y") > 0.5, t2

            # --- Leave: settle to a defined rest, drop the class + sheen vars. -
            page.evaluate("() => window.__leave()")
            page.wait_for_function(
                "() => window.__card.style.transform.indexOf('rotateX(0deg) rotateY(0deg)') !== -1"
            )
            t3 = page.evaluate("() => window.__card.style.transform")
            assert "rotateX(0deg) rotateY(0deg)" in t3
            assert "scale(1)" in t3 and "scale(1.02)" not in t3
            rest = page.evaluate(r"""() => {
              var c = window.__card;
              return {
                tilting: c.classList.contains('is-tilting'),
                gx: c.style.getPropertyValue('--mh-gx'),
                gy: c.style.getPropertyValue('--mh-gy')
              };
            }""")
            assert rest["tilting"] is False
            assert rest["gx"] == "" and rest["gy"] == ""   # sheen vars cleared
        finally:
            browser.close()
            pw.stop()

    def test_no_tilt_under_reduced_motion(self, client):
        body = _home(client)
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            # Set BEFORE the document's script runs so the binder sees `reduce`
            # at evaluation time and stands down.
            page.emulate_media(reduced_motion="reduce")
            page.set_content(body)
            page.wait_for_load_state("domcontentloaded")

            assert page.evaluate(
                "() => matchMedia('(prefers-reduced-motion: reduce)').matches"
            ), "reduced-motion emulation did not take"

            info = page.evaluate(self._SETUP)
            assert info.get("hasBinder"), "MH.bindCardTilt should still exist"

            # Move the pointer the same way — the binder never attached, so
            # nothing tilts and the sheen is removed by CSS.
            page.evaluate("() => window.__move(0.15, 0.15)")
            page.wait_for_timeout(150)   # generous: any stray rAF would fire
            out = page.evaluate(r"""() => {
              var c = window.__card;
              return {
                transform: c.style.transform,
                tilting: c.classList.contains('is-tilting'),
                sheen: getComputedStyle(c, '::before').display
              };
            }""")
            assert out["transform"] == "", out      # no inline tilt at all
            assert out["tilting"] is False
            assert out["sheen"] == "none"           # CSS no-op hides the sheen
        finally:
            browser.close()
            pw.stop()
