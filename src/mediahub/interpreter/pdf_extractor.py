"""
pdf_extractor.py — pdfplumber-based PDF extraction with spatial column awareness.

Operates purely on geometry:
  * Detects vertical white-space corridors → column bands.
  * Within each band, groups words by y-position → logical lines.
  * Detects and merges "child" lines that contain only time-shaped tokens
    (the Hytek multi-line split-time pattern).

NO swim vocabulary literals; only structural regex (digits, time-shape, etc.).
"""

from __future__ import annotations

import io
import logging
import re
from collections import defaultdict
from typing import Optional

from .schema_dataclasses import Line, TableCandidate

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex helpers — purely structural
# ---------------------------------------------------------------------------

# Time shapes: "ss.cc" or "mm:ss.cc" (also leading "1:23.45")
_TIME_TOKEN = re.compile(r"^\d{1,2}:\d{2}\.\d{2}$|^\d{1,3}\.\d{2}$")
# "Pure" numeric tokens (places, ages, lap counts)
_NUM_TOKEN = re.compile(r"^=?\*?\d{1,3}\.?$|^---$|^DQ$|^DNS$|^DNF$|^NS$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Column band detection
# ---------------------------------------------------------------------------


def detect_column_bands(
    words: list[dict],
    page_width: float,
    *,
    min_band_width: int = 80,
) -> list[tuple[float, float]]:
    """Return [(x_lo, x_hi), ...] column bands for *words* on a page.

    Algorithm
    ---------
    1. Build a 1pt-resolution coverage histogram of how many distinct y-rows
       have *any* word covering each x-position.
    2. Find the inner text zone (first/last x where coverage ≥ 30 % of max).
    3. Inside that zone, locate sustained low-coverage corridors (≤ ~5 % of
       max, width ≥ 12 pt) — those are the column boundaries.
    4. Merge bands narrower than ``min_band_width`` into their neighbours,
       drop bands that contain very few words.
    """
    if not words:
        return [(0.0, float(page_width))]

    page_w = int(page_width)
    coverage = [0] * (page_w + 5)

    by_y: dict[int, list[dict]] = defaultdict(list)
    for w in words:
        by_y[round(w["top"])].append(w)

    # If the page has too few rows to reliably detect column corridors, treat
    # it as a single column.  Without enough rows the coverage histogram is
    # noisy and small inter-token gaps can be mistaken for column boundaries.
    if len(by_y) < 8:
        return [(0.0, float(page_width))]

    for y, ws in by_y.items():
        seen: set[int] = set()
        for w in ws:
            x0, x1 = int(w["x0"]), int(w["x1"]) + 1
            for x in range(x0, min(x1, len(coverage))):
                seen.add(x)
        for x in seen:
            coverage[x] += 1

    max_cov = max(coverage) or 1

    # Find text zone
    text_threshold = max_cov * 0.30
    text_lo = next((x for x in range(page_w) if coverage[x] >= text_threshold), 0)
    text_hi = next(
        (x for x in range(page_w - 1, -1, -1) if coverage[x] >= text_threshold),
        page_w,
    )

    abs_threshold = min(3, max(1, max_cov // 20))
    min_gap_width = 12

    boundaries: list[int] = []
    in_gap = False
    gap_start = 0
    for x in range(text_lo + 5, text_hi - 5):
        if coverage[x] <= abs_threshold:
            if not in_gap:
                in_gap = True
                gap_start = x
        else:
            if in_gap:
                in_gap = False
                if x - gap_start >= min_gap_width:
                    boundaries.append((gap_start + x) // 2)

    if not boundaries:
        return [(0.0, float(page_width))]

    raw_bands: list[tuple[float, float]] = []
    prev = 0.0
    for b in boundaries:
        raw_bands.append((prev, float(b)))
        prev = float(b)
    raw_bands.append((prev, float(page_width)))

    # Merge bands narrower than min_band_width into their neighbours.
    merged: list[tuple[float, float]] = []
    for band in raw_bands:
        if not merged:
            merged.append(band)
            continue
        if band[1] - band[0] < min_band_width:
            merged[-1] = (merged[-1][0], band[1])
        else:
            merged.append(band)
    if len(merged) >= 2 and merged[-1][1] - merged[-1][0] < min_band_width:
        merged[-2] = (merged[-2][0], merged[-1][1])
        merged.pop()

    # Drop bands with fewer than ~5 words; merge into adjacent.
    final: list[tuple[float, float]] = []
    for lo, hi in merged:
        c = sum(1 for w in words if lo <= w["x0"] < hi)
        if c < 5:
            if final:
                final[-1] = (final[-1][0], hi)
            # else drop leading empty band entirely
        else:
            final.append((lo, hi))

    return final or [(0.0, float(page_width))]


# ---------------------------------------------------------------------------
# Row grouping inside a column band
# ---------------------------------------------------------------------------


def _looks_like_split_time_only(tokens: list[str]) -> bool:
    """Return True if every token is a time-shape value or pure number.

    Used to detect "child" lines in the Hytek multi-line row pattern.
    """
    if not tokens:
        return False
    matches = sum(1 for t in tokens if _TIME_TOKEN.match(t) or _NUM_TOKEN.match(t))
    return matches == len(tokens) and any(_TIME_TOKEN.match(t) for t in tokens)


def _has_alpha_word(tokens: list[str]) -> bool:
    """Detect tokens with at least 2 alpha characters in a row (a name/word)."""
    for t in tokens:
        if re.search(r"[A-Za-z]{2,}", t):
            return True
    return False


def _band_lines(
    words_in_band: list[dict],
    y_tolerance: float = 2.5,
) -> list[tuple[float, list[dict]]]:
    """Group words into logical lines by y-position within a column band."""
    if not words_in_band:
        return []
    # Sort by y, then x
    sorted_words = sorted(words_in_band, key=lambda w: (w["top"], w["x0"]))
    grouped: list[tuple[float, list[dict]]] = []
    cur_y: Optional[float] = None
    cur_line: list[dict] = []
    for w in sorted_words:
        if cur_y is None or abs(w["top"] - cur_y) <= y_tolerance:
            if cur_y is None:
                cur_y = w["top"]
            cur_line.append(w)
            # Update cur_y to running average so wide y bands don't drift
            cur_y = sum(x["top"] for x in cur_line) / len(cur_line)
        else:
            grouped.append((cur_y, cur_line))
            cur_y = w["top"]
            cur_line = [w]
    if cur_line:
        grouped.append((cur_y if cur_y is not None else 0.0, cur_line))
    # Sort grouped lines by y again and within each line sort words by x
    grouped.sort(key=lambda g: g[0])
    for y, ws in grouped:
        ws.sort(key=lambda w: w["x0"])
    return grouped


def _merge_split_time_continuations(
    lines: list[tuple[float, list[str]]],
) -> list[tuple[float, list[str]]]:
    """Merge "child" lines that contain only time/numeric tokens into the
    immediately preceding parent line.

    A child is a line whose every token is time-shaped or a pure number, AND
    that has at least one time-shaped token, AND that follows a parent line
    that itself contains alphabetic content (a name, place, etc.).
    """
    if not lines:
        return lines
    out: list[tuple[float, list[str]]] = []
    for y, toks in lines:
        if out and _looks_like_split_time_only(toks) and _has_alpha_word(out[-1][1]):
            out[-1] = (out[-1][0], out[-1][1] + toks)
        else:
            out.append((y, list(toks)))
    return out


# ---------------------------------------------------------------------------
# Public extraction entry point
# ---------------------------------------------------------------------------


def extract_pdf(data: bytes) -> tuple[str, list[Line], list[TableCandidate], dict]:
    """Extract text, lines, and table candidates from a PDF using pdfplumber.

    Returns
    -------
    (text, lines, tables, info)
        ``info`` reports per-page column counts and any extraction warnings.
    """
    info: dict = {"engine": "pdfplumber", "page_columns": [], "warnings": []}
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
                    continue

                bands = detect_column_bands(words, page.width)
                info["page_columns"].append(len(bands))

                page_text_parts: list[str] = []
                for band_idx, (lo, hi) in enumerate(bands):
                    in_band = [w for w in words if lo <= w["x0"] < hi]
                    grouped = _band_lines(in_band)

                    # Convert each grouped row to a list of tokens
                    raw_rows: list[tuple[float, list[str]]] = []
                    for y, ws in grouped:
                        raw_rows.append((y, [w["text"] for w in ws]))

                    # Merge split-time continuation lines
                    merged_rows = _merge_split_time_continuations(raw_rows)

                    # Build per-line records for downstream stages.
                    # Use TableCandidate row format AND emit Line objects so
                    # both schema-by-table and schema-by-line paths see data.
                    table_rows: list[list[str]] = []
                    for y, toks in merged_rows:
                        line_text = " ".join(toks)
                        page_text_parts.append(line_text)
                        # Compute approximate x of first token for x_position
                        # by finding it in the raw words list
                        first_x = lo
                        for raw_y, raw_ws in grouped:
                            if abs(raw_y - y) <= 5 and raw_ws:
                                first_x = raw_ws[0]["x0"]
                                break
                        lines.append(
                            Line(
                                text=line_text,
                                page_no=page_no,
                                y_position=float(line_y_counter),
                                x_position=float(first_x),
                                font_size_hint=None,
                            )
                        )
                        line_y_counter += 1
                        table_rows.append(toks)

                    if len(table_rows) >= 2:
                        tables.append(
                            TableCandidate(
                                rows=table_rows,
                                page_no=page_no,
                                x_range=(float(lo), float(hi)),
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
