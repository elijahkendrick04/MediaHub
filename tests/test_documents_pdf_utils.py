"""Document engine (roadmap 1.15) — build 3: deterministic PDF utilities."""

from __future__ import annotations

import pytest

from mediahub.documents import pdf_utils


def _png(path, color, size=(200, 150)):
    from PIL import Image

    Image.new("RGB", size, color).save(str(path))
    return path


def _pdf(tmp_path, name, n_pages, colors=None):
    colors = colors or ["red", "green", "blue", "orange", "purple"]
    imgs = [_png(tmp_path / f"{name}-{i}.png", colors[i % len(colors)]) for i in range(n_pages)]
    out = tmp_path / f"{name}.pdf"
    return pdf_utils.images_to_pdf(imgs, out)


def test_images_to_pdf_one_page_per_image(tmp_path):
    pdf = _pdf(tmp_path, "doc", 3)
    assert pdf.exists() and pdf.read_bytes()[:4] == b"%PDF"
    assert pdf_utils.pdf_page_count(pdf) == 3


def test_images_to_pdf_requires_input(tmp_path):
    with pytest.raises(ValueError):
        pdf_utils.images_to_pdf([], tmp_path / "x.pdf")


def test_merge_pdfs(tmp_path):
    a = _pdf(tmp_path, "a", 2)
    b = _pdf(tmp_path, "b", 3)
    merged = pdf_utils.merge_pdfs([a, b], tmp_path / "merged.pdf")
    assert pdf_utils.pdf_page_count(merged) == 5


def test_merge_missing_file_errors(tmp_path):
    a = _pdf(tmp_path, "a", 1)
    with pytest.raises(FileNotFoundError):
        pdf_utils.merge_pdfs([a, tmp_path / "nope.pdf"], tmp_path / "m.pdf")


def test_organise_delete_pages(tmp_path):
    src = _pdf(tmp_path, "src", 4)
    out = pdf_utils.organise_pdf(src, tmp_path / "o.pdf", delete=[2, 3])
    assert pdf_utils.pdf_page_count(out) == 2
    # input untouched
    assert pdf_utils.pdf_page_count(src) == 4


def test_organise_reorder_subset(tmp_path):
    src = _pdf(tmp_path, "src", 4)
    out = pdf_utils.organise_pdf(src, tmp_path / "o.pdf", order=[4, 1])
    assert pdf_utils.pdf_page_count(out) == 2


def test_organise_rotate(tmp_path):
    src = _pdf(tmp_path, "src", 1)
    out = pdf_utils.organise_pdf(src, tmp_path / "o.pdf", rotate={1: 90})
    from pypdf import PdfReader

    page = PdfReader(str(out)).pages[0]
    assert int(page.get("/Rotate", 0)) % 360 == 90


def test_organise_empty_result_errors(tmp_path):
    src = _pdf(tmp_path, "src", 2)
    with pytest.raises(ValueError):
        pdf_utils.organise_pdf(src, tmp_path / "o.pdf", delete=[1, 2])


def test_pdf_to_images_roundtrip(tmp_path):
    src = _pdf(tmp_path, "src", 3)
    imgs = pdf_utils.pdf_to_images(src, tmp_path / "out", scale=1.0)
    assert len(imgs) == 3
    assert all(p.exists() and p.read_bytes()[:4] == b"\x89PNG" for p in imgs)
