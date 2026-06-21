"""data_hub.view — sort/filter a table for display (roadmap 1.13).

The grid's "sort", "filter" and "freeze" are view concerns kept *out* of the
stored data: this module arranges a copy of a table's rows for rendering, never
mutating the table. Sorting respects the column kind (numbers/times/ints sort by
value, everything else by display text); filtering is a case-insensitive
substring match across the row. Deterministic and stable.
"""

from __future__ import annotations

from typing import Optional

from .models import DataCell, DataTable

_NUMERIC_TYPES = {"number", "int", "time"}


def _cell(row: dict, key: str) -> DataCell:
    c = row.get(key)
    if isinstance(c, DataCell):
        return c
    if c is None:
        return DataCell()
    return DataCell.from_dict(c)


def _row_matches(row: dict, query: str) -> bool:
    q = query.strip().lower()
    if not q:
        return True
    for cell in row.values():
        c = cell if isinstance(cell, DataCell) else DataCell.from_dict(cell)
        if q in (c.display or "").lower():
            return True
    return False


def _sort_key(row: dict, key: str, numeric: bool):
    cell = _cell(row, key)
    if numeric and isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
        return (0, float(cell.value))
    disp = (cell.display or "").lower()
    if disp == "":
        return (2, "")  # empties sort last
    return (1, disp)


def arrange(
    table: DataTable,
    *,
    sort: Optional[str] = None,
    direction: str = "asc",
    query: str = "",
) -> list[dict]:
    """Return the table's rows filtered by ``query`` and sorted by ``sort``.

    Pure: the input table is not modified.
    """
    rows = [r for r in table.rows if _row_matches(r, query)]
    if sort and table.column(sort) is not None:
        numeric = table.column(sort).type in _NUMERIC_TYPES
        rows = sorted(rows, key=lambda r: _sort_key(r, sort, numeric))
        if direction == "desc":
            rows.reverse()
    return rows


__all__ = ["arrange"]
