"""
ingest.py — bytes → IngestStream.

Sniffs the document format and produces a normalised stream of text, lines,
and table candidates.  No swim-domain logic in this file.

When the optional ``source_path`` is provided, frameset HTML pages and
sibling-aggregated layouts are followed
transparently — purely via shape detection (``<frameset>`` tags + a
sibling-filename heuristic), never by domain or brand name.
"""

from __future__ import annotations

import csv
import io
import os
import json
import logging
import pathlib
import re
import zipfile
from typing import Optional

from .schema_dataclasses import IngestStream, Line, TableCandidate

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Format sniffing
# ---------------------------------------------------------------------------

_PDF_MAGIC = b"%PDF"
_ZIP_MAGIC = b"PK\x03\x04"
_HY3_MAGIC = re.compile(rb"^[A-Z]\d", re.MULTILINE)


def _is_xlsx(data: bytes) -> bool:
    """True if ZIP bytes are an Office Open XML spreadsheet (.xlsx).

    An ``.xlsx`` IS a ZIP, so this must be checked before the generic ZIP
    branch. We only read the central directory (member names) — no bytes are
    decompressed — so a bomb can't be triggered here.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
    except Exception:
        return False
    return "[Content_Types].xml" in names and any(n.startswith("xl/") for n in names)


def _looks_like_csv(sample: bytes) -> bool:
    """Heuristic CSV/TSV sniff for un-hinted bytes: ≥2 lines that share a
    consistent comma/tab delimiter (≥1 per line). Conservative on purpose so
    space-aligned text and hy3 record streams are NOT misread as CSV."""
    try:
        text = sample.decode("utf-8", "replace")
    except Exception:
        return False
    lines = [ln for ln in text.splitlines() if ln.strip()][:6]
    if len(lines) < 2:
        return False
    for delim in (",", "\t"):
        counts = [ln.count(delim) for ln in lines]
        if all(c >= 1 for c in counts) and (max(counts) - min(counts)) <= 1:
            return True
    return False


def _sniff_format(data: bytes, hint: Optional[str] = None) -> str:
    if hint:
        h = hint.lower()
        if "pdf" in h:
            return "pdf"
        if any(x in h for x in ("html", "htm")):
            return "html"
        if "json" in h:
            return "json"
        # xlsx/xls before generic zip — an .xlsx is a ZIP container.
        if any(x in h for x in ("xlsx", "xls")):
            return "xlsx"
        if any(x in h for x in ("csv", "tsv")):
            return "csv"
        if "zip" in h:
            return "zip"
        if "hy3" in h:
            return "hy3"
        if any(x in h for x in ("lef", "lxf", "lenex")):
            return "lenex"
        if any(x in h for x in ("png", "jpg", "jpeg", "gif", "tiff", "bmp", "webp")):
            return "image"
    if data[:4] == _PDF_MAGIC:
        return "pdf"
    if data[:4] == _ZIP_MAGIC:
        # .xlsx spreadsheets are ZIPs — disambiguate before generic zip handling.
        return "xlsx" if _is_xlsx(data) else "zip"
    # LENEX .lef: XML declaration + a <LENEX root tag near the top.
    # (The native parser in interpreter/__init__ intercepts these before
    # the schema-induce pipeline; this sniff keeps routing honest.)
    head2k = data[:2048]
    if head2k.lstrip()[:5] == b"<?xml" and b"<lenex" in head2k.lower():
        return "lenex"
    # HTML heuristic
    sample = data[:2000].lower()
    if b"<!doctype html" in sample or b"<html" in sample or b"<table" in sample:
        return "html"
    # JSON: leading { or [ after optional whitespace
    if data[:512].lstrip()[:1] in (b"{", b"["):
        return "json"
    # hy3: many lines starting with a capital letter + digit
    if len(_HY3_MAGIC.findall(data[:4096])) > 3:
        return "hy3"
    # CSV/TSV: consistent delimiter across the first lines (conservative)
    if _looks_like_csv(data[:4096]):
        return "csv"
    return "text"


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------


def _max_pdf_pages() -> int:
    """Resource cap for PDF parsing (THREAT_MODEL §1): a hostile PDF with
    thousands of pages must not pin the worker. Real meet result PDFs run
    tens of pages; the default cap is generous. 0 disables the cap."""
    raw = os.environ.get("MEDIAHUB_MAX_PDF_PAGES", "").strip()
    try:
        return max(0, int(raw)) if raw else 500
    except ValueError:
        return 500


def _assert_pdf_page_cap(data: bytes) -> None:
    cap = _max_pdf_pages()
    if cap <= 0:
        return
    try:
        import pypdf  # noqa: PLC0415

        n_pages = len(pypdf.PdfReader(io.BytesIO(data)).pages)
    except Exception:
        return  # unreadable header — let the extractors produce the real error
    if n_pages > cap:
        raise ValueError(
            f"PDF has {n_pages} pages — more than this deployment accepts ({cap}). "
            "Split the results document and upload the relevant sessions."
        )


def _extract_pdf(data: bytes) -> tuple[str, list[Line], list[TableCandidate]]:
    """Extract a PDF.

    Primary path: spatial pdfplumber extractor (column-aware, multi-line
    row aware) — see :mod:`interpreter.pdf_extractor`.
    Fallbacks: pypdf layout extraction, then pdfminer.six.
    """
    _assert_pdf_page_cap(data)
    # Primary: pdfplumber spatial extractor
    try:
        from .pdf_extractor import extract_pdf as _spatial_extract  # noqa: PLC0415

        text, lines, tables, info = _spatial_extract(data)
        if text or lines or tables:
            log.debug(
                "spatial pdfplumber extracted %d chars, %d lines, %d tables",
                len(text),
                len(lines),
                len(tables),
            )
            return text, lines, tables
        else:
            log.info("spatial extractor returned empty result; trying pypdf")
    except Exception as exc:  # noqa: BLE001
        log.info("spatial pdfplumber extractor failed (%s)", exc)

    # Fallback 1: pypdf
    try:
        import pypdf  # noqa: PLC0415

        reader = pypdf.PdfReader(io.BytesIO(data))
        all_text_parts: list[str] = []
        lines: list[Line] = []
        tables: list[TableCandidate] = []

        for page_no, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text(extraction_mode="layout") or ""
            except Exception:  # noqa: BLE001
                page_text = page.extract_text() or ""

            all_text_parts.append(page_text)

            for y_idx, raw_line in enumerate(page_text.splitlines()):
                if raw_line.strip():
                    lines.append(
                        Line(
                            text=raw_line,
                            page_no=page_no,
                            y_position=float(y_idx),
                            x_position=0.0,
                            font_size_hint=None,
                        )
                    )

            table_rows = _detect_table_rows(page_text.splitlines())
            if len(table_rows) >= 2:
                tables.append(
                    TableCandidate(
                        rows=table_rows,
                        page_no=page_no,
                    )
                )

        text = "\n".join(all_text_parts)
        log.debug("pypdf extracted %d chars from PDF", len(text))
        return text, lines, tables

    except Exception as exc:  # noqa: BLE001
        log.info("pypdf extraction failed (%s), trying pdfminer fallback", exc)

    # Fallback 2: pdfminer.six
    try:
        from pdfminer.high_level import extract_text_to_fp  # noqa: PLC0415
        from pdfminer.layout import LAParams  # noqa: PLC0415

        buf = io.StringIO()
        extract_text_to_fp(
            io.BytesIO(data),
            buf,
            laparams=LAParams(),
            output_type="text",
            codec="utf-8",
        )
        text = buf.getvalue()
        lines = [
            Line(text=ln, page_no=0, y_position=float(i))
            for i, ln in enumerate(text.splitlines())
            if ln.strip()
        ]
        table_rows = _detect_table_rows(text.splitlines())
        tables = [TableCandidate(rows=table_rows)] if len(table_rows) >= 2 else []
        log.debug("pdfminer extracted %d chars from PDF", len(text))
        return text, lines, tables
    except Exception as exc2:  # noqa: BLE001
        log.error("All PDF extractors failed: %s", exc2)
        return "", [], []


# ---------------------------------------------------------------------------
# HTML extraction
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# HTML helpers — frameset / sibling detection
# ---------------------------------------------------------------------------

_FRAMESET_RE = re.compile(rb"<\s*frameset\b", re.IGNORECASE)
_FRAME_SRC_RE = re.compile(
    rb"<\s*frame\b[^>]*\bsrc\s*=\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
# Heuristic: an event-page filename inside a frameset-style result site
# typically looks like ``RG12H304.HTM`` (some letters then digits).  We do
# *not* hard-code the brand — we look for the structural shape.
_SIBLING_FILENAME_RE = re.compile(
    r"^[A-Za-z]{1,4}\d{1,3}[A-Za-z]?\d*\.html?$",
    re.IGNORECASE,
)


def _is_frameset(data: bytes) -> bool:
    head = data[:4096]
    return bool(_FRAMESET_RE.search(head))


def _frame_srcs(data: bytes) -> list[str]:
    return [m.decode("utf-8", errors="replace") for m in _FRAME_SRC_RE.findall(data)]


def _looks_like_event_page(html_bytes: bytes) -> bool:
    """True if the document looks like an individual event-result page.

    Shape only: contains a ``<table>`` AND multiple time-shaped values.
    """
    sample = html_bytes[:4000].lower()
    if b"<table" not in sample:
        return False
    # Look for at least 2 time-like patterns ``\d{2}\.\d{2}`` in the doc
    times = len(re.findall(rb"\d{1,2}\.\d{2}", html_bytes))
    return times >= 4


def _gather_sibling_html(
    source_path: pathlib.Path,
    seen: Optional[set[pathlib.Path]] = None,
) -> list[bytes]:
    """Read sibling HTML files in the same directory that look like event pages."""
    seen = seen or set()
    out: list[bytes] = []
    parent = source_path.parent
    if not parent.is_dir():
        return out
    for child in sorted(parent.iterdir()):
        if child == source_path:
            continue
        if child in seen:
            continue
        if not child.is_file():
            continue
        suffix = child.suffix.lower()
        if suffix not in (".htm", ".html"):
            continue
        if _SIBLING_FILENAME_RE.match(child.name):
            try:
                blob = child.read_bytes()
            except OSError:
                continue
            if _looks_like_event_page(blob):
                out.append(blob)
                seen.add(child)
    return out


def _gather_sibling_pdfs(
    source_path: pathlib.Path,
    seen: Optional[set[pathlib.Path]] = None,
) -> list[pathlib.Path]:
    """Return sibling PDF files alongside a thin/landing HTML page.

    Used when an HTML shell links out to one or more PDFs that contain the
    actual results.  Selection is purely structural: any sibling ``*.pdf``
    file in the same directory as ``source_path``.
    """
    seen = seen or set()
    out: list[pathlib.Path] = []
    parent = source_path.parent
    if not parent.is_dir():
        return out
    for child in sorted(parent.iterdir()):
        if child == source_path or child in seen:
            continue
        if not child.is_file():
            continue
        if child.suffix.lower() == ".pdf":
            out.append(child)
            seen.add(child)
    return out


def _parse_html_bytes(data: bytes) -> tuple[str, list[TableCandidate]]:
    """Parse raw HTML bytes → (plain text, list of <table> candidates)."""
    try:
        from bs4 import BeautifulSoup  # noqa: PLC0415

        soup = BeautifulSoup(data, "lxml")
        tables: list[TableCandidate] = []
        for tbl in soup.find_all("table"):
            rows: list[list[str]] = []
            for tr in tbl.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if any(cells):
                    rows.append(cells)
            if rows:
                tables.append(TableCandidate(rows=rows))

        for script_or_style in soup(["script", "style", "noscript"]):
            script_or_style.decompose()
        text = soup.get_text("\n")
    except Exception as exc:  # noqa: BLE001
        log.warning("HTML parsing failed (%s), falling back to raw decode", exc)
        text = data.decode("utf-8", errors="replace")
        tables = []
    return text, tables


def _extract_html(
    data: bytes,
    source_path: Optional[pathlib.Path] = None,
) -> tuple[str, list[Line], list[TableCandidate]]:
    """Parse HTML bytes; if it's a frameset shell or thin/empty body, follow
    referenced frames and/or sibling event pages on disk (when ``source_path``
    is supplied).
    """
    text, tables = _parse_html_bytes(data)

    # Decide if we should harvest more sibling content.
    body_chars = len(text.strip())
    is_thin = body_chars < 120 or _is_frameset(data) or not tables

    if is_thin and source_path is not None:
        seen: set[pathlib.Path] = {source_path}
        # 1. Follow explicit <frame src="..."> children if any
        for src in _frame_srcs(data):
            cand = (source_path.parent / src).resolve()
            try:
                cand.relative_to(source_path.parent.resolve())
            except ValueError:
                continue  # outside parent — skip
            if cand.is_file() and cand not in seen:
                seen.add(cand)
                try:
                    blob = cand.read_bytes()
                except OSError:
                    continue
                t2, tb2 = _parse_html_bytes(blob)
                text = text + "\n" + t2
                tables.extend(tb2)

        # 2. Pick up sibling event pages by filename shape + content shape
        for blob in _gather_sibling_html(source_path, seen):
            t2, tb2 = _parse_html_bytes(blob)
            text = text + "\n" + t2
            tables.extend(tb2)

    lines = [
        Line(text=ln, page_no=0, y_position=float(i))
        for i, ln in enumerate(text.splitlines())
        if ln.strip()
    ]

    # 3. If we still have effectively no usable content but the HTML is a
    #    thin landing page sitting next to one or more PDF files, harvest
    #    those PDFs.  Purely structural — no domain or filename special-cases.
    has_useful_content = (
        any(len(tbl.rows) >= 2 for tbl in tables)
        or len([ln for ln in lines if len(ln.text) > 20]) >= 10
    )
    if (not has_useful_content) and source_path is not None:
        try:
            from .pdf_extractor import extract_pdf as _pdfx  # noqa: PLC0415
        except Exception:
            _pdfx = None  # type: ignore[assignment]
        if _pdfx is not None:
            seen_pdfs: set[pathlib.Path] = set()
            line_offset = len(lines)
            for pdf_path in _gather_sibling_pdfs(source_path, seen_pdfs):
                try:
                    pdf_bytes = pdf_path.read_bytes()
                    p_text, p_lines, p_tables, _info = _pdfx(pdf_bytes)
                except Exception as exc:  # noqa: BLE001
                    log.debug("sibling pdf extract failed for %s: %s", pdf_path, exc)
                    continue
                if not p_text:
                    continue
                text = text + "\n" + p_text
                # Re-position pdf lines to come after html lines
                for ln in p_lines:
                    lines.append(
                        Line(
                            text=ln.text,
                            page_no=ln.page_no,
                            y_position=float(line_offset),
                            x_position=ln.x_position,
                            font_size_hint=ln.font_size_hint,
                        )
                    )
                    line_offset += 1
                tables.extend(p_tables)

    return text, lines, tables


# ---------------------------------------------------------------------------
# ZIP recursion
# ---------------------------------------------------------------------------


def _is_mirror_sidecar(name: str) -> bool:
    """True for results-fetch mirror bookkeeping that must never be ingested as
    document content: the crawl provenance JSON (``_provenance.json``), captured
    screenshots (``_screenshots/``) and AI sidecars (``_ai/``, ``*.ai.json``).

    These are written into the mirror ZIP by ``results_fetch/package.py`` for
    audit/provenance, not as results. Ingesting ``_provenance.json`` leaks its
    ``entry_url`` line into the combined text — and because provenance is the
    first ZIP member, that URL leads the stream and gets picked as the meet
    title (``_extract_meet_metadata`` takes the first non-trivial line). Skip
    them so crawl bookkeeping never reaches the parser.
    """
    parts = [p for p in name.replace("\\", "/").split("/") if p]
    base = parts[-1] if parts else name
    if base == "_provenance.json" or base.endswith(".ai.json"):
        return True
    return any(seg in ("_screenshots", "_ai") for seg in parts)


def _extract_zip(
    data: bytes,
    hint: Optional[str] = None,
    source_path: Optional[pathlib.Path] = None,
) -> IngestStream:
    # Member iteration goes through _zip_safety so a compression bomb
    # can't pass arbitrary-size payloads down into nested ingestion.
    from ._zip_safety import safe_iter_members, UnsafeZipError

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            all_streams: list[IngestStream] = []
            for name, member_data in safe_iter_members(zf):
                if name.endswith("/"):
                    continue
                # Mirror bookkeeping (provenance / screenshots / AI sidecars) is
                # not document content — never let it into the parsed stream.
                if _is_mirror_sidecar(name):
                    continue
                child_hint = name.rsplit(".", 1)[-1] if "." in name else hint
                child_stream = ingest(
                    member_data,
                    content_type_hint=child_hint,
                    source_path=None,  # zip members have no on-disk siblings
                )
                all_streams.append(child_stream)

            combined_text = "\n".join(s.text for s in all_streams)
            combined_lines: list[Line] = []
            combined_tables: list[TableCandidate] = []
            for s in all_streams:
                combined_lines.extend(s.lines)
                combined_tables.extend(s.tables)
            return IngestStream(
                text=combined_text,
                lines=combined_lines,
                tables=combined_tables,
                format_detected="zip",
            )
    except UnsafeZipError as exc:
        log.warning("ZIP rejected by safety check: %s", exc)
        return IngestStream(text="", lines=[], tables=[], format_detected="zip-error")
    except Exception as exc:  # noqa: BLE001
        log.error("ZIP extraction failed: %s", exc)
        return IngestStream(text="", lines=[], tables=[], format_detected="zip-error")


# ---------------------------------------------------------------------------
# hy3 line-based
# ---------------------------------------------------------------------------


def _extract_hy3(data: bytes) -> tuple[str, list[Line], list[TableCandidate]]:
    text = data.decode("latin-1", errors="replace")
    lines = [
        Line(text=ln, page_no=0, y_position=float(i)) for i, ln in enumerate(text.splitlines())
    ]
    return text, lines, []


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------


def _extract_text(data: bytes) -> tuple[str, list[Line], list[TableCandidate]]:
    text = data.decode("utf-8", errors="replace")
    lines = [
        Line(text=ln, page_no=0, y_position=float(i)) for i, ln in enumerate(text.splitlines())
    ]
    table_rows = _detect_table_rows(text.splitlines())
    tables = [TableCandidate(rows=table_rows)] if len(table_rows) >= 2 else []
    return text, lines, tables


# ---------------------------------------------------------------------------
# JSON / CSV / XLSX — tabular data formats (deterministic, no domain logic)
# ---------------------------------------------------------------------------

_MAX_JSON_TABLES = 50
_MAX_DATA_ROWS = 20000


def _json_scalar(value) -> str:
    """Stringify one JSON value for a table cell."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False)[:200]
        except Exception:
            return ""
    return str(value)


def _union_keys(dicts: list[dict]) -> list[str]:
    """Ordered union of all keys across ``dicts`` (first-seen order)."""
    seen: set = set()
    order: list[str] = []
    for d in dicts:
        for k in d.keys():
            ks = str(k)
            if ks not in seen:
                seen.add(ks)
                order.append(ks)
    return order


def _find_object_arrays(obj, depth: int = 0):
    """Yield arrays of homogeneous objects (≥3 dict items sharing ≥3 keys).

    Recurses into nested containers so a results array buried under
    ``{"data":{"results":[...]}}`` is still found. Shape only — no key names
    are interpreted, so it works for any sport's API.
    """
    if depth > 8:
        return
    if isinstance(obj, list):
        dicts = [x for x in obj if isinstance(x, dict)]
        if len(dicts) >= 3:
            common = set(dicts[0].keys())
            for d in dicts[1:]:
                common &= set(d.keys())
            if len(common) >= 3:
                yield dicts
        for x in obj:
            yield from _find_object_arrays(x, depth + 1)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _find_object_arrays(v, depth + 1)


def _collect_scalar_text(obj, out: list[str], depth: int = 0) -> None:
    """Gather scalar metadata (meet name, dates, …) into the text stream."""
    if depth > 6:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (str, int, float, bool)):
                out.append(f"{k}: {v}")
            else:
                _collect_scalar_text(v, out, depth + 1)
    elif isinstance(obj, list):
        for x in obj[:50]:
            if not isinstance(x, (str, int, float, bool)):
                _collect_scalar_text(x, out, depth + 1)


def _lines_from_text(text: str) -> list[Line]:
    return [
        Line(text=ln, page_no=0, y_position=float(i))
        for i, ln in enumerate(text.splitlines())
        if ln.strip()
    ]


def _extract_json(data: bytes) -> tuple[str, list[Line], list[TableCandidate]]:
    """JSON → tables (arrays of homogeneous objects) + scalar-metadata text.

    SPAs serve results as JSON; this turns each array-of-objects into a
    ``TableCandidate`` (keys = header row) so schema induction downstream is
    untouched. Pure shape — no swim/sport vocabulary.
    """
    try:
        parsed = json.loads(data.decode("utf-8", "replace"))
    except Exception as exc:  # not valid JSON after all → treat as text
        log.info("JSON parse failed (%s); falling back to text", exc)
        return _extract_text(data)

    tables: list[TableCandidate] = []
    for arr in _find_object_arrays(parsed):
        if len(tables) >= _MAX_JSON_TABLES:
            break
        header = _union_keys(arr)
        if len(header) < 1:
            continue
        rows: list[list[str]] = [header]
        for obj in arr[:_MAX_DATA_ROWS]:
            rows.append([_json_scalar(obj.get(k)) for k in header])
        tables.append(TableCandidate(rows=rows))

    text_bits: list[str] = []
    _collect_scalar_text(parsed, text_bits)
    text = "\n".join(text_bits)
    return text, _lines_from_text(text), tables


def _sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
    except Exception:
        return "\t" if sample.count("\t") > sample.count(",") else ","


def _extract_csv(data: bytes) -> tuple[str, list[Line], list[TableCandidate]]:
    """CSV/TSV → one TableCandidate. Delimiter sniffed; pure shape."""
    text = data.decode("utf-8", "replace")
    delim = _sniff_delimiter(text[:4096])
    rows: list[list[str]] = []
    try:
        for raw in csv.reader(io.StringIO(text), delimiter=delim):
            cells = [c.strip() for c in raw]
            if any(cells):
                rows.append(cells)
            if len(rows) >= _MAX_DATA_ROWS:
                break
    except Exception as exc:  # malformed CSV → keep the text, drop the table
        log.info("CSV parse failed (%s)", exc)
    tables = [TableCandidate(rows=rows)] if rows else []
    return text, _lines_from_text(text), tables


def _extract_xlsx(data: bytes) -> tuple[str, list[Line], list[TableCandidate]]:
    """XLSX → one TableCandidate per non-empty sheet (openpyxl, read-only)."""
    try:
        import openpyxl  # noqa: PLC0415
    except Exception as exc:  # dependency missing → honest empty stream
        log.warning("openpyxl unavailable (%s); cannot read xlsx", exc)
        return "", [], []
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        log.info("xlsx load failed (%s)", exc)
        return "", [], []

    tables: list[TableCandidate] = []
    text_bits: list[str] = []
    try:
        for ws in wb.worksheets:
            rows: list[list[str]] = []
            for raw in ws.iter_rows(values_only=True):
                cells = ["" if c is None else str(c) for c in raw]
                if any(c.strip() for c in cells):
                    rows.append(cells)
                if len(rows) >= _MAX_DATA_ROWS:
                    break
            if rows:
                tables.append(TableCandidate(rows=rows))
                text_bits.append(f"[sheet: {ws.title}]")
                text_bits.extend("\t".join(r) for r in rows)
    finally:
        try:
            wb.close()
        except Exception:
            pass

    text = "\n".join(text_bits)
    return text, _lines_from_text(text), tables


# ---------------------------------------------------------------------------
# Table row detection helper (layout-based)
# ---------------------------------------------------------------------------

_MULTI_SPACE = re.compile(r"  +|\t")


def _detect_table_rows(raw_lines: list[str], min_cols: int = 2) -> list[list[str]]:
    """
    Heuristic: lines that split into >= *min_cols* tokens when split on
    runs of whitespace / tabs are table row candidates.
    """
    rows: list[list[str]] = []
    for raw in raw_lines:
        stripped = raw.strip()
        if not stripped:
            continue
        cols = [c.strip() for c in _MULTI_SPACE.split(stripped) if c.strip()]
        if len(cols) >= min_cols:
            rows.append(cols)
    return rows


# ---------------------------------------------------------------------------
# OCR fallback (W.10) — optional engine seam, see interpreter/ocr.py
# ---------------------------------------------------------------------------

# Below this many extracted characters a PDF is treated as scanned/image-only
# (every text extractor returns ~nothing for a photographed printout).
_SCANNED_PDF_TEXT_MIN_CHARS = 50


def _stream_from_ocr(result) -> IngestStream:
    """Build an IngestStream from an ``ocr.OcrResult``.

    Per-line confidences ride along as dynamic attributes (``ocr_engine``,
    ``ocr_lines``) — ``schema_dataclasses.Line`` has no confidence field, and
    the interpreter reads these to flag uncertain rows for human review.
    """
    kept = [(t, c) for t, c in result.lines if t.strip()]
    text = "\n".join(t for t, _c in kept)
    lines = [Line(text=t, page_no=0, y_position=float(i)) for i, (t, _c) in enumerate(kept)]
    stream = IngestStream(text=text, lines=lines, tables=[], format_detected="image-ocr")
    stream.ocr_engine = result.engine
    stream.ocr_lines = kept
    return stream


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def ingest(
    data: bytes,
    content_type_hint: Optional[str] = None,
    *,
    source_path: Optional[pathlib.Path] = None,
) -> IngestStream:
    """Convert *data* bytes into a normalised IngestStream.

    Parameters
    ----------
    data:
        Raw document bytes.
    content_type_hint:
        Optional string such as "pdf", "html", "text", "zip", "hy3", or an
        image MIME type.  Used as a tie-breaker when sniffing is ambiguous.
    source_path:
        Optional on-disk path of the document.  Used to follow HTML
        framesets and aggregate sibling event-page HTML files.  Bytes-only
        callers can pass ``None`` (default).
    """
    fmt = _sniff_format(data, content_type_hint)
    log.debug("Detected format: %s", fmt)

    ocr_unavailable_note: Optional[str] = None

    if fmt == "pdf":
        text, lines, tables = _extract_pdf(data)
        # W.10: a scanned/photographed PDF has no text layer, so every
        # extractor above yields (near-)nothing. Attempt the optional OCR
        # fallback; with no engine installed, keep the honest empty stream
        # and let the interpreter flag it for human review.
        if len(text.strip()) < _SCANNED_PDF_TEXT_MIN_CHARS:
            from . import ocr as _ocr  # noqa: PLC0415

            result = _ocr.ocr_pdf_pages(data)
            if result.ok and result.lines:
                log.info("Scanned PDF OCR'd via %s: %d lines", result.engine, len(result.lines))
                return _stream_from_ocr(result)
            ocr_unavailable_note = f"Scanned PDF; {result.error or 'OCR recognised no text'}"
            log.warning(
                "PDF has no usable text layer and OCR fallback did not engage: %s",
                result.error,
            )
    elif fmt == "html":
        text, lines, tables = _extract_html(data, source_path=source_path)
    elif fmt == "zip":
        return _extract_zip(data, content_type_hint, source_path=source_path)
    elif fmt == "hy3":
        text, lines, tables = _extract_hy3(data)
    elif fmt == "lenex":
        # LENEX is parsed by interpreter.lenex_parser via the native fast
        # path before ingest is reached; raw text keeps this branch honest
        # for any direct caller.
        text, lines, tables = _extract_text(data)
    elif fmt == "json":
        text, lines, tables = _extract_json(data)
    elif fmt == "csv":
        text, lines, tables = _extract_csv(data)
    elif fmt == "xlsx":
        text, lines, tables = _extract_xlsx(data)
    elif fmt == "image":
        # W.10: photographed/scanned results sheet — OCR when an engine is
        # installed, otherwise keep the existing honest needs-review path.
        from . import ocr as _ocr  # noqa: PLC0415

        result = _ocr.ocr_image(data)
        if result.ok and result.lines:
            log.info("Image input OCR'd via %s: %d lines", result.engine, len(result.lines))
            return _stream_from_ocr(result)
        log.warning(
            "Image input detected and OCR did not engage (%s). "
            "Returning empty stream with needs_review flag.",
            result.error or "no text recognised",
        )
        return IngestStream(
            text="",
            lines=[],
            tables=[],
            format_detected="image-needs-ocr",
        )
    else:
        text, lines, tables = _extract_text(data)

    stream = IngestStream(
        text=text,
        lines=lines,
        tables=tables,
        format_detected=fmt,
    )
    if ocr_unavailable_note is not None:
        # Read by interpret_document → needs_review (uncertainty made explicit).
        stream.ocr_unavailable_detail = ocr_unavailable_note
    return stream
