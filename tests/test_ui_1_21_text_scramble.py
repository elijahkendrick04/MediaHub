"""tests/test_ui_1_21_text_scramble.py — UI 1.21 text-scramble / decode animation.

Roadmap **UI 1.21** (Phase 1 product polish, inspired by Locomotive): a
character-by-character scramble-then-decode reveal for the "engine is
generating…" processing state and an optional hero headline reveal. Vanilla
JS, ``prefers-reduced-motion`` respected, no new dependency.

The effect is first-party in ``static/js/ui-kit.js`` (the existing
progressive-enhancement layer) + ``static/theme/theme-motion.css``:

  * declarative ``<h1 class="mh-scramble">…</h1>`` decodes in once on reveal
    (the ``/upload`` hero and the processing page's ``Processing run`` H1);
  * imperative ``MH.scrambleTo(el, "new text")`` decodes *to* a new string —
    the processing poller drives the live ``#mh-current-stage`` label through
    it as each pipeline stage arrives (the core "engine is generating…" state).

Two tiers, matching tests/test_ui_cycle_placeholder.py:

  1. **Server-side** — the JS/CSS ship the feature (with its reduced-motion
     guard and its XSS-safe text-node implementation), the static asset is
     served, and every wired surface carries the right markup.
  2. **Browser-side** (Playwright) — the text actually flickers then settles to
     the exact final string, markup (``<br>``/``<em>``) survives, the a11y name
     stays correct, and reduced motion freezes it to the final text.

The Playwright tier skips when Playwright or the pinned Chromium build is
absent, mirroring tests/test_ui_cycle_placeholder.py.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.web import web as webmod  # noqa: E402

_SKIP_BROWSER = os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower() in ("1", "true", "yes")
_PINNED_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")

_STATIC_DIR = Path(webmod.__file__).resolve().parent / "static"
_UIKIT_PATH = _STATIC_DIR / "js" / "ui-kit.js"
_UIKIT_SRC = _UIKIT_PATH.read_text(encoding="utf-8")
_MOTION_CSS_PATH = _STATIC_DIR / "theme" / "theme-motion.css"


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401

        return True
    except ImportError:
        return False


def _chromium_available() -> bool:
    return _PINNED_CHROMIUM.is_file()


# --------------------------------------------------------------------------- #
# Fixtures (modelled on tests/test_u2_states.py)
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(webmod, "RUNS_DIR", runs, raising=False)
    # DB_PATH is a module constant resolved from DATA_DIR at import — repoint it
    # so each test gets its own SQLite file (the processing page reads the DB)
    # and create the schema in it.
    monkeypatch.setattr(webmod, "DB_PATH", tmp_path / "data.db", raising=False)
    webmod._init_db()
    app = webmod.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _get(client, path: str, expect: int = 200) -> str:
    r = client.get(path)
    assert r.status_code == expect, f"{path} -> {r.status_code}"
    return r.get_data(as_text=True)


def _processing_html(client) -> str:
    """Render the in-progress processing page for a freshly-seeded running run."""
    conn = webmod._db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
            "VALUES ('run-scram', datetime('now'), 'running', NULL, 'Spring Gala', 'spring.hy3')"
        )
        conn.commit()
    finally:
        conn.close()
    return _get(client, "/runs/run-scram")


def _brace_block(src: str, open_idx: int) -> str:
    """Return ``src[open_idx:]`` up to and including the brace that matches the
    ``{`` at ``open_idx`` (so a CSS rule/@media block can be isolated)."""
    depth, j = 0, open_idx
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[open_idx : j + 1]
        j += 1
    raise AssertionError("unbalanced braces")


def _func_body(src: str, name: str) -> str:
    """Return the source text of a top-level ``function <name>(...) { … }`` by
    brace-matching, so a test can assert on that one function in isolation."""
    m = re.search(r"function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", src)
    assert m, f"function {name} not found in ui-kit.js"
    i = src.index("{", m.start())
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i : j + 1]
        j += 1
    raise AssertionError(f"unbalanced braces in function {name}")


# =========================================================================== #
# Server-side: the JS ships the scramble engine
# =========================================================================== #
class TestUiKitShipsScramble:
    def test_runscramble_and_public_api_present(self):
        assert "function runScramble(" in _UIKIT_SRC
        # Both the imperative entry points are exported on the MH namespace.
        assert "MH.scramble = function" in _UIKIT_SRC
        assert "MH.scrambleTo = function" in _UIKIT_SRC

    def test_declarative_class_is_observed_and_fired(self):
        # .mh-scramble is wired into the shared IntersectionObserver reveal …
        assert re.search(r"each\(root,\s*\"[^\"]*\.mh-scramble[^\"]*\",\s*observe\)", _UIKIT_SRC)
        # … and fire() decodes it (once — guarded against a re-observe).
        fire = _func_body(_UIKIT_SRC, "fire")
        assert "mh-scramble" in fire and "runScramble(el)" in fire
        assert "data-mh-scrambled" in fire  # the once-guard key

    def test_reduced_motion_guard_inside_runscramble(self):
        body = _func_body(_UIKIT_SRC, "runScramble")
        # REDUCE short-circuits before any animation frame is scheduled.
        assert "REDUCE" in body
        guard = body[: body.index("requestAnimationFrame")]
        assert "REDUCE" in guard and "return" in guard

    def test_scrambleto_is_a_noop_on_unchanged_text(self):
        # Polling the same stage label must not re-trigger the flicker.
        assert 'getAttribute("data-mh-scramble-target") === text' in _UIKIT_SRC

    def test_implementation_is_xss_safe_text_nodes_only(self):
        """The decode must never write innerHTML — it rewrites the .data of the
        element's existing text nodes, so embedded markup is preserved and no
        attacker-influenced string can introduce nodes."""
        body = _func_body(_UIKIT_SRC, "runScramble")
        assert "createTreeWalker" in body
        assert "nodeValue" in body
        assert "innerHTML" not in body
        assert "insertAdjacentHTML" not in body
        assert "document.write" not in body

    def test_glyph_alphabet_defined(self):
        m = re.search(r'var SCRAMBLE_GLYPHS = "([^"]+)";', _UIKIT_SRC)
        assert m and len(m.group(1)) >= 20

    def test_long_text_guard(self):
        # Very long strings skip the animation (show final) — keeps it snappy.
        body = _func_body(_UIKIT_SRC, "runScramble")
        assert "length > 240" in body


# =========================================================================== #
# Server-side: the CSS ships the decode cast + reduced-motion reset
# =========================================================================== #
class TestCssShipsScramble:
    def test_css_defines_scramble_cast(self):
        css = webmod.BASE_CSS
        assert ".mh-scramble" in css
        assert ".mh-scramble.is-scrambling" in css
        # the lit-while-decoding colour is a brand token (re-skins for free)
        block = re.search(r"\.mh-scramble\.is-scrambling\s*\{[^}]*\}", css)
        assert block and "var(--mh-primary)" in block.group(0)

    def test_css_reduced_motion_resets_cast(self):
        # Brace-match the reduced-motion @media block in the motion stylesheet
        # (its source of truth) and assert the cast is neutralised there.
        motion = _MOTION_CSS_PATH.read_text(encoding="utf-8")
        m = re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{", motion)
        assert m, "reduced-motion block not found in theme-motion.css"
        block = _brace_block(motion, motion.index("{", m.start()))
        assert ".mh-scramble.is-scrambling { color: inherit; }" in block
        assert ".mh-scramble { transition: none; }" in block
        # and it actually ships in the assembled CSS
        assert ".mh-scramble.is-scrambling { color: inherit; }" in webmod.BASE_CSS


# =========================================================================== #
# Server-side: the static asset is actually served + linked
# =========================================================================== #
class TestAssetServed:
    def test_uikit_served_with_scramble_code(self, client):
        body = _get(client, "/static/js/ui-kit.js")
        assert "function runScramble(" in body
        assert "MH.scrambleTo" in body

    def test_uikit_linked_deferred_on_pages(self, client):
        body = _get(client, "/upload")
        assert "js/ui-kit.js" in body
        assert re.search(r"<script[^>]*\bdefer\b[^>]*ui-kit\.js", body)


# =========================================================================== #
# Server-side: the wired surfaces carry the right markup
# =========================================================================== #
class TestWiredSurfaces:
    def test_upload_hero_is_scramble(self, client):
        body = _get(client, "/upload")
        assert '<h1 class="mh-scramble">Drop the results.' in body
        # markup the decode must preserve (text-node rewrite leaves these alone)
        assert '<br><em class="editorial">We&rsquo;ll do the rest.</em></h1>' in body or \
               "<br><em class=\"editorial\">We'll do the rest.</em></h1>" in body

    def test_processing_headline_is_scramble(self, client):
        body = _processing_html(client)
        assert '<h1 class="mh-scramble">Processing run</h1>' in body

    def test_processing_live_stage_is_scramble(self, client):
        body = _processing_html(client)
        assert 'id="mh-current-stage" class="mh-scramble"' in body

    def test_processing_poller_decodes_each_stage(self, client):
        body = _processing_html(client)
        # the helper + its use, and the scrambleTo wiring with a plain fallback
        assert "function setStage(txt)" in body
        assert "MH.scrambleTo(stage, txt)" in body
        assert "else stage.textContent = txt;" in body
        assert "setStage(log[log.length - 1] || 'Starting…');" in body

    def test_content_pack_holding_headline_is_scramble(self):
        # The secondary "still generating your content pack" holding screen.
        with webmod.app.test_request_context():
            html = webmod._in_progress_page("run-xyz")
        assert 'class="mh-scramble"' in html
        assert "Still processing your run" in html

    def test_home_heroes_untouched(self, client):
        """UI 1.21 must not have added attributes to the landing <h1> (the U.9
        word-cycle tests rely on the bare ``<h1>…</h1>``)."""
        body = _get(client, "/")
        m = re.search(r"<h1>.*?</h1>", body, re.DOTALL)
        assert m, "landing hero <h1> must stay attribute-free"
        assert "mh-scramble" not in m.group(0)


# =========================================================================== #
# Browser-side: the decode really animates (and really freezes)
# =========================================================================== #
def _build_doc(markup: str) -> str:
    return (
        "<!doctype html><html class='mh-js'><head><meta charset='utf-8'>"
        "<style>body{margin:0;font-size:32px}</style></head>"
        f"<body>{markup}</body></html>"
    )


def _launch():
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        executable_path=str(_PINNED_CHROMIUM),
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    return pw, browser


@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="chromium-1194 not at pinned path")
class TestScrambleBrowser:
    def _page(self, browser, markup, reduced="no-preference"):
        ctx = browser.new_context(reduced_motion=reduced, viewport={"width": 900, "height": 600})
        page = ctx.new_page()
        page.set_content(_build_doc(markup))
        page.wait_for_load_state("domcontentloaded")
        page.add_script_tag(content=_UIKIT_SRC)  # runs immediately (readyState != loading)
        return page

    def test_declarative_headline_decodes_then_settles(self):
        pw, browser = _launch()
        try:
            page = self._page(browser, "<h1 id='t' class='mh-scramble'>Decode this headline</h1>")
            page.evaluate(
                """() => {
                    window.__caps = [];
                    var el = document.getElementById('t');
                    window.__iv = setInterval(function(){
                        window.__caps.push({txt: el.textContent,
                                            scr: el.classList.contains('is-scrambling')});
                    }, 16);
                }"""
            )
            page.wait_for_timeout(2000)
            caps = page.evaluate("() => { clearInterval(window.__iv); return window.__caps; }")
            final = page.eval_on_selector("#t", "el => el.textContent")
        finally:
            browser.close()
            pw.stop()

        assert caps, "no frames captured"
        texts = [c["txt"] for c in caps]
        # A real decode produces many distinct intermediate frames …
        assert len(set(texts)) >= 8, f"barely changed: {sorted(set(texts))[:5]}"
        # … was flagged scrambling at some point …
        assert any(c["scr"] for c in caps), "is-scrambling never applied"
        # … and settled to the exact final text with the flag cleared.
        assert final == "Decode this headline"
        assert texts[-1] == "Decode this headline"
        assert caps[-1]["scr"] is False, "still scrambling at the end"

    def test_decode_preserves_inline_markup(self):
        pw, browser = _launch()
        try:
            page = self._page(
                browser,
                "<h1 id='t' class='mh-scramble'>Drop the results.<br><em>We'll do the rest.</em></h1>",
            )
            page.wait_for_timeout(2000)  # settle
            inner = page.eval_on_selector("#t", "el => el.innerHTML")
            em_text = page.eval_on_selector("#t em", "el => el.textContent")
            full = page.eval_on_selector("#t", "el => el.textContent")
        finally:
            browser.close()
            pw.stop()

        assert "<br>" in inner.lower(), inner
        assert "<em>" in inner.lower(), inner
        assert em_text == "We'll do the rest."
        assert full == "Drop the results.We'll do the rest."

    def test_scrambleto_decodes_to_new_text(self):
        pw, browser = _launch()
        try:
            page = self._page(browser, "<span id='s'>Starting…</span>")
            page.evaluate(
                """() => {
                    window.__caps = [];
                    window.__labels = [];
                    var el = document.getElementById('s');
                    window.__iv = setInterval(function(){
                        window.__caps.push(el.textContent);
                        window.__labels.push(el.getAttribute('aria-label'));
                    }, 16);
                    window.MH.scrambleTo('#s', 'Ranking moments');
                }"""
            )
            page.wait_for_timeout(1800)
            caps = page.evaluate("() => { clearInterval(window.__iv); return window.__caps; }")
            labels = page.evaluate("() => window.__labels")
            final = page.eval_on_selector("#s", "el => el.textContent")
            final_label = page.eval_on_selector("#s", "el => el.getAttribute('aria-label')")
        finally:
            browser.close()
            pw.stop()

        assert len(set(caps)) >= 8, f"scrambleTo barely changed: {sorted(set(caps))[:5]}"
        assert final == "Ranking moments"
        # During the decode the accessible name is pinned to the target …
        assert "Ranking moments" in labels, f"aria-label never tracked target: {set(labels)}"
        # … then handed back to the natural name (textContent) once settled.
        assert final_label is None

    def test_scrambleto_is_noop_on_repeat(self):
        pw, browser = _launch()
        try:
            page = self._page(browser, "<span id='s'>Starting…</span>")
            page.evaluate("() => window.MH.scrambleTo('#s', 'County Finals')")
            page.wait_for_timeout(1500)  # let it settle
            saw = page.evaluate(
                """() => new Promise(function(resolve){
                    var el = document.getElementById('s');
                    var saw = false;
                    var iv = setInterval(function(){
                        if (el.classList.contains('is-scrambling')) saw = true;
                    }, 8);
                    window.MH.scrambleTo('#s', 'County Finals');  // identical → no-op
                    setTimeout(function(){ clearInterval(iv); resolve(saw); }, 250);
                })"""
            )
            final = page.eval_on_selector("#s", "el => el.textContent")
        finally:
            browser.close()
            pw.stop()

        assert saw is False, "repeat scrambleTo with identical text re-triggered the flicker"
        assert final == "County Finals"

    def test_aria_busy_during_then_cleared(self):
        pw, browser = _launch()
        try:
            page = self._page(browser, "<h1 id='t' class='mh-scramble'>Engine is generating</h1>")
            page.evaluate(
                """() => {
                    window.__busy = [];
                    window.__labels = [];
                    var el = document.getElementById('t');
                    window.__iv = setInterval(function(){
                        window.__busy.push(el.getAttribute('aria-busy'));
                        window.__labels.push(el.getAttribute('aria-label'));
                    }, 16);
                }"""
            )
            page.wait_for_timeout(1800)
            busy = page.evaluate("() => { clearInterval(window.__iv); return window.__busy; }")
            labels = page.evaluate("() => window.__labels")
            final_label = page.eval_on_selector("#t", "el => el.getAttribute('aria-label')")
        finally:
            browser.close()
            pw.stop()

        assert any(b == "true" for b in busy), "aria-busy never set during decode"
        assert busy[-1] in (None, "false"), f"aria-busy not cleared: {busy[-1]!r}"
        # The accessible name is pinned to the real text while busy, then removed
        # so the (now-correct) natural name takes over.
        assert "Engine is generating" in labels, f"aria-label never pinned: {set(labels)}"
        assert final_label is None, f"aria-label not handed back: {final_label!r}"

    def test_reduced_motion_freezes_to_final(self):
        pw, browser = _launch()
        try:
            page = self._page(
                browser, "<h1 id='t' class='mh-scramble'>Decode this headline</h1>", reduced="reduce"
            )
            page.evaluate(
                """() => {
                    window.__caps = [];
                    var el = document.getElementById('t');
                    window.__iv = setInterval(function(){
                        window.__caps.push({txt: el.textContent,
                                            scr: el.classList.contains('is-scrambling')});
                    }, 16);
                }"""
            )
            page.wait_for_timeout(900)
            caps = page.evaluate("() => { clearInterval(window.__iv); return window.__caps; }")
            final = page.eval_on_selector("#t", "el => el.textContent")
        finally:
            browser.close()
            pw.stop()

        assert caps, "no frames captured"
        # Under reduced motion the text never flickers and never scrambles.
        assert all(c["txt"] == "Decode this headline" for c in caps), (
            f"reduced motion still animated: {sorted({c['txt'] for c in caps})[:5]}"
        )
        assert not any(c["scr"] for c in caps), "is-scrambling applied under reduced motion"
        assert final == "Decode this headline"

    def test_reduced_motion_scrambleto_updates_instantly(self):
        pw, browser = _launch()
        try:
            page = self._page(browser, "<span id='s'>Starting…</span>", reduced="reduce")
            page.evaluate("() => window.MH.scrambleTo('#s', 'Ranking moments')")
            page.evaluate(
                """() => {
                    window.__caps = [];
                    var el = document.getElementById('s');
                    window.__iv = setInterval(function(){ window.__caps.push(el.textContent); }, 16);
                }"""
            )
            page.wait_for_timeout(500)
            caps = page.evaluate("() => { clearInterval(window.__iv); return window.__caps; }")
        finally:
            browser.close()
            pw.stop()

        # Instant swap to the target, no flicker frames.
        assert all(c == "Ranking moments" for c in caps), f"reduced-motion flicker: {set(caps)}"
