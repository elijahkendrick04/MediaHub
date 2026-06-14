"""UI 1.7 — Pinned-panel scrollytelling (landing how-it-works section).

Pins the landing-page workflow scrollytelling (presentation-only; no engine, AI
or data surface is touched):

  * structure — a left rail of four ordered narrative steps beside a sticky
    visual panel with one mock per step (results → moments → drafts → approve)
  * the workflow story — the four stages in order, each with its real,
    screen-reader-read copy, paired with a decorative visual mock
  * the roadmap mandate — *pure CSS, scroll-driven, no JS library*: the pin is
    ``position: sticky`` and the per-step swap is driven by CSS scroll-driven
    animations (named ``view-timeline`` + ``timeline-scope`` +
    ``animation-timeline``); no ``<script>``, no IntersectionObserver, no library
  * progressive enhancement — the pin + hide live ONLY behind
    ``@supports (animation-timeline: view())`` + ``prefers-reduced-motion:
    no-preference`` + a desktop width, so unsupported / reduced-motion / mobile
    visitors get a clean, all-visible static layout and nothing is hidden
  * on-brand restraint — lane-yellow chrome; medal-gold only inside the
    detected-moments mock (a real athlete achievement), never as section chrome;
    self-hosted fonts only (no Google-Fonts CDN)
  * well-formed markup, deterministic output, accessibility
  * end-to-end render on / for both fresh and pinned-org visitors, with the CSS
    injected before the guardrails layer and ordered hero → pipeline → workflow
"""
import xml.etree.ElementTree as ET

import pytest

from mediahub.web import scrollytelling as sc
from mediahub.web import web as webmod


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    app = webmod.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(scope="module")
def grid():
    return sc.scrollytelling_grid_html()


_STEP_TITLES = [
    "Add an input",
    "We find the moments",
    "On-brand drafts appear",
    "Approve. Then post.",
]


# =========================================================================== #
# Structure & copy
# =========================================================================== #
def test_grid_has_rail_stage_and_panel(grid):
    assert grid.startswith('<div class="mh-scrolly-grid">')
    assert grid.rstrip().endswith("</div>")
    assert '<ol class="mh-scrolly-rail">' in grid       # ordered = a workflow
    assert '<div class="mh-scrolly-stage">' in grid
    assert '<div class="mh-scrolly-panel">' in grid


def test_four_steps_and_four_visuals(grid):
    assert grid.count('<li class="mh-scrolly-step">') == 4
    assert grid.count('class="mh-scrolly-vis"') == 4


@pytest.mark.parametrize("title", _STEP_TITLES)
def test_each_step_title_present(grid, title):
    assert f"<span>{title}</span>" in grid


def test_steps_appear_in_workflow_order(grid):
    positions = [grid.index(f"<span>{t}</span>") for t in _STEP_TITLES]
    assert positions == sorted(positions), "workflow steps out of order"


def test_step_numbers_and_foots(grid):
    for num in ("01", "02", "03", "04"):
        assert f'<span class="mh-scrolly-num">{num}</span>' in grid
    # The "time-to" feet survived the move from the old static grid.
    for foot in ("~ 30s", "~ 45s", "~ 60s", "Human in the loop"):
        assert foot in grid


def test_grid_is_well_formed_xml(grid):
    # A single parseable root catches any unclosed tag / stray-entity slip in
    # the hand-built markup (the copy uses literal Unicode, not named entities).
    ET.fromstring(f"<root>{grid}</root>")


def test_output_is_deterministic():
    assert sc.scrollytelling_grid_html() == sc.scrollytelling_grid_html()


# =========================================================================== #
# The per-step visual mocks (results → moments → drafts → approve)
# =========================================================================== #
def test_input_visual_shows_the_uploaded_results_file(grid):
    assert "results.hy3" in grid
    assert "Davies, Tom" in grid                 # a row from the sample sheet
    for fmt in (">PDF<", ">CSV<", ">HY3<"):
        assert fmt in grid


def test_detect_visual_is_ranked_with_confidence(grid):
    assert "moments detected" in grid
    # Ranked 1..4
    for rank in ("1", "2", "3", "4"):
        assert f'<span class="mh-scm-rank">{rank}</span>' in grid
    # Honest achievement tags + visible confidence scores.
    assert "PB −0.74s" in grid             # minus sign, not hyphen
    assert "Gold" in grid
    assert "Club record" in grid
    for conf in ("98%", "95%", "92%", "88%"):
        assert conf in grid


def test_draft_visual_is_a_branded_caption_in_voice(grid):
    assert "Riverside SC" in grid
    assert "your voice" in grid
    assert "personal best" in grid
    assert "#RiversideSC" in grid


def test_approve_visual_keeps_human_in_the_loop(grid):
    assert "Approved by you" in grid
    assert "Nothing leaves without your sign-off." in grid
    assert "Post to Stories" in grid


# =========================================================================== #
# Roadmap mandate: pure CSS, scroll-driven, NO JS library
# =========================================================================== #
def test_grid_contains_no_javascript(grid):
    for bad in ("<script", "onclick", "onscroll", "addEventListener",
                "IntersectionObserver", "requestAnimationFrame", "javascript:"):
        assert bad not in grid, f"unexpected JS hook in markup: {bad}"


def test_css_uses_pure_css_scroll_driven_primitives():
    css = sc.SCROLLYTELLING_CSS
    # The scroll-driven-animations vocabulary — the feature literally named in
    # the roadmap ("pure CSS scroll-driven").
    assert "timeline-scope:" in css
    assert "view-timeline-name:" in css
    assert "view-timeline-axis:" in css
    assert "animation-timeline:" in css
    # The pin itself.
    assert "position: sticky" in css


def test_css_brace_balance():
    css = sc.SCROLLYTELLING_CSS
    assert css.count("{") == css.count("}")


def test_css_defines_the_swap_and_spotlight_keyframes():
    css = sc.SCROLLYTELLING_CSS
    # The cross-dissolve: first (shown from entry), mid (fade in + out), last
    # (held through exit), plus the active-step spotlight.
    assert "@keyframes mh-scrolly-first" in css
    assert "@keyframes mh-scrolly-mid" in css
    assert "@keyframes mh-scrolly-last" in css
    assert "@keyframes mh-scrolly-spotlight" in css


# =========================================================================== #
# Progressive enhancement + reduced-motion safety
# =========================================================================== #
def test_pin_and_hide_are_enhancement_only():
    """The pin + the hidden (to-be-swapped) visuals live ONLY behind the
    @supports + motion-preference + desktop gate. So an unsupported browser, a
    reduced-motion visitor and a phone all fall back to the static, all-visible
    layout — nothing is ever hidden without the machinery to reveal it."""
    css = sc.SCROLLYTELLING_CSS
    base, sep, enh = css.partition("@supports (animation-timeline: view())")
    assert sep, "missing @supports feature gate"
    # Nothing is pinned in the base layer (the @keyframes that live above the
    # gate define opacity:0 but are only *applied* inside it — see
    # test_base_layer_keeps_every_visual_visible for the visibility guarantee).
    assert "position: sticky" not in base
    # The pin, the hide and the scroll-driven wiring are all gated.
    assert "position: sticky" in enh
    assert "opacity: 0" in enh
    assert "animation-timeline:" in enh
    # …and the gate also requires motion + desktop width.
    assert "prefers-reduced-motion: no-preference" in enh
    assert "min-width: 900px" in enh


def test_base_layer_keeps_every_visual_visible():
    """Belt-and-braces: the base ``.mh-scrolly-vis`` rule must not hide a
    visual (no opacity:0 before the gate), so a no-JS / unsupported visitor sees
    all four stages."""
    css = sc.SCROLLYTELLING_CSS
    base = css.partition("@supports (animation-timeline: view())")[0]
    vis_rule = base.split(".mh-scrolly-vis {", 1)[1].split("}", 1)[0]
    assert "opacity" not in vis_rule


# =========================================================================== #
# Brand rules
# =========================================================================== #
def test_lane_is_the_chrome_accent():
    css = sc.SCROLLYTELLING_CSS
    assert "var(--lane)" in css
    assert "var(--ink-dim)" in css


def test_medal_gold_only_marks_an_achievement_not_chrome():
    # Medal-gold is allowed inside the detected-moments mock (a real athlete
    # achievement) but must not leak into section chrome. Every var(--medal)
    # use is confined to the one medal-tag rule.
    css = sc.SCROLLYTELLING_CSS
    assert ".mh-scm-tag--medal" in css
    medal_rule = css.split(".mh-scm-tag--medal {", 1)[1].split("}", 1)[0]
    assert "var(--medal)" in medal_rule
    assert css.count("var(--medal)") == medal_rule.count("var(--medal)")


def test_self_hosted_fonts_only():
    css = sc.SCROLLYTELLING_CSS
    assert "googleapis" not in css
    assert "gstatic" not in css


# =========================================================================== #
# Accessibility
# =========================================================================== #
def test_visual_mocks_are_decorative(grid):
    # The four panel mocks are decorative duplicates of the step copy; the
    # narrative <li> text is what assistive tech reads. So every figure is
    # aria-hidden and there are exactly four of them.
    assert grid.count('<figure class="mh-scrolly-vis" aria-hidden="true">') == 4


def test_steps_are_a_semantic_ordered_list(grid):
    # The rail is one ordered list of four step items. (The detect mock's
    # moments are a separate <ul>, so count the step <li> specifically.)
    assert grid.count('<ol class="mh-scrolly-rail">') == 1
    assert grid.count('<li class="mh-scrolly-step">') == 4


# =========================================================================== #
# End-to-end render on /
# =========================================================================== #
def _home_body(client):
    r = client.get("/")
    assert r.status_code == 200
    return r.get_data(as_text=True)


def test_home_renders_scrollytelling_for_fresh_visitor(client):
    body = _home_body(client)
    assert "mh-scrolly-grid" in body
    for title in _STEP_TITLES:
        assert f"<span>{title}</span>" in body


def test_home_renders_scrollytelling_for_pinned_org(client):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(
        profile_id="otter-sc", display_name="Otter SC",
        brand_voice_summary="A friendly community club.",
    ))
    pinned = client.post("/api/organisation/active", data={"profile_id": "otter-sc"})
    assert pinned.status_code == 200, pinned.get_data(as_text=True)

    body = _home_body(client)
    assert "mh-scrolly-grid" in body
    assert body.count('class="mh-scrolly-vis"') == 4


def test_home_injects_scrollytelling_css(client):
    body = _home_body(client)
    assert "@keyframes mh-scrolly-mid" in body
    assert "timeline-scope:" in body
    assert ".mh-scrolly-panel" in body


def test_home_section_order_hero_then_pipeline_then_scrollytelling(client):
    body = _home_body(client)
    # Anchor on the HTML class="…" form: the bare class name also appears in
    # the injected <style> block in <head>, which would order by stylesheet
    # position rather than DOM position.
    i_hero = body.index('class="mh-hero"')
    i_pipeline = body.index('class="mh-pl-stage"')
    i_scrolly = body.index('class="mh-scrolly-grid"')
    assert i_hero < i_pipeline < i_scrolly


def test_scrollytelling_css_sits_before_guardrails_layer(client):
    # The responsive guardrails must remain the final cascade layer; the
    # scrollytelling CSS therefore appears before them in the served stylesheet.
    body = _home_body(client)
    marker = "RESPONSIVE GUARDRAILS (2026)"
    assert marker in body
    assert body.index("@keyframes mh-scrolly-mid") < body.index(marker)


def test_workflow_heading_copy_preserved(client):
    # The section keeps the "From the results sheet to …" heading the rest of
    # the page (and other tests) reference, plus the eyebrow + a lede.
    body = _home_body(client)
    assert "From the results sheet" in body
    assert '<span class="label">The workflow</span>' in body
    assert 'class="mh-scrolly-lede"' in body
