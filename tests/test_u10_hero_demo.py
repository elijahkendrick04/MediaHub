"""U.10 — framed in-app product demo in the landing hero.

Pins the U.10 deliverable (presentation-only; the deterministic engine, AI
surfaces and explainability logic are untouched): a browser-framed mockup in
the hero that loops the core flow **generate → review → approve** with a
subtle ambient glow behind it. Inspired by Reflect (reflect.app).

The contract these tests defend:

  * the demo is built by ``_hero_product_demo()`` and emits stable hooks for
    the frame, the ambient glow, three cross-fading scenes (with the Review
    scene marked as the resting frame), and a three-step indicator;
  * it is first-party and self-contained — no screen-capture asset, no
    ``<script>``/``<video>``/``<iframe>``, no fonts CDN — so it can never
    drag in an external dependency or trip the self-hosted-fonts guard;
  * it is decorative and ``aria-hidden`` (the same workflow is real text in
    the four-step explainer), so it adds no screen-reader noise;
  * it is shown to fresh / signed-out visitors only — a pinned, ready org
    gets the utilitarian "Ready to file" hero instead;
  * the CSS loop is pure keyframes: the step-indicator dots reuse the *same*
    p1/p2/p3 scene tracks (so the indicator can never desync), it pauses on
    hover/focus, and under ``prefers-reduced-motion`` it freezes on the
    single Review scene with no movement at all.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# --------------------------------------------------------------------------- #
# App fixture (modelled on tests/test_capture_profile_reuse.py) — a tmp
# DATA_DIR with no LLM keys and the web + profile modules reloaded so saved
# profiles land under the temp dir.
# --------------------------------------------------------------------------- #
@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    application = wm.create_app()
    application.config["TESTING"] = True
    return application


def _seed_ready(profile_id="otter-sc", display_name="Otter SC"):
    """Save a genuinely is_ready() profile (name + a brand voice signal)."""
    from mediahub.web.club_profile import ClubProfile, load_profile, save_profile

    save_profile(
        ClubProfile(
            profile_id=profile_id,
            display_name=display_name,
            brand_voice_summary="Friendly competitive club.",
        )
    )
    assert load_profile(profile_id).is_ready(), "seed profile should be ready"
    return profile_id


def _demo_html() -> str:
    from mediahub.web import web as webmod

    return webmod._hero_product_demo()


def _components_css() -> str:
    from mediahub.web.theme_tokens import THEME_COMPONENTS_CSS

    return THEME_COMPONENTS_CSS


def _u10_css_section() -> str:
    """The U.10 slice of the components stylesheet, bounded by its banner
    comment and the next section header — so every CSS assertion is scoped to
    this feature and can't pass on a coincidental match elsewhere."""
    css = _components_css()
    start = css.index("U.10 — FRAMED IN-APP PRODUCT DEMO")
    end = css.index("PHASE 13 — EMPTY / ERROR", start)
    return css[start:end]


# =========================================================================== #
# Group A — the helper renders the designed, self-contained mockup
# =========================================================================== #
def test_helper_emits_frame_glow_and_three_scenes():
    html = _demo_html()
    assert '<div class="mh-hero-demo"' in html       # the wrapper hook
    assert '<div class="mh-demo-glow"></div>' in html  # ambient glow element
    assert '<div class="mh-demo-frame">' in html      # the browser frame
    # Three cross-fading scenes, in order, with Review marked as the rest.
    assert '<div class="mh-demo-phase p1">' in html
    assert '<div class="mh-demo-phase p2 is-rest">' in html
    assert '<div class="mh-demo-phase p3">' in html
    assert html.index('class="mh-demo-phase p1"') < html.index('class="mh-demo-phase p2')
    assert html.index('class="mh-demo-phase p2') < html.index('class="mh-demo-phase p3"')


def test_helper_emits_three_step_indicator_reusing_scene_ids():
    html = _demo_html()
    for s in ("s1", "s2", "s3"):
        assert f'<span class="mh-demo-step {s}">' in html
        # each step carries the dot + the animated "on" overlay the CSS lights
        assert '<span class="dot"><i class="on"></i></span>' in html


def test_helper_conveys_the_generate_review_approve_flow():
    html = _demo_html()
    # The workflow words appear in step order.
    g, r, a = html.index("Generate"), html.index("Review"), html.index("Approve")
    assert g < r < a
    # The scene eyebrows name the numbered steps too.
    for label in ("01 · Generate", "02 · Review", "03 · Approve"):
        assert label in html


def test_helper_review_scene_shows_card_caption_and_confidence():
    html = _demo_html()
    assert '<div class="mh-demo-card">' in html              # a branded card
    assert '<p class="mh-demo-caption">' in html             # a caption draft
    assert "<mark>" in html                                  # grounded entities
    assert "0.94" in html                                    # a confidence score
    # The approval scene shows the human gate and the honest promise.
    assert "Approved by you" in html
    assert "Nothing leaves the queue without your approval." in html


def test_helper_is_decorative_and_aria_hidden():
    html = _demo_html()
    # Hidden from assistive tech (the four-step explainer carries the text).
    assert html.startswith('<div class="mh-hero-demo" aria-hidden="true">')


def test_helper_is_first_party_and_static():
    """No screen-capture asset, no scripting, no external fetch, no fonts CDN
    — the whole demo is self-contained HTML/CSS."""
    html = _demo_html()
    for forbidden in (
        "<script",
        "<video",
        "<iframe",
        "<img",
        "src=",
        "http://",
        "https://",
        "googleapis",
        "gstatic",
    ):
        assert forbidden not in html, f"demo must not contain {forbidden!r}"


def test_helper_markup_is_balanced():
    html = _demo_html()
    assert html.count("<div") == html.count("</div>")
    assert html.count("<span") == html.count("</span>")
    # The only self-closing leaf elements are the <i> dots/fills and one <svg>.
    assert html.count("<svg") == html.count("</svg>") == 1


def test_helper_reuses_the_sample_examples_for_cohesion():
    """The demo reuses the same showcase athlete/time as the 'what lands in
    your queue' sample row, so the landing page tells one coherent story."""
    html = _demo_html()
    assert "Tom Davies" in html
    assert "52.41" in html


# =========================================================================== #
# Group B — home-page integration + the fresh-visitor-only gate
# =========================================================================== #
def test_home_fresh_visitor_shows_demo_inside_the_hero(app):
    with app.test_client() as c:
        body = c.get("/").get_data(as_text=True)
    el = '<div class="mh-hero-demo"'
    assert body.count(el) == 1, "demo should appear exactly once"
    hero_start = body.index('<section class="mh-hero"')
    hero_end = body.index("</section>", hero_start)
    assert hero_start < body.index(el) < hero_end, "demo must live inside the hero"


def test_home_still_renders_the_rest_of_the_landing(app):
    """Regression: inserting the demo didn't break the existing sections."""
    with app.test_client() as c:
        body = c.get("/").get_data(as_text=True)
    for hook in (
        "mh-steps",
        "mh-sample-row",
        "mh-audience-row",
        "mh-promise",
        "mh-final-cta",
    ):
        assert hook in body, f"home page lost {hook!r}"


def test_home_pinned_ready_org_does_not_get_the_demo(app):
    pid = _seed_ready()
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["active_profile_id"] = pid
        body = c.get("/").get_data(as_text=True)
    assert '<div class="mh-hero-demo"' not in body, "ready org should not see the demo"
    assert "Ready" in body  # the pinned "<org>. Ready to file." hero copy


def test_home_serves_the_demo_css_inline(app):
    """The keyframes + reduced-motion + pause rules must reach the browser,
    not merely sit in the source file."""
    with app.test_client() as c:
        body = c.get("/").get_data(as_text=True)
    for css in (
        "@keyframes mh-demo-p1",
        "@keyframes mh-demo-p2",
        "@keyframes mh-demo-p3",
        "prefers-reduced-motion",
        "animation-play-state: paused",
    ):
        assert css in body, f"served page is missing demo CSS {css!r}"


# =========================================================================== #
# Group C — the CSS contract (scoped to the U.10 section)
# =========================================================================== #
def test_css_defines_the_scene_and_glow_keyframes():
    sec = _u10_css_section()
    for kf in (
        "@keyframes mh-demo-p1",
        "@keyframes mh-demo-p2",
        "@keyframes mh-demo-p3",
        "@keyframes mh-demo-fill",
        "@keyframes mh-demo-breathe",
    ):
        assert kf in sec, f"missing keyframes {kf!r}"


@pytest.mark.parametrize("i", [1, 2, 3])
def test_css_step_dot_reuses_the_same_scene_track(i):
    """Sync guarantee: the indicator dot for step i is driven by the *same*
    keyframe track as scene i, so the dots can never drift out of step with
    the scenes they label."""
    sec = _u10_css_section()
    assert f".mh-demo-phase.p{i} {{ animation: mh-demo-p{i} 12s linear infinite; }}" in sec
    assert f".mh-demo-step.s{i} .dot .on {{ animation: mh-demo-p{i} 12s linear infinite; }}" in sec


def test_css_ambient_glow_is_a_blurred_brand_bloom():
    sec = _u10_css_section()
    assert ".mh-demo-glow {" in sec
    assert "filter: blur(" in sec
    # The glow is tinted with the brand glow tokens, not a hardcoded colour.
    assert "var(--lane-glow)" in sec
    assert "var(--medal-glow)" in sec
    assert "radial-gradient(" in sec


def test_css_pauses_the_loop_on_hover_and_focus():
    sec = _u10_css_section()
    assert ".mh-hero-demo:hover .mh-demo-phase" in sec
    assert ".mh-hero-demo:focus-within .mh-demo-phase" in sec
    assert "animation-play-state: paused;" in sec


def test_css_reduced_motion_freezes_on_the_review_scene():
    sec = _u10_css_section()
    assert "prefers-reduced-motion" in sec
    # Resting frame visible, the other scenes hidden, no looping.
    assert ".mh-demo-phase.is-rest { opacity: 1; }" in sec
    assert "animation: none !important;" in sec
    # The progress bar settles full and the Review step dot stays lit — both
    # appear ONLY in the reduced-motion block.
    assert ".mh-demo-phase.p1 .mh-demo-meter .bar i { transform: scaleX(1); }" in sec
    assert ".mh-demo-step.s2 .dot .on { opacity: 1; }" in sec


def test_css_caption_marks_are_themed_not_default_yellow():
    """A bare <mark> renders as black-on-yellow; the demo must restyle it to
    the lane-tinted highlight pill (the U.7 'focus the facts' motif)."""
    sec = _u10_css_section()
    assert ".mh-demo-caption mark {" in sec
    assert "var(--lane)" in sec


def test_css_section_introduces_no_external_dependency():
    sec = _u10_css_section()
    for forbidden in ("googleapis", "gstatic", "fonts.google", "url(http", "@import"):
        assert forbidden not in sec, f"U.10 CSS must not contain {forbidden!r}"


def test_every_demo_html_class_has_a_css_rule():
    """No orphan hooks: every class the helper emits is styled in the U.10
    CSS section (guards against a renamed hook silently losing its styling)."""
    html = _demo_html()
    sec = _u10_css_section()
    classes = set()
    for attr in re.findall(r'class="([^"]+)"', html):
        classes.update(attr.split())
    # Decorative state classes handled via compound selectors are fine to skip.
    for cls in sorted(classes):
        assert f".{cls}" in sec, f"class {cls!r} is emitted but never styled"
