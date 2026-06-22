"""U.8 — Animated how-it-works pipeline diagram.

Pins the landing-page pipeline diagram (presentation-only; no engine, AI or
data surface is touched):

  * structure — eyebrow / editorial title / lede / stage, joined to the
    existing scroll-reveal system
  * the read → engine → write story — three read sources, the lane-accented
    engine with its detect/rank/brand/generate stages, three write outputs,
    each label drawn in BOTH the horizontal and the vertical (mobile) layout
  * the blueprint-grid motif reused as an in-SVG <pattern> (unique ids per SVG)
  * connecting traces — static base wires that always read, plus travelling
    light pulses (cool/raw in, lane/branded out) with path-length-independent
    dash maths
  * reduced-motion safety — pulses default to and END at opacity:0 so the
    global prefers-reduced-motion freeze settles to a clean static diagram
  * SVG + CSS keyframes only — no SMIL, no JS, no Google-Fonts CDN, no
    medal-gold (reserved for athlete achievements)
  * well-formed markup, deterministic output, accessibility
  * end-to-end render on / for both fresh and pinned-org visitors, with the
    CSS injected and the section ordered hero → pipeline → workflow steps
"""
import re
import xml.etree.ElementTree as ET

import pytest

from mediahub.web import pipeline_diagram as pd
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
    return pd.pipeline_diagram_section_html()


@pytest.fixture(scope="module")
def svgs(section):
    found = re.findall(r"<svg\b.*?</svg>", section, flags=re.S)
    assert len(found) == 2, f"expected two SVG orientations, found {len(found)}"
    return found


_READ_LABELS = ["Club site", "Socials", "Brand kit"]
_WRITE_LABELS = ["Captions", "Graphics", "Reels"]


# =========================================================================== #
# Structure & copy
# =========================================================================== #
def test_section_is_one_reveal_section(section):
    assert section.startswith("<section")
    assert section.rstrip().endswith("</section>")
    # Joins the established section chrome + scroll-reveal system.
    assert "mh-section" in section
    assert "mh-reveal" in section
    assert "mh-pl-section" in section
    assert "mh-pl-stage" in section


def test_eyebrow_title_and_lede(section):
    assert '<span class="label">How it works</span>' in section
    assert 'class="mh-section-title"' in section
    assert '<em class="editorial">Writes</em>' in section
    # The lede states the read → write thesis in words.
    assert 'class="mh-pl-lede"' in section
    assert "club site, social profiles and brand kit" in section
    assert "captions, builds graphics and renders reels" in section
    assert "Nothing leaves without your approval." in section


def test_brand_kit_lede_explains_what_it_means(section):
    """'brand kit' in the lede must be followed by a plain-English parenthetical
    so a club volunteer understands what to provide.  Without it the term is
    unexplained jargon — this test is the regression pin for that UX gap."""
    # The parenthetical must mention at least one of: logo, colours/colors, fonts.
    assert re.search(r"brand kit\s*\([^)]*(?:logo|colour|color|font)[^)]*\)", section, re.I), (
        "The lede must explain 'brand kit' with a parenthetical such as "
        "'brand kit (logo, colours and fonts)' so club volunteers understand "
        "what to provide."
    )


def test_whole_section_is_well_formed_xml(section):
    # A single <section> root that parses cleanly catches any unclosed tag,
    # stray entity, or attribute-quoting slip in the hand-built markup.
    ET.fromstring(section)


# =========================================================================== #
# Read → engine → write story
# =========================================================================== #
def test_two_orientations_present(section):
    assert "mh-pl-svg--h" in section          # horizontal (desktop/tablet)
    assert "mh-pl-svg--v" in section          # vertical (mobile)


def test_each_svg_is_well_formed_xml(svgs):
    for s in svgs:
        ET.fromstring(s)


@pytest.mark.parametrize("label", _READ_LABELS + _WRITE_LABELS)
def test_every_node_label_drawn_in_both_orientations(section, label):
    # One <text> per orientation = two per label, so neither the desktop nor
    # the mobile layout silently drops a source/output.
    assert section.count(f">{label}</text>") == 2, label


def test_engine_node_and_intelligence_stages(section):
    assert section.count(">THE ENGINE</text>") == 2
    # The intelligence-moat phrasing (ingest → detect → rank → brand → generate).
    assert section.count(">detect · rank · brand · generate</text>") == 2


def test_reads_are_neutral_writes_are_lit(section):
    # Reads stay matte ink; writes + engine are lane-lit (brand restraint).
    assert section.count("mh-pl-ico--read") == 6      # 3 reads x 2 orientations
    assert section.count("mh-pl-ico--write") == 6
    assert section.count("mh-pl-ico--engine") == 2


def test_node_chip_and_engine_counts(section):
    assert section.count("mh-pl-chip-bg") == 12       # 6 chips x 2 orientations
    assert section.count("mh-pl-engine-bg") == 2


# =========================================================================== #
# Blueprint grid motif
# =========================================================================== #
def test_blueprint_grid_pattern_reused(section):
    # An in-SVG <pattern> lattice, one per SVG with a unique id, referenced by
    # a fill — the same faint scoreboard substrate used behind the hero.
    assert 'id="mh-pl-grid-h"' in section
    assert 'id="mh-pl-grid-v"' in section
    assert "url(#mh-pl-grid-h)" in section
    assert "url(#mh-pl-grid-v)" in section
    assert section.count('class="mh-pl-grid"') == 2


# =========================================================================== #
# Connecting traces + travelling pulses
# =========================================================================== #
def test_static_base_wires_always_present(section):
    # 6 wires per orientation (3 read→engine, 3 engine→write).
    assert section.count('class="mh-pl-wire"') == 12


def test_travelling_pulses_in_and_out(section):
    # Cool/raw on the way in, lane/branded on the way out.
    assert section.count("mh-pl-pulse--in") == 6
    assert section.count("mh-pl-pulse--out") == 6


def test_pulses_use_path_length_independent_dash(section):
    # pathLength="100" lets one dasharray drive every trace regardless of its
    # actual length — one pulse path per trace = 12.
    assert section.count('pathLength="100"') == 12


def test_glowing_connection_nodes(section):
    # 2 dots per trace (chip end + engine port) x 6 traces x 2 orientations.
    # (Counted by the kind modifier so the two <g class="mh-pl-dots"> wrappers
    # don't inflate the tally.)
    assert section.count("mh-pl-dot--") == 24
    assert section.count('class="mh-pl-dots"') == 2


# =========================================================================== #
# Motion technique & brand rules
# =========================================================================== #
def test_no_smil_animation(section):
    # Roadmap mandates SVG + CSS keyframes; SMIL also bypasses the global
    # prefers-reduced-motion freeze, so it must not appear.
    assert "<animate" not in section
    assert "animateMotion" not in section
    assert "animateTransform" not in section


def test_css_defines_the_three_keyframes():
    css = pd.PIPELINE_DIAGRAM_CSS
    assert "@keyframes mh-pl-flow" in css
    assert "@keyframes mh-pl-dot-pulse" in css
    assert "@keyframes mh-pl-breathe" in css


def test_css_brace_balance():
    css = pd.PIPELINE_DIAGRAM_CSS
    assert css.count("{") == css.count("}")


def test_pulses_are_reduced_motion_safe():
    """The travelling pulse must default to opacity:0 AND its keyframe must END
    at opacity:0, so when the global reduced-motion rule freezes the animation
    at its final frame the pulses vanish and the static wires carry the
    diagram."""
    css = pd.PIPELINE_DIAGRAM_CSS
    # Default (at-rest / pre-animation) state on the pulse class.
    pulse_rule = css.split(".mh-pl-pulse {", 1)[1].split("}", 1)[0]
    assert "opacity: 0;" in pulse_rule
    # Final keyframe parks it off-path and invisible.
    assert "stroke-dashoffset: -100; opacity: 0;" in css


def test_css_stays_on_brand():
    css = pd.PIPELINE_DIAGRAM_CSS
    # Lane-yellow is the only chrome accent; reads use neutral ink.
    assert "var(--lane)" in css
    assert "var(--ink-dim)" in css
    # Medal-gold is reserved for athlete achievements — never chrome.
    assert "var(--medal" not in css
    assert "var(--gold" not in css
    # Self-hosted fonts only — no Google Fonts CDN may sneak in here.
    assert "googleapis" not in css
    assert "gstatic" not in css


def test_output_is_deterministic():
    assert pd.pipeline_diagram_section_html() == pd.pipeline_diagram_section_html()


# =========================================================================== #
# Accessibility
# =========================================================================== #
def test_section_labelled_by_its_title(section):
    assert 'aria-labelledby="mh-pl-title"' in section
    assert 'id="mh-pl-title"' in section


def test_svgs_are_decorative_with_a_text_alternative(section):
    # Both SVGs are aria-hidden duplicates; one visually-hidden summary is the
    # single spoken description for every viewport.
    assert section.count('aria-hidden="true"') == 2
    assert 'class="mh-visually-hidden"' in section
    summary = section.split('class="mh-visually-hidden">', 1)[1].split("</p>", 1)[0]
    assert "reads" in summary and "writes" in summary
    assert "approval" in summary


# =========================================================================== #
# End-to-end render on /
# =========================================================================== #
def _home_body(client):
    r = client.get("/")
    assert r.status_code == 200
    return r.get_data(as_text=True)


def test_home_renders_diagram_for_fresh_visitor(client):
    body = _home_body(client)
    assert "mh-pl-stage" in body
    assert ">THE ENGINE</text>" in body
    for label in _READ_LABELS + _WRITE_LABELS:
        assert label in body


def test_pinned_home_omits_diagram_now_on_help(client):
    # The signed-in home became a content-creation workspace; the how-it-works
    # diagram (and the rest of the product-story explainer) moved to the Help
    # page, reached from the account menu. Seed + pin a real organisation so
    # home() takes the returning-tenant branch.
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(
        profile_id="otter-sc", display_name="Otter SC",
        brand_voice_summary="A friendly community club.",
    ))
    pinned = client.post("/api/organisation/active", data={"profile_id": "otter-sc"})
    assert pinned.status_code == 200, pinned.get_data(as_text=True)

    # The diagram's SVG text is markup-only (the .mh-pl-stage class name also
    # appears in the always-shipped CSS), so it is the honest signal that the
    # section itself is gone from the signed-in home.
    home = _home_body(client)
    assert ">THE ENGINE</text>" not in home

    # …and renders in full on the Help page.
    help_body = client.get("/help").get_data(as_text=True)
    assert "mh-pl-stage" in help_body
    assert "mh-pl-svg--h" in help_body and "mh-pl-svg--v" in help_body
    assert ">THE ENGINE</text>" in help_body


def test_home_injects_pipeline_css(client):
    body = _home_body(client)
    assert "@keyframes mh-pl-flow" in body
    assert ".mh-pl-stage" in body


def test_home_section_order_hero_then_pipeline_then_engine(client):
    body = _home_body(client)
    i_hero = body.index("mh-hero")
    i_pipeline = body.index("mh-pl-stage")
    i_engine = body.index("What the engine does")
    assert i_hero < i_pipeline < i_engine


def test_pipeline_css_sits_before_guardrails_layer(client):
    # The responsive guardrails must remain the final cascade layer; the
    # pipeline CSS therefore appears before them in the served stylesheet.
    body = _home_body(client)
    # A marker unique to the guardrails layer (the leading comment block).
    marker = "RESPONSIVE GUARDRAILS (2026)"
    assert marker in body
    assert body.index("@keyframes mh-pl-flow") < body.index(marker)
