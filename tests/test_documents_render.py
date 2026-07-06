"""Document engine (roadmap 1.15) — build 1: HTML assembly + PDF/PNG rendering."""

from __future__ import annotations

import pytest

from mediahub.documents import models as m
from mediahub.documents.models import DocumentSpec, Section, new_document
from mediahub.documents.render import (
    render_document_html,
    render_document_pdf,
    render_section_png,
)

_RV = {
    "--mh-primary": "#A30D2D",
    "--mh-secondary": "#2B6CB0",
    "--mh-surface": "#0B1B2E",
    "--mh-accent": "#F2C14E",
    "--mh-on-primary": "#FFFFFF",
    "--mh-on-surface": "#FFFFFF",
    "--mh-outline": "rgba(255,255,255,0.2)",
}


def _report():
    return DocumentSpec(
        title="Otters SC Season Report",
        kind="document",
        doc_format="season_report",
        geometry="a4",
        meta={"club_name": "Otters SC", "date": "June 2026"},
        source_refs=["run:abc123"],
        sections=[
            Section(blocks=[m.heading("Highlights", 1), m.text("A **great** season.")]),
            Section(
                break_before=True,
                blocks=[
                    m.heading("By the numbers", 2),
                    m.kpi_row([{"value": "42", "label": "PBs"}, {"value": "9", "label": "Medals"}]),
                    m.table(["Swimmer", "PBs"], [["Ada", 5], ["Bo", 4]], caption="Top PB makers"),
                ],
            ),
            Section(
                break_before=True, blocks=[m.heading("Thanks", 2), m.text("See you next term.")]
            ),
        ],
    )


def _deck():
    return DocumentSpec(
        title="AGM 2026",
        kind="deck",
        doc_format="agm_deck",
        geometry="slide_16_9",
        sections=[
            Section(layout="cover", background="primary", blocks=[m.heading("AGM 2026", 1)]),
            Section(
                blocks=[
                    m.heading("The year", 2),
                    m.bullet_list(["Grew to 120 members", "9 medals"]),
                ]
            ),
            Section(layout="closing", background="accent", blocks=[m.heading("Thank you", 1)]),
        ],
    )


# ---------------------------------------------------------------------------
# HTML assembly (deterministic, no Chromium)
# ---------------------------------------------------------------------------


def test_html_contains_title_and_content():
    html = render_document_html(_report(), role_vars=_RV)
    assert "Otters SC Season Report" in html
    assert "Highlights" in html
    assert "By the numbers" in html


def test_html_escapes_user_text_no_xss():
    spec = new_document("x", "blank")
    spec = DocumentSpec(
        title="<script>alert(1)</script>",
        sections=[
            Section(blocks=[m.text('<img src=x onerror="alert(2)">'), m.heading("<b>h</b>")])
        ],
    )
    html = render_document_html(spec, role_vars=_RV)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img src=x" not in html  # no live tag — opening bracket escaped
    assert "&lt;img src=x" in html  # rendered as inert text
    assert "<b>h</b>" not in html  # heading text escaped


def test_inline_markup_bold_italic():
    spec = DocumentSpec(title="t", sections=[Section(blocks=[m.text("a **bold** and *em* word")])])
    html = render_document_html(spec, role_vars=_RV)
    assert "<strong>bold</strong>" in html
    assert "<em>em</em>" in html


def test_self_hosted_fonts_only_no_google_cdn():
    html = render_document_html(_deck(), role_vars=_RV)
    assert "fonts.googleapis.com" not in html
    assert "gstatic" not in html
    # font faces are inlined (file:// woff2) when the renderer CSS is present
    assert "@font-face" in html


def test_img_src_blocks_remote_and_out_of_root_paths(tmp_path, monkeypatch):
    """Spec image srcs are tenant-editable: remote URLs (server-side Chromium
    fetch → SSRF) and paths outside DATA_DIR (local file inclusion) must not
    resolve; files under DATA_DIR and data: URIs still do."""
    from mediahub.documents.render import _img_src

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    inside = tmp_path / "data" / "uploads_v4" / "media_library" / "pic.png"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(b"\x89PNG")
    outside = tmp_path / "elsewhere" / "secret.png"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"\x89PNG")

    assert _img_src("http://169.254.169.254/latest/meta-data") == ""
    assert _img_src("https://example.com/x.png") == ""
    assert _img_src(str(outside)) == ""
    assert _img_src(outside.as_uri()) == ""
    assert _img_src(str(inside)) == inside.resolve().as_uri()
    assert _img_src(inside.as_uri()) == inside.resolve().as_uri()
    assert _img_src("data:image/png;base64,AAAA") == "data:image/png;base64,AAAA"
    assert _img_src("") == ""


def test_media_block_with_remote_src_renders_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    spec = DocumentSpec(
        title="t",
        sections=[Section(blocks=[m.media("http://169.254.169.254/x.png", alt="a")])],
    )
    html = render_document_html(spec, role_vars=_RV)
    assert "169.254.169.254" not in html
    assert "<img" not in html  # dropped, never a fabricated placeholder


def test_brand_tokens_present():
    html = render_document_html(_report(), role_vars=_RV)
    assert "--doc-accent:#F2C14E" in html
    assert "--doc-brand:#A30D2D" in html


def test_table_and_kpis_render():
    html = render_document_html(_report(), role_vars=_RV)
    assert '<table class="doc-table">' in html
    assert "Top PB makers" in html
    assert '<div class="doc-kpi">' in html
    assert ">42<" in html


def test_deck_has_one_sheet_per_section_with_slide_numbers():
    html = render_document_html(_deck(), role_vars=_RV)
    assert html.count('class="doc-sheet') == 3
    assert "1 / 3" in html
    assert "3 / 3" in html
    assert "bg-primary" in html
    assert "bg-accent" in html


def test_document_uses_sections_not_slides():
    html = render_document_html(_report(), role_vars=_RV)
    assert '<section class="doc-section' in html
    assert html.count("brk") >= 2  # two break_before sections
    assert "doc-runhead" in html  # running header from meta
    assert "Sources:" in html


def test_chart_block_embeds_inline_svg():
    from mediahub.charts.models import Axis, ChartSpec, DataPoint, Series

    spec_chart = ChartSpec(
        kind="bar",
        title="PBs",
        series=(Series(points=(DataPoint("A", 3), DataPoint("B", 6))),),
        y_axis=Axis(value_format="integer"),
    )
    doc = DocumentSpec(title="t", sections=[Section(blocks=[m.chart(spec_chart)])])
    html = render_document_html(doc, role_vars=_RV)
    assert '<div class="doc-chart">' in html
    assert "<svg" in html


def test_html_is_deterministic():
    a = render_document_html(_report(), role_vars=_RV)
    b = render_document_html(_report(), role_vars=_RV)
    assert a == b


# ---------------------------------------------------------------------------
# PDF + PNG (need Chromium; skip cleanly if unavailable)
# ---------------------------------------------------------------------------


def _skip_if_no_chromium(fn):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        if any(t in str(e).lower() for t in ("playwright", "chromium", "executable", "browser")):
            pytest.skip(f"render needs Playwright/Chromium: {e}")
        raise


def test_document_pdf_has_one_page_per_section(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    pdf = _skip_if_no_chromium(lambda: render_document_pdf(_report(), role_vars=_RV))
    assert pdf.exists() and pdf.read_bytes()[:4] == b"%PDF"
    from pypdf import PdfReader

    # three sections, each forcing its own sheet (the second/third break_before)
    assert len(PdfReader(str(pdf)).pages) == 3


def test_deck_pdf_has_one_page_per_slide(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    pdf = _skip_if_no_chromium(lambda: render_document_pdf(_deck(), role_vars=_RV))
    from pypdf import PdfReader

    assert len(PdfReader(str(pdf)).pages) == 3


def test_pdf_is_content_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    p1 = _skip_if_no_chromium(lambda: render_document_pdf(_deck(), role_vars=_RV))
    p2 = render_document_pdf(_deck(), role_vars=_RV)
    assert p1 == p2  # same content → same cached path


def test_section_png_preview_matches_geometry(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    png = _skip_if_no_chromium(lambda: render_section_png(_deck(), 0, role_vars=_RV))
    assert png.exists() and png.read_bytes()[:4] == b"\x89PNG"
    from PIL import Image

    with Image.open(png) as im:
        assert im.size == (1280, 720)
