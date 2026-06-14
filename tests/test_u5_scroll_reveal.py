"""U.5 — Scroll-driven progressive (line-by-line) reveal on the landing page.

Pins the U.5 deliverable: the landing sections reveal *line-by-line* as they
scroll up through the viewport (inspired by Opal, op.al), on the existing
dark-first editorial theme, using only the Phase-10 IntersectionObserver — no
new dependency, no client framework.

U.5 is presentation-only. It adds one reveal primitive on top of the shipped
Phase-10 motion system:

  ``.mh-reveal-lines``  — a heading whose ``.mh-line`` children are each
      observed *individually* by ``bindReveals`` (so a section's headline
      surfaces line after line as you scroll, rather than all at once like the
      one-shot ``.mh-reveal-group`` stagger). A small per-line CSS delay keeps
      the cascade gentle when tightly-stacked lines cross the trigger together.

Two guarantees the codebase already holds and U.5 must not break:
  * Progressive enhancement — the hidden state is gated by ``.mh-js`` on
    <html>, so no-JS visitors and the ``prefers-reduced-motion`` cohort always
    see fully-visible content; a 1.5 s safety timer guarantees nothing can stay
    stuck hidden even if a scroll never happens or the observer misfires.
  * The deterministic engine is untouched — this is landing-page chrome only.

Three layers of assertion, mirroring tests/test_activity_count_up.py:
  1. Unit — the ``_reveal_lines`` helper renders the line markup.
  2. Server-side — ``GET /`` carries the line-reveal markup (both the
     signed-out and the pinned-org hero variants), and the served CSS/JS carry
     the primitive + its reduced-motion guard.
  3. Browser (Playwright, skipped when unavailable) — the lines actually start
     hidden below the fold, reveal on scroll, settle fully visible (nothing
     stuck), and are shown immediately under reduced-motion.
"""

from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path

import pytest

from mediahub.web import web as webmod

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_SKIP_BROWSER = os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower() in (
    "1",
    "true",
    "yes",
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


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def app(tmp_path, monkeypatch):
    """Isolated Flask app with one saved, ready organisation (for the pinned
    hero variant). Mirrors tests/test_activity_count_up.py."""
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

    application = wm.create_app()
    application.config["TESTING"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="test-org",
            display_name="Test Org",
            brand_voice_summary="Testing.",
            brand_capture_status="ok",
        )
    )
    return application


def _home(application, *, pinned: bool = False) -> str:
    with application.test_client() as c:
        if pinned:
            with c.session_transaction() as s:
                s["active_profile_id"] = "test-org"
        resp = c.get("/")
        assert resp.status_code == 200, f"GET / → {resp.status_code}"
        return resp.get_data(as_text=True)


def _theme_css(application) -> str:
    with application.test_client() as c:
        resp = c.get("/static/theme/theme-components.css")
        assert resp.status_code == 200
        return resp.get_data(as_text=True)


# =========================================================================== #
# 1) Unit — the _reveal_lines helper
# =========================================================================== #
class TestRevealLinesHelper:
    def test_default_heading_wraps_each_line_in_a_span(self):
        html = webmod._reveal_lines(["First line", "Second line"])
        assert html.startswith('<h2 class="mh-section-title mh-reveal-lines">')
        assert html.endswith("</h2>")
        assert html.count('<span class="mh-line">') == 2
        assert "<span class=\"mh-line\">First line</span>" in html
        assert "<span class=\"mh-line\">Second line</span>" in html

    def test_custom_tag_and_class(self):
        html = webmod._reveal_lines(
            ["A", "B", "C"], tag="h2", cls="mh-promise-title"
        )
        assert 'class="mh-promise-title mh-reveal-lines"' in html
        assert html.count('<span class="mh-line">') == 3

    def test_editorial_accent_fragment_preserved_verbatim(self):
        # lines are TRUSTED HTML fragments (static product copy) — the helper
        # must not double-escape the <em class="editorial"> accent markup.
        html = webmod._reveal_lines(
            ["plain", '<em class="editorial">gold word</em>']
        )
        assert '<em class="editorial">gold word</em>' in html
        assert "&lt;em" not in html

    def test_single_line(self):
        assert webmod._reveal_lines(["Only one"]).count('class="mh-line"') == 1

    def test_empty_is_safe(self):
        # Defensive: an empty heading still produces a valid, empty container.
        html = webmod._reveal_lines([])
        assert html == '<h2 class="mh-section-title mh-reveal-lines"></h2>'


# =========================================================================== #
# 2a) Server-side — signed-out hero variant carries the line-reveal markup
# =========================================================================== #
class TestHomeSignedOut:
    def test_every_section_headline_is_a_reveal_lines_block(self, app):
        body = _home(app)
        # steps + before/after + bento + audience + promise + final-CTA(fresh)
        # = 6 reveal-lines headlines. (The before/after slider's headline was
        # reconciled onto the U.5 pattern so no plain section-title survives.)
        assert body.count("mh-reveal-lines") >= 5
        # The legacy single-run section title (no reveal-lines) is gone.
        assert '<h2 class="mh-section-title">' not in body
        assert '<h2 class="mh-section-title mh-reveal-lines">' in body

    def test_line_spans_two_per_headline(self, app):
        # Each of the 6 reveal-lines headlines is split into exactly two
        # editorial lines (steps, before/after, bento, audience, promise,
        # final-CTA) → 12 line spans.
        body = _home(app)
        assert body.count('<span class="mh-line">') == 12

    def test_section_eyebrows_and_ledes_reveal_on_scroll(self, app):
        body = _home(app)
        # The four content-section eyebrows now reveal (were static before):
        # steps, before/after, bento, audience.
        assert body.count("mh-section-eyebrow-strip mh-reveal") == 4
        # Promise lede + final-CTA sub reveal as their own blocks.
        assert "mh-promise-lede mh-reveal" in body
        assert "mh-final-cta-sub mh-reveal" in body

    def test_rows_keep_their_group_stagger(self, app):
        body = _home(app)
        # The card/step rows + the promise list stagger via .mh-reveal-group.
        assert "mh-steps mh-reveal-group" in body
        assert "mh-bento mh-reveal-group" in body
        assert "mh-audience-row mh-reveal-group" in body
        assert "mh-promise-list mh-reveal-group" in body
        # The promise section is no longer one big block reveal.
        assert '<section class="mh-section mh-reveal">' not in body

    def test_headline_copy_and_accents_intact(self, app):
        body = _home(app)
        # The marketing copy survived the split into lines …
        for frag in (
            "From the results sheet to",
            "A results sheet in.",
            "of content out.",
            "Built for the people who",
            "Human in the loop,",
            "A minute to set up.",
        ):
            assert frag in body, frag
        # … and the gold editorial accents still ride inside their lines.
        for em in (
            '<em class="editorial">posting-ready</em>',
            '<em class="editorial">weekend</em>',
            '<em class="editorial">post the results</em>',
            "<em>by design</em>",
            "<em>Then</em>",
        ):
            assert em in body, em


# =========================================================================== #
# 2b) Server-side — pinned-org hero variant (the OTHER final-CTA branch)
# =========================================================================== #
class TestHomePinned:
    def test_pinned_final_cta_headline_is_reveal_lines(self, app):
        body = _home(app, pinned=True)
        # Sanity: the pinned branch actually ran.
        assert "Test Org" in body
        # Final-CTA variant A headline split into reveal lines.
        assert 'class="mh-final-cta-headline mh-reveal-lines"' in body
        assert "Next weekend&#39;s meet," in body or "Next weekend's meet," in body
        assert "in a sitting." in body
        assert "mh-final-cta-sub mh-reveal" in body


# =========================================================================== #
# 2c) Served CSS — the primitive + its no-JS / reduced-motion gating
# =========================================================================== #
class TestRevealLinesCss:
    def test_hidden_state_is_gated_by_mh_js(self, app):
        css = _theme_css(app)
        # The hidden (animated-in) state only applies under .mh-js, so a no-JS
        # visitor is never left with invisible content.
        assert ".mh-js .mh-reveal-lines > *" in css
        # There is no UNGATED rule that hides the lines.
        assert not re.search(r"(?<!\.mh-js )\.mh-reveal-lines > \*\s*\{[^}]*opacity:\s*0", css)

    def test_lines_stack_without_js(self, app):
        # display:block (the line LAYOUT) must NOT be gated by .mh-js — a no-JS
        # visitor still needs the line breaks, since the declared lines carry no
        # joining space and would otherwise render as inline run-on text.
        css = _theme_css(app)
        assert re.search(r"(?<!\.mh-js )\.mh-reveal-lines > \*\s*\{\s*display: block", css)

    def test_lines_rise_when_animated(self, app):
        css = _theme_css(app)
        block = css.split(".mh-js .mh-reveal-lines > *", 1)[1].split("}", 1)[0]
        assert "opacity: 0" in block
        assert "translateY(0.5em)" in block       # em-relative rise
        assert "display: block" not in block       # layout lives in the ungated rule

    def test_is_in_reveals(self, app):
        css = _theme_css(app)
        assert ".mh-js .mh-reveal-lines > .is-in" in css

    def test_per_line_cascade_delays(self, app):
        css = _theme_css(app)
        for nth in (2, 3, 4):
            assert f".mh-reveal-lines > .is-in:nth-child({nth})" in css

    def test_reveal_lines_titles_drop_the_tight_measure(self, app):
        css = _theme_css(app)
        assert ".mh-section-title.mh-reveal-lines { max-width: none; }" in css

    def test_reduced_motion_neutralises_the_lines(self, app):
        css = _theme_css(app)
        # The Phase-10 reduced-motion block resets the line reveal too. Match a
        # prefers-reduced-motion block whose (multi-line) selector list covers
        # .mh-reveal-lines and whose body forces full visibility. [^}] lets the
        # match span the comma-separated selectors + the rule's opening brace.
        assert re.search(
            r"@media \(prefers-reduced-motion: reduce\) \{"
            r"[^}]*\.mh-js \.mh-reveal-lines > \*[^}]*opacity: 1 !important",
            css,
        ), "reveal-lines is not neutralised under prefers-reduced-motion"


# =========================================================================== #
# 2d) Inlined JS — bindReveals observes each line individually
# =========================================================================== #
class TestBindRevealsJs:
    def test_observes_reveal_lines_children(self, app):
        body = _home(app)
        assert "querySelectorAll('.mh-reveal-lines')" in body
        # each direct child (a line) is pushed and observed on its own
        assert "grp.children" in body
        assert "lineItems" in body

    def test_counters_inside_lines_are_not_double_animated(self, app):
        body = _home(app)
        # the counter-exclusion selector was broadened to include reveal-lines
        assert "'.mh-reveal, .mh-reveal-group, .mh-reveal-lines'" in body

    def test_safety_net_still_present(self, app):
        # The "nothing stays hidden" timer must survive the change.
        body = _home(app)
        assert "1500" in body and "Safety net" in body


# =========================================================================== #
# 3) Browser — the reveal actually behaves (scroll-driven + safe)
# =========================================================================== #
def _launch_browser():
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        executable_path=str(_PINNED_CHROMIUM),
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    return pw, browser


_LINE_STATES = """() => {
    const lines = Array.from(document.querySelectorAll('.mh-reveal-lines > .mh-line'));
    return lines.map(el => {
        const cs = getComputedStyle(el);
        return { isIn: el.classList.contains('is-in'), opacity: parseFloat(cs.opacity) };
    });
}"""


@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="chromium-1194 not at pinned path")
class TestRevealLinesBrowser:
    def test_reduced_motion_shows_every_line_immediately(self, app):
        body = _home(app)
        pw, browser = _launch_browser()
        try:
            page = browser.new_page(
                viewport={"width": 1100, "height": 700}, reduced_motion="reduce"
            )
            page.set_content(body)
            page.wait_for_load_state("domcontentloaded")
            states = page.evaluate(_LINE_STATES)
        finally:
            browser.close()
            pw.stop()
        assert states, "no reveal lines rendered"
        for s in states:
            assert s["opacity"] >= 0.99, f"reduced-motion line hidden: {s}"

    def test_lines_start_hidden_then_reveal_on_scroll(self, app):
        # Target the DEEPEST line: it starts hidden below the fold, then
        # reveals once scrolled into view — and crucially this happens well
        # within the 1.5 s safety net, so the reveal is genuinely scroll-driven
        # (not the fallback timer). We scroll that one element into view rather
        # than jumping to scrollHeight, because an instant jump can skip past
        # intermediate elements without the observer ever firing for them.
        body = _home(app)
        pw, browser = _launch_browser()
        _deepest = """() => {
            const lines = document.querySelectorAll('.mh-reveal-lines > .mh-line');
            const el = lines[lines.length - 1];
            return { isIn: el.classList.contains('is-in'),
                     opacity: parseFloat(getComputedStyle(el).opacity) };
        }"""
        try:
            # Short viewport so the deeper sections sit below the fold on load.
            page = browser.new_page(viewport={"width": 1100, "height": 560})
            page.set_content(body)
            page.wait_for_load_state("domcontentloaded")
            # Read immediately (well within the safety net): some below-fold
            # lines — including the deepest — must NOT yet be revealed.
            initial = page.evaluate(_LINE_STATES)
            deepest_before = page.evaluate(_deepest)
            page.evaluate("""() => {
                const lines = document.querySelectorAll('.mh-reveal-lines > .mh-line');
                lines[lines.length - 1].scrollIntoView({block: 'center'});
            }""")
            page.wait_for_timeout(400)  # < safety net → scroll-driven, not the timer
            deepest_after = page.evaluate(_deepest)
        finally:
            browser.close()
            pw.stop()
        assert initial, "no reveal lines rendered"
        assert any(not s["isIn"] for s in initial), (
            "expected some below-fold lines to start hidden before any scroll"
        )
        assert not deepest_before["isIn"], (
            "deepest line should start hidden below the fold"
        )
        assert deepest_after["isIn"], (
            "deepest line did not reveal after being scrolled into view"
        )

    def test_no_js_lines_stack_vertically(self, app):
        # Regression guard: with JavaScript disabled (.mh-js never added) the
        # declared lines must still stack as separate lines — not collapse onto
        # one run-on line (the splits carry no joining space). Verified via
        # layout boxes, since evaluate() is unavailable with JS off.
        body = _home(app)
        pw, browser = _launch_browser()
        try:
            ctx = browser.new_context(
                java_script_enabled=False, viewport={"width": 1100, "height": 800}
            )
            page = ctx.new_page()
            page.set_content(body)
            block = page.query_selector(".mh-reveal-lines")
            spans = block.query_selector_all(".mh-line")
            boxes = [s.bounding_box() for s in spans]
        finally:
            browser.close()
            pw.stop()
        assert len(boxes) >= 2 and all(boxes), "reveal-lines block has < 2 measurable lines"
        # Line 2 sits clearly below line 1 → stacked, not inline run-on text.
        assert boxes[1]["y"] >= boxes[0]["y"] + boxes[0]["height"] * 0.5, (
            f"no-JS reveal lines did not stack vertically: {boxes}"
        )

    def test_nothing_stays_stuck_hidden(self, app):
        # Even with NO scroll, the 1.5 s safety net must reveal everything —
        # content can never be permanently hidden.
        body = _home(app)
        pw, browser = _launch_browser()
        try:
            page = browser.new_page(viewport={"width": 1100, "height": 560})
            page.set_content(body)
            page.wait_for_load_state("domcontentloaded")
            # Safety net adds .is-in at 1500 ms, then each line fades over
            # 600 ms (+ up to a 90 ms per-line delay). Wait past all of it so
            # the opacity transition has fully settled to 1.
            page.wait_for_timeout(2500)
            states = page.evaluate(_LINE_STATES)
        finally:
            browser.close()
            pw.stop()
        assert states, "no reveal lines rendered"
        for s in states:
            assert s["isIn"], f"line stuck hidden after safety net: {s}"
            assert s["opacity"] >= 0.99, f"line not fully visible: {s}"
