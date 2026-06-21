"""data_hub.scaffold — "a sheet from a prompt" (roadmap 1.13).

Canva's "Sheets AI" makes a spreadsheet from a prompt. The MediaHub shape is
narrower and honest: the AI proposes a **schema** — a set of columns with kinds
— for a new *empty* org table. It never invents rows or data; a human reviews
the columns, then creates the table and fills it (or imports a CSV into it).

Raises ``ProviderNotConfigured`` / ``ProviderError`` when no AI provider is
configured — an honest error, never a fabricated schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mediahub.ai_core import ask  # honest errors propagate

from ._aiutil import parse_json_object
from .models import COLUMN_TYPES, DataColumn


@dataclass
class ScaffoldResult:
    ok: bool
    title: str = ""
    columns: list[DataColumn] = field(default_factory=list)
    rationale: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "title": self.title,
            "columns": [c.to_dict() for c in self.columns],
            "rationale": self.rationale,
            "reason": self.reason,
        }


def _key_from_title(title: str, taken: set[str]) -> str:
    import re

    base = re.sub(r"[^a-z0-9]+", "_", title.strip().lower()).strip("_") or "col"
    key = base
    n = 1
    while key in taken:
        n += 1
        key = f"{base}_{n}"
    taken.add(key)
    return key


def scaffold_table(prompt: str, *, max_columns: int = 12) -> ScaffoldResult:
    """Propose columns for a new org table from a plain-English ``prompt``.

    Returns a proposal for a human to confirm. The columns are marked editable;
    no rows are created. Honest-errors with no provider configured.
    """
    system = (
        "You design the COLUMNS of a simple club data table from a request. "
        "You never invent rows or data. Reply with a single JSON object: "
        '{"title": str, "columns": [{"title": str, "type": one of '
        f"{list(COLUMN_TYPES)}, \"description\": str}}], \"rationale\": str}}. "
        f"Use at most {max_columns} columns. 'time' means a swim time."
    )
    reply = ask(system, f"Request: {prompt}", max_tokens=500)
    obj = parse_json_object(reply)
    if not obj:
        return ScaffoldResult(False, reason="The AI reply could not be understood.")
    raw_cols = obj.get("columns")
    if not isinstance(raw_cols, list) or not raw_cols:
        return ScaffoldResult(False, reason="The AI didn't propose any columns.")

    taken: set[str] = set()
    columns: list[DataColumn] = []
    for rc in raw_cols[:max_columns]:
        if not isinstance(rc, dict):
            continue
        title = str(rc.get("title") or "").strip()
        if not title:
            continue
        ctype = str(rc.get("type") or "text").strip().lower()
        if ctype not in COLUMN_TYPES:
            ctype = "text"
        columns.append(
            DataColumn(
                key=_key_from_title(title, taken),
                title=title,
                type=ctype,
                editable=True,
                description=str(rc.get("description") or ""),
            )
        )
    if not columns:
        return ScaffoldResult(False, reason="No usable columns were proposed.")
    return ScaffoldResult(
        True,
        title=str(obj.get("title") or "New table").strip(),
        columns=columns,
        rationale=str(obj.get("rationale") or ""),
    )


__all__ = ["ScaffoldResult", "scaffold_table"]
