"""UI 1.3 — inline media thumbnails in a display headline (Samara-inspired).

The landing page carries a large display sentence — "From a results sheet
[img] to a story [img], a feed graphic [img] and a reel [img]" — with four
*real* sample-output thumbnails inlined. The images are first-party SVGs
served from /static/samples (no external fetch); they mirror the same
facts/formats as the larger sample row further down the page.

These tests pin:
  - the four sample SVGs exist, are well-formed, and are fully self-contained
    (no remote URL, webfont import, or raster <image> embed)
  - each is served from /static with an SVG content-type
  - the home page renders the headline band, inlines all four via
    url_for('static', ...), and gives every inline <img> a descriptive alt
  - no CDN/remote image source sneaks onto the band
"""
from __future__ import annotations

import re
import xml.dom.minidom as minidom
from pathlib import Path

import pytest

from mediahub.web import web as webmod

_ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = _ROOT / "src" / "mediahub" / "web" / "static" / "samples"
# (filename, kind, alt-substring the home page must carry for this output)
SAMPLES = [
    ("results-sheet.svg", "results", "freestyle"),
    ("story-card.svg", "story", "personal best"),
    ("feed-graphic.svg", "feed", "podium"),
    ("reel.svg", "reel", "highlights"),
]
SAMPLE_FILES = [fn for fn, _k, _a in SAMPLES]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(webmod, "RUNS_DIR", runs, raising=False)
    app = webmod.app
    app.config["TESTING"] = True  # disables CSRF enforcement (see _csrf_enforced)
    with app.test_client() as c:
        yield c


# --------------------------------------------------------------------------- #
# The static assets
# --------------------------------------------------------------------------- #
class TestSampleAssets:
    def test_all_four_present(self):
        for fn in SAMPLE_FILES:
            assert (SAMPLES_DIR / fn).is_file(), f"missing sample output {fn}"

    @pytest.mark.parametrize("fn", SAMPLE_FILES)
    def test_well_formed_svg(self, fn):
        txt = (SAMPLES_DIR / fn).read_text(encoding="utf-8")
        doc = minidom.parseString(txt)  # raises on malformed XML
        root = doc.documentElement
        assert root.tagName == "svg"
        # A square-portrait chip aspect shared by all four so the row reads
        # evenly inline.
        assert root.getAttribute("viewBox") == "0 0 144 200"

    @pytest.mark.parametrize("fn", SAMPLE_FILES)
    def test_self_contained_no_remote_refs(self, fn):
        """No external fetch of any kind — the whole point of /static."""
        txt = (SAMPLES_DIR / fn).read_text(encoding="utf-8").lower()
        assert "googleapis" not in txt and "gstatic" not in txt
        # no remote resource references (the only http(s) allowed is the SVG
        # xmlns namespace URI, which never appears in these attributes)
        assert 'href="http' not in txt and "href='http" not in txt
        assert "url(http" not in txt
        assert "@import" not in txt
        # pure vector — no embedded raster pulling in a binary/remote bitmap
        assert "<image" not in txt
        assert "data:image" not in txt

    @pytest.mark.parametrize("fn", SAMPLE_FILES)
    def test_has_accessible_title(self, fn):
        txt = (SAMPLES_DIR / fn).read_text(encoding="utf-8")
        assert "role=\"img\"" in txt
        assert "<title>" in txt and "</title>" in txt


# --------------------------------------------------------------------------- #
# Served from /static
# --------------------------------------------------------------------------- #
class TestSampleServed:
    @pytest.mark.parametrize("fn", SAMPLE_FILES)
    def test_served_as_svg(self, client, fn):
        resp = client.get(f"/static/samples/{fn}")
        assert resp.status_code == 200, f"/static/samples/{fn} -> {resp.status_code}"
        assert "svg" in resp.content_type, resp.content_type  # image/svg+xml
        assert "<svg" in resp.get_data(as_text=True)


# --------------------------------------------------------------------------- #
# The home-page band
# --------------------------------------------------------------------------- #
class TestHomeHeadline:
    def _home(self, client):
        resp = client.get("/")
        assert resp.status_code == 200, resp.status_code
        return resp.get_data(as_text=True)

    def _about(self, client):
        resp = client.get("/about")
        assert resp.status_code == 200, resp.status_code
        return resp.get_data(as_text=True)

    def test_headline_band_present(self, client):
        body = self._home(client)
        assert 'class="mh-pipeline"' in body
        assert "mh-pipeline-headline" in body
        # the roadmap-specified sentence scaffolding
        assert "From a results sheet" in body
        assert "to a story" in body
        assert "feed graphic" in body
        assert "and a reel" in body

    def test_band_sits_after_hero_before_engine(self, client):
        # The engine bento moved to /about (the brief home keeps the band but
        # drops the deep sections), so the band→engine ordering is asserted on
        # /about, where hero, the io band and the bento all coexist.
        body = self._about(client)
        i_hero = body.find('class="mh-hero"')
        i_band = body.find('class="mh-pipeline"')
        # After the input→output band comes the "what the engine does" bento.
        # Anchor on the HTML class="…" form (the bare name also appears in the
        # injected <style>, which would order by stylesheet, not DOM, position).
        i_engine = body.find('class="mh-bento')
        assert -1 < i_hero < i_band < i_engine, (i_hero, i_band, i_engine)

    def test_all_four_thumbs_inlined(self, client):
        body = self._home(client)
        for fn in SAMPLE_FILES:
            assert f"samples/{fn}" in body, f"home does not inline {fn}"
        imgs = re.findall(r'<img[^>]*class="mh-inline-thumb[^>]*>', body)
        assert len(imgs) == 4, f"expected 4 inline thumbs, found {len(imgs)}"
        for _fn, kind, _alt in SAMPLES:
            assert f"mh-inline-thumb--{kind}" in body

    def test_every_inline_image_is_same_origin_static(self, client):
        body = self._home(client)
        for tag in re.findall(r'<img[^>]*class="mh-inline-thumb[^>]*>', body):
            src = re.search(r'src="([^"]+)"', tag)
            assert src, f"inline thumb missing src: {tag[:90]}"
            assert src.group(1).startswith("/static/samples/"), src.group(1)

    def test_every_inline_image_has_descriptive_alt(self, client):
        body = self._home(client)
        alts = []
        for tag in re.findall(r'<img[^>]*class="mh-inline-thumb[^>]*>', body):
            alt = re.search(r'alt="([^"]*)"', tag)
            assert alt and alt.group(1).strip(), f"inline thumb missing alt: {tag[:90]}"
            alts.append(alt.group(1).lower())
        joined = " ".join(alts)
        for _fn, _kind, needle in SAMPLES:
            assert needle in joined, f"no alt describes the {_kind} output ({needle!r})"

    def test_no_external_image_source_on_page(self, client):
        # Every <img> on the landing is same-origin — no remote/CDN bitmaps.
        # (The page text legitimately *names* the Google Fonts CDN in a comment
        # explaining why fonts are self-hosted, so a blanket substring check on
        # the body would be wrong; the guarantee that matters is image sources.)
        body = self._home(client)
        for src in re.findall(r'<img[^>]*\bsrc="([^"]+)"', body):
            assert not src.startswith("http://") and not src.startswith("https://"), src

    def test_inline_images_are_lazy_and_sized(self, client):
        """Inline thumbs declare intrinsic size + lazy/async so they never
        cause layout shift or block the hero."""
        body = self._home(client)
        for tag in re.findall(r'<img[^>]*class="mh-inline-thumb[^>]*>', body):
            assert 'width="144"' in tag and 'height="200"' in tag, tag[:90]
            assert 'loading="lazy"' in tag, tag[:90]
            assert 'decoding="async"' in tag, tag[:90]


# --------------------------------------------------------------------------- #
# The CSS contract (motion is reduced-motion gated; chips are styled)
# --------------------------------------------------------------------------- #
class TestBandCss:
    CSS = (
        _ROOT / "src" / "mediahub" / "web" / "static" / "theme" / "theme-components.css"
    ).read_text(encoding="utf-8")

    def test_band_rules_exist(self):
        for sel in (
            ".mh-pipeline",
            ".mh-pipeline-headline",
            ".mh-inline-thumb",
            ".mh-inline-thumb-wrap",
            "@keyframes mh-thumb-pop",
        ):
            assert sel in self.CSS, f"missing CSS rule {sel}"

    def test_motion_is_reduced_motion_gated(self):
        # the hover/entrance animation must collapse under reduced motion
        block = self.CSS[self.CSS.find("UI 1.3"):]
        assert "prefers-reduced-motion: reduce" in block
        rm = block[block.find("prefers-reduced-motion"):]
        assert "animation: none" in rm
        assert "transform: none" in rm

    def test_headline_uses_brand_display_font(self):
        block = self.CSS[self.CSS.find(".mh-pipeline-headline"):]
        head = block[: block.find("}")]
        assert "var(--font-display)" in head
