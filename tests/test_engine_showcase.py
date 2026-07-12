"""Engine showcase — the landing "What the engine does" section *shows* real
sample outputs (inline SVG renders) instead of describing them in text.

Pins:
  * the generator (``web/sample_graphics.py``) emits well-formed, fully
    self-contained inline SVG for every format, that consumes the live brand
    tokens + self-hosted fonts (never a CDN / remote fetch);
  * the samples are factually exact (the verified PB facts; honest, present
    ranked scores) — no invented numbers;
  * the home page frames all six in the bento showcase, preserving the
    tilt/reveal structure, and labels them honestly;
  * the CSS showcase contract (grid areas, the reduced-motion sheen stand-down
    that the U.16 browser test needs, the reel pulse + its reduced-motion gate).
"""
from __future__ import annotations

import re
import xml.dom.minidom as minidom
from pathlib import Path

import pytest

from mediahub.web import sample_graphics as sg
from mediahub.web import web as webmod

_ROOT = Path(__file__).resolve().parents[1]
COMPONENTS_CSS = (
    _ROOT / "src" / "mediahub" / "web" / "static" / "theme" / "theme-components.css"
).read_text(encoding="utf-8")


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


def _home(client) -> str:
    resp = client.get("/")
    assert resp.status_code == 200, resp.status_code
    return resp.get_data(as_text=True)


# --------------------------------------------------------------------------- #
# The generator
# --------------------------------------------------------------------------- #
class TestSampleGenerator:
    def test_all_formats_present(self):
        assert set(sg.SAMPLES) == {
            "story", "reel", "feed", "ranked", "brand", "moments"
        }

    @pytest.mark.parametrize("name", list(sg.SAMPLES))
    def test_well_formed_svg(self, name):
        svg = sg.SAMPLES[name]()
        doc = minidom.parseString(svg)  # raises on malformed XML
        assert doc.documentElement.tagName == "svg"
        assert "viewBox" in svg

    @pytest.mark.parametrize("name", list(sg.SAMPLES))
    def test_self_contained_no_remote_refs(self, name):
        low = sg.SAMPLES[name]().lower()
        assert "googleapis" not in low and "gstatic" not in low
        assert 'href="http' not in low and "href='http" not in low
        assert "url(http" not in low and "@import" not in low
        # pure vector — no raster / remote bitmap, no script
        assert "<image" not in low and "data:image" not in low
        assert "<script" not in low

    @pytest.mark.parametrize("name", list(sg.SAMPLES))
    def test_accessible(self, name):
        svg = sg.SAMPLES[name]()
        assert 'role="img"' in svg
        assert "<title>" in svg and "</title>" in svg

    @pytest.mark.parametrize("name", list(sg.SAMPLES))
    def test_uses_live_brand_tokens_and_self_hosted_fonts(self, name):
        # On-brand by construction: consume the role tokens + self-hosted font
        # stacks, never a hardcoded family or a CDN webfont.
        svg = sg.SAMPLES[name]()
        assert "var(--font-display" in svg or "var(--font-mono" in svg
        assert "var(--ink" in svg or "var(--lane" in svg

    def test_story_card_is_factually_exact(self):
        svg = sg.story_card_svg()
        for fact in ("TOM", "DAVIES", "52.41", "100M FREESTYLE", "0.74s", "53.15"):
            assert fact in svg, f"story card missing verified fact {fact!r}"

    def test_medal_gold_reserved_for_achievement(self):
        # Gold appears on the achievement surfaces (story PB chip, podium,
        # ranked medal badges) — never as plain chrome.
        assert "var(--medal" in sg.story_card_svg()
        assert "var(--medal" in sg.feed_graphic_svg()

    def test_ranked_scores_present_and_ordered(self):
        # The intelligence read-out shows honest content-worthiness scores,
        # descending (the ranking the engine computed).
        svg = sg.detected_ranked_svg()
        scores = [float(m) for m in re.findall(r">(0\.\d\d)<", svg)]
        assert scores, "no ranked scores rendered"
        assert scores == sorted(scores, reverse=True), scores


# --------------------------------------------------------------------------- #
# The home-page showcase
# --------------------------------------------------------------------------- #
class TestHomeShowcase:
    def test_section_and_heading(self, client):
        body = _home(client)
        assert 'id="mh-ch-engine"' in body
        assert "What the engine does" in body
        assert "A results sheet in." in body

    def test_six_tiles_with_one_feature(self, client):
        body = _home(client)
        assert "mh-bento mh-reveal-group" in body
        assert 'class="mh-bento-tile feature' in body
        assert body.count('class="mh-bento-tile') == 6

    def test_every_tile_frames_an_inline_svg_render(self, client):
        # Each showcase tile carries a real inline SVG output (role="img"),
        # not a text description.
        body = _home(client)
        section = body[body.find('id="mh-ch-engine"'):body.find('id="mh-ch-audience"')]
        assert section.count("<svg") == 6, section.count("<svg")
        assert "mh-bento-caption" in section
        # the old text-tile copy is gone
        for dead in ("mh-bento-stat", "mh-bento-timeline", "mh-bento-moments",
                     "A clean vertical story graphic"):
            assert dead not in body, f"stale bento text artefact left: {dead!r}"

    def test_showcase_outputs_are_labelled(self, client):
        body = _home(client)
        for needle in ("MEET-DAY", "TOP THREE", "DETECTED &amp; RANKED",
                       "YOUR BRAND", "WE DETECT"):
            assert needle in body, f"showcase missing output {needle!r}"

    def test_sits_after_the_input_output_band(self, client):
        body = _home(client)
        i_hero = body.find('class="mh-hero"')
        i_band = body.find('class="mh-pipeline"')
        i_engine = body.find('class="mh-bento')
        assert -1 < i_hero < i_band < i_engine

    def test_no_remote_image_sources(self, client):
        # The inline SVGs add no <img>; the page stays same-origin only.
        body = _home(client)
        for src in re.findall(r'<img[^>]*\bsrc="([^"]+)"', body):
            assert not src.startswith("http://") and not src.startswith("https://"), src

    def test_demo_meet_moment_count_consistent_across_sections(self, client):
        # The "See it in action" carousel (_hero_product_demo) and the
        # "Detected & ranked" bento tile (sample_graphics.detected_ranked_svg)
        # both narrate the SAME fixed demo file ("42 swims read"). If they
        # disagree on how many moments that file produced, a volunteer reading
        # the page gets two different answers to "how much content will I get
        # from my results file?" in the same scroll.
        body = _home(client)
        carousel = re.search(r"(\d+) swims read.{0,20}?(\d+) moments ranked", body)
        assert carousel, "carousel demo meter text not found on the home page"
        carousel_swims, carousel_moments = int(carousel.group(1)), int(carousel.group(2))

        bento = re.search(
            r'font-size="68"[^>]*>(\d+)</text>.*?FROM (\d+) SWIMS READ', body, re.S
        )
        assert bento, "bento 'detected & ranked' stat not found on the home page"
        bento_moments, bento_swims = int(bento.group(1)), int(bento.group(2))

        assert carousel_swims == bento_swims, (
            f"same demo file quoted as {carousel_swims} swims read in the "
            f"carousel but {bento_swims} in the bento tile"
        )
        assert carousel_moments == bento_moments, (
            f"same {carousel_swims}-swim demo file scored {carousel_moments} "
            f"moments ranked in the carousel but {bento_moments} moments "
            "detected in the bento tile"
        )


# --------------------------------------------------------------------------- #
# CSS contract
# --------------------------------------------------------------------------- #
class TestShowcaseCss:
    def test_grid_areas_and_feature(self):
        assert "grid-template-areas" in COMPONENTS_CSS
        assert ".mh-bento-tile.feature" in COMPONENTS_CSS
        assert ".mh-bento-tile > svg" in COMPONENTS_CSS

    def test_reduced_motion_stands_down_sheen_explicitly(self):
        # The U.16 browser test asserts the sheen ::before computes to
        # display:none under reduced motion — there must be a real rule.
        m = re.search(
            r"@media \(prefers-reduced-motion: reduce\)\s*\{[^}]*"
            r"\.mh-bento-tile::before\s*\{\s*display:\s*none",
            COMPONENTS_CSS,
        )
        assert m, "no explicit reduced-motion display:none for .mh-bento-tile::before"

    def test_reel_pulse_is_defined_and_reduced_motion_gated(self):
        assert "@keyframes mh-reel-pulse" in COMPONENTS_CSS
        assert ".mhg-reel-pulse" in COMPONENTS_CSS
        rm = COMPONENTS_CSS[COMPONENTS_CSS.rfind("prefers-reduced-motion: reduce"):]
        # the gate that disables the pulse lives in a reduced-motion block
        assert ".mhg-reel-pulse" in COMPONENTS_CSS[
            COMPONENTS_CSS.find("@media (prefers-reduced-motion: reduce) {",
                                COMPONENTS_CSS.find("mh-reel-pulse")):
        ]
