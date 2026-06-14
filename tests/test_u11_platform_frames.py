"""U.11 — Outputs inside real platform frames.

Pins the U.11 deliverable (presentation-only; the deterministic engine, AI
surfaces and explainability logic are untouched): the three default output
formats (story / feed / reel) presented inside credible Instagram device
mockups on the logged-out home, advanced by a *pure-CSS* autoplay carousel —
no JS framework. Inspired by AndAgain.

What these tests guard:

  * the home page renders the framed carousel (replacing the old flat
    ``.mh-sample`` row) with exactly three platform phones;
  * each phone is an accessible ``role="img"`` with a descriptive label, and
    its decorative Instagram chrome (status bar, action rails) is aria-hidden;
  * the honest sample facts the old cards carried (Tom Davies 52.41, top three
    finals, match-day reel) survive into the new frames — nothing invented;
  * the autoplay is genuinely CSS-only: the cross-slide keyframes and the
    in-sync dot keyframes ship in the inlined theme CSS that reaches the page,
    the loop pauses on hover/focus, and it is fully disabled (unfolded into a
    static row) under ``prefers-reduced-motion``;
  * the dead ``.mh-sample`` component is gone from both the rendered page and
    the theme stylesheet (dead-code sweep), with no stray references.
"""
import re
from pathlib import Path

import pytest

from mediahub.web import web as webmod
from mediahub.web import theme_tokens


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
    app = webmod.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def home(client):
    resp = client.get("/")
    assert resp.status_code == 200, f"/ -> {resp.status_code}"
    return resp.get_data(as_text=True)


# Source of truth for the component CSS — exactly what web.py inlines.
COMPONENTS_CSS = theme_tokens.THEME_COMPONENTS_CSS


# =========================================================================== #
# Structure — the three framed phones replace the flat sample row
# =========================================================================== #
def test_home_renders_frames_section(home):
    assert 'class="mh-frames mh-reveal"' in home
    assert 'class="mh-frames-stage"' in home
    # An ambient brand halo sits behind the active phone.
    assert 'class="mh-frames-glow"' in home


def test_exactly_three_platform_phones(home):
    assert home.count('class="mh-phone ') == 3
    assert 'class="mh-phone story"' in home
    assert 'class="mh-phone feed"' in home
    assert 'class="mh-phone reel"' in home


def test_three_carousel_dots(home):
    assert 'class="mh-frames-dots"' in home
    for dot in ("d1", "d2", "d3"):
        assert f'class="{dot}"' in home


def test_platform_chrome_present(home):
    # Story chrome: progress segments + the compose/reply row.
    assert 'class="mh-ig-progress"' in home
    assert 'class="mh-ig-compose"' in home
    assert "Send message" in home
    # Feed chrome: action row + likes + caption.
    assert 'class="mh-ig-actions"' in home
    assert "128 likes" in home
    assert 'class="mh-ig-cap"' in home
    # Reel chrome: the Reels label, the right action rail, the audio ticker.
    assert 'class="mh-ig-reels-label"' in home
    assert 'class="mh-ig-rail"' in home
    assert "Original audio" in home


def test_status_bar_drawn(home):
    # Each phone carries the iOS-style status cluster (time + signal/wifi/battery).
    assert home.count('class="mh-ig-status"') == 3
    assert "9:41" in home
    assert 'class="mh-ig-sys"' in home


# =========================================================================== #
# Honest facts — the old sample content survives into the frames
# =========================================================================== #
def test_sample_facts_preserved(home):
    # Story — the PB swim, unchanged from the old flat card.
    assert "Tom" in home and "Davies" in home
    assert "52.41" in home
    assert "−0.74s" in home  # U+2212 minus, as the old card used
    # Feed — the podium graphic.
    assert "Top three" in home
    assert 'class="mh-ig-bars"' in home
    # Reel — the match-day cut.
    assert "Match-day" in home
    assert 'class="mh-ig-timeline"' in home


# =========================================================================== #
# Accessibility — labelled images, hidden chrome, honest section copy
# =========================================================================== #
def test_phones_are_labelled_images(home):
    # Three role="img" phones, each with a non-empty aria-label.
    labels = re.findall(r'<article class="mh-phone [a-z]+" role="img" aria-label="([^"]+)">', home)
    assert len(labels) == 3, labels
    assert all(lbl.strip() for lbl in labels)
    joined = " ".join(labels).lower()
    assert "story" in joined and "feed" in joined and "reel" in joined


def test_decorative_chrome_is_aria_hidden(home):
    # The status bar, progress, action rows and rails are decorative.
    for needle in (
        '<div class="mh-ig-status" aria-hidden="true">',
        '<div class="mh-ig-progress" aria-hidden="true">',
        '<div class="mh-ig-actions" aria-hidden="true">',
        '<div class="mh-ig-rail" aria-hidden="true">',
        '<span class="mh-frames-glow" aria-hidden="true">',
    ):
        assert needle in home, needle


def test_stage_is_grouped_for_at(home):
    assert 'class="mh-frames-stage" role="group"' in home
    assert "In the feed" in home  # section eyebrow
    assert "followers</em>" in home  # section headline accent


# =========================================================================== #
# Pure-CSS autoplay — keyframes reach the page, pause + reduced-motion guards
# =========================================================================== #
def test_autoplay_keyframes_inlined_on_page(home):
    # The carousel motion is CSS-only: its keyframes must ship in the page.
    for kf in ("@keyframes mh-frame-a", "@keyframes mh-frame-b", "@keyframes mh-frame-c"):
        assert kf in home, kf
    # Dots are driven by their own in-sync keyframes.
    for kf in ("@keyframes mh-dot-a", "@keyframes mh-dot-b", "@keyframes mh-dot-c"):
        assert kf in home, kf


def test_each_phone_bound_to_its_animation():
    assert ".mh-phone.story { animation: mh-frame-a" in COMPONENTS_CSS
    assert ".mh-phone.feed  { animation: mh-frame-b" in COMPONENTS_CSS
    assert ".mh-phone.reel  { animation: mh-frame-c" in COMPONENTS_CSS


def test_autoplay_pauses_on_hover_and_focus():
    css = COMPONENTS_CSS
    assert ".mh-frames:hover .mh-phone" in css
    assert ".mh-frames:focus-within .mh-phone" in css
    assert "animation-play-state: paused" in css


def test_reduced_motion_disables_autoplay_and_unfolds_row():
    css = COMPONENTS_CSS
    # Locate the reduced-motion block that owns the frames fallback.
    idx = css.find("@media (prefers-reduced-motion: reduce)", css.find(".mh-frames-stage"))
    assert idx != -1
    block = css[idx:idx + 600]
    assert "animation: none" in block
    # The stack unfolds into a static, visible row (no movement, all formats shown).
    assert "position: static" in block
    assert "opacity: 1" in block


def test_no_js_framework_for_carousel(home):
    # The roadmap is explicit: pure HTML/CSS, no JS framework. The frames
    # markup must not smuggle in a script or framework hook.
    frag = home[home.index('class="mh-frames mh-reveal"'):home.index("</section>", home.index('class="mh-frames'))]
    assert "<script" not in frag
    assert "data-react" not in frag and "v-" not in frag and "x-data" not in frag


# =========================================================================== #
# Dead-code sweep — the old flat sample component is fully gone
# =========================================================================== #
def test_old_sample_component_removed_from_page(home):
    assert "mh-sample" not in home


def test_old_sample_css_removed():
    assert "mh-sample" not in COMPONENTS_CSS
    # And the new component genuinely replaced it.
    assert ".mh-phone {" in COMPONENTS_CSS
    assert ".mh-ig-canvas {" in COMPONENTS_CSS


def test_no_stray_sample_refs_in_tree():
    root = Path(__file__).resolve().parents[1] / "src" / "mediahub"
    hits = []
    for ext in ("*.py", "*.css", "*.js"):
        for f in root.rglob(ext):
            if "mh-sample" in f.read_text(encoding="utf-8", errors="ignore"):
                hits.append(str(f))
    assert not hits, f"stray mh-sample references: {hits}"


# =========================================================================== #
# Well-formedness — balanced device markup
# =========================================================================== #
def test_frames_markup_is_balanced(home):
    start = home.index('class="mh-frames mh-reveal"')
    end = home.index("</section>", start)
    frag = home[start:end]
    assert len(re.findall(r"<article[ >]", frag)) == frag.count("</article>") == 3
    # Every inline glyph SVG is closed.
    assert len(re.findall(r"<svg[ >]", frag)) == frag.count("</svg>")
