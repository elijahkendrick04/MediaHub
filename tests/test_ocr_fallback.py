"""W.10 — OCR fallback for scanned/photographed result sheets.

The OCR module is an optional engine seam: with no engine installed the
interpreter keeps the existing honest "image-needs-ocr" review path; with an
engine, recognised text flows into ingestion with per-line confidences and
every uncertain row is flagged for human review — never silently guessed.

All tests run with NO OCR package installed, using the injectable test
engine (`ocr.set_engine_for_tests`).
"""

from __future__ import annotations

import importlib.util
import io

import pytest

from mediahub.interpreter import interpret_document
from mediahub.interpreter import ocr
from mediahub.interpreter.ingest import ingest

_HAS_PDFIUM = importlib.util.find_spec("pypdfium2") is not None

# A tiny but plausible OCR'd results sheet, mixed confidences (one < 0.6).
FAKE_SHEET = [
    ("Event 1 Girls 100 Free", 0.95),
    ("1. Maya PATEL 10 SUNY 1:05.32", 0.88),
    ("2. Lily JONES 11 SUNY 1:07.45", 0.74),
    ("3. Ava BROWN 10 GLAM 1:0B.12", 0.4),
]


def _fake_engine(image_bytes: bytes):
    assert isinstance(image_bytes, (bytes, bytearray))
    return list(FAKE_SHEET)


@pytest.fixture(autouse=True)
def _clean_ocr_state():
    """Every test starts and ends with no injected engine and a fresh probe."""
    ocr.clear_engine_for_tests()
    ocr.reset_probe_cache()
    yield
    ocr.clear_engine_for_tests()
    ocr.reset_probe_cache()


def _force_no_engines(monkeypatch):
    """Pin the probe cache to 'no engines', whatever the environment has."""
    monkeypatch.setattr(ocr, "_PROBE_CACHE", [])


def _tiny_png() -> bytes:
    from PIL import Image

    img = Image.new("RGB", (8, 8), "white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _scanned_pdf(pages: int = 1) -> bytes:
    """A real %PDF with blank page(s) and no text layer — scanned-style."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    data = buf.getvalue()
    assert data.startswith(b"%PDF")
    return data


# ---------------------------------------------------------------------------
# No engine: the existing honest path is pinned, byte-for-byte
# ---------------------------------------------------------------------------


def test_image_without_engine_keeps_honest_needs_ocr_path(monkeypatch):
    _force_no_engines(monkeypatch)
    png = _tiny_png()

    stream = ingest(png, content_type_hint="png")
    assert stream.format_detected == "image-needs-ocr"
    assert stream.text == ""
    assert stream.lines == []
    assert stream.tables == []

    meet = interpret_document(png, hint="png")
    assert meet.overall_confidence == 0.0
    assert meet.events == []
    # Pin the existing honest needs_review entry exactly.
    assert meet.needs_review == [{"reason": "image-needs-ocr", "detail": "OCR not available"}]
    assert meet.sources_used == ["format:image-needs-ocr"]


def test_ocr_image_without_engine_returns_honest_error(monkeypatch):
    _force_no_engines(monkeypatch)
    result = ocr.ocr_image(_tiny_png())
    assert result.ok is False
    assert result.lines == []
    assert result.engine == ""
    assert result.error == "OCR engine not installed on this deployment"


# ---------------------------------------------------------------------------
# Engine probe: cached + resettable
# ---------------------------------------------------------------------------


def test_engine_probe_is_cached_and_resettable(monkeypatch):
    first = ocr.available_engines()
    # The probe result is cached: a pinned cache is returned verbatim...
    monkeypatch.setattr(ocr, "_PROBE_CACHE", ["sentinel"])
    assert ocr.available_engines() == ["sentinel"]
    # ...and reset_probe_cache() forces a genuine re-probe.
    ocr.reset_probe_cache()
    assert ocr.available_engines() == first
    # available_engines hands out copies — callers can't poison the cache.
    probed = ocr.available_engines()
    probed.append("mutated")
    assert ocr.available_engines() == first


# ---------------------------------------------------------------------------
# Injected fake engine: image → OCR stream → flagged, capped interpretation
# ---------------------------------------------------------------------------


def test_fake_engine_ingest_returns_image_ocr_stream():
    ocr.set_engine_for_tests(_fake_engine)
    stream = ingest(_tiny_png(), content_type_hint="png")

    assert stream.format_detected == "image-ocr"
    assert stream.tables == []
    assert [ln.text for ln in stream.lines] == [t for t, _c in FAKE_SHEET]
    assert stream.text == "\n".join(t for t, _c in FAKE_SHEET)
    # Per-line confidences ride along for the interpreter.
    assert stream.ocr_engine == "fake"
    assert stream.ocr_lines == FAKE_SHEET


def test_fake_engine_interpret_flags_uncertainty_and_caps_confidence():
    ocr.set_engine_for_tests(_fake_engine)
    meet = interpret_document(_tiny_png(), hint="png")

    # OCR text is never high-confidence.
    assert meet.overall_confidence <= 0.55

    reasons = [entry["reason"] for entry in meet.needs_review]
    assert "ocr-used" in reasons
    used = next(e for e in meet.needs_review if e["reason"] == "ocr-used")
    assert "fake" in used["detail"]
    assert "1 low-confidence lines" in used["detail"]

    low_rows = [e for e in meet.needs_review if e["reason"] == "ocr-low-confidence-row"]
    assert len(low_rows) == 1
    assert low_rows[0]["detail"] == "3. Ava BROWN 10 GLAM 1:0B.12"
    assert low_rows[0]["confidence"] == pytest.approx(0.4)

    # interpreting-phase visibility: the engine is recorded in sources_used.
    assert "ocr:fake" in meet.sources_used
    assert "format:image-ocr" in meet.sources_used


def test_low_confidence_row_flags_are_capped_at_20():
    def noisy_engine(_data: bytes):
        return [(f"garbled row {i}", 0.2) for i in range(30)]

    ocr.set_engine_for_tests(noisy_engine)
    meet = interpret_document(_tiny_png(), hint="png")
    low_rows = [e for e in meet.needs_review if e["reason"] == "ocr-low-confidence-row"]
    assert len(low_rows) == 20
    used = next(e for e in meet.needs_review if e["reason"] == "ocr-used")
    assert "30 low-confidence lines" in used["detail"]


# ---------------------------------------------------------------------------
# Scanned PDFs (no text layer)
# ---------------------------------------------------------------------------


def test_scanned_pdf_without_engine_flags_review(monkeypatch):
    _force_no_engines(monkeypatch)
    pdf = _scanned_pdf()

    stream = ingest(pdf)
    # Current behaviour otherwise intact: still a pdf stream, still empty.
    assert stream.format_detected == "pdf"
    assert stream.text.strip() == ""
    assert "OCR engine not installed" in stream.ocr_unavailable_detail
    assert stream.ocr_unavailable_detail.startswith("Scanned PDF;")

    meet = interpret_document(pdf)
    flagged = [e for e in meet.needs_review if e["reason"] == "image-needs-ocr"]
    assert len(flagged) == 1
    assert flagged[0]["detail"].startswith("Scanned PDF;")
    assert "OCR engine not installed" in flagged[0]["detail"]


def test_ocr_pdf_pages_without_engine_returns_honest_error(monkeypatch):
    _force_no_engines(monkeypatch)
    result = ocr.ocr_pdf_pages(_scanned_pdf())
    assert result.ok is False
    assert result.lines == []
    assert result.error == "OCR engine not installed on this deployment"


def test_scanned_pdf_with_fake_engine_goes_through_ocr():
    ocr.set_engine_for_tests(_fake_engine)
    pdf = _scanned_pdf()

    stream = ingest(pdf)
    assert stream.format_detected == "image-ocr"
    assert "Maya PATEL" in stream.text

    meet = interpret_document(pdf)
    assert "ocr:fake" in meet.sources_used
    assert meet.overall_confidence <= 0.55
    reasons = [entry["reason"] for entry in meet.needs_review]
    assert "ocr-used" in reasons
    assert "ocr-low-confidence-row" in reasons


@pytest.mark.skipif(not _HAS_PDFIUM, reason="pypdfium2 not installed")
def test_ocr_pdf_pages_caps_pages_at_10():
    calls = {"n": 0}

    def counting_engine(_data: bytes):
        calls["n"] += 1
        return [(f"page text {calls['n']}", 0.9)]

    ocr.set_engine_for_tests(counting_engine)
    result = ocr.ocr_pdf_pages(_scanned_pdf(pages=12))
    assert result.ok is True
    assert result.engine == "fake"
    assert calls["n"] == 10  # MAX_PDF_PAGES
    assert len(result.lines) == 10
