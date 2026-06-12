"""
ocr.py — optional OCR fallback for scanned/photographed result sheets (W.10).

This module is a deterministic *engine seam* with NO hard dependency: the
interpreter works exactly as before when no OCR package is installed — the
existing honest "image-needs-ocr" review path is preserved. When an engine
is available, recognised text flows back into ingestion with a per-line
confidence so uncertain rows are flagged downstream, never silently guessed.

Engines, probed in order:
  1. "rapidocr"   — ``rapidocr_onnxruntime`` importable (pure-pip wheel)
  2. "tesseract"  — ``pytesseract`` importable AND the ``tesseract`` binary
                    on PATH (the deployed Docker image installs both)

When neither is present, every entry point returns an honest
``OcrResult(ok=False, error=...)`` — a fabricated transcription is worse
than a clear error (CLAUDE.md: never silently guess).

Tests inject a fake engine via :func:`set_engine_for_tests` so the whole
fallback is exercisable with no OCR package installed.

No swim-domain logic in this file.
"""

from __future__ import annotations

import importlib.util
import io
import logging
import shutil
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger(__name__)

# One recognised line: (text, confidence 0..1).
OcrLine = tuple[str, float]

NO_ENGINE_ERROR = "OCR engine not installed on this deployment"
NO_RASTERISER_ERROR = (
    "pypdfium2 not installed on this deployment; cannot rasterise scanned PDF pages"
)

# Scanned PDFs are capped to keep a single upload from monopolising a worker;
# 10 pages is far beyond any phone-photographed results printout.
MAX_PDF_PAGES = 10

_TEST_ENGINE_NAME = "fake"


@dataclass
class OcrResult:
    engine: str
    lines: list[OcrLine] = field(default_factory=list)
    ok: bool = False
    error: str = ""


# ---------------------------------------------------------------------------
# Engine probe (cached) + test seam
# ---------------------------------------------------------------------------

# None = not probed yet; [] is a valid cached "no engines" answer.
_PROBE_CACHE: Optional[list[str]] = None

# Injected by tests: fn(image_bytes) -> list[OcrLine].
_TEST_ENGINE: Optional[Callable[[bytes], list[OcrLine]]] = None

# Lazily-built singleton so the (slow) rapidocr model load happens once.
_RAPIDOCR_INSTANCE = None


def available_engines() -> list[str]:
    """Probe installed OCR engines, in preference order. Cached per process."""
    global _PROBE_CACHE
    if _PROBE_CACHE is not None:
        return list(_PROBE_CACHE)
    engines: list[str] = []
    if importlib.util.find_spec("rapidocr_onnxruntime") is not None:
        engines.append("rapidocr")
    if importlib.util.find_spec("pytesseract") is not None and shutil.which("tesseract"):
        engines.append("tesseract")
    _PROBE_CACHE = engines
    return list(engines)


def reset_probe_cache() -> None:
    """Forget the cached engine probe (test hook)."""
    global _PROBE_CACHE
    _PROBE_CACHE = None


def set_engine_for_tests(fn: Callable[[bytes], list[OcrLine]]) -> None:
    """Inject a fake engine ``fn(image_bytes) -> list[(text, confidence)]``.

    Lets the full OCR fallback run with no OCR package installed. The
    injected engine reports as engine name ``"fake"``.
    """
    global _TEST_ENGINE
    _TEST_ENGINE = fn


def clear_engine_for_tests() -> None:
    global _TEST_ENGINE
    _TEST_ENGINE = None


# ---------------------------------------------------------------------------
# Real engine backends (only imported when probed present)
# ---------------------------------------------------------------------------


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _ocr_rapidocr(data: bytes) -> list[OcrLine]:
    global _RAPIDOCR_INSTANCE
    from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415

    if _RAPIDOCR_INSTANCE is None:
        _RAPIDOCR_INSTANCE = RapidOCR()
    result, _elapse = _RAPIDOCR_INSTANCE(data)
    lines: list[OcrLine] = []
    for item in result or []:
        # item: [box, text, score]
        text = str(item[1]).strip()
        score = float(item[2]) if len(item) > 2 else 0.0
        if text:
            lines.append((text, _clamp(score)))
    return lines


def _ocr_tesseract(data: bytes) -> list[OcrLine]:
    import pytesseract  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    img = Image.open(io.BytesIO(data))
    d = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    n = len(d.get("text", []))
    pages = d.get("page_num", [0] * n)
    grouped: dict[tuple, list[tuple[str, float]]] = {}
    order: list[tuple] = []
    for i in range(n):
        word = (d["text"][i] or "").strip()
        if not word:
            continue
        try:
            conf = float(d["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf < 0:  # tesseract uses -1 for non-text boxes
            continue
        key = (pages[i], d["block_num"][i], d["par_num"][i], d["line_num"][i])
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append((word, conf))
    lines: list[OcrLine] = []
    for key in order:
        words = grouped[key]
        text = " ".join(w for w, _c in words)
        mean_conf = sum(c for _w, c in words) / len(words) / 100.0
        lines.append((text, _clamp(mean_conf)))
    return lines


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def ocr_image(data: bytes) -> OcrResult:
    """OCR one image (photo/scan of a results sheet) → per-line text + confidence.

    Honest failure modes: no engine installed, engine raised, or the engine
    recognised no text at all — never fabricated output.
    """
    if _TEST_ENGINE is not None:
        try:
            lines = [(str(t), _clamp(c)) for t, c in _TEST_ENGINE(data)]
        except Exception as exc:  # noqa: BLE001
            return OcrResult(
                engine=_TEST_ENGINE_NAME, ok=False, error=f"injected test engine failed: {exc}"
            )
        if not lines:
            return OcrResult(
                engine=_TEST_ENGINE_NAME, ok=False, error="OCR recognised no text"
            )
        return OcrResult(engine=_TEST_ENGINE_NAME, lines=lines, ok=True)

    engines = available_engines()
    if not engines:
        return OcrResult(engine="", ok=False, error=NO_ENGINE_ERROR)
    engine = engines[0]
    try:
        lines = _ocr_rapidocr(data) if engine == "rapidocr" else _ocr_tesseract(data)
    except Exception as exc:  # noqa: BLE001
        log.warning("OCR via %s failed: %s", engine, exc)
        return OcrResult(engine=engine, ok=False, error=f"OCR failed ({engine}): {exc}")
    if not lines:
        return OcrResult(engine=engine, ok=False, error="OCR recognised no text")
    return OcrResult(engine=engine, lines=lines, ok=True)


def ocr_pdf_pages(data: bytes) -> OcrResult:
    """OCR an image-only (scanned) PDF: rasterise pages, then OCR each.

    Pages are rendered via ``pypdfium2`` when importable (optional extra);
    without it the result is an honest error. Page count capped at
    :data:`MAX_PDF_PAGES`.
    """
    if _TEST_ENGINE is None and not available_engines():
        return OcrResult(engine="", ok=False, error=NO_ENGINE_ERROR)

    try:
        import pypdfium2 as pdfium  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        if _TEST_ENGINE is not None:
            # Test seam only: with no rasteriser in the environment the
            # injected engine defines its own decoding, so hand it the raw
            # bytes once. Real engines never take this path.
            return ocr_image(data)
        return OcrResult(engine="", ok=False, error=NO_RASTERISER_ERROR)

    try:
        doc = pdfium.PdfDocument(data)
    except Exception as exc:  # noqa: BLE001
        return OcrResult(engine="", ok=False, error=f"could not open PDF for OCR: {exc}")

    all_lines: list[OcrLine] = []
    engine_name = ""
    try:
        page_count = min(len(doc), MAX_PDF_PAGES)
        for page_no in range(page_count):
            page = doc[page_no]
            bitmap = page.render(scale=2.0)
            pil_image = bitmap.to_pil()
            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            page_result = ocr_image(buf.getvalue())
            if not page_result.ok:
                if page_result.error == "OCR recognised no text":
                    engine_name = page_result.engine
                    continue  # a blank page is not a hard failure
                return page_result
            engine_name = page_result.engine
            all_lines.extend(page_result.lines)
    except Exception as exc:  # noqa: BLE001
        return OcrResult(engine=engine_name, ok=False, error=f"PDF page OCR failed: {exc}")
    finally:
        try:
            doc.close()
        except Exception:  # noqa: BLE001
            pass

    if not all_lines:
        return OcrResult(engine=engine_name, ok=False, error="OCR recognised no text on any page")
    return OcrResult(engine=engine_name, lines=all_lines, ok=True)
