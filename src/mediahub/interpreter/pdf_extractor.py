"""
pdf_extractor.py — pdfplumber-based PDF extraction, full-width line aware.

Operates purely on geometry, no swim vocabulary:

  * Groups words on a page into *full-width physical lines* by y-position.
    A physical line is every word that shares a baseline, left-to-right across
    the whole page — NOT split into column bands.
  * Reconstructs each line's text with a column-break marker (a run of 2+
    spaces) wherever the horizontal gap between adjacent words is large, so the
    downstream row parser can see the column structure.
  * Emits per-page table candidates by splitting those lines on the column
    breaks.

Why full-width and not per-column bands?  Multi-column results PDFs (the very
common Hy-Tek "two swimmers per printed line" layout) put two complete records
on one baseline:

    1 Arthur, Andrew 23 UoAPS 28.73     33 Warner, Liam 16 East Lothian 32.82

A vertical-corridor band splitter cuts that line in the wrong place — the right
swimmer's place+name land in the left band and their club+time in the right
band, so half of every event is lost.  Keeping the line whole lets the row
parser (rows.py) split it into N records by anchoring on the time token, which
is layout-independent.
"""

from __future__ import annotations

import io
import logging
import statistics
from collections import defaultdict
from typing import Optional

from .schema_dataclasses import Line, TableCandidate

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Physical-line reconstruction
# ---------------------------------------------------------------------------


def _group_words_into_lines(
    words: list[dict],
    y_tolerance: float = 2.5,
) -> list[list[dict]]:
    """Group words into full-width physical lines by baseline (``top``).

    Words within ``y_tolerance`` points of the running line baseline join the
    same line; each returned line is sorted left-to-right by ``x0``.
    """
    if not words:
        return []
    by_top: dict[float, list[dict]] = defaultdict(list)
    for w in words:
        by_top[round(float(w["top"]), 1)].append(w)

    lines: list[tuple[float, list[dict]]] = []
    for top in sorted(by_top):
        ws = by_top[top]
        if lines and (top - lines[-1][0]) <= y_tolerance:
            lines[-1][1].extend(ws)
        else:
            lines.append((top, list(ws)))

    out: list[list[dict]] = []
    for _top, ws in lines:
        ws.sort(key=lambda w: float(w["x0"]))
        out.append(ws)
    return out


def _column_break_gap(ws: list[dict]) -> float:
    """Threshold (in points) above which an inter-word gap is a column break.

    Derived per-line from the distribution of gaps so it adapts to the page's
    font size: a column break is markedly wider than the line's typical
    word-to-word gap.
    """
    gaps = [
        float(ws[i + 1]["x0"]) - float(ws[i]["x1"])
        for i in range(len(ws) - 1)
        if float(ws[i + 1]["x0"]) > float(ws[i]["x1"])
    ]
    if not gaps:
        return 8.0
    med = statistics.median(gaps)
    # A typical single-space gap is ~one median; a column gap is clearly wider.
    return max(6.0, med * 2.2)


def _line_text_and_cells(ws: list[dict]) -> tuple[str, list[str]]:
    """Reconstruct a physical line's text + column cells from its words.

    Adjacent words are joined with a single space; a column-break gap inserts a
    double space.  Cells are the runs between column breaks.
    """
    if not ws:
        return "", []
    threshold = _column_break_gap(ws)
    parts: list[str] = [str(ws[0]["text"])]
    cells: list[list[str]] = [[str(ws[0]["text"])]]
    for i in range(1, len(ws)):
        gap = float(ws[i]["x0"]) - float(ws[i - 1]["x1"])
        tok = str(ws[i]["text"])
        if gap >= threshold:
            parts.append("  ")
            cells.append([tok])
        else:
            parts.append(" ")
            cells[-1].append(tok)
        parts.append(tok)
    text = "".join(parts)
    cell_strs = [" ".join(c).strip() for c in cells]
    return text, [c for c in cell_strs if c]


# ---------------------------------------------------------------------------
# Public extraction entry point
# ---------------------------------------------------------------------------


def extract_pdf(data: bytes) -> tuple[str, list[Line], list[TableCandidate], dict]:
    """Extract text, full-width lines, and table candidates from a PDF.

    Returns
    -------
    (text, lines, tables, info)
        ``info`` reports per-page line counts and any extraction warnings.
    """
    info: dict = {"engine": "pdfplumber", "page_lines": [], "warnings": []}
    try:
        import pdfplumber  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        info["warnings"].append(f"pdfplumber unavailable: {exc}")
        return "", [], [], info

    all_text_parts: list[str] = []
    lines: list[Line] = []
    tables: list[TableCandidate] = []
    line_y_counter = 0

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page_no, page in enumerate(pdf.pages):
                try:
                    words = page.extract_words(
                        use_text_flow=False,
                        keep_blank_chars=False,
                    )
                except Exception as exc:  # noqa: BLE001
                    info["warnings"].append(f"page {page_no}: extract_words failed: {exc}")
                    continue

                if not words:
                    info["page_lines"].append(0)
                    continue

                phys_lines = _group_words_into_lines(words)
                info["page_lines"].append(len(phys_lines))

                page_text_parts: list[str] = []
                table_rows: list[list[str]] = []
                for ws in phys_lines:
                    line_text, cells = _line_text_and_cells(ws)
                    if not line_text.strip():
                        continue
                    page_text_parts.append(line_text)
                    lines.append(
                        Line(
                            text=line_text,
                            page_no=page_no,
                            y_position=float(line_y_counter),
                            x_position=float(ws[0]["x0"]),
                            font_size_hint=_height(ws),
                        )
                    )
                    line_y_counter += 1
                    if len(cells) >= 2:
                        table_rows.append(cells)

                if len(table_rows) >= 2:
                    tables.append(
                        TableCandidate(
                            rows=table_rows,
                            page_no=page_no,
                        )
                    )
                all_text_parts.append("\n".join(page_text_parts))

    except Exception as exc:  # noqa: BLE001
        info["warnings"].append(f"pdfplumber.open failed: {exc}")
        return "", [], [], info

    text = "\n".join(all_text_parts)
    log.debug(
        "pdfplumber extracted %d chars, %d lines, %d tables",
        len(text),
        len(lines),
        len(tables),
    )
    return text, lines, tables, info


def _height(ws: list[dict]) -> Optional[float]:
    """Median glyph height for a line — a cheap font-size hint for headers."""
    hs = [float(w["bottom"]) - float(w["top"]) for w in ws if "bottom" in w and "top" in w]
    return round(statistics.median(hs), 1) if hs else None
