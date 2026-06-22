"""documents.pdf_utils — bounded, deterministic PDF tools committee volunteers need.

Not an Acrobat clone — just the handful of honest operations a club actually uses:
merge several PDFs, reorder / rotate / delete pages, turn images into a PDF, and
turn a PDF back into page images. Every operation is deterministic (pypdf / Pillow
/ pypdfium2 — all already deployment deps) and leaves the input untouched. When a
dependency or input is unusable the caller gets a clear error, never a corrupt file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional


def pdf_page_count(path: str | Path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(str(path)).pages)


def merge_pdfs(paths: Iterable[str | Path], out_path: str | Path) -> Path:
    """Concatenate PDFs in order into one file."""
    from pypdf import PdfWriter

    paths = [Path(p) for p in paths]
    if not paths:
        raise ValueError("merge_pdfs needs at least one input PDF")
    writer = PdfWriter()
    for p in paths:
        if not p.exists():
            raise FileNotFoundError(f"PDF not found: {p}")
        writer.append(str(p))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as fh:
        writer.write(fh)
    writer.close()
    return out_path


def organise_pdf(
    in_path: str | Path,
    out_path: str | Path,
    *,
    order: Optional[list[int]] = None,
    rotate: Optional[dict[int, int]] = None,
    delete: Optional[list[int]] = None,
) -> Path:
    """Reorder / rotate / delete pages (all page numbers are 1-based).

    ``order`` is the new sequence of pages to keep (a subset is allowed); when
    omitted, all pages survive in their original order minus ``delete``. ``rotate``
    maps a page number to a clockwise rotation (90/180/270). The input is never
    modified — a new PDF is written to ``out_path``."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(in_path))
    n = len(reader.pages)
    delete_set = {int(d) for d in (delete or [])}
    rotate = {int(k): int(v) for k, v in (rotate or {}).items()}

    if order:
        seq = [int(p) for p in order if 1 <= int(p) <= n and int(p) not in delete_set]
    else:
        seq = [p for p in range(1, n + 1) if p not in delete_set]
    if not seq:
        raise ValueError("organise_pdf would produce an empty document")

    writer = PdfWriter()
    for page_no in seq:
        page = reader.pages[page_no - 1]
        deg = rotate.get(page_no, 0) % 360
        if deg:
            page = page.rotate(deg)
        writer.add_page(page)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as fh:
        writer.write(fh)
    writer.close()
    return out_path


def images_to_pdf(image_paths: Iterable[str | Path], out_path: str | Path) -> Path:
    """Combine images into a single PDF, one image per page (in order)."""
    from PIL import Image

    paths = [Path(p) for p in image_paths]
    if not paths:
        raise ValueError("images_to_pdf needs at least one image")
    frames = []
    for p in paths:
        if not p.exists():
            raise FileNotFoundError(f"image not found: {p}")
        im = Image.open(p)
        frames.append(im.convert("RGB") if im.mode != "RGB" else im)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(str(out_path), "PDF", save_all=True, append_images=frames[1:])
    return out_path


def pdf_to_images(
    in_path: str | Path,
    out_dir: str | Path,
    *,
    scale: float = 2.0,
    fmt: str = "png",
    stem: str = "page",
) -> list[Path]:
    """Rasterise every PDF page to an image. ``scale`` 2.0 ≈ 144 DPI.

    Uses pypdfium2 (already a deployment dep for OCR). Raises a clear error when
    it isn't installed rather than producing nothing."""
    try:
        import pypdfium2 as pdfium
    except Exception as e:  # pragma: no cover - environment-dependent
        raise RuntimeError(f"pdf_to_images needs pypdfium2: {e}") from e

    fmt = (fmt or "png").lower().lstrip(".")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(in_path))
    try:
        out: list[Path] = []
        for i in range(len(pdf)):
            page = pdf[i]
            pil = page.render(scale=scale).to_pil()
            dest = out_dir / f"{stem}-{i + 1:03d}.{fmt}"
            pil.save(str(dest))
            out.append(dest)
        return out
    finally:
        pdf.close()


__all__ = [
    "pdf_page_count",
    "merge_pdfs",
    "organise_pdf",
    "images_to_pdf",
    "pdf_to_images",
]
