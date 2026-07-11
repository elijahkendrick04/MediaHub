"""tests/test_ui_2_7_caption_type_on.py — UI2.7 caption type-on reveal.

Roadmap **UI2.7** (UI2, top priority): Text-Generate (``.mh-text-generate``)
word-by-word reveal on a *read-only* generated-caption preview only — **never**
the editable caption, which stays plain — so the "AI is writing" moment reads.

The host surface is the per-card creative toolbar's tone picker: the
``.caption-text`` ``<div>`` is the read-only generated-caption preview; the
``.caption-textarea`` is the (hidden) editable store. UI2.7 reuses the kit's
``.mh-text-generate`` effect but fires it *immediately* (the caption is already
on screen) via a new ``MH.typeOn`` helper, only on a fresh generation.

Two tiers (mirrors tests/test_ui_cycle_placeholder.py):

  1. **Source / server** — the kit CSS carries the word-reveal rules with a
     *tunable* stagger (back-compatible 55ms default) + the reduced-motion gate;
     ``ui-kit.js`` exposes ``MH.typeOn`` (immediate, whitespace-preserving,
     re-entrancy-guarded, fail-safe); the per-card caption JS types on the
     read-only preview on fresh generation only (variant swaps stay plain) and
     never touches the editable textarea; the toolbar markup keeps the editable
     textarea plain; the kit ships globally and is served from /static.
  2. **Browser** (Playwright + pinned Chromium) — ``MH.typeOn`` really splits a
     caption into staggered ``.mh-word`` spans and *preserves its newlines*; the
     real ``switchToneLive`` → ``_fetchCaption`` flow types on ``.caption-text``
     while ``.caption-textarea`` keeps a plain value with no word spans; and
     reduced motion shows every word at once.

The Playwright tier skips when Playwright or the pinned Chromium build is absent
(as tests/test_ui_cycle_placeholder.py does).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "mediahub" / "web" / "static"
_MOTION_CSS_PATH = _STATIC / "theme" / "theme-motion.css"
_UIKIT_JS_PATH = _STATIC / "js" / "ui-kit.js"

MOTION_CSS = _MOTION_CSS_PATH.read_text(encoding="utf-8")
UIKIT_JS = _UIKIT_JS_PATH.read_text(encoding="utf-8")

_SKIP_BROWSER = os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower() in ("1", "true", "yes")
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


@pytest.fixture(scope="module")
def caption_js() -> str:
    """The per-card creative client JS (the tone-picker / caption renderer)."""
    from mediahub.web import web as wm

    return wm._card_creative_js()


class TestCopilotEscaperIsGlobal:
    """Copilot replies, model-derived rejection reasons, comments and preview
    errors reach innerHTML — they MUST be escaped. Previously `safeText` was only
    a local var in the caption closure and never global, so the
    `window.safeText?safeText():raw` guards silently took the raw branch → a
    prompt-injection-to-XSS sink on the review surface."""

    def test_global_escaper_is_defined(self, caption_js):
        assert "window.safeText = window.safeText ||" in caption_js

    def test_no_falsy_fallback_guards_remain(self, caption_js):
        # The broken guard that fell through to the raw string is gone.
        assert "window.safeText?safeText" not in caption_js
        assert "window.safeText ? safeText" not in caption_js

    def test_copilot_sinks_escape_unconditionally(self, caption_js):
        # Reply body, rejection reasons, preview error and comment text all route
        # through the global escaper before innerHTML.
        assert ":</span> ' + window.safeText(text)" in caption_js
        assert "Skipped: ' + window.safeText(reasons)" in caption_js
        assert "window.safeText(res.err)" in caption_js
        assert "function _cmTxt(s){ return window.safeText(s); }" in caption_js

    def test_motion_and_reel_error_paths_escape_server_detail(self, caption_js):
        # generateMotion / generateReel / generateReelBatch fall back to a raw
        # str(e) `detail` (meet names, node stderr) — escape before innerHTML.
        # D-13 moved the failure surface into the shared _mhJobFail helper;
        # the escape must still be unconditional there, and the reel paths
        # must still carry their "Reel render error: " prefix into it.
        assert "(ctx.prefix || '') + window.safeText(msg)" in caption_js
        assert "prefix: 'Reel render error: '" in caption_js

    def test_visual_panel_escapes_why_layout_and_errors(self, caption_js):
        # _renderVisualPanel: why_this_design is LLM output; layout + errors are
        # server-derived. All must be escaped before innerHTML.
        assert "window.safeText(why)" in caption_js
        assert "window.safeText(layout" in caption_js
        assert "window.safeText(data.errors.join" in caption_js

    def test_reel_batch_shows_honest_reasons_not_stale_engine_advice(self, caption_js):
        # The batch reel panel must surface the API's per-cut formats_failed
        # reason (escaped), not the misleading hardcoded "switch engine" line
        # (the ffmpeg engine renders all four cuts since R1.16).
        assert "Switch to the Remotion engine" not in caption_js
        assert "Not produced by the active render engine" not in caption_js
        assert "These cuts failed to render" in caption_js
        assert "window.safeText(reason)" in caption_js

    def test_variant_picker_escapes_hook_label_and_errors(self, caption_js):
        # _vFail msg + the variant picker's LLM hook, layout label and per-seed
        # error join are all server/LLM-echoed and go to innerHTML.
        assert "font-size:13px\">' + window.safeText(msg)" in caption_js
        assert "window.safeText((vt.errors||[]).join" in caption_js
        assert "&middot; ' + window.safeText(label)" in caption_js
        assert "margin-top:2px\">' + window.safeText(hook)" in caption_js


# ════════════════════════════════════════════════════════════════════════════
# Tier 1a — the kit CSS contract
# ════════════════════════════════════════════════════════════════════════════
class TestKitCss:
    def test_word_reveal_rules_present(self):
        # The Text-Generate effect the roadmap names by class.
        assert ".mh-text-generate .mh-word" in MOTION_CSS
        assert ".mh-text-generate.is-in .mh-word" in MOTION_CSS
        assert "@keyframes mh-word-in" in MOTION_CSS

    def test_initial_hidden_state(self):
        # Words start hidden (opacity 0, blurred, nudged) so the reveal reads.
        block = MOTION_CSS[MOTION_CSS.find(".mh-text-generate .mh-word") :]
        head = block[: block.find("}")]
        assert "opacity: 0" in head
        assert "blur(" in head
        assert "translateY" in head

    def test_stagger_is_tunable_with_backcompat_default(self):
        """The per-word delay reads --mh-stagger with a 55ms fallback, so
        MH.typeOn can bound a long caption's reveal while scroll headings (which
        never set it) keep the historic 55ms cadence byte-for-byte."""
        assert "calc(var(--i, 0) * var(--mh-stagger, 55ms))" in MOTION_CSS

    def test_reveal_persists_does_not_flash(self):
        """Each word must keep its revealed state — fill-mode `both`/`forwards`,
        never bare `backwards`, which snaps the word back to opacity:0 the
        instant it finishes (the caption would flash in then vanish)."""
        m = re.search(r"\.mh-text-generate\.is-in \.mh-word\s*\{([^}]*)\}", MOTION_CSS)
        assert m, "no .is-in word-reveal rule"
        am = re.search(r"animation:\s*mh-word-in[^;]*;", m.group(1))
        assert am, m.group(1)
        fill = am.group(0)
        assert "both" in fill or "forwards" in fill, f"reveal does not persist: {fill}"

    def test_reduced_motion_gate_shows_all_words(self):
        """Under prefers-reduced-motion the words are simply visible — no
        per-word animation. This single gate also covers the caption use."""
        assert "prefers-reduced-motion: reduce" in MOTION_CSS
        # The override rule (the one carrying opacity:1, i.e. the reduced-motion
        # branch — not the at-rest opacity:0 rule) neutralises the animation.
        m = re.search(r"\.mh-text-generate \.mh-word\s*\{[^}]*opacity:\s*1[^}]*\}", MOTION_CSS)
        assert m, "no reduced-motion override for .mh-text-generate .mh-word"
        body = m.group(0)
        assert "animation: none" in body


# ════════════════════════════════════════════════════════════════════════════
# Tier 1b — the ui-kit.js MH.typeOn contract
# ════════════════════════════════════════════════════════════════════════════
class TestKitJs:
    def test_js_is_valid_syntax(self):
        """node --check the shipped file (skips cleanly if node is absent)."""
        node = None
        for cand in ("node", "nodejs"):
            try:
                subprocess.run([cand, "--version"], capture_output=True, check=True)
                node = cand
                break
            except (OSError, subprocess.CalledProcessError):
                continue
        if node is None:
            pytest.skip("node not available")
        r = subprocess.run([node, "--check", str(_UIKIT_JS_PATH)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    def test_typeon_is_a_public_helper(self):
        assert "MH.typeOn = function" in UIKIT_JS

    def test_typeon_reuses_the_text_generate_effect(self):
        block = self._typeon_block()
        # reuses the kit's own classes rather than inventing a parallel effect
        assert 'classList.add("mh-text-generate")' in block
        assert '"mh-word"' in block
        assert 'classList.add("is-in")' in block

    def test_typeon_preserves_whitespace_and_newlines(self):
        """Caption-critical: unlike splitWords() (which collapses \\s+ to single
        spaces for headings), typeOn keeps whitespace/newlines verbatim so a
        multi-line caption rendered under white-space:pre-wrap stays faithful."""
        block = self._typeon_block()
        assert r"split(/(\s+)/)" in block  # tokenise keeping the separators
        assert "createTextNode(part)" in block  # whitespace runs kept verbatim
        # and it is NOT the heading collapser
        assert r'replace(/\s+/g, " ")' not in block

    def test_typeon_bounds_reveal_time(self):
        block = self._typeon_block()
        assert 'setProperty("--mh-stagger"' in block

    def test_typeon_fires_immediately_not_on_scroll(self):
        block = self._typeon_block()
        assert "requestAnimationFrame" in block
        # no IntersectionObserver in the immediate path
        assert "IntersectionObserver" not in block

    def test_typeon_is_reentrancy_guarded(self):
        block = self._typeon_block()
        assert "data-mh-typed" in block  # don't re-type the same node
        assert "data-mh-split" in block  # keep the scroll splitWords() off it

    def test_typeon_is_reduced_motion_aware(self):
        block = self._typeon_block()
        assert "REDUCE" in block

    def test_typeon_fails_safe(self):
        block = self._typeon_block()
        assert "try {" in block and "catch (e)" in block

    # -- helper: isolate the MH.typeOn function body ------------------------- #
    def _typeon_block(self) -> str:
        i = UIKIT_JS.find("MH.typeOn = function")
        assert i != -1, "MH.typeOn not found"
        # up to the next top-level MH.* assignment / section comment
        j = UIKIT_JS.find("\n  /* ---", i + 1)
        return UIKIT_JS[i : j if j != -1 else i + 2000]


# ════════════════════════════════════════════════════════════════════════════
# Tier 1c — the per-card caption JS wiring (read-only preview only)
# ════════════════════════════════════════════════════════════════════════════
class TestCaptionWiring:
    def test_readonly_preview_gets_typed_on_on_fresh_generation(self, caption_js):
        assert 'class="mh-cap-body"' in caption_js  # the read-only preview body
        assert "MH.typeOn(capBody)" in caption_js
        assert "_renderActive(0, true)" in caption_js  # fresh gen → reveal=true

    def test_typeon_guarded_on_MH_presence(self, caption_js):
        # never throws when the kit JS failed to load (effects are decorative)
        assert "window.MH && typeof MH.typeOn === 'function'" in caption_js

    def test_variant_swaps_render_plainly(self, caption_js):
        # clicking a variant pill re-renders WITHOUT the reveal flag
        assert "_renderActive(parseInt(btn.dataset.idx, 10) || 0)" in caption_js
        # exactly one call site actually types on — the fresh-generation render
        assert caption_js.count("MH.typeOn(") == 1

    def test_editable_textarea_is_set_plainly(self, caption_js):
        # the editable store gets the plain value; it is never typed on
        assert "textarea.value = active;" in caption_js
        # the only type-on target is the read-only preview body, not a textarea
        assert "MH.typeOn(capBody)" in caption_js
        assert "typeOn(textarea" not in caption_js
        assert "typeOn(ta" not in caption_js

    def test_assist_path_stays_plain(self, caption_js):
        # Assist rewrites set textContent/value directly — no type-on reveal,
        # so the single typeOn *call site* is the fresh-generation render only.
        assert "textEl.textContent = j.caption;" in caption_js
        assert caption_js.count("MH.typeOn(") == 1


# ════════════════════════════════════════════════════════════════════════════
# Tier 1d — the rendered toolbar keeps the editable caption plain
# ════════════════════════════════════════════════════════════════════════════
class TestToolbarMarkup:
    @pytest.fixture(scope="class")
    def toolbar_html(self) -> str:
        from mediahub.web import web as wm

        with wm.app.test_request_context("/"):
            return wm._render_card_creative_toolbar("run-x", "swim-1")

    def test_readonly_preview_present(self, toolbar_html):
        assert 'class="caption-text"' in toolbar_html  # the read-only host div

    def test_editable_textarea_is_hidden_and_plain(self, toolbar_html):
        # the editable store renders hidden and carries NONE of the effect hooks
        m = re.search(r'<textarea class="caption-textarea"[^>]*>', toolbar_html)
        assert m, "caption-textarea not rendered"
        tag = m.group(0)
        assert "display:none" in tag
        # at-rest markup carries no reveal classes (they're added at runtime,
        # to the read-only preview only)
        assert "mh-text-generate" not in toolbar_html
        assert "mh-word" not in toolbar_html
        assert "mh-cap-body" not in toolbar_html


# ════════════════════════════════════════════════════════════════════════════
# Tier 1e — the kit ships globally + is served from /static
# ════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    from mediahub.web import web as wm

    monkeypatch.setattr(wm, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(wm, "RUNS_DIR", runs, raising=False)
    app = wm.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestServedAssets:
    def test_uikit_js_served_with_typeon(self, client):
        r = client.get("/static/js/ui-kit.js")
        assert r.status_code == 200, r.status_code
        body = r.get_data(as_text=True)
        assert "MH.typeOn = function" in body

    def test_uikit_and_mhjs_ship_in_the_shell(self, client):
        # ui-kit.js (deferred) and the .mh-js capability flag ride the shared
        # shell on every page, so the effect is available wherever a caption is.
        body = client.get("/").get_data(as_text=True)
        assert "js/ui-kit.js" in body
        assert "classList.add('mh-js')" in body

    def test_motion_css_in_base_bundle_with_stagger_var(self, client):
        # theme-motion.css is concatenated into the served theme bundle.
        from mediahub.web.theme_tokens import THEME_MOTION_CSS

        assert "var(--mh-stagger, 55ms)" in THEME_MOTION_CSS


# ════════════════════════════════════════════════════════════════════════════
# Tier 2 — Playwright browser behaviour (the effect really runs)
# ════════════════════════════════════════════════════════════════════════════
def _launch_browser():
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        executable_path=str(_PINNED_CHROMIUM),
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    return pw, browser


# A genuinely multi-line caption (newlines + a double space) so whitespace
# preservation is observable. No <>& so it round-trips the real safeText().
_CAPTION = (
    "Brilliant swimming from the squad today.\n"
    "Tom smashed a new  personal best in the 100m freestyle.\n"
    "More moments to come this season."
)
_WORD_COUNT = len(_CAPTION.split())


# theme-motion.css's word reveal animates with var(--ease-out); that token is
# declared in theme-components.css, which the production shell loads first. The
# harness injects the real value so the animation shorthand is valid here too.
_BASE_VARS = ":root{--ease-out:cubic-bezier(0.16, 1, 0.3, 1);}"


def _typeon_page(caption: str) -> str:
    """A minimal harness: the kit CSS + JS and a read-only caption preview."""
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{_BASE_VARS}{MOTION_CSS}</style></head><body>"
        "<div class='tone-picker'><div class='caption-text'>"
        f"<span class='mh-cap-body'>{caption}</span>"
        "</div></div>"
        f"<script>{UIKIT_JS}</script>"
        "</body></html>"
    )


@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="prebaked chromium not found")
class TestTypeOnBrowser:
    def test_splits_into_staggered_words_preserving_newlines(self):
        pw, browser = _launch_browser()
        try:
            ctx = browser.new_context(reduced_motion="no-preference")
            page = ctx.new_page()
            page.set_content(_typeon_page(_CAPTION))
            page.wait_for_load_state("domcontentloaded")
            page.evaluate("() => document.documentElement.classList.add('mh-js')")
            page.evaluate("() => MH.typeOn(document.querySelector('.mh-cap-body'))")
            # .is-in is flipped on the next animation frame — wait for it.
            page.wait_for_function(
                "() => document.querySelector('.mh-cap-body').classList.contains('is-in')"
            )

            # structure: one .mh-word per word, ascending --i, newlines intact
            info = page.evaluate(
                """() => {
                    var body = document.querySelector('.mh-cap-body');
                    var words = body.querySelectorAll('.mh-word');
                    return {
                        n: words.length,
                        text: body.textContent,
                        isIn: body.classList.contains('is-in'),
                        gen: body.classList.contains('mh-text-generate'),
                        stagger: body.style.getPropertyValue('--mh-stagger'),
                        firstI: words[0] && words[0].style.getPropertyValue('--i'),
                        lastI: words[words.length-1] && words[words.length-1].style.getPropertyValue('--i')
                    };
                }"""
            )
            assert info["n"] == _WORD_COUNT, info
            assert info["text"] == _CAPTION, "whitespace/newlines were not preserved"
            assert info["isIn"] is True
            assert info["gen"] is True
            assert info["stagger"].endswith("ms")
            assert info["firstI"] == "0"
            assert info["lastI"] == str(_WORD_COUNT - 1)

            # behaviour: a genuine left-to-right stagger — early in the reveal
            # the first word is well ahead of the last, then both settle visible.
            page.wait_for_timeout(120)
            mid = page.evaluate(
                """() => {
                    var w = document.querySelectorAll('.mh-cap-body .mh-word');
                    var cs = function(el){ return parseFloat(getComputedStyle(el).opacity); };
                    return { first: cs(w[0]), last: cs(w[w.length-1]) };
                }"""
            )
            assert mid["first"] > mid["last"] + 0.15, f"no visible stagger: {mid}"

            page.wait_for_timeout(2000)
            end = page.evaluate(
                """() => {
                    var w = document.querySelectorAll('.mh-cap-body .mh-word');
                    var cs = function(el){ return parseFloat(getComputedStyle(el).opacity); };
                    return { first: cs(w[0]), last: cs(w[w.length-1]) };
                }"""
            )
            assert end["first"] >= 0.95 and end["last"] >= 0.95, f"words never settled: {end}"
        finally:
            browser.close()
            pw.stop()

    def test_reduced_motion_shows_all_words_at_once(self):
        pw, browser = _launch_browser()
        try:
            ctx = browser.new_context(reduced_motion="reduce")
            page = ctx.new_page()
            page.set_content(_typeon_page(_CAPTION))
            page.wait_for_load_state("domcontentloaded")
            page.evaluate("() => document.documentElement.classList.add('mh-js')")
            page.evaluate("() => MH.typeOn(document.querySelector('.mh-cap-body'))")
            page.wait_for_timeout(60)  # far shorter than any staggered reveal
            res = page.evaluate(
                """() => {
                    var w = document.querySelectorAll('.mh-cap-body .mh-word');
                    var cs = function(el){ return parseFloat(getComputedStyle(el).opacity); };
                    return { n: w.length, first: cs(w[0]), last: cs(w[w.length-1]) };
                }"""
            )
            assert res["n"] == _WORD_COUNT
            # every word is already fully visible — no per-word animation ran
            assert res["first"] >= 0.95 and res["last"] >= 0.95, res
        finally:
            browser.close()
            pw.stop()


# ── the real switchToneLive → _fetchCaption flow, end-to-end ──────────────────
def _e2e_page(caption_js: str, caption: str, cap_url: str, card: str) -> str:
    cap_json = json.dumps(caption)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{_BASE_VARS}{MOTION_CSS}</style></head><body>"
        f"<div class='tone-picker' id='wf-{card}' data-caption-url='{cap_url}' data-card='{card}'>"
        f"<button class='tone-tab tone-tab-ai active' data-card='{card}' data-tone='ai'>AI</button>"
        f"<div class='tone-panels' data-card='{card}'>"
        f"<div class='tone-panel' data-tone='ai' data-card='{card}'>"
        "<div class='caption-text'><span class='caption-placeholder'>Click to generate</span></div>"
        "<textarea class='caption-textarea' style='display:none'></textarea>"
        "</div></div><span class='caption-timestamp'></span></div>"
        f"<script>{UIKIT_JS}</script>"
        "<script>window._API_BASE='';window.WF_API_BASE='/api/x/';"
        "window.fetch=function(u,o){return Promise.resolve({ok:true,json:function(){"
        f"return Promise.resolve({{caption:{cap_json},variants:[{cap_json}],"
        "tone:'ai',live:true,generated_at:new Date().toISOString()});}});};</script>"
        f"{caption_js}"
        "</body></html>"
    )


@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="prebaked chromium not found")
class TestRealCaptionFlowBrowser:
    """Drive the *actual* shipped caption JS: a fresh generation must type on the
    read-only preview while the editable textarea keeps a plain value."""

    def test_preview_types_on_textarea_stays_plain(self, caption_js):
        card, cap_url = "swim-1", "/api/runs/r/swim/swim-1/caption"
        pw, browser = _launch_browser()
        try:
            ctx = browser.new_context(reduced_motion="no-preference")
            page = ctx.new_page()
            page.set_content(_e2e_page(caption_js, _CAPTION, cap_url, card))
            page.wait_for_load_state("domcontentloaded")
            page.evaluate("() => document.documentElement.classList.add('mh-js')")
            page.evaluate(
                "() => switchToneLive(document.querySelector('.tone-tab'), %s, %s)"
                % (json.dumps(cap_url), json.dumps(card))
            )
            page.wait_for_timeout(400)  # fetch microtask + rAF + a few frames

            res = page.evaluate(
                """() => {
                    var cap = document.querySelector('.caption-text .mh-cap-body');
                    var ta = document.querySelector('.caption-textarea');
                    return {
                        previewWords: cap ? cap.querySelectorAll('.mh-word').length : -1,
                        previewIsGen: cap ? cap.classList.contains('mh-text-generate') : false,
                        previewText: cap ? cap.textContent : null,
                        taValue: ta ? ta.value : null,
                        taWords: ta ? ta.querySelectorAll('.mh-word').length : -1,
                        taIsGen: ta ? ta.classList.contains('mh-text-generate') : true
                    };
                }"""
            )
            # read-only preview: typed on, word-by-word, newlines preserved
            assert res["previewWords"] == _WORD_COUNT, res
            assert res["previewIsGen"] is True, res
            assert res["previewText"] == _CAPTION, "preview lost the caption whitespace"
            # editable caption: holds the plain value, with NO word spans and no
            # effect class — it stays plain, exactly as the roadmap requires
            assert res["taValue"] == _CAPTION, res
            assert res["taWords"] == 0, res
            assert res["taIsGen"] is False, res
        finally:
            browser.close()
            pw.stop()
