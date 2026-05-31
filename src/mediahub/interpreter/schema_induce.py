"""
schema_induce.py — IngestStream → list[ColumnSchema].

Determines which columns are present in a results document and assigns
a semantic type to each.  Works by voting across three independent signals:

    1. Header-word matching   (against data/ontology/column_headers.json)
    2. Regex-family matching  (shape of values in the column)
    3. Position clustering    (x-coordinate grouping from PDF layout)

No swim-vocabulary literals.  All header synonyms come from the ontology.
"""

from __future__ import annotations

import logging
import re
from collections import Counter

from .ontology_loader import OntologyLoader
from .schema_dataclasses import ColumnSchema, IngestStream, TableCandidate

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex families — pure structural patterns, no domain vocab
# ---------------------------------------------------------------------------

_FAMILIES: dict[str, re.Pattern] = {
    "time": re.compile(r"^\d{0,2}:?\d{2}\.\d{2}$"),
    "place": re.compile(r"^=?\d{1,3}$"),
    "yob": re.compile(r"^(19[4-9]\d|20[0-3]\d)$"),
    "reaction": re.compile(r"^0\.\d{2,3}$"),
    "name": re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+$"),
    "club": re.compile(r"^[A-Z]{2,6}$|^[A-Z][a-z]+ (?:SC|AC|TC|CC)$"),
}

# Weight for each signal when voting
_WEIGHTS = {"header": 0.55, "regex": 0.35, "position": 0.10}
_LOW_CONF_THRESHOLD = 0.6


def _header_vote(
    header_text: str,
    canonical_map: dict[str, str],
) -> tuple[str | None, float]:
    """Return (col_type, confidence) from header text alone."""
    cleaned = header_text.strip().lower()
    if cleaned in canonical_map:
        return canonical_map[cleaned], 1.0
    # Partial / prefix match
    for alias, col_type in canonical_map.items():
        if alias in cleaned or cleaned in alias:
            return col_type, 0.75
    return None, 0.0


def _regex_vote(
    values: list[str],
    families: dict[str, re.Pattern] = _FAMILIES,
) -> tuple[str | None, float]:
    """
    Try each regex family against the sample values.
    Returns the best-matching type and its hit-rate as confidence.
    """
    if not values:
        return None, 0.0
    best_type: str | None = None
    best_score = 0.0
    for col_type, pattern in families.items():
        hits = sum(1 for v in values if v and pattern.match(v.strip()))
        score = hits / len(values)
        if score > best_score:
            best_score = score
            best_type = col_type
    return best_type, best_score


def _position_vote(
    col_index: int,
    total_cols: int,
    known_schemas: list[ColumnSchema],
) -> tuple[str | None, float]:
    """
    Very rough positional heuristic: leftmost column is likely place/name,
    rightmost is often time.  Only fires when no better signal available.
    """
    if total_cols == 0:
        return None, 0.0
    frac = col_index / max(total_cols - 1, 1)
    if frac <= 0.15:
        return "place", 0.35
    if frac <= 0.55:
        return "name", 0.30
    if frac >= 0.85:
        return "time", 0.35
    return None, 0.0


# ---------------------------------------------------------------------------
# Main induction
# ---------------------------------------------------------------------------


def induce_schema(
    stream: IngestStream,
    ontology: OntologyLoader | None = None,
    low_conf_threshold: float = _LOW_CONF_THRESHOLD,
) -> list[ColumnSchema]:
    """
    Derive column schemas from *stream*.

    Priority:
      1. Use TableCandidate rows if present (structured layout).
      2. Fall back to line-by-line heuristic analysis.
    """
    if ontology is None:
        ontology = OntologyLoader()

    canonical_map = ontology.canonical_map("column_headers")

    if stream.tables:
        # Use the first (largest) table candidate
        table = max(stream.tables, key=lambda t: len(t.rows))
        return _induce_from_table(table, canonical_map, low_conf_threshold)

    return _induce_from_lines(stream.lines, canonical_map, low_conf_threshold)


def _header_row_score(row: list[str], canonical_map: dict[str, str]) -> float:
    """
    Score how much a row looks like a column-header row vs. a data row.
    Returns a score > 0.5 if the row is more header-like.
    """
    if not row:
        return 0.0
    _num_start = re.compile(r"^\d")
    _time_shape = re.compile(r"\d+:\d{2}\.\d{2}|^\d{2}\.\d{2}$")
    _alpha_short = re.compile(r"^[A-Za-z][A-Za-z\s\.]{0,19}$")
    header_score = 0.0
    data_score = 0.0
    cells = [c.strip() for c in row if c.strip()]
    if not cells:
        return 0.0
    for cell in cells:
        cell_lo = cell.lower()
        if cell_lo in canonical_map:
            header_score += 2.0
        elif _alpha_short.match(cell) and len(cell) <= 15:
            header_score += 0.8
        if _num_start.match(cell):
            data_score += 1.0
        if _time_shape.search(cell):
            data_score += 1.5
    total = header_score + data_score
    return header_score / total if total > 0 else 0.0


def _find_best_header_row(rows: list[list[str]], canonical_map: dict[str, str]) -> int:
    """
    Return the index of the row most likely to be the column-header row.
    Searches the first 5 rows only.
    """
    best_idx = 0
    best_score = -1.0
    for idx, row in enumerate(rows[:5]):
        score = _header_row_score(row, canonical_map)
        if score > best_score:
            best_score = score
            best_idx = idx
    # If best score is very low, assume no header row
    if best_score < 0.4:
        return -1
    return best_idx


def _induce_from_table(
    table: TableCandidate,
    canonical_map: dict[str, str],
    low_conf_threshold: float,
) -> list[ColumnSchema]:
    if not table.rows:
        return []

    num_cols = max(len(r) for r in table.rows)

    # Find the best header row
    header_idx = _find_best_header_row(table.rows, canonical_map)
    if header_idx >= 0:
        first_row = table.rows[header_idx]
        data_rows = table.rows[header_idx + 1 :]
    else:
        first_row = [""] * num_cols
        data_rows = table.rows

    # If first_row has fewer cols than num_cols, pad it
    if len(first_row) < num_cols:
        first_row = list(first_row) + [""] * (num_cols - len(first_row))

    schemas: list[ColumnSchema] = []
    for col_idx in range(num_cols):
        header_text = first_row[col_idx].strip() if col_idx < len(first_row) else ""
        sample_values = [
            row[col_idx] for row in data_rows if col_idx < len(row) and row[col_idx].strip()
        ][:20]  # cap sample size

        h_type, h_conf = _header_vote(header_text, canonical_map)
        r_type, r_conf = _regex_vote(sample_values)
        p_type, p_conf = _position_vote(col_idx, num_cols, schemas)

        # Weighted vote
        votes: Counter = Counter()
        if h_type:
            votes[h_type] += _WEIGHTS["header"] * h_conf
        if r_type:
            votes[r_type] += _WEIGHTS["regex"] * r_conf
        if p_type:
            votes[p_type] += _WEIGHTS["position"] * p_conf

        if votes:
            col_type, raw_score = votes.most_common(1)[0]
            confidence = min(raw_score, 1.0)
        else:
            col_type = "unknown"
            confidence = 0.0

        schemas.append(
            ColumnSchema(
                name=col_type,
                col_type=col_type,
                confidence=confidence,
                col_index=col_idx,
                header_text=header_text,
            )
        )

    log.debug(
        "Induced %d column schemas from table (min_conf=%.2f)",
        len(schemas),
        min((s.confidence for s in schemas), default=0),
    )
    return schemas


def _induce_from_lines(
    lines: list[object],
    canonical_map: dict[str, str],
    low_conf_threshold: float,
) -> list[ColumnSchema]:
    """
    Line-based fallback: treat whitespace-delimited tokens as pseudo-columns.
    """
    # Build token columns by position within a line
    max_cols = 6
    col_buckets: list[list[str]] = [[] for _ in range(max_cols)]

    _multi_space = re.compile(r"\s{2,}|\t")
    for line in lines:
        text = getattr(line, "text", str(line))
        tokens = [t.strip() for t in _multi_space.split(text.strip()) if t.strip()]
        for i, tok in enumerate(tokens[:max_cols]):
            col_buckets[i].append(tok)

    schemas: list[ColumnSchema] = []
    non_empty = [(i, b) for i, b in enumerate(col_buckets) if b]
    total = len(non_empty)

    for col_idx, (orig_idx, sample_values) in enumerate(non_empty):
        r_type, r_conf = _regex_vote(sample_values)
        p_type, p_conf = _position_vote(col_idx, total, schemas)

        votes: Counter = Counter()
        if r_type:
            votes[r_type] += _WEIGHTS["regex"] * r_conf
        if p_type:
            votes[p_type] += _WEIGHTS["position"] * p_conf

        if votes:
            col_type, raw_score = votes.most_common(1)[0]
            confidence = min(raw_score, 1.0)
        else:
            col_type = "unknown"
            confidence = 0.0

        schemas.append(
            ColumnSchema(
                name=col_type,
                col_type=col_type,
                confidence=confidence,
                col_index=orig_idx,
            )
        )

    return schemas
