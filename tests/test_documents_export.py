"""Document engine (roadmap 1.15) — build 3: PPTX / DOCX exports."""

from __future__ import annotations

from mediahub.documents import export
from mediahub.documents import models as m
from mediahub.documents.models import DocumentSpec, Section


def _doc():
    return DocumentSpec(
        title="Otters SC Season Report",
        subtitle="2025/26",
        kind="document",
        doc_format="season_report",
        source_refs=["run:r1", "meet results file"],
        sections=[
            Section(
                blocks=[
                    m.heading("Highlights", 1),
                    m.text("A **strong** season."),
                    m.bullet_list(["Grew to 120 members", "9 medals"]),
                ]
            ),
            Section(
                blocks=[
                    m.heading("By the numbers", 2),
                    m.kpi_row([{"value": "42", "label": "PBs"}, {"value": "9", "label": "Medals"}]),
                    m.table(
                        ["Swimmer", "PBs"], [["Ada", "5"], ["Bo", "4"]], caption="Top PB makers"
                    ),
                ]
            ),
        ],
    )


def _deck():
    return DocumentSpec(
        title="AGM 2026",
        kind="deck",
        doc_format="agm_deck",
        sections=[
            Section(layout="cover", blocks=[m.heading("AGM 2026", 1)]),
            Section(blocks=[m.heading("The year", 2), m.bullet_list(["120 members", "9 medals"])]),
            Section(layout="closing", blocks=[m.heading("Thank you", 1)]),
        ],
    )


def test_docx_export_is_valid_and_has_content(tmp_path):
    out = export.document_docx(_doc(), tmp_path / "report.docx")
    assert out.exists()
    import docx

    doc = docx.Document(str(out))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Otters SC Season Report" in text
    assert "strong season" in text  # markup stripped to runs
    assert "Grew to 120 members" in text
    # the table came across as a real editable table
    assert len(doc.tables) == 1
    cells = [c.text for row in doc.tables[0].rows for c in row.cells]
    assert "Swimmer" in cells and "Ada" in cells
    # sources footer
    assert "Sources:" in text


def test_pptx_export_one_slide_per_section(tmp_path):
    out = export.document_pptx(_deck(), tmp_path / "agm.pptx")
    assert out.exists()
    from pptx import Presentation

    prs = Presentation(str(out))
    assert len(prs.slides) == 3
    # text made it onto the slides
    all_text = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                all_text.append(shape.text_frame.text)
    joined = "\n".join(all_text)
    assert "AGM 2026" in joined
    assert "120 members" in joined


def test_pptx_export_includes_tables(tmp_path):
    out = export.document_pptx(_doc(), tmp_path / "report.pptx")
    from pptx import Presentation

    prs = Presentation(str(out))
    found_table = any(shape.has_table for slide in prs.slides for shape in slide.shapes)
    assert found_table


def test_export_formats_listed():
    assert export.EXPORT_FORMATS == ("pdf", "pptx", "docx")
