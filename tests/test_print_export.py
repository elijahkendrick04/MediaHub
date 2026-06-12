"""Tests for graphic_renderer.print_export — W.12 A4 PDF print exports.

HTML-builder tests run everywhere. The PDF tests run real Playwright
print-to-PDF renders and are skipped if Playwright/Chromium isn't installed
(same convention as tests/test_v8_graphic_renderer.py).
"""

from __future__ import annotations

import pytest

from mediahub.graphic_renderer.print_export import (
    build_certificate_html,
    build_poster_html,
    export_certificate_pdf,
    export_poster_pdf,
    render_html_to_pdf,
)


def _have_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
                browser.close()
                return True
            except Exception:
                return False
    except Exception:
        return False


_PLAYWRIGHT = pytest.mark.skipif(
    not _have_playwright(), reason="Playwright/Chromium not available"
)


BRAND = {"primary": "#0E5BFF", "secondary": "#101820", "accent": "#FFD24A"}


def _certificate_html(**overrides) -> str:
    kwargs = dict(
        swimmer_name="Eira Hughes",
        event_label="200m Freestyle",
        time_str="2:08.41",
        achievement_headline="Personal Best Certificate",
        meet_name="Welsh Winter Open 2026",
        meet_date="7 June 2026",
        club_name="Test Swim Club",
        brand=BRAND,
        detail_line="2.3 seconds faster than her previous best.",
    )
    kwargs.update(overrides)
    return build_certificate_html(**kwargs)


def _poster_html(rows=None, **overrides) -> str:
    kwargs = dict(
        title="The Weekend in Numbers",
        meet_name="Welsh Winter Open 2026",
        stat_lines=[("PBs", "14"), ("Medals", "6"), ("Swims", "92"), ("Finals", "11")],
        highlight_rows=rows if rows is not None else _rows(3),
        club_name="Test Swim Club",
        brand=BRAND,
    )
    kwargs.update(overrides)
    return build_poster_html(**kwargs)


def _rows(n: int) -> list[dict]:
    return [
        {
            "swimmer": f"Swimmer {i}",
            "event": f"{50 * (i + 1)}m Freestyle",
            "time": f"1:0{i}.4{i}",
            "note": f"New PB by {i}.{i}s",
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# HTML builders — escaping, placeholder coverage, brand colours
# ---------------------------------------------------------------------------


class TestCertificateHtml:
    def test_escapes_injected_script_in_names(self):
        html = _certificate_html(
            swimmer_name='<script>alert("x")</script>',
            meet_name="<b>Meet</b> & Friends",
            achievement_headline='<img src=x onerror="evil()">',
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "<b>Meet</b>" not in html
        assert "&amp; Friends" in html
        assert "<img src=x" not in html

    def test_all_placeholders_substituted(self):
        html = _certificate_html()
        assert "{{" not in html
        assert "}}" not in html

    def test_content_present(self):
        html = _certificate_html()
        assert "Eira Hughes" in html
        assert "200m Freestyle" in html
        assert "2:08.41" in html
        assert "Welsh Winter Open 2026" in html
        assert "7 June 2026" in html
        assert "Test Swim Club" in html
        assert "2.3 seconds faster" in html
        assert "Verified from official results" in html

    def test_brand_colours_appear(self):
        html = _certificate_html()
        assert "#0E5BFF" in html
        assert "#FFD24A" in html

    def test_no_external_font_cdn(self):
        html = _certificate_html()
        assert "fonts.googleapis.com" not in html
        assert "gstatic" not in html
        # Self-hosted woff2 rewritten to absolute file:// URLs.
        assert "file://" in html
        assert ".woff2" in html

    def test_empty_detail_line_ok(self):
        html = _certificate_html(detail_line="")
        assert "{{" not in html

    def test_a4_page_rule(self):
        html = _certificate_html()
        assert "size: A4" in html


class TestPosterHtml:
    def test_all_placeholders_substituted(self):
        html = _poster_html()
        assert "{{" not in html
        assert "}}" not in html

    def test_escapes_injected_script(self):
        html = _poster_html(
            rows=[{"swimmer": "<script>boom()</script>", "event": "<i>50 Free</i>",
                   "time": "29.99", "note": 'a"b<c>'}],
            title="<script>t()</script>",
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "<i>50 Free</i>" not in html
        assert "&lt;c&gt;" in html

    def test_brand_colours_appear(self):
        html = _poster_html()
        assert "#0E5BFF" in html
        assert "#FFD24A" in html

    def test_stat_chips_rendered(self):
        html = _poster_html()
        for label, value in [("PBs", "14"), ("Medals", "6"), ("Swims", "92")]:
            assert label in html
            assert value in html

    def test_zero_highlight_rows_renders_empty_state(self):
        html = _poster_html(rows=[])
        assert "{{" not in html
        assert "no-highlights" in html
        assert "<table" not in html

    def test_ten_highlight_rows_all_present(self):
        html = _poster_html(rows=_rows(10))
        assert "{{" not in html
        assert "<table" in html
        for i in range(10):
            assert f"Swimmer {i}" in html

    def test_no_external_font_cdn(self):
        html = _poster_html()
        assert "fonts.googleapis.com" not in html
        assert "gstatic" not in html
        assert "file://" in html


# ---------------------------------------------------------------------------
# Real Playwright print-to-PDF renders
# ---------------------------------------------------------------------------


def _assert_real_pdf(path):
    assert path.exists()
    data = path.read_bytes()
    assert data[:5] == b"%PDF-"
    assert len(data) > 5 * 1024, f"suspiciously small PDF: {len(data)} bytes"


@_PLAYWRIGHT
def test_render_certificate_pdf(tmp_path):
    out = tmp_path / "certificate.pdf"
    result = render_html_to_pdf(_certificate_html(), out)
    assert result == out
    _assert_real_pdf(out)
    # The throwaway .render.html beside the PDF must be cleaned up.
    assert not list(tmp_path.glob("*.render.html"))


@_PLAYWRIGHT
def test_render_poster_pdf_ten_rows(tmp_path):
    out = tmp_path / "poster.pdf"
    result = render_html_to_pdf(_poster_html(rows=_rows(10)), out)
    assert result == out
    _assert_real_pdf(out)


@_PLAYWRIGHT
def test_render_poster_pdf_zero_rows(tmp_path):
    out = tmp_path / "poster_empty.pdf"
    render_html_to_pdf(_poster_html(rows=[]), out)
    _assert_real_pdf(out)


@_PLAYWRIGHT
def test_export_wrappers(tmp_path):
    cert = export_certificate_pdf(
        tmp_path / "cert.pdf",
        swimmer_name="Eira Hughes",
        event_label="200m Freestyle",
        time_str="2:08.41",
        achievement_headline="New Personal Best",
        meet_name="Welsh Winter Open 2026",
        meet_date="7 June 2026",
        club_name="Test Swim Club",
        brand=BRAND,
    )
    _assert_real_pdf(cert)
    poster = export_poster_pdf(
        tmp_path / "poster.pdf",
        title="The Weekend in Numbers",
        meet_name="Welsh Winter Open 2026",
        stat_lines=[("PBs", "14")],
        highlight_rows=_rows(2),
        club_name="Test Swim Club",
        brand=BRAND,
    )
    _assert_real_pdf(poster)
