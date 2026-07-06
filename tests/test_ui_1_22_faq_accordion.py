"""UI 1.22 — FAQ accordion on the landing page (Limitless / status-page).

The landing page carries an expandable Q&A section — the objections a club
raises before it trusts the engine — built from *native* ``<details>`` /
``<summary>`` disclosure widgets. The roadmap is explicit about the shape:

    "Expandable Q&A section on the landing; pure HTML <details>/<summary>
     with CSS transition animation, no JS library."

So these tests pin three layers, mirroring tests/test_ui_1_3_inline_headline.py
and tests/test_u5_scroll_reveal.py:

  1. Unit — the ``_reveal_lines`` helper's new ``el_id`` hook (used to label
     the FAQ region) is byte-identical to the original when unused.
  2. Server-side — ``GET /`` renders the section in *both* hero variants
     (signed-out and pinned), with seven native disclosure rows, grounded
     answer copy, the right placement (after the promise panel, before the
     final CTA), no ``<script>`` / no JS fallback, and an accessible,
     same-origin, image-free region.
  3. CSS contract — the served stylesheet animates the open state with a
     ``grid-template-rows`` transition + a ``+/-`` marker, removes the native
     disclosure triangle, styles keyboard focus, and gates all motion behind
     ``prefers-reduced-motion`` (so a no-JS / reduced-motion / forced-colors
     visitor is never left with trapped or invisible content).
  4. Browser (Playwright, skipped when unavailable) — clicking a question
     genuinely opens its native disclosure and reveals the answer.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from mediahub.web import web as webmod

_ROOT = Path(__file__).resolve().parents[1]

# The seven questions the section must answer. Each entry is an
# apostrophe-free fragment of the question (markupsafe escapes ' -> &#39;, so
# the assertions stay copy-stable) plus a distinctive, grounded phrase from the
# answer that ties it back to a real MediaHub product principle.
FAQ_EXPECTATIONS = [
    ("Does anything post to our socials automatically", "not an auto-poster"),
    ("Will it ever invent a time or a result", "grounded in the result line"),
    ("What files can we upload", "HY3, SDIF, SportSystems"),
    ("How does it learn our club brand", "re-train a shared model"),
    ("What can it produce from one upload", "branded motion reels"),
    ("Which sports does it work for", "sport-agnostic"),
    ("Is our athlete data kept private", "auto-publishes"),
]

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


# --------------------------------------------------------------------------- #
# Fixtures — an isolated app with one saved org so we can exercise both the
# signed-out and the pinned-org hero variants (the FAQ must show in both).
# --------------------------------------------------------------------------- #
@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs", "uploads", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import importlib

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
        assert resp.status_code == 200, f"GET / -> {resp.status_code}"
        return resp.get_data(as_text=True)


def _help(application, *, pinned: bool = False) -> str:
    """The Help page — where the product-story explainer (incl. the FAQ) now
    lives after the signed-in home became a content-creation workspace."""
    with application.test_client() as c:
        if pinned:
            with c.session_transaction() as s:
                s["active_profile_id"] = "test-org"
        resp = c.get("/help")
        assert resp.status_code == 200, f"GET /help -> {resp.status_code}"
        return resp.get_data(as_text=True)


def _theme_css(application) -> str:
    """Fetch the stylesheet *as served* — proves the rules ship, not just that
    they sit in the source file."""
    with application.test_client() as c:
        resp = c.get("/static/theme/theme-components.css")
        assert resp.status_code == 200
        assert "css" in resp.content_type, resp.content_type
        return resp.get_data(as_text=True)


def _faq_section(body: str) -> str:
    """Slice out just the FAQ <section>. It contains no nested <section>, so the
    first closing tag after its open tag bounds it exactly."""
    start = body.find('<section class="mh-section mh-faq"')
    assert start != -1, "FAQ section not found on the home page"
    end = body.find("</section>", start)
    assert end != -1, "FAQ section is not closed"
    return body[start : end + len("</section>")]


def _faq_css_block(css: str) -> str:
    """Just the UI 1.22 stanza of the stylesheet (between its banner comment and
    the next component's), so selector assertions can't accidentally match an
    unrelated rule elsewhere in the sheet."""
    start = css.find("UI 1.22")
    assert start != -1, "UI 1.22 CSS banner not found"
    end = css.find("FINAL-CTA STRIP", start)
    assert end != -1, "could not bound the FAQ CSS block"
    return css[start:end]


# =========================================================================== #
# 1) Unit — the _reveal_lines el_id hook used to label the FAQ region
# =========================================================================== #
class TestRevealLinesElId:
    def test_no_el_id_is_byte_identical(self):
        # The FAQ reuse must not perturb every other reveal-lines headline.
        assert (
            webmod._reveal_lines(["a"])
            == '<h2 class="mh-section-title mh-reveal-lines">'
            '<span class="mh-line">a</span></h2>'
        )
        assert "id=" not in webmod._reveal_lines(["a"])

    def test_el_id_stamps_an_id_on_the_heading(self):
        html = webmod._reveal_lines(["q"], cls="mh-faq-title", el_id="mh-faq-h")
        assert html.startswith('<h2 id="mh-faq-h" class="mh-faq-title mh-reveal-lines">')
        assert html.count('<span class="mh-line">') == 1


# =========================================================================== #
# 2) Server-side — the section renders, with the right structure
# =========================================================================== #
class TestFaqOnPage:
    def test_section_present_signed_out(self, app):
        body = _home(app)
        assert '<section class="mh-section mh-faq"' in body
        assert 'aria-labelledby="mh-faq-h"' in body
        assert 'id="mh-faq-h"' in body

    def test_section_present_on_help_page(self, app):
        # The FAQ is product-story explainer. It moved off the signed-in home
        # (now a content-creation workspace) onto the Help page, reached from
        # the account menu — it must still render there in full.
        body = _help(app, pinned=True)
        assert '<section class="mh-section mh-faq"' in body
        assert _faq_section(body).count('<details class="mh-faq-item">') == 7

    def test_section_absent_from_signed_in_home(self, app):
        # A returning, pinned organisation gets the workspace home, not the
        # pitch: the FAQ (and the rest of the explainer) is no longer there.
        body = _home(app, pinned=True)
        assert "Test Org" in body, "pinned hero variant did not run"
        assert '<section class="mh-section mh-faq"' not in body

    def test_eyebrow_and_editorial_headline(self, app):
        sec = _faq_section(_home(app))
        assert "mh-section-eyebrow-strip mh-reveal" in sec
        assert "Common questions" in sec
        # Editorial reveal-lines headline with the gold accent word.
        assert "mh-faq-title mh-reveal-lines" in sec
        assert "The questions clubs" in sec
        assert "ask us" in sec
        assert '<em class="editorial">first</em>' in sec

    def test_seven_native_disclosure_rows(self, app):
        sec = _faq_section(_home(app))
        assert sec.count('<details class="mh-faq-item">') == 7
        assert sec.count('<summary class="mh-faq-q">') == 7
        # Each row carries an answer panel wrapped for the grid-rows animation.
        assert sec.count('class="mh-faq-a"') == 7
        assert sec.count("mh-faq-a-inner") == 7

    def test_each_row_has_question_text_and_answer(self, app):
        sec = _faq_section(_home(app))
        questions = re.findall(
            r'<span class="mh-faq-q-text">(.*?)</span>', sec, flags=re.S
        )
        assert len(questions) == 7
        assert all(q.strip() for q in questions), "an FAQ question is empty"
        answers = re.findall(
            r'<div class="mh-faq-a-inner"><p>(.*?)</p>', sec, flags=re.S
        )
        assert len(answers) == 7
        assert all(len(a.strip()) > 40 for a in answers), "an FAQ answer is too thin"

    def test_marker_icon_is_decorative(self, app):
        sec = _faq_section(_home(app))
        assert sec.count('<span class="mh-faq-icon" aria-hidden="true"></span>') == 7


class TestFaqContent:
    def test_all_seven_questions_present(self, app):
        body = _home(app)
        for question, _answer in FAQ_EXPECTATIONS:
            assert question in body, f"missing FAQ question: {question!r}"

    def test_answers_are_grounded_in_real_principles(self, app):
        body = _home(app)
        for _question, answer_phrase in FAQ_EXPECTATIONS:
            assert answer_phrase in body, f"missing grounded answer: {answer_phrase!r}"

    def test_human_in_the_loop_is_answered_first(self, app):
        # The single most important objection (does it auto-post?) leads.
        sec = _faq_section(_home(app))
        first = sec.find("mh-faq-q-text")
        assert first != -1
        assert "Does anything post to our socials automatically" in sec[first : first + 120]


class TestFaqIsPureHtmlNoJs:
    """The roadmap requires pure HTML <details>/<summary> with CSS animation —
    no JS library, no scripted fallback inside the section."""

    def test_section_carries_no_script(self, app):
        assert "<script" not in _faq_section(_home(app))

    def test_uses_native_disclosure_not_a_scripted_button(self, app):
        sec = _faq_section(_home(app))
        assert "<details" in sec and "<summary" in sec
        # No ARIA-button / scripted accordion fallback — the native element
        # already exposes expanded/collapsed state to assistive tech.
        assert "<button" not in sec
        assert 'role="button"' not in sec
        assert "aria-expanded" not in sec
        assert "onclick" not in sec


class TestFaqPlacement:
    def test_after_promise_before_final_cta(self, app):
        body = _home(app)
        i_hero = body.find('class="mh-hero"')
        i_promise = body.find('class="mh-promise"')
        i_faq = body.find('class="mh-section mh-faq"')
        i_final = body.find('class="mh-final-cta')
        assert -1 < i_hero < i_promise < i_faq < i_final, (
            i_hero,
            i_promise,
            i_faq,
            i_final,
        )


class TestFaqAccessibilityAndIsolation:
    def test_region_is_labelled_by_its_heading(self, app):
        body = _home(app)
        sec = _faq_section(body)
        assert 'aria-labelledby="mh-faq-h"' in sec
        # the referenced id must actually exist on the heading
        assert re.search(r'<h2 id="mh-faq-h"[^>]*class="mh-faq-title', sec)

    def test_no_external_or_image_resources_in_section(self, app):
        sec = _faq_section(_home(app))
        assert "http://" not in sec and "https://" not in sec
        assert "<img" not in sec
        assert "googleapis" not in sec and "gstatic" not in sec


# =========================================================================== #
# 3) Served CSS — the animation + a11y + reduced-motion contract
# =========================================================================== #
class TestFaqCss:
    def test_core_rules_ship(self, app):
        block = _faq_css_block(_theme_css(app))
        for sel in (
            ".mh-faq",
            ".mh-faq-title",
            ".mh-faq-list",
            ".mh-faq-item",
            ".mh-faq-q",
            ".mh-faq-a",
            ".mh-faq-a-inner",
            ".mh-faq-icon",
        ):
            assert sel in block, f"missing CSS rule {sel}"

    def test_native_disclosure_triangle_is_removed(self, app):
        block = _faq_css_block(_theme_css(app))
        assert ".mh-faq-q::-webkit-details-marker { display: none; }" in block
        assert ".mh-faq-q::marker" in block  # Firefox list-marker reset

    def test_open_state_animates_height_via_grid_rows(self, app):
        block = _faq_css_block(_theme_css(app))
        assert "grid-template-rows: 0fr" in block
        assert "transition: grid-template-rows" in block
        assert re.search(
            r"\.mh-faq-item\[open\] \.mh-faq-a \{\s*grid-template-rows: 1fr;", block
        )
        # the inner wrapper clips while the row collapses
        assert re.search(r"\.mh-faq-a-inner \{[^}]*overflow: hidden", block)

    def test_marker_collapses_to_a_minus_on_open(self, app):
        block = _faq_css_block(_theme_css(app))
        assert re.search(
            r"\.mh-faq-item\[open\] \.mh-faq-icon::after \{[^}]*scaleY\(0\)", block
        )

    def test_question_uses_brand_display_font(self, app):
        block = _faq_css_block(_theme_css(app))
        head = block[block.find(".mh-faq-q {") :]
        head = head[: head.find("}")]
        assert "var(--font-display)" in head

    def test_keyboard_focus_is_visible(self, app):
        block = _faq_css_block(_theme_css(app))
        assert ".mh-faq-q:focus-visible" in block
        focus = block[block.find(".mh-faq-q:focus-visible") :]
        focus = focus[: focus.find("}")]
        assert "outline" in focus

    def test_motion_is_reduced_motion_gated(self, app):
        block = _faq_css_block(_theme_css(app))
        assert "@media (prefers-reduced-motion: reduce)" in block
        rm = block[block.find("@media (prefers-reduced-motion: reduce)") :]
        assert ".mh-faq-a" in rm
        assert "transition: none" in rm

    def test_marker_stays_visible_in_forced_colors(self, app):
        # This rule lives in the global forced-colors @media block, not the FAQ
        # stanza, so search the whole served sheet.
        css = _theme_css(app)
        assert re.search(
            r"\.mh-faq-icon::before, \.mh-faq-icon::after \{ background: CanvasText; \}",
            css,
        )


# =========================================================================== #
# 4) Browser — clicking a question opens its native disclosure
# =========================================================================== #
@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="prebaked chromium not found")
class TestFaqBrowser:
    def _launch(self):
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            executable_path=str(_PINNED_CHROMIUM),
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        return pw, browser

    def test_clicking_a_question_reveals_its_answer(self, app):
        body = _home(app)
        pw, browser = self._launch()
        try:
            page = browser.new_page(viewport={"width": 1100, "height": 800})
            page.set_content(body)
            page.wait_for_load_state("domcontentloaded")
            first_item = page.locator(".mh-faq-item").first
            answer = first_item.locator(".mh-faq-a-inner p")
            # Closed by default → native <details> keeps the answer hidden.
            assert first_item.get_attribute("open") is None
            assert not answer.is_visible()
            # Click the question → native disclosure opens, answer shows.
            first_item.locator("summary").click()
            assert first_item.get_attribute("open") is not None
            assert answer.is_visible()
            # Click again → closes.
            first_item.locator("summary").click()
            assert first_item.get_attribute("open") is None
        finally:
            browser.close()
            pw.stop()
