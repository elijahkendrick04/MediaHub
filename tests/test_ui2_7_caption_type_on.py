"""tests/test_ui2_7_caption_type_on.py — UI2.7 caption "AI is writing" type-on.

Roadmap **UI2.7** (UI2, top priority): wire the kit's Text-Generate
(``.mh-text-generate``) word-by-word reveal onto the **read-only generated-caption
preview only** — so the "AI is writing" moment reads — while the **editable**
caption (``.caption-textarea``) stays plain. Parallel-safe and presentation-only:
the deterministic engine, the AI caption writer, and the explainability logic are
all untouched.

Four layers of assertion (mirrors ``tests/test_u16_card_tilt.py``):

  1. **CSS contract** (``theme-motion.css``) — the ``.mh-text-generate`` effect,
     including the UI2.7 fix that the reveal SETTLES visible (``both``, not
     ``backwards`` — a ``to``-only keyframe under ``backwards`` would drop every
     word back to ``opacity:0`` the instant its run ended), and the
     reduced-motion no-op.
  2. **JS contract** (``web.py`` → ``_card_creative_js``) — the ``_revealCaption``
     helper (whitespace-preserving tokeniser, fail-safe), the "animate only on a
     fresh live AI write" gate, and the editable-stays-plain guarantee.
  3. **Rendered surface** — ``/pack`` ships the toolbar JS + the kit CSS; the
     per-card toolbar markup has a read-only preview *and* a hidden editable
     textarea.
  4. **Browser behaviour** (Playwright + the pinned Chromium; skips when absent)
     — the real shipped JS reveals the preview word-by-word and settles fully
     visible, keeps the editable caption plain, preserves newlines, and stands
     down under ``prefers-reduced-motion``.

The Playwright gating/launch pattern mirrors ``tests/test_u16_card_tilt.py``.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from mediahub.web import web as webmod
from mediahub.web.theme_tokens import THEME_MOTION_CSS


# --------------------------------------------------------------------------- #
# Browser-test gating (mirrors tests/test_u16_card_tilt.py)
# --------------------------------------------------------------------------- #
_SKIP_BROWSER = (
    os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower()
    in ("1", "true", "yes")
)
_PINNED_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
_NODE = shutil.which("node")
requires_node = pytest.mark.skipif(_NODE is None, reason="node not on PATH")


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
@pytest.fixture(scope="module")
def motion_css() -> str:
    return THEME_MOTION_CSS


@pytest.fixture(scope="module")
def creative_js() -> str:
    """The per-card creative toolbar JS that hosts the live-caption render +
    the UI2.7 reveal. Sliced from the <script> wrapper so node --check + the
    substring assertions see the body."""
    return webmod._card_creative_js()


@pytest.fixture(scope="module")
def reveal_js(creative_js) -> str:
    """Just the body of _revealCaption — so assertions about the reveal can't
    accidentally match unrelated code elsewhere in the toolbar JS."""
    start = creative_js.index("function _revealCaption(")
    end = creative_js.index("function _fetchCaption(", start)
    return creative_js[start:end]


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    """One owned run + active profile, app reloaded against a temp DATA_DIR.
    Returns (app, module). Modelled on tests/test_u6_render_progress.py."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    run = {
        "run_id": "r1",
        "profile_id": "alpha",
        "meet_name": "Test Open",
        "meet": {"name": "Test Open"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "id": "swim-1",
                    "rank": 1,
                    "priority": 0.9,
                    "achievement": {
                        "swim_id": "swim-1",
                        "swimmer_name": "Eira Hughes",
                        "event": "100m Freestyle",
                        "time": "59.80",
                    },
                }
            ]
        },
        "cards": [
            {"id": "swim-1", "swimmer_name": "Eira Hughes",
             "event": "100m Freestyle", "time": "59.80"}
        ],
    }
    (wm.RUNS_DIR / "r1.json").write_text(json.dumps(run), encoding="utf-8")
    return app, wm


@pytest.fixture
def pack_html(app_env) -> str:
    """The Content builder page for a run with one APPROVED card — the surface
    that hosts the per-card creative toolbar (and so the UI2.7 reveal JS)."""
    app, _wm = app_env
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "alpha"})
        appr = c.post(
            "/api/workflow/r1/swim-1",
            json={"action": "set_status", "status": "approved"},
        )
        assert appr.status_code == 200, f"approve -> {appr.status_code}"
        resp = c.get("/pack/r1")
        assert resp.status_code == 200, f"/pack/r1 -> {resp.status_code}"
        return resp.get_data(as_text=True)


@pytest.fixture
def toolbar_html(app_env) -> str:
    """The real per-card creative toolbar markup — the host for the reveal."""
    app, wm = app_env
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "alpha"})
    with app.test_request_context("/pack/r1"):
        return wm._render_card_creative_toolbar("r1", "swim-1")


# =========================================================================== #
# Layer 1 — CSS contract (theme-motion.css)
# =========================================================================== #
class TestRevealCss:
    def test_word_starts_hidden(self, motion_css):
        m = re.search(
            r"\.mh-js \.mh-text-generate \.mh-word\s*\{([^}]*)\}", motion_css
        )
        assert m, "no base .mh-text-generate .mh-word rule"
        body = m.group(1)
        assert "opacity: 0" in body          # hidden until revealed
        assert "filter: blur" in body        # the soft "writing" blur
        assert "translateY" in body          # rises into place

    def test_reveal_settles_visible_not_backwards(self, motion_css):
        """UI2.7's load-bearing fix: the words must STAY visible after the
        reveal. A `to`-only keyframe under `backwards` reverts each word to its
        hidden base style the instant its run ends — so the fill must be `both`.
        This is the regression guard against the latent kit bug."""
        m = re.search(
            r"\.mh-js \.mh-text-generate\.is-in \.mh-word\s*\{([^}]*)\}",
            motion_css,
        )
        assert m, "no .mh-text-generate.is-in .mh-word rule"
        body = m.group(1)
        anim = re.search(r"animation:\s*mh-word-in[^;]*;", body)
        assert anim, "the reveal animation must be mh-word-in"
        decl = anim.group(0)
        assert "both" in decl, f"reveal must settle visible (fill `both`): {decl!r}"
        assert "backwards" not in decl, (
            "fill `backwards` alone makes the revealed words vanish again"
        )
        assert "var(--i" in body, "stagger must key off the per-word --i index"

    def test_keyframe_lands_fully_visible(self, motion_css):
        m = re.search(r"@keyframes mh-word-in\s*\{(.*?)\}\s*\}", motion_css, re.DOTALL)
        # The keyframe block ends at the first standalone `}` after the `to {…}`.
        m = re.search(r"@keyframes mh-word-in\s*\{\s*to\s*\{([^}]*)\}", motion_css)
        assert m, "no mh-word-in keyframe"
        to = m.group(1)
        assert "opacity: 1" in to
        assert "blur(0)" in to
        assert "translateY(0)" in to

    def test_reduced_motion_shows_words_instantly(self, motion_css):
        """Reduced-motion visitors must get the full caption immediately, never
        a stuck-invisible word."""
        blocks = re.findall(
            r"@media \(prefers-reduced-motion: reduce\)\s*\{(.*?\.mh-text-generate.*?)\n\s*\}",
            motion_css,
            re.DOTALL,
        )
        joined = "\n".join(blocks)
        assert ".mh-text-generate .mh-word" in joined
        assert "opacity: 1" in joined
        assert "animation: none" in joined

    def test_motion_css_braces_balanced(self, motion_css):
        assert motion_css.count("{") == motion_css.count("}")

    def test_effect_rides_base_css(self):
        """Every page that uses the shared shell ships the effect (it lives in
        BASE_CSS), so the reveal is available wherever a caption renders."""
        assert ".mh-text-generate" in webmod.BASE_CSS
        assert "mh-word-in" in webmod.BASE_CSS


# =========================================================================== #
# Layer 2 — JS contract (web.py: _card_creative_js / _revealCaption)
# =========================================================================== #
class TestRevealJs:
    def test_helper_defined(self, creative_js):
        assert "function _revealCaption(host, text, animate)" in creative_js

    def test_reuses_kit_classes(self, reveal_js):
        assert "mh-text-generate" in reveal_js   # the kit effect host class
        assert "'mh-word'" in reveal_js           # the kit per-word class
        assert "setProperty('--i'" in reveal_js   # the kit stagger index
        assert "'is-in'" in reveal_js             # triggers the kit animation

    def test_tokeniser_preserves_whitespace(self, reveal_js):
        """Captions are multi-line (hashtags on their own lines); the kit's own
        splitWords collapses whitespace, so UI2.7 keeps whitespace runs as text
        nodes under white-space:pre-wrap."""
        assert r"\S+|\s+" in reveal_js            # word-run / whitespace-run split
        assert "createTextNode" in reveal_js      # whitespace kept verbatim

    def test_fails_safe_to_plain_text(self, reveal_js):
        # reduced-motion / animate=false / empty / error → plain, readable text.
        assert "prefers-reduced-motion: reduce" in reveal_js
        assert "if (!animate || reduce || !text)" in reveal_js
        assert "try {" in reveal_js and "catch (e)" in reveal_js
        # both the short-circuit and the catch fall back to plain textContent.
        assert reveal_js.count("host.textContent = text") >= 1

    def test_no_xss_uses_textcontent(self, reveal_js):
        # Words are written via textContent, never innerHTML — no escaping holes.
        assert "w.textContent = tokens[i]" in reveal_js
        assert "innerHTML" not in reveal_js

    def test_reveal_targets_readonly_body_only(self, creative_js):
        # The reveal only ever touches the read-only preview's body span.
        assert "_revealCaption(captionDiv.querySelector('.mh-caption-body')" in creative_js

    def test_editable_textarea_stays_plain(self, creative_js):
        # The editable caption is assigned plainly and is never passed to the
        # reveal helper.
        assert "textarea.value = active;" in creative_js
        assert "_revealCaption(textarea" not in creative_js
        assert "_revealCaption(panel.querySelector('.caption-textarea'" not in creative_js

    def test_animate_only_on_fresh_live_ai_write(self, creative_js):
        # The "AI is writing" gate: animate iff a fresh live AI caption arrived.
        assert "_renderActive(0, j.live === true);" in creative_js

    def test_variant_switch_does_not_reanimate(self, creative_js):
        # Browsing variants re-renders the preview plainly (animate=false).
        assert "_renderActive(parseInt(btn.dataset.idx, 10) || 0, false);" in creative_js

    @requires_node
    def test_toolbar_js_is_syntactically_valid(self, creative_js):
        js = re.sub(r"</?script[^>]*>", "", creative_js)
        with tempfile.NamedTemporaryFile(
            "w", suffix=".js", delete=False, encoding="utf-8"
        ) as f:
            f.write(js)
            path = f.name
        try:
            r = subprocess.run([_NODE, "--check", path], capture_output=True, text=True)
            assert r.returncode == 0, f"_card_creative_js invalid:\n{r.stderr}"
        finally:
            os.unlink(path)


# =========================================================================== #
# Layer 3 — rendered surface (/pack ships it; toolbar has both surfaces)
# =========================================================================== #
class TestRenderedSurface:
    def test_pack_ships_the_reveal_js(self, pack_html):
        assert "function _revealCaption(host, text, animate)" in pack_html

    def test_pack_ships_the_kit_css_and_loader(self, pack_html):
        # The effect CSS (via BASE_CSS) and the kit behaviour script + the JS-gate
        # class all ride onto the page.
        assert ".mh-text-generate" in pack_html
        assert "mh-word-in 560ms" in pack_html
        assert "js/ui-kit.js" in pack_html
        assert "classList.add('mh-js')" in pack_html

    def test_toolbar_has_readonly_preview(self, toolbar_html):
        # The read-only preview node the reveal animates, starting on a
        # placeholder (never an editable field).
        assert 'class="caption-text"' in toolbar_html
        assert "white-space:pre-wrap" in toolbar_html
        assert 'class="caption-placeholder"' in toolbar_html

    def test_toolbar_keeps_editable_caption_separate_and_hidden(self, toolbar_html):
        # The editable caption is a distinct, initially-hidden textarea — the
        # thing UI2.7 must NOT animate.
        assert 'class="caption-textarea"' in toolbar_html
        m = re.search(r'<textarea class="caption-textarea"[^>]*>', toolbar_html)
        assert m, "no .caption-textarea in the toolbar"
        assert "display:none" in m.group(0)


# =========================================================================== #
# Layer 4 — real browser behaviour (Playwright + pinned Chromium)
# =========================================================================== #
@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="chromium-1194 not at pinned path")
class TestRevealBrowserBehaviour:
    """Drive the real shipped toolbar JS in Chromium and prove the read-only
    preview reveals word-by-word and SETTLES visible, the editable caption stays
    plain, newlines survive, and reduced-motion stands the effect down."""

    def _doc(self, creative_js: str, motion_css: str, *, reduced: bool = False) -> str:
        """A minimal page carrying the kit CSS + the real toolbar JS + one
        faithful tone-panel (read-only .caption-text + hidden .caption-textarea),
        exactly as _render_card_creative_toolbar emits it."""
        return (
            "<!doctype html><html class=\"mh-js\"><head><meta charset=\"utf-8\">"
            "<style>:root{--ease-out:cubic-bezier(.16,1,.3,1);--ink:#fff;"
            "--ink-muted:#999;--accent:#d4ff3a;--border:#333;--ink-dim:#bbb;}</style>"
            f"<style>{motion_css}</style></head><body>"
            '<div class="tone-picker" id="wf-CARD" data-caption-url="/api/x" data-card="CARD">'
            '<div class="tone-panels" data-card="CARD">'
            '<div class="tone-panel" data-tone="ai" data-card="CARD">'
            '<div class="caption-text" style="font-size:12px;color:var(--ink);white-space:pre-wrap">'
            '<span class="caption-placeholder">Click to generate&hellip;</span></div>'
            '<textarea class="caption-textarea" dir="auto" style="display:none"></textarea>'
            "</div></div></div>"
            # Host for the direct _revealCaption unit drive:
            '<span id="host" style="white-space:pre-wrap"></span>'
            f"{creative_js}"
            "</body></html>"
        )

    # ---- _revealCaption unit drive ------------------------------------- #
    def test_reveal_settles_fully_visible(self, creative_js, motion_css):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(self._doc(creative_js, motion_css))
            page.wait_for_function("() => typeof window._revealCaption === 'function'")
            text = "Eira Hughes smashed a new personal best tonight"  # 8 words
            page.evaluate(
                "(t) => window._revealCaption(document.getElementById('host'), t, true)",
                text,
            )
            host = page.query_selector("#host")
            # The reveal split into per-word spans + the kit host class.
            n = page.evaluate("() => document.querySelectorAll('#host .mh-word').length")
            assert n == 8, f"expected 8 word spans, got {n}"
            assert "mh-text-generate" in (host.get_attribute("class") or "")
            assert "is-in" in (host.get_attribute("class") or "")
            # Wait past the WHOLE staggered run ((n-1)*55 + 560ms ≈ 945ms), then
            # assert every word is STILL fully opaque. Under the old `backwards`
            # fill each word would have reverted to opacity:0 by now.
            page.wait_for_timeout(1800)
            ops = page.evaluate(
                "() => Array.prototype.map.call("
                "document.querySelectorAll('#host .mh-word'),"
                "function(w){ return parseFloat(getComputedStyle(w).opacity); })"
            )
            assert ops and all(o > 0.99 for o in ops), f"words did not settle visible: {ops}"
            # Round-trips the text exactly.
            assert page.evaluate("() => document.getElementById('host').textContent") == text
        finally:
            browser.close()
            pw.stop()

    def test_reveal_preserves_newlines(self, creative_js, motion_css):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(self._doc(creative_js, motion_css))
            page.wait_for_function("() => typeof window._revealCaption === 'function'")
            text = "Big swims at Test Open!\n\n#AlphaSC #PB"
            page.evaluate(
                "(t) => window._revealCaption(document.getElementById('host'), t, true)",
                text,
            )
            page.wait_for_timeout(900)
            # The caption layout (the blank line before the hashtags) survives.
            got = page.evaluate("() => document.getElementById('host').textContent")
            assert got == text, f"newlines not preserved: {got!r}"
            # And the words still revealed as spans.
            assert page.evaluate(
                "() => document.querySelectorAll('#host .mh-word').length"
            ) >= 5
        finally:
            browser.close()
            pw.stop()

    def test_no_animate_renders_plain(self, creative_js, motion_css):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(self._doc(creative_js, motion_css))
            page.wait_for_function("() => typeof window._revealCaption === 'function'")
            page.evaluate(
                "() => window._revealCaption(document.getElementById('host'), 'plain caption', false)"
            )
            out = page.evaluate(r"""() => {
              var h = document.getElementById('host');
              return {
                words: h.querySelectorAll('.mh-word').length,
                cls: h.className,
                text: h.textContent
              };
            }""")
            assert out["words"] == 0, "animate=false must not split into words"
            assert "mh-text-generate" not in out["cls"]
            assert out["text"] == "plain caption"
        finally:
            browser.close()
            pw.stop()

    def test_reduced_motion_shows_caption_instantly(self, creative_js, motion_css):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.emulate_media(reduced_motion="reduce")
            page.set_content(self._doc(creative_js, motion_css))
            page.wait_for_function("() => typeof window._revealCaption === 'function'")
            assert page.evaluate(
                "() => matchMedia('(prefers-reduced-motion: reduce)').matches"
            ), "reduced-motion emulation did not take"
            text = "Reduced motion still reads the whole caption"
            page.evaluate(
                "(t) => window._revealCaption(document.getElementById('host'), t, true)",
                text,
            )
            page.wait_for_timeout(120)
            out = page.evaluate(r"""() => {
              var h = document.getElementById('host');
              // Whatever the path, the caption must be present and fully visible.
              var words = h.querySelectorAll('.mh-word');
              var ops = Array.prototype.map.call(words, function(w){
                return parseFloat(getComputedStyle(w).opacity); });
              return { text: h.textContent, hiddenWord: ops.some(function(o){ return o < 0.99; }) };
            }""")
            assert out["text"] == text
            assert not out["hiddenWord"], "no word may be stuck invisible under reduced-motion"
        finally:
            browser.close()
            pw.stop()

    # ---- _fetchCaption integration drive (stubbed network) ------------- #
    def _drive_fetch(self, page, resp: dict, tone: str, is_ai: bool):
        page.evaluate("(r) => { window.__RESP = r; }", resp)
        page.evaluate(
            """(args) => {
              window.fetch = function(){
                return Promise.resolve({ json: function(){ return Promise.resolve(window.__RESP); } });
              };
              var panel = document.querySelector('.tone-panel');
              window._fetchCaption('/api/x', args.tone, panel, 'CARD|' + args.tone, args.isAi, 'CARD');
            }""",
            {"tone": tone, "isAi": is_ai},
        )

    def test_live_caption_animates_preview_but_textarea_plain(self, creative_js, motion_css):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(self._doc(creative_js, motion_css))
            page.wait_for_function("() => typeof window._fetchCaption === 'function'")
            caption = "Eira Hughes took the 100m Free in 59.80!\n#AlphaSC"
            self._drive_fetch(page, {"caption": caption, "live": True}, "ai", True)
            # The read-only preview reveals word-by-word…
            page.wait_for_function(
                "() => document.querySelectorAll('.caption-text .mh-word').length > 0"
            )
            page.wait_for_timeout(1600)
            out = page.evaluate(r"""() => {
              var panel = document.querySelector('.tone-panel');
              var words = panel.querySelectorAll('.caption-text .mh-word');
              var ops = Array.prototype.map.call(words, function(w){
                return parseFloat(getComputedStyle(w).opacity); });
              return {
                nWords: words.length,
                allVisible: ops.length > 0 && ops.every(function(o){ return o > 0.99; }),
                previewText: panel.querySelector('.caption-text .mh-caption-body').textContent,
                textareaValue: panel.querySelector('.caption-textarea').value,
                textareaWords: panel.querySelectorAll('.caption-textarea .mh-word').length
              };
            }""")
            assert out["nWords"] >= 6, out
            assert out["allVisible"], f"live preview did not settle visible: {out}"
            assert out["previewText"] == caption          # newlines + text intact
            # …the EDITABLE caption gets the exact same text, PLAIN (no reveal).
            assert out["textareaValue"] == caption
            assert out["textareaWords"] == 0
        finally:
            browser.close()
            pw.stop()

    def test_deterministic_tone_renders_preview_plain(self, creative_js, motion_css):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(self._doc(creative_js, motion_css))
            page.wait_for_function("() => typeof window._fetchCaption === 'function'")
            caption = "Solid swimming from the Alpha squad today."
            # A deterministic voice render omits `live` — no "AI is writing" moment.
            self._drive_fetch(page, {"caption": caption, "tone": "warm-club"}, "warm-club", False)
            page.wait_for_function(
                "() => { var b = document.querySelector('.caption-text .mh-caption-body');"
                " return b && b.textContent.length > 0; }"
            )
            page.wait_for_timeout(120)
            out = page.evaluate(r"""() => {
              var panel = document.querySelector('.tone-panel');
              return {
                words: panel.querySelectorAll('.caption-text .mh-word').length,
                previewText: panel.querySelector('.caption-text .mh-caption-body').textContent,
                textareaValue: panel.querySelector('.caption-textarea').value
              };
            }""")
            assert out["words"] == 0, "deterministic tone must not type-on"
            assert out["previewText"] == caption
            assert out["textareaValue"] == caption
        finally:
            browser.close()
            pw.stop()

    def test_variant_switch_renders_plain(self, creative_js, motion_css):
        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(self._doc(creative_js, motion_css))
            page.wait_for_function("() => typeof window._fetchCaption === 'function'")
            self._drive_fetch(
                page,
                {"caption": "one two three", "variants": ["one two three", "four five six"], "live": True},
                "ai",
                True,
            )
            # First arrival animates.
            page.wait_for_function(
                "() => document.querySelectorAll('.caption-text .mh-word').length > 0"
            )
            # Switch to v2 — browsing, not a fresh write → plain re-render.
            page.click('.caption-text .cap-var-pill[data-idx="1"]')
            page.wait_for_function(
                "() => { var b = document.querySelector('.caption-text .mh-caption-body');"
                " return b && b.textContent.indexOf('four') !== -1; }"
            )
            out = page.evaluate(r"""() => {
              var panel = document.querySelector('.tone-panel');
              return {
                words: panel.querySelectorAll('.caption-text .mh-word').length,
                previewText: panel.querySelector('.caption-text .mh-caption-body').textContent
              };
            }""")
            assert out["words"] == 0, "switching variants must not re-run the type-on"
            assert out["previewText"] == "four five six"
        finally:
            browser.close()
            pw.stop()
