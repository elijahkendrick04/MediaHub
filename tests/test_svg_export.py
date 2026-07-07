"""Tests for graphic_renderer.svg_export — G1.13 SVG vector export path.

The API-surface tests run everywhere. The real conversions drive Chromium
(HTML → vector PDF) + PDFium (PDF → SVG) and are skipped when Playwright/
Chromium isn't installed (same convention as tests/test_v8_graphic_renderer.py
and tests/test_print_export.py).

Faithfulness is checked by re-rasterising the produced SVG through Chromium and
comparing it to the source render: an outlined-vector SVG that reopens to the
same picture is the whole point of the feature.
"""

from __future__ import annotations

import base64
import re
from io import BytesIO
from pathlib import Path

import pytest

from mediahub.graphic_renderer import svg_export
from mediahub.graphic_renderer.svg_export import (
    SvgExportError,
    SvgExportUnavailable,
    export_svg_alongside,
    html_to_svg,
    render_html_to_svg,
    svg_sidecar_path,
)


def _have_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(args=["--no-sandbox"])
                browser.close()
                return True
            except Exception:
                return False
    except Exception:
        return False


def _have_pdfium() -> bool:
    try:
        import pypdfium2  # noqa
        import pypdfium2.raw  # noqa

        return True
    except Exception:
        return False


_LIVE = pytest.mark.skipif(
    not (_have_playwright() and _have_pdfium()),
    reason="Playwright/Chromium or pypdfium2 not available",
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _png_data_uri(w: int = 120, h: int = 80, rgb=(220, 40, 40)) -> str:
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (w, h), rgb)
    ImageDraw.Draw(im).ellipse([w * 0.2, h * 0.2, w * 0.8, h * 0.8], fill=(40, 160, 220))
    buf = BytesIO()
    im.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


_BOX_HTML = (
    "<!doctype html><meta charset=utf-8>"
    "<style>@page{margin:0}html,body{margin:0;padding:0}"
    ".box{position:absolute;left:40px;top:30px;width:160px;height:90px;background:#cc1133}"
    ".t{position:absolute;left:40px;top:150px;font:700 44px sans-serif;color:#0a2540}"
    "</style><div class=box></div><div class=t>PB</div>"
)


def _raster_svg(svg: str, size, tmp_path: Path):
    """Re-rasterise an SVG string through Chromium → PIL RGB image."""
    from PIL import Image
    from playwright.sync_api import sync_playwright

    wrap = tmp_path / "wrap.html"
    wrap.write_text(f"<!doctype html><meta charset=utf-8><style>*{{margin:0}}</style>{svg}")
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": size[0], "height": size[1]})
        page.goto(wrap.as_uri(), wait_until="networkidle")
        shot = page.screenshot(clip={"x": 0, "y": 0, "width": size[0], "height": size[1]})
        browser.close()
    return Image.open(BytesIO(shot)).convert("RGB")


def _mean_diff(a, b) -> float:
    from PIL import ImageChops, ImageStat

    if a.size != b.size:
        b = b.resize(a.size)
    stat = ImageStat.Stat(ImageChops.difference(a, b))
    return sum(stat.mean) / len(stat.mean)


# ---------------------------------------------------------------------------
# API surface (no Chromium needed)
# ---------------------------------------------------------------------------


class TestApiSurface:
    def test_sidecar_path(self):
        assert svg_sidecar_path("runs/r1/feed_portrait.png") == Path("runs/r1/feed_portrait.svg")
        assert svg_sidecar_path(Path("/a/b/story.png")).suffix == ".svg"

    def test_exceptions_are_runtime_errors(self):
        assert issubclass(SvgExportError, RuntimeError)
        assert issubclass(SvgExportUnavailable, SvgExportError)

    def test_unavailable_when_playwright_missing(self, monkeypatch):
        # Simulate Playwright import failing inside the PDF step.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "playwright.sync_api":
                raise ImportError("no playwright")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(SvgExportUnavailable):
            svg_export._render_html_to_pdf_bytes("<p>x</p>", (100, 100))

    def test_bad_pdf_bytes_raise(self):
        with pytest.raises(SvgExportError):
            svg_export._pdf_bytes_to_svg(
                b"not a pdf", (100, 100), embed_images=True, clip=True, background=None, title=None
            )


# ---------------------------------------------------------------------------
# Real HTML → SVG conversions
# ---------------------------------------------------------------------------


@_LIVE
class TestHtmlToSvg:
    def test_basic_structure(self):
        svg = html_to_svg(_BOX_HTML, (300, 260), title="Card")
        assert svg.startswith("<?xml")
        assert "<svg" in svg and "</svg>" in svg
        assert 'viewBox="0 0 300 260"' in svg
        assert 'width="300"' in svg and 'height="260"' in svg
        assert "<title>Card</title>" in svg

    def test_text_is_outlined_not_font(self):
        svg = html_to_svg(_BOX_HTML, (300, 260))
        # Outlined fonts: real <path> glyphs, never a <text> element or a font.
        assert "<text" not in svg
        assert "@font-face" not in svg
        assert "fonts.googleapis.com" not in svg and "gstatic" not in svg
        assert ".woff" not in svg
        assert svg.count("<path") >= 2  # the box + outlined "PB" glyphs

    def test_shapes_keep_their_colour(self):
        svg = html_to_svg(_BOX_HTML, (300, 260))
        assert "#cc1133" in svg.lower()  # the box fill survives as a vector path

    def test_title_is_escaped(self):
        svg = html_to_svg(_BOX_HTML, (300, 260), title='<script>alert(1)</script>')
        assert "<script>" not in svg
        assert "&lt;script&gt;" in svg

    def test_deterministic(self):
        a = html_to_svg(_BOX_HTML, (300, 260))
        b = html_to_svg(_BOX_HTML, (300, 260))
        assert a == b

    def test_faithful_when_rerasterised(self, tmp_path):
        size = (300, 260)
        svg = html_to_svg(_BOX_HTML, size, background="#ffffff")
        from playwright.sync_api import sync_playwright
        from PIL import Image

        src_html = tmp_path / "src.html"
        src_html.write_text(_BOX_HTML)
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": size[0], "height": size[1]})
            page.goto(src_html.as_uri(), wait_until="networkidle")
            orig = Image.open(
                BytesIO(page.screenshot(clip={"x": 0, "y": 0, "width": size[0], "height": size[1]}))
            ).convert("RGB")
            browser.close()
        rer = _raster_svg(svg, size, tmp_path)
        assert _mean_diff(orig, rer) < 12.0


@_LIVE
class TestImages:
    def test_photo_is_embedded(self):
        uri = _png_data_uri()
        html = (
            "<!doctype html><meta charset=utf-8><style>@page{margin:0}body{margin:0;background:#10202f}"
            "img{position:absolute;left:30px;top:30px;width:200px;height:140px}</style>"
            f'<img src="{uri}">'
        )
        svg = html_to_svg(html, (300, 220))
        assert "<image" in svg
        assert "data:image/png;base64," in svg

    def test_strict_mode_has_no_raster(self):
        uri = _png_data_uri()
        html = (
            "<!doctype html><meta charset=utf-8><style>@page{margin:0}body{margin:0;background:#10202f}"
            "img{position:absolute;left:30px;top:30px;width:200px;height:140px}</style>"
            f'<img src="{uri}">'
        )
        svg = html_to_svg(html, (300, 220), embed_images=False)
        assert "<image" not in svg
        assert "data:image" not in svg
        assert "mh-image-placeholder" in svg

    def test_embedded_photo_is_faithful(self, tmp_path):
        size = (320, 320)
        uri = _png_data_uri(300, 200)
        html = (
            "<!doctype html><meta charset=utf-8><style>@page{margin:0}body{margin:0;background:#0a2540}"
            ".w{position:absolute;inset:30px}img{width:100%;height:100%;object-fit:cover}</style>"
            f'<div class=w><img src="{uri}"></div>'
        )
        svg = html_to_svg(html, size)
        from playwright.sync_api import sync_playwright
        from PIL import Image

        src = tmp_path / "src.html"
        src.write_text(html)
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": size[0], "height": size[1]})
            page.goto(src.as_uri(), wait_until="networkidle")
            orig = Image.open(
                BytesIO(page.screenshot(clip={"x": 0, "y": 0, "width": size[0], "height": size[1]}))
            ).convert("RGB")
            browser.close()
        assert _mean_diff(orig, _raster_svg(svg, size, tmp_path)) < 12.0


@_LIVE
class TestWriteFile:
    def test_render_html_to_svg_writes(self, tmp_path):
        out = tmp_path / "card.svg"
        res = render_html_to_svg(_BOX_HTML, out, (300, 260))
        assert res == out
        assert out.exists()
        assert out.read_text().startswith("<?xml")
        # No throwaway render html left behind anywhere.
        assert not list(tmp_path.glob("*.render.html"))

    def test_export_svg_alongside(self, tmp_path):
        png = tmp_path / "feed_portrait.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")  # stand-in PNG
        out = export_svg_alongside(png, _BOX_HTML, (300, 260))
        assert out == tmp_path / "feed_portrait.svg"
        assert out.exists() and "<svg" in out.read_text()
        # The re-export of the identical inputs is a cheap freshness hit — the
        # sidecar bytes stay identical (same stamped content key).
        first = out.read_text()
        assert export_svg_alongside(png, _BOX_HTML, (300, 260)) == out
        assert out.read_text() == first


class TestSidecarFreshness:
    """A fresh <stem>.svg (same html+size+options key) skips the whole
    Chromium + PDFium pass; any input change re-exports. No browser needed —
    the conversion is stubbed and counted."""

    def _counting_stub(self, monkeypatch):
        calls = {"n": 0}

        def fake_html_to_svg(html, size, **kw):
            calls["n"] += 1
            return (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{size[0]}" '
                f'height="{size[1]}"><path d="M0 0"/></svg>\n'
            )

        monkeypatch.setattr(svg_export, "html_to_svg", fake_html_to_svg)
        return calls

    def test_fresh_sidecar_is_not_re_exported(self, tmp_path, monkeypatch):
        calls = self._counting_stub(monkeypatch)
        png = tmp_path / "story.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")
        out1 = export_svg_alongside(png, "<p>card</p>", (1080, 1920))
        assert calls["n"] == 1
        assert f"{svg_export._SIDECAR_KEY_MARK}" in out1.read_text()[:512]
        out2 = export_svg_alongside(png, "<p>card</p>", (1080, 1920))
        assert out2 == out1
        assert calls["n"] == 1  # skipped: sidecar was fresh

    def test_changed_html_or_size_re_exports(self, tmp_path, monkeypatch):
        calls = self._counting_stub(monkeypatch)
        png = tmp_path / "story.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")
        export_svg_alongside(png, "<p>card</p>", (1080, 1920))
        export_svg_alongside(png, "<p>CHANGED</p>", (1080, 1920))
        assert calls["n"] == 2
        export_svg_alongside(png, "<p>CHANGED</p>", (1080, 1080))
        assert calls["n"] == 3

    def test_changed_options_re_export(self, tmp_path, monkeypatch):
        calls = self._counting_stub(monkeypatch)
        png = tmp_path / "story.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")
        export_svg_alongside(png, "<p>card</p>", (1080, 1920))
        export_svg_alongside(png, "<p>card</p>", (1080, 1920), embed_images=False)
        assert calls["n"] == 2


class TestNeedsShaping:
    def test_latin_never_flagged(self):
        for ch in "PB Eira Hughes 2:08.41 — ÉÀÖ":
            assert not svg_export._needs_shaping(ord(ch)), ch

    def test_shaped_scripts_flagged(self):
        for ch in "سلאकส":  # Arabic, Hebrew, Devanagari, Thai
            assert svg_export._needs_shaping(ord(ch)), hex(ord(ch))


@_LIVE
class TestShapedScriptFallback:
    _AR_HTML = (
        "<!doctype html><meta charset=utf-8>"
        "<style>@page{margin:0}html,body{margin:0;padding:0}"
        ".t{position:absolute;left:20px;top:60px;font:700 44px sans-serif;color:#0a2540}"
        "</style><div class=t>سباحة رائعة</div>"
    )

    def test_arabic_text_is_not_silently_dropped(self):
        """A shaped-script run must ship as a raster embed of its rendered
        footprint — never as silently-dropped / isolated-form outlines."""
        svg = html_to_svg(self._AR_HTML, (400, 200))
        assert "mh-text-raster" in svg

    def test_strict_mode_logs_fidelity_warning(self, caplog):
        import logging as _logging

        with caplog.at_level(_logging.WARNING, logger="mediahub.graphic_renderer.svg_export"):
            svg = html_to_svg(self._AR_HTML, (400, 200), embed_images=False)
        assert "mh-text-raster" not in svg  # strict export stays raster-free
        assert any("not faithfully outlineable" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Real card briefs end-to-end
# ---------------------------------------------------------------------------


def _brand():
    from mediahub.brand.kit import BrandKit

    return BrandKit(
        profile_id="t",
        display_name="Test Swim Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="TSC",
    )


def _brief(layout="individual_hero"):
    from mediahub.creative_brief.generator import generate as gen_brief
    from mediahub.media_requirements.evaluator import EvaluationResult

    ev = EvaluationResult(
        content_item_id="ci-1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout=layout,
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label="NEW PB",
        explain="ok",
    )
    item = {
        "id": "ci-1",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
        },
    }
    return gen_brief(item, ev, _brand(), profile_id="t", meet_name="Manchester Open", venue_name="Pool")


@_LIVE
class TestCardEndToEnd:
    def test_card_svg_is_outlined_and_faithful(self, tmp_path):
        from mediahub.graphic_renderer.render import render_brief

        size = (1080, 1350)
        res = render_brief(_brief(), output_dir=tmp_path, size=size, format_name="feed_portrait", brand_kit=_brand())
        svg = html_to_svg(res.html, size, title="card")
        assert "<text" not in svg  # fonts outlined
        assert svg.count("<path") > 20  # masthead + headline + result + footer glyphs
        # A strong brand-blue fill reaches the SVG (the exact shade is Chromium's
        # role-resolved render of the primary, not necessarily the literal hex).
        fills = [m for m in re.findall(r'fill="#([0-9a-fA-F]{6})"', svg)]
        blues = [f for f in fills if int(f[4:6], 16) > 150 and int(f[4:6], 16) > int(f[0:2], 16) + 40]
        assert blues, f"expected a blue brand fill, got {set(fills)}"
        from PIL import Image

        orig = Image.open(res.visual.file_path).convert("RGB")
        assert _mean_diff(orig, _raster_svg(svg, size, tmp_path)) < 18.0

    def test_sidecar_flag_emits_svg(self, tmp_path, monkeypatch):
        from mediahub.graphic_renderer.render import render_brief

        monkeypatch.setenv("MEDIAHUB_SVG_SIDECAR", "1")
        res = render_brief(_brief(), output_dir=tmp_path, size=(1080, 1080), format_name="feed_square", brand_kit=_brand())
        sidecar = svg_sidecar_path(res.visual.file_path)
        assert sidecar.exists()
        assert "<text" not in sidecar.read_text()

    def test_no_sidecar_by_default(self, tmp_path, monkeypatch):
        from mediahub.graphic_renderer.render import render_brief

        monkeypatch.delenv("MEDIAHUB_SVG_SIDECAR", raising=False)
        res = render_brief(_brief(), output_dir=tmp_path, size=(1080, 1080), format_name="feed_square", brand_kit=_brand())
        assert not svg_sidecar_path(res.visual.file_path).exists()

    def test_format_sizes_match_viewbox(self, tmp_path):
        from mediahub.graphic_renderer.render import render_brief

        for fmt, size in (("feed_square", (1080, 1080)), ("story", (1080, 1920))):
            res = render_brief(_brief(), output_dir=tmp_path, size=size, format_name=fmt, brand_kit=_brand())
            svg = html_to_svg(res.html, size)
            assert f'viewBox="0 0 {size[0]} {size[1]}"' in svg
            assert f'width="{size[0]}"' in svg and f'height="{size[1]}"' in svg
