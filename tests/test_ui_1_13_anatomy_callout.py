"""UI 1.13 — Annotated UI callouts ("anatomy of a card").

Pins the landing-page anatomy diagram (presentation-only; no engine, AI or
data surface is touched):

  * structure — eyebrow / editorial title / lede / stage, joined to the
    existing scroll-reveal + section chrome
  * the example card — a faithful story card (logo, club, swimmer, event,
    headline time, moment pill, verified PB delta, confidence score + bar,
    caption, brand palette), drawn identically in BOTH orientations
  * eight numbered hotspot pins, each drawn in both orientations
  * eight SVG connector lines + eight side callouts in the horizontal layout;
    the narrow layout swaps the crossing lines for a numbered HTML legend
  * every callout label drawn on BOTH surfaces (desktop SVG callout + the
    mobile legend) so neither viewport silently drops a part
  * on-brand restraint — lane-yellow chrome (pins, lines, logo, confidence);
    medal-gold only on the athlete achievement it depicts (moment + PB delta)
  * static markup with one reduced-motion-safe pin shimmer; no SMIL, no JS,
    no Google-Fonts CDN
  * well-formed markup, deterministic output, accessibility
  * end-to-end render on / for both fresh and pinned-org visitors, the CSS
    injected, and the section ordered hero → bento → anatomy → audience
"""
import re
import xml.etree.ElementTree as ET

import pytest

from mediahub.web import anatomy_callout as ac
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
def section():
    return ac.anatomy_callout_section_html()


@pytest.fixture(scope="module")
def svgs(section):
    found = re.findall(r"<svg\b.*?</svg>", section, flags=re.S)
    assert len(found) == 2, f"expected two SVG orientations, found {len(found)}"
    return found


# The eight annotated parts, in declaration order.
_TITLES = [t for _n, _fx, _fy, _s, t, _d in ac._ANATOMY]
_DESCS = [d for _n, _fx, _fy, _s, _t, d in ac._ANATOMY]


# =========================================================================== #
# Structure & copy
# =========================================================================== #
def test_section_is_one_reveal_section(section):
    assert section.startswith("<section")
    assert section.rstrip().endswith("</section>")
    # Joins the established section chrome + scroll-reveal system.
    assert "mh-section" in section
    assert "mh-reveal" in section
    assert "mh-an-section" in section
    assert "mh-an-stage" in section


def test_eyebrow_title_and_lede(section):
    assert '<span class="label">Anatomy of a card</span>' in section
    assert 'class="mh-section-title"' in section
    assert '<em class="editorial">accounted for</em>' in section
    assert 'class="mh-an-lede"' in section
    assert "confidence score" in section
    assert "where each piece comes from" in section


def test_whole_section_is_well_formed_xml(section):
    # A single <section> root that parses cleanly catches any unclosed tag,
    # stray entity, or attribute-quoting slip in the hand-built markup.
    ET.fromstring(section)


def test_no_named_html_entities_that_break_xml(section):
    # The whole section is XML-parsed above, so only numeric/the five named XML
    # entities are legal — a stray &mdash;/&rarr;/&middot; would have failed
    # parsing. Guard explicitly so a future edit gets a clear message.
    for bad in ("&mdash;", "&rarr;", "&middot;", "&nbsp;", "&amp;amp;"):
        assert bad not in section, bad


# =========================================================================== #
# Two orientations
# =========================================================================== #
def test_two_orientations_present(section):
    assert "mh-an-svg--h" in section          # horizontal (desktop/tablet)
    assert "mh-an-svg--v" in section          # vertical (mobile)


def test_each_svg_is_well_formed_xml(svgs):
    for s in svgs:
        ET.fromstring(s)


def test_exactly_two_svgs(svgs):
    assert len(svgs) == 2


# =========================================================================== #
# The example card — faithful to a real story card
# =========================================================================== #
@pytest.mark.parametrize(
    "needle",
    [
        "RS",                 # club logo monogram
        "Riverside SC",       # club name (uppercased via CSS, literal in markup)
        "Tom Davies",         # swimmer
        "100m Freestyle",     # event
        "52.41",              # headline time
        "PERSONAL BEST",      # moment pill
        "0.74s",              # PB delta magnitude
        "SEASON BEST",        # delta sub-label
        "CONFIDENCE 92%",     # confidence chip
        "STORY",              # format badge
    ],
)
def test_card_content_drawn_in_both_orientations(svgs, needle):
    # Asserted per-SVG (not on the whole section) so the visually-hidden a11y
    # summary — which legitimately restates some of these facts — can't mask a
    # part missing from one of the two cards.
    h = next(s for s in svgs if "mh-an-svg--h" in s)
    v = next(s for s in svgs if "mh-an-svg--v" in s)
    assert needle in h, f"{needle!r} missing from the desktop card"
    assert needle in v, f"{needle!r} missing from the mobile card"


def test_caption_lines_present_in_both_orientations(svgs):
    h = next(s for s in svgs if "mh-an-svg--h" in s)
    v = next(s for s in svgs if "mh-an-svg--v" in s)
    for line in ac._CAPTION:
        assert line in h and line in v, line


def test_palette_has_four_swatches_per_orientation(section):
    # Four brand swatches drawn per card, in both orientations.
    assert section.count('class="mh-an-sw ') == 8


def test_club_name_matches_constant(section):
    # The club name is uppercased only by CSS; the markup carries it verbatim.
    assert ac._CLUB in section


# =========================================================================== #
# Hotspot pins (the labelled hotspots)
# =========================================================================== #
def test_eight_numbered_pins_per_orientation(section):
    # 8 pins x 2 orientations = 16 pin number labels + 16 dots + 16 halos.
    assert section.count('class="mh-an-pin-num"') == 16
    assert section.count('class="mh-an-pin-dot"') == 16
    assert section.count('class="mh-an-pin-halo"') == 16


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6, 7, 8])
def test_each_pin_number_drawn(section, n):
    # Each number 1..8 appears as a pin label in both orientations, plus once
    # as the callout tag and once in the legend = 4 occurrences total.
    assert section.count(f">{n}</text>") == 3   # 2 pins + 1 callout tag
    assert f'class="mh-an-leg-num">{n}</span>' in section


def test_anatomy_table_has_eight_unique_balanced_points():
    nums = [n for n, *_ in ac._ANATOMY]
    sides = [s for _n, _fx, _fy, s, _t, _d in ac._ANATOMY]
    assert nums == list(range(1, 9)), "pins must be numbered 1..8 in order"
    assert sides.count("L") == 4 and sides.count("R") == 4, "balanced columns"
    # Every hotspot sits inside the card box (fractions within 0..1).
    for _n, fx, fy, _s, _t, _d in ac._ANATOMY:
        assert 0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0


# =========================================================================== #
# Connector lines + side callouts (horizontal) ⇄ legend (mobile)
# =========================================================================== #
def test_eight_connector_lines_horizontal_only(section, svgs):
    h_svg = next(s for s in svgs if "mh-an-svg--h" in s)
    v_svg = next(s for s in svgs if "mh-an-svg--v" in s)
    assert h_svg.count('class="mh-an-line"') == 8
    # The narrow layout uses the numbered legend, not crossing lines.
    assert v_svg.count('class="mh-an-line"') == 0


def test_connector_lines_are_paths(svgs):
    h_svg = next(s for s in svgs if "mh-an-svg--h" in s)
    paths = re.findall(r'<path class="mh-an-line"[^>]*\bd="([^"]+)"', h_svg)
    assert len(paths) == 8
    # Each is a cubic-bezier connector (M … C …).
    for d in paths:
        assert d.startswith("M ") and " C " in d


def test_eight_callouts_with_titles_and_descs(section):
    assert section.count('class="mh-an-title"') == 8
    assert section.count('class="mh-an-desc"') == 8
    assert section.count('class="mh-an-tag-num"') == 8


@pytest.mark.parametrize("title", _TITLES)
def test_every_title_on_both_surfaces(section, title):
    # Each label is drawn once as a desktop SVG callout and once in the mobile
    # legend, so neither viewport drops a part.
    assert section.count(title) == 2, title


@pytest.mark.parametrize("desc", _DESCS)
def test_every_desc_on_both_surfaces(section, desc):
    assert section.count(desc) == 2, desc


# =========================================================================== #
# Mobile legend
# =========================================================================== #
def test_legend_is_an_ordered_list_of_eight(section):
    assert '<ol class="mh-an-legend"' in section
    assert section.count("mh-an-leg-item") == 8
    assert section.count('class="mh-an-leg-title"') == 8
    assert section.count('class="mh-an-leg-desc"') == 8


# =========================================================================== #
# CSS — structure, brand rules, responsive, motion safety
# =========================================================================== #
def test_css_brace_balance():
    css = ac.ANATOMY_CALLOUT_CSS
    assert css.count("{") == css.count("}")


def test_css_defines_the_core_classes():
    css = ac.ANATOMY_CALLOUT_CSS
    for sel in (
        ".mh-an-stage",
        ".mh-an-card-bg",
        ".mh-an-line",
        ".mh-an-pin-dot",
        ".mh-an-pin-num",
        ".mh-an-title",
        ".mh-an-desc",
        ".mh-an-legend",
        ".mh-an-time",
    ):
        assert sel in css, sel


def test_legend_hidden_on_desktop_shown_on_mobile():
    css = ac.ANATOMY_CALLOUT_CSS
    # Base: the legend is hidden (desktop uses the SVG callouts)…
    assert ".mh-an-legend { display: none; }" in css
    # …and the <760px media query turns it on (and the horizontal SVG off).
    mobile = css.split("@media (max-width: 760px) {", 1)[1]
    assert ".mh-an-legend { display: grid; }" in mobile
    assert ".mh-an-svg--h { display: none; }" in mobile
    assert ".mh-an-svg--v { display: block;" in mobile


def test_css_stays_on_brand():
    css = ac.ANATOMY_CALLOUT_CSS
    # Lane-yellow is the system/chrome accent (pins, lines, logo, confidence).
    assert "var(--lane)" in css
    # Medal-gold IS allowed here — it marks the athlete achievement the card
    # legitimately depicts (the moment pill + the verified PB delta), which is
    # exactly what medal-gold is reserved for.
    assert "var(--medal)" in css
    # The connector lines + hotspot pins are lane-yellow, never medal.
    line_rule = css.split(".mh-an-line {", 1)[1].split("}", 1)[0]
    assert "var(--lane)" in line_rule and "medal" not in line_rule
    dot_rule = css.split(".mh-an-pin-dot {", 1)[1].split("}", 1)[0]
    assert "var(--lane)" in dot_rule and "medal" not in dot_rule
    # Self-hosted fonts only — no Google Fonts CDN may sneak in here.
    assert "googleapis" not in css
    assert "gstatic" not in css


def test_pin_shimmer_is_reduced_motion_safe():
    """The only animation is a gentle pin-halo opacity shimmer. It must
    oscillate around a *visible* value (never reach 0), so when the global
    prefers-reduced-motion rule freezes it at any frame the pins stay legible
    and the diagram settles cleanly."""
    css = ac.ANATOMY_CALLOUT_CSS
    assert "@keyframes mh-an-shimmer" in css
    block = css.split("@keyframes mh-an-shimmer {", 1)[1].split("}\n", 1)[0]
    opacities = [float(x) for x in re.findall(r"opacity:\s*([0-9.]+)", block)]
    assert opacities, "shimmer keyframe must set opacity"
    assert min(opacities) > 0.0, "halo never fully disappears under a freeze"


def test_responsive_breakpoint_present():
    assert "@media (max-width: 760px)" in ac.ANATOMY_CALLOUT_CSS


# =========================================================================== #
# Motion technique & determinism
# =========================================================================== #
def test_no_smil_animation(section):
    assert "<animate" not in section
    assert "animateMotion" not in section
    assert "animateTransform" not in section


def test_no_inline_script(section):
    assert "<script" not in section


def test_output_is_deterministic():
    assert ac.anatomy_callout_section_html() == ac.anatomy_callout_section_html()


# =========================================================================== #
# Accessibility
# =========================================================================== #
def test_section_labelled_by_its_title(section):
    assert 'aria-labelledby="mh-an-title"' in section
    assert 'id="mh-an-title"' in section


def test_svgs_and_legend_are_decorative_with_a_text_alternative(section):
    # Both SVGs AND the legend are aria-hidden; the single visually-hidden
    # summary is the one spoken description (so AT isn't read the labels twice).
    assert section.count('aria-hidden="true"') == 3   # 2 svgs + the legend
    assert 'class="mh-visually-hidden"' in section
    summary = section.split('class="mh-visually-hidden">', 1)[1].split("</p>", 1)[0]
    assert "confidence" in summary
    assert "approval" in summary
    assert "52.41" in summary


# =========================================================================== #
# End-to-end render on /
# =========================================================================== #
def _home_body(client):
    r = client.get("/")
    assert r.status_code == 200
    return r.get_data(as_text=True)


def test_home_renders_anatomy_for_fresh_visitor(client):
    body = _home_body(client)
    assert "mh-an-stage" in body
    assert "Tom Davies" in body
    for title in _TITLES:
        assert title in body


def test_home_renders_anatomy_for_pinned_org(client):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(
        profile_id="otter-sc", display_name="Otter SC",
        brand_voice_summary="A friendly community club.",
    ))
    pinned = client.post("/api/organisation/active", data={"profile_id": "otter-sc"})
    assert pinned.status_code == 200, pinned.get_data(as_text=True)

    body = _home_body(client)
    assert "mh-an-stage" in body
    assert "mh-an-svg--h" in body and "mh-an-svg--v" in body


def test_home_injects_anatomy_css(client):
    body = _home_body(client)
    assert ".mh-an-stage" in body
    assert "@keyframes mh-an-shimmer" in body


def test_home_section_order_bento_then_anatomy_then_audience(client):
    # Anchor on body-only prose (the section eyebrows), not class names — the
    # served stylesheet also contains `.mh-bento`/`.mh-an-stage` selectors, so
    # `.index()` on a class would find the CSS, not the section.
    body = _home_body(client)
    i_hero = body.index("Sport content automation")
    i_bento = body.index("What the engine does")
    i_anat = body.index("Anatomy of a card")
    i_aud = body.index("Made for")
    assert i_hero < i_bento < i_anat < i_aud


def test_anatomy_css_sits_before_guardrails_layer(client):
    # The responsive guardrails must remain the final cascade layer; the
    # anatomy CSS therefore appears before them in the served stylesheet.
    body = _home_body(client)
    marker = "RESPONSIVE GUARDRAILS (2026)"
    assert marker in body
    assert body.index("@keyframes mh-an-shimmer") < body.index(marker)
