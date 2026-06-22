"""Document engine (roadmap 1.15) — build 3: bounded PPTX / DOCX / PDF import."""

from __future__ import annotations

import pytest

from mediahub.documents import export, import_doc
from mediahub.documents import models as m
from mediahub.documents.models import DocumentSpec, Section


def _doc():
    return DocumentSpec(
        title="Club Report",
        kind="document",
        sections=[
            Section(blocks=[m.heading("Welcome", 1), m.text("Hello committee.")]),
            Section(blocks=[m.table(["Swimmer", "PBs"], [["Ada", "5"], ["Bo", "4"]])]),
        ],
    )


def test_docx_roundtrip_recovers_text_and_table(tmp_path):
    path = export.document_docx(_doc(), tmp_path / "r.docx")
    spec = import_doc.import_docx(path)
    kinds = [b.kind for s in spec.sections for b in s.blocks]
    assert "heading" in kinds
    assert "text" in kinds
    assert "table" in kinds
    # the heading text survived
    headings = [b.props["text"] for s in spec.sections for b in s.blocks if b.kind == "heading"]
    assert any("Welcome" in h for h in headings)
    # table content survived
    tables = [b for s in spec.sections for b in s.blocks if b.kind == "table"]
    flat = [c for t in tables for row in t.props["rows"] for c in row] + [
        c for t in tables for c in t.props["columns"]
    ]
    assert "Ada" in flat


def test_pptx_roundtrip_recovers_slides(tmp_path):
    deck = DocumentSpec(
        title="Deck",
        kind="deck",
        sections=[
            Section(blocks=[m.heading("Intro", 2), m.text("First slide")]),
            Section(blocks=[m.heading("Numbers", 2), m.bullet_list(["a", "b"])]),
        ],
    )
    path = export.document_pptx(deck, tmp_path / "d.pptx")
    spec = import_doc.import_pptx(path)
    assert spec.kind == "deck"
    assert len(spec.sections) == 2
    txt = " ".join(
        b.props.get("text", "") for s in spec.sections for b in s.blocks if b.kind == "text"
    )
    assert "First slide" in txt


def test_pdf_import_one_section_per_page(tmp_path):
    reportlab = pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas

    path = tmp_path / "in.pdf"
    c = canvas.Canvas(str(path), pagesize=(400, 600))
    c.drawString(50, 550, "Annual report opening line")
    c.showPage()
    c.drawString(50, 550, "Second page content here")
    c.showPage()
    c.save()

    spec = import_doc.import_pdf(path)
    assert len(spec.sections) == 2
    assert spec.meta["imported_from"] == "pdf"
    text = " ".join(b.props.get("text", "") for s in spec.sections for b in s.blocks)
    assert "Annual report opening line" in text
    assert "Second page" in text


def test_import_file_dispatch_and_unknown(tmp_path):
    path = export.document_docx(_doc(), tmp_path / "r.docx")
    assert import_doc.import_file(path).kind == "document"
    with pytest.raises(ValueError):
        import_doc.import_file(tmp_path / "thing.rtf")


def test_fidelity_note_is_recorded(tmp_path):
    path = export.document_docx(_doc(), tmp_path / "r.docx")
    spec = import_doc.import_docx(path)
    assert "bounded fidelity" in spec.meta.get("fidelity", "").lower()
