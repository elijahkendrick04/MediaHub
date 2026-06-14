"""UI 1.19 — Testimonial / social-proof carousel on the landing page.

Pins the UI 1.19 deliverable (presentation-only; the deterministic engine, the
pipeline and every AI surface are untouched): a club/coach quote-card carousel
on the home page with avatar initials, arrow controls, position dots and a
gentle autoplay. Pure CSS/JS — a native scroll-snap viewport progressively
enhanced by a single vanilla-JS initialiser, no carousel library. Inspired by
Sketch (sketch.com).

What these tests hold in place:

  * the carousel renders on the landing for both a fresh visitor and a
    returning pinned organisation (it is marketing shown to everyone);
  * it carries the full quote-card content — five blockquotes, each with an
    avatar-initials badge and a role + sample-club attribution;
  * it is an accessible carousel: a labelled ``role=group`` carousel, labelled
    ``slide`` figures, real ``<button>`` arrow + dot controls with ARIA, a
    focusable viewport, and a polite live region announcing the active slide;
  * the motion is honest progressive enhancement — the viewport works on its
    own (scroll-snap, no JS), the JS-only controls are hidden until the binder
    marks the carousel ``is-ready``, autoplay is gated off under
    ``prefers-reduced-motion`` and paused on hover/focus/tab-hide;
  * the CSS + the single namespaced JS initialiser actually ship in the
    rendered document, defined exactly once (no drift / duplication);
  * the copy is HONEST: MediaHub is pre-launch, so the quotes are framed as
    *illustrative* voices of the roles it is built for — never passed off as
    real customer endorsements — consistent with the page's own "we don't
    invent results" promise;
  * it is no carousel *library*: the markup smuggles in no script or framework
    hook, and the device markup is well-formed.
"""
import re
from pathlib import Path

import pytest

from mediahub.web import web as webmod
from mediahub.web import theme_tokens
from mediahub.web.club_profile import ClubProfile, save_profile


# --------------------------------------------------------------------------- #
# Fixtures (modelled on tests/test_u11_platform_frames.py)
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(webmod, "RUNS_DIR", runs, raising=False)
    app = webmod.app
    app.config["TESTING"] = True  # disables CSRF + the login-idle drop
    with app.test_client() as c:
        yield c


@pytest.fixture
def home(client):
    resp = client.get("/")
    assert resp.status_code == 200, f"/ -> {resp.status_code}"
    return resp.get_data(as_text=True)


# Source of truth for the component CSS — exactly what web.py inlines.
COMPONENTS_CSS = theme_tokens.THEME_COMPONENTS_CSS
# Source of truth for the JS initialiser.
WEB_SRC = Path(webmod.__file__).read_text(encoding="utf-8")

# The expected count of quote cards (kept in sync with the home() builder).
N_CARDS = 5


def _pin_ready_org(client):
    """Persist a ready organisation and pin it into the session."""
    save_profile(
        ClubProfile(
            profile_id="riverside",
            display_name="Riverside SC",
            brand_voice_summary="A friendly, fast club.",
        )
    )
    resp = client.post("/api/organisation/active", data={"profile_id": "riverside"})
    assert resp.status_code == 200, resp.get_json()


def _carousel_fragment(home: str) -> str:
    """The carousel + note, from the .mh-testi container to its </section>."""
    start = home.index('class="mh-testi mh-reveal"')
    end = home.index("</section>", start)
    return home[start:end]


# =========================================================================== #
# Structure — the carousel renders with its section framing
# =========================================================================== #
def test_home_renders_testimonials_section(home):
    assert 'class="mh-testi mh-reveal"' in home
    assert "data-mh-testi" in home
    assert 'class="mh-testi-rail"' in home
    assert 'class="mh-testi-viewport"' in home


def test_section_eyebrow_and_headline(home):
    # Distinctive eyebrow + the editorial headline accent.
    assert '<span class="label">In their words</span>' in home
    assert 'hands <em class="editorial">back</em>.' in home


def test_five_quote_cards_each_with_a_blockquote(home):
    assert home.count('class="mh-testi-card"') == N_CARDS
    frag = _carousel_fragment(home)
    assert frag.count('<blockquote class="mh-testi-quote">') == N_CARDS
    assert frag.count("</blockquote>") == N_CARDS


def test_cards_carry_avatar_initials(home):
    # One decorative avatar badge per card, carrying the (sample) club initials.
    assert home.count('class="mh-testi-avatar"') == N_CARDS
    # The avatar is decorative — the role + org text is the real attribution.
    assert home.count('class="mh-testi-avatar" aria-hidden="true"') == N_CARDS
    for initials in ("RS", "KA", "US", "HR", "PN"):
        assert f'aria-hidden="true">{initials}</span>' in home, initials


def test_cards_carry_role_and_sample_club(home):
    # Role attribution (primary line) …
    for role in (
        "Club secretary",
        "Head coach",
        "Social secretary",
        "Comms volunteer",
        "Team manager",
    ):
        assert f'class="mh-testi-name">{role}</b>' in home, role
    # … and the illustrative sample clubs + sports (secondary line).
    for org in (
        "Riverside SC",
        "Kingsmead Aquatics",
        "University Swim Society",
        "Harbourside Rowing",
        "Parkside Netball",
    ):
        assert org in home, org


# =========================================================================== #
# Accessibility — labelled carousel, labelled slides, real controls
# =========================================================================== #
def test_carousel_has_group_role_and_roledescription(home):
    frag = _carousel_fragment(home)
    assert 'role="group"' in frag
    assert 'aria-roledescription="carousel"' in frag
    # The carousel names itself for assistive tech.
    assert 'aria-label="What clubs and coaches say (illustrative)"' in home


def test_slides_are_labelled(home):
    # Each card is a labelled slide ("Testimonial N of 5").
    labels = re.findall(
        r'<figure class="mh-testi-card" role="group" '
        r'aria-roledescription="slide" aria-label="([^"]+)">',
        home,
    )
    assert len(labels) == N_CARDS, labels
    for i, lbl in enumerate(labels, start=1):
        assert lbl == f"Testimonial {i} of {N_CARDS}", lbl


def test_arrow_controls_are_real_labelled_buttons(home):
    assert (
        '<button type="button" class="mh-testi-arrow prev" '
        'data-mh-testi-prev aria-label="Previous testimonial">' in home
    )
    assert (
        '<button type="button" class="mh-testi-arrow next" '
        'data-mh-testi-next aria-label="Next testimonial">' in home
    )
    # Exactly one of each arrow.
    assert home.count('class="mh-testi-arrow prev"') == 1
    assert home.count('class="mh-testi-arrow next"') == 1


def test_dots_present_labelled_and_first_is_current(home):
    frag = _carousel_fragment(home)
    # Five dot buttons, each addressable by index.
    assert frag.count('data-mh-testi-to="') == N_CARDS
    for i in range(N_CARDS):
        assert f'aria-label="Show testimonial {i + 1}"' in frag, i
    # Only the first dot starts active / current.
    assert frag.count("mh-testi-dot is-active") == 1
    assert frag.count('aria-current="true"') == 1
    assert (
        'class="mh-testi-dot is-active" data-mh-testi-to="0" '
        'aria-label="Show testimonial 1" aria-current="true"' in frag
    )


def test_viewport_is_focusable_for_keyboard_users(home):
    assert '<div class="mh-testi-viewport" tabindex="0">' in home


def test_polite_live_region_announces_the_slide(home):
    assert (
        '<p class="mh-sr-only" data-mh-testi-status aria-live="polite">'
        f"Testimonial 1 of {N_CARDS}</p>" in home
    )


# =========================================================================== #
# Honesty — illustrative framing, not fabricated endorsements
# =========================================================================== #
def test_illustrative_framing_is_explicit(home):
    note_start = home.index('class="mh-testi-note">')
    note = home[note_start : home.index("</p>", note_start)]
    # The note is unambiguous that these are not real customer endorsements.
    assert "Illustrative" in note
    assert "pre-launch" in note
    assert "not paid endorsements" in note
    # The carousel's own accessible name carries the caveat too.
    assert "(illustrative)" in home


def test_no_invented_results_in_quotes(home):
    """The quotes echo the product's honesty stance and must not fabricate a
    concrete result (a time / placing) the way a real attributed metric would.
    Guards against the carousel drifting into invented social-proof stats."""
    frag = _carousel_fragment(home)
    # No swim-time-shaped tokens (mm:ss.xx or ss.xx) smuggled into the prose.
    assert not re.search(r"\b\d{1,2}:\d\d\.\d\d\b", frag), "invented time in quote"
    assert not re.search(r"\b\d{2}\.\d{2}s?\b", frag), "invented split in quote"


# =========================================================================== #
# Pure CSS/JS — no carousel library, controls are progressive enhancement
# =========================================================================== #
def test_no_js_framework_or_inline_script_in_markup(home):
    frag = _carousel_fragment(home)
    assert "<script" not in frag
    # No framework hooks smuggled into the carousel markup.
    for hook in ("data-react", "v-bind", "v-for", "x-data", "ng-", "data-swiper"):
        assert hook not in frag, hook


def test_controls_are_hidden_until_js_marks_ready():
    css = COMPONENTS_CSS
    # Arrows + dots are display:none by default …
    assert ".mh-testi-arrow { display: none; }" in css
    assert ".mh-testi-dots { display: none; }" in css
    # … and only revealed once the binder adds .is-ready.
    assert ".mh-testi.is-ready .mh-testi-arrow {" in css
    assert ".mh-testi.is-ready .mh-testi-dots {" in css


def test_binder_adds_is_ready_class():
    # The JS reveals the controls (so no-JS visitors never see dead buttons).
    assert "root.classList.add('is-ready')" in WEB_SRC


# =========================================================================== #
# CSS ships in the document
# =========================================================================== #
def test_carousel_css_is_in_the_document(home):
    # The CSS is inlined into every page, so it must reach the rendered home.
    for rule in (
        ".mh-testi {",
        ".mh-testi-viewport {",
        "scroll-snap-type: x mandatory",
        ".mh-testi-card {",
        "scroll-snap-align: center",
        ".mh-testi-avatar {",
        ".mh-testi-dot.is-active",
    ):
        assert rule in home, rule


def test_card_surface_mirrors_audience_card_language():
    css = COMPONENTS_CSS
    block_start = css.index(".mh-testi-card {")
    block = css[block_start : block_start + 600]
    # Same surface + hairline + medium radius as the audience cards above.
    assert "background: var(--surface)" in block
    assert "border: 1px solid var(--hairline)" in block
    assert "border-radius: var(--radius-md)" in block


# =========================================================================== #
# JS initialiser ships, is namespaced, and is idempotent
# =========================================================================== #
def test_js_initialiser_ships_and_is_namespaced(home):
    assert "function bindTestimonials()" in home
    assert "MH.bindTestimonials = bindTestimonials;" in home
    # Idempotent binding guard so a re-init never double-wires the carousel.
    assert "data-mh-testi-bound" in home


def test_initialiser_defined_once():
    assert WEB_SRC.count("function bindTestimonials()") == 1
    assert WEB_SRC.count("MH.bindTestimonials = bindTestimonials;") == 1


def test_carousel_html_built_in_home_route_only():
    """The carousel markup lives in the home() builder, not scattered across
    the monolith — one source of truth for the landing element."""
    assert WEB_SRC.count("testimonials_html = (") == 1
    assert WEB_SRC.count('class="mh-testi mh-reveal"') == 1


# =========================================================================== #
# Reduced motion + autoplay safety
# =========================================================================== #
def _binder_src() -> str:
    start = WEB_SRC.index("function bindTestimonials()")
    end = WEB_SRC.index("MH.bindTestimonials = bindTestimonials;")
    return WEB_SRC[start:end]


def test_autoplay_is_gated_off_under_reduced_motion(home):
    # JS: autoplay never starts under prefers-reduced-motion (or with one card).
    assert "if (prefersReduced || n <= 1) return;" in _binder_src()
    # CSS: a reduced-motion block neutralises smooth scrolling for the viewport.
    css = COMPONENTS_CSS
    idx = css.find(
        "@media (prefers-reduced-motion: reduce)", css.find(".mh-testi-viewport {")
    )
    assert idx != -1
    block = css[idx : idx + 200]
    assert "scroll-behavior: auto" in block


def test_autoplay_pauses_on_hover_focus_and_tab_hide():
    src = _binder_src()
    for needle in (
        "'mouseenter', stop",
        "'mouseleave', play",
        "'focusin', stop",
        "'focusout', play",
        "visibilitychange",
    ):
        assert needle in src, needle


def test_controls_restart_the_autoplay_timer():
    # Each manual control nudges then re-arms the timer (so it doesn't fight
    # the user immediately after an interaction).
    src = _binder_src()
    assert "function restart()" in src
    assert src.count("restart();") >= 3  # prev + next + dots (+ keyboard)


def test_keyboard_arrows_navigate_the_carousel():
    src = _binder_src()
    assert "addEventListener('keydown'" in src
    assert "ArrowLeft" in src and "ArrowRight" in src


# =========================================================================== #
# Shown to everyone (fresh + returning pinned organisation)
# =========================================================================== #
def test_carousel_renders_for_pinned_org(client):
    _pin_ready_org(client)
    body = client.get("/").get_data(as_text=True)
    assert "Ready" in body  # returning-user hero copy is in play …
    assert 'class="mh-testi mh-reveal"' in body  # … and the carousel still ships
    assert body.count('class="mh-testi-card"') == N_CARDS


# =========================================================================== #
# Narrative placement — after "Made for", before the trust panel
# =========================================================================== #
def test_carousel_sits_after_audience_and_before_promise(home):
    i_audience = home.index("Built for the people who")  # audience headline
    i_testi = home.index('<span class="label">In their words</span>')
    i_promise = home.index("Human in the loop,")  # promise panel headline
    assert i_audience < i_testi < i_promise


# =========================================================================== #
# Well-formedness — balanced carousel markup
# =========================================================================== #
def test_carousel_markup_is_balanced(home):
    frag = _carousel_fragment(home)
    # Five slides …
    assert len(re.findall(r"<figure[ >]", frag)) == frag.count("</figure>") == N_CARDS
    assert frag.count("<blockquote") == frag.count("</blockquote>") == N_CARDS
    # … two arrows + five dots = seven buttons …
    assert frag.count("<button") == frag.count("</button>") == 2 + N_CARDS
    # … and every inline arrow glyph is closed.
    assert len(re.findall(r"<svg[ >]", frag)) == frag.count("</svg>") == 2
