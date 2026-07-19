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

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# --------------------------------------------------------------------------- #
# App fixture — a fresh app on this test's isolated DATA_DIR (the canonical
# ``web_module`` fixture repoints the storage dirs + clears caches) with no LLM
# provider keys configured, so the signed-out landing/demo surface renders its
# honest no-provider state. Provider keys are read live at call time, so pinning
# them empty here (not at import) is what the honest-error assertions rely on.
# --------------------------------------------------------------------------- #
@pytest.fixture
def app(web_module, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")

    application = web_module.create_app()
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
    """The demo reuses the same showcase athlete/time as the bento story
    tile, so the landing page tells one coherent story."""
    html = _demo_html()
    assert "Tom Davies" in html
    assert "52.41" in html


# =========================================================================== #
# Group B — home-page integration + the fresh-visitor-only gate
# =========================================================================== #
def test_home_fresh_visitor_shows_demo_in_its_own_section(app):
    with app.test_client() as c:
        body = c.get("/").get_data(as_text=True)
    el = '<div class="mh-hero-demo"'
    assert body.count(el) == 1, "demo should appear exactly once"
    # The looping demo was relocated out of the hero into its own "See it work"
    # section (id mh-see-it-work) just below the engine diagram, so the diagram
    # is the hero's first visual. The section deliberately uses a non-chapter id
    # (it is shown to fresh visitors only, while the chapter rail is static), so
    # the nav-integrity tests don't expect it in the rail.
    hero_start = body.index('<section class="mh-hero"')
    hero_end = body.index("</section>", hero_start)
    assert body.index(el) > hero_end, "demo no longer lives inside the hero"
    assert 'id="mh-see-it-work"' in body and "See it work" in body
    assert body.index('id="mh-see-it-work"') < body.index(el), "demo is in the See-it-work section"


def test_demo_omnibox_uses_request_host_not_hardcoded_render(app):
    """The decorative Chrome omnibox shows the LIVE host, so a custom domain no
    longer advertises the internal Render hostname. A local/empty host falls
    back to the canonical Render host so dev screenshots stay clean."""
    with app.test_client() as c:
        # A custom domain shows through into the omnibox…
        body = c.get("/", headers={"Host": "clubs.example.com"}).get_data(as_text=True)
        assert '<span class="mh-demo-url">clubs.example.com</span>' in body
        assert "mediahub-gzwc.onrender.com" not in body
        # …but the default local test host falls back to the canonical host.
        body_local = c.get("/").get_data(as_text=True)
        assert '<span class="mh-demo-url">mediahub-gzwc.onrender.com</span>' in body_local


def test_home_still_renders_the_rest_of_the_landing(app):
    """Regression: inserting the demo didn't break the existing sections."""
    with app.test_client() as c:
        body = c.get("/").get_data(as_text=True)
    for hook in (
        "mh-bento",
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


# =========================================================================== #
# Group D — the richer scenes: input is shown, the output looks premium, and
# the approval fans out into the posting-ready formats. These guard the
# "engaging + explains the product" redesign, not just the loop skeleton.
# =========================================================================== #
def test_generate_scene_shows_the_raw_results_sheet_being_read():
    """Scene 1 makes the *input* visible: a raw results sheet (with a scan
    line) sitting before the detected moments, so the input → intelligence
    story reads at a glance."""
    html = _demo_html()
    assert '<div class="mh-demo-ingest">' in html        # the two-column wrap
    assert '<div class="mh-demo-sheet">' in html          # the raw source sheet
    assert '<span class="scan">' in html                  # the reading scan line
    assert '<span class="row head">' in html              # a header row
    assert "T. Davies" in html                            # raw rows, sheet voice
    # The raw sheet is *read first*, then resolves into the ranked finds.
    assert html.index("mh-demo-sheet") < html.index("mh-demo-finds")


def test_review_scene_card_is_a_premium_branded_story_card():
    """Scene 2's card reads like a real branded post, not a flat placeholder:
    a brand mark, a PB sticker, the athlete, an improvement delta and a brand
    footer bar — the actual value the product produces."""
    html = _demo_html()
    assert '<span class="mh-demo-brandmark">' in html      # club brand mark
    assert '<span class="mh-demo-flash">PB</span>' in html  # the PB sticker
    assert '<span class="mh-demo-delta">' in html           # improvement delta
    assert "0.74s" in html                                  # the delta value
    assert '<span class="mh-demo-cardbar">' in html         # brand footer bar
    # The full lockup: event, the headline time, the athlete.
    assert "100m Freestyle" in html
    assert '<span class="tm">52.41</span>' in html
    assert '<span class="nm">Tom Davies</span>' in html


def test_approve_scene_fans_out_into_the_posting_ready_formats():
    """Scene 3 pays off the human gate with the breadth — one approval becomes
    four posting-ready formats."""
    html = _demo_html()
    assert '<div class="mh-demo-formats">' in html
    assert html.count('<span class="mh-demo-chip">') == 4
    s, f, r, c = (
        html.index(">Story<"), html.index(">Feed<"),
        html.index(">Reel<"), html.index(">Caption<"),
    )
    assert s < f < r < c, "formats light in a stable order"


# =========================================================================== #
# Group E — the new motion contract (scoped to the U.10 CSS section). Each beat
# carries its own purposeful, reduced-motion-safe micro-motion.
# =========================================================================== #
def test_scene_crossfade_is_blur_masked():
    """The cross-fade blurs each scene as it leaves so two very different
    layouts never ghost through one another (Emil's blur-to-mask tip)."""
    sec = _u10_css_section()
    assert "filter: blur(7px)" in sec
    # the blur rides the same opacity tracks, so it stays perfectly in sync
    assert "@keyframes mh-demo-p1" in sec


def test_each_beat_defines_and_binds_its_micro_motion():
    sec = _u10_css_section()
    for kf in (
        "@keyframes mh-demo-scan",   # s1: reads the sheet
        "@keyframes mh-demo-land",   # s2: the stat lands
        "@keyframes mh-demo-pop",    # s2: the PB sticker pops
        "@keyframes mh-demo-mark",   # s2: facts highlight in turn
        "@keyframes mh-demo-conf",   # s2: confidence fills
        "@keyframes mh-demo-check",  # s3: the tick draws on
        "@keyframes mh-demo-chips",  # s3: formats light up
    ):
        assert kf in sec, f"missing keyframes {kf!r}"
    # Each micro-motion is bound to its own scene's phase, so it only plays
    # while that scene owns the frame.
    assert ".mh-demo-phase.p1 .mh-demo-sheet .scan { animation: mh-demo-scan 12s linear infinite; }" in sec
    assert ".mh-demo-phase.p2 .mh-demo-thumb .tm { animation: mh-demo-land 12s var(--ease-out) infinite; }" in sec
    assert ".mh-demo-phase.p2 .mh-demo-flash { animation: mh-demo-pop 12s var(--ease-spring) infinite; }" in sec
    assert ".mh-demo-phase.p3 .mh-demo-chip { animation: mh-demo-chips 12s var(--ease-out) infinite; }" in sec


def test_caption_facts_wipe_in_sequence():
    """The grounded facts use a highlighter *wipe* (background-size 0→100%),
    staggered so they light one after another rather than all at once."""
    sec = _u10_css_section()
    assert "background-size: 0% 100%" in sec  # the un-wiped resting width
    # the wipe is a lane-tinted background-IMAGE, so the UA default yellow
    # background-color must be explicitly cleared or it bleeds through.
    mark_rule = sec[sec.index(".mh-demo-caption mark {"):]
    mark_rule = mark_rule[: mark_rule.index("}")]
    assert "background-color: transparent" in mark_rule
    assert ".mh-demo-caption mark:nth-of-type(1) { animation-delay: -0.34s; }" in sec
    assert ".mh-demo-caption mark:nth-of-type(2) { animation-delay: -0.17s; }" in sec


def test_approval_tick_draws_on():
    sec = _u10_css_section()
    assert ".mh-demo-check svg polyline { stroke-dasharray: 26; stroke-dashoffset: 26; }" in sec
    assert ".mh-demo-phase.p3 .mh-demo-check svg polyline { animation: mh-demo-check" in sec


def test_new_micro_motions_pause_on_dwell():
    """Dwell-to-pause must freeze the new beats too, or the loop would desync
    when a visitor hovers."""
    sec = _u10_css_section()
    assert ".mh-hero-demo:hover .mh-demo-chip" in sec
    assert ".mh-hero-demo:focus-within .mh-demo-flash" in sec
    assert ".mh-hero-demo:hover .mh-demo-caption mark" in sec


def test_reduced_motion_rests_every_new_beat_composed():
    """Under reduced motion every one-shot settles in its end state: the tick
    fully drawn, the facts fully highlighted, the confidence full."""
    sec = _u10_css_section()
    rm = sec[sec.index("prefers-reduced-motion"):]
    assert ".mh-demo-check svg polyline { stroke-dashoffset: 0; }" in rm
    assert ".mh-demo-caption mark { background-size: 100% 100%; }" in rm
    assert ".mh-demo-conf .track i { transform: scaleX(1); }" in rm
    assert ".mh-demo-chip { opacity: 1; transform: none; }" in rm
    # the new beats are also in the hard `animation: none !important` reset
    assert ".mh-demo-chip { animation: none !important; }" in rm


def test_demo_review_confidence_score_has_label():
    """The confidence number in the Review demo panel must carry an explanatory
    tooltip so a volunteer does not see a bare decimal with no context.

    Regression guard for: 'Two unexplained decimal numbers appear on the
    review card with no label, tooltip, or legend indicating what they
    represent or what an acceptable value looks like.'
    """
    import re

    html = _demo_html()
    m = re.search(r'<span[^>]*class="mh-demo-conf"[^>]*>', html)
    assert m, "mh-demo-conf span not found in demo HTML"
    tag = m.group()
    assert "title=" in tag, (
        "mh-demo-conf span must include a title= tooltip explaining what the "
        "confidence score means; currently the bare value '0.94' appears with "
        "no label or tooltip (regression: unexplained decimal on review card)"
    )


def test_demo_review_confidence_score_has_a_visible_plain_language_label():
    """A ``title=`` tooltip alone is not a legend: it only reaches a sighted
    mouse user who happens to hover, so a non-technical volunteer scanning the
    Review scene still sees a bare '0.94' with nothing on the page explaining
    what it means or what a good value looks like. The visible text must carry
    a plain-language label (e.g. 'High confidence'), not just the raw decimal.

    Regression guard for: unexplained numeric confidence scores shown as core
    UI without a legend ('SOURCE-GROUNDED · 0.96' / '0.94' with no plain-word
    label visible without hovering).
    """
    import re

    html = _demo_html()
    m = re.search(r'<span[^>]*class="mh-demo-conf"[^>]*>(.*?)</span>\s*</div>', html, re.S)
    assert m, "mh-demo-conf span not found in demo HTML"
    inner = m.group(1)
    visible_text = re.sub(r"<[^>]+>", "", inner)
    assert re.search(r"[A-Za-z]", visible_text), (
        "the Review scene's confidence indicator must show a plain-language "
        f"label as VISIBLE text (not only in a title= tooltip); got {visible_text!r}"
    )


# =========================================================================== #
# Group F — queue context (regression guard for autotest finding f51fbb0c9424)
# =========================================================================== #
def test_review_scene_shows_queue_position():
    """The review scene must surface a queue position indicator so a visitor
    understands there are 3 ranked moments to triage — not just the one
    visible Tom Davies card.

    Without this the demo advertises '3 moments ranked' in Scene 1, then
    dead-ends after a single card with no indication that the relay and Aoife
    Nolan's sub-1:00 are also waiting for approval.
    """
    html = _demo_html()
    # Scene 1 must still advertise 3 moments (precondition for the bug).
    assert "3 moments ranked" in html
    # The review scene must carry a queue position indicator so the visitor
    # knows which moment they are looking at and how many remain.
    assert "mh-demo-qcount" in html, (
        "review scene must carry a queue position element (mh-demo-qcount); "
        "without it '3 moments ranked' advertises a queue that appears to have "
        "only 1 card — the other 2 ranked moments have no visible path to review"
    )
    # The indicator text must show position-in-queue context (e.g. '1 of 3').
    assert "of 3" in html, (
        "queue indicator must show position context e.g. '1 of 3' so the visitor "
        "understands two more moments follow Tom Davies in the queue"
    )


# =========================================================================== #
# Group G — the Approve scene must clarify the post-approval path is a manual
# download, not scheduling or direct publishing to a social platform
# (regression guard for autotest finding: publishing path unclear).
# =========================================================================== #
def test_approve_scene_clarifies_download_is_manual_not_auto_publish():
    """The Approve scene's only visible action is '⬇ Download .zip' with no
    surrounding text — a fresh visitor cannot tell whether approving a card
    schedules or auto-publishes it to a social platform, or whether they must
    post it themselves. Every real (authenticated) surface in the app spells
    this out already (e.g. the content builder's 'MediaHub never posts on
    your behalf'); the landing-page demo must say so too.
    """
    html = _demo_html()
    p3_html = html[html.index('<div class="mh-demo-phase p3">') :]
    lowered = p3_html.lower()
    assert "manual" in lowered or "never post" in lowered or "yourself" in lowered, (
        "Approve scene shows only '⬇ Download .zip' with no text clarifying this "
        "is a manual download (not direct/auto publishing to a social platform) "
        "— a fresh visitor can't tell which workflow this is"
    )
