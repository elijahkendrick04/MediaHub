"""data_hub.derive — derived columns: real maths, AI only suggests (1.13).

A *derived column* is computed from other columns. The computation is **real,
deterministic code** — a "formula" is a registered Python function, never an LLM
guess (the facts-are-code rule). The AI is allowed exactly one job here:
*suggest* which registered derivation fits a plain-English request, for a human
to confirm. It never computes a value or fills a cell.

Two flavours of derivation:

* **row** — computed from one row's own cells (e.g. an age group from a birth
  year, initials from a name).
* **table** — computed across the whole table (e.g. each swimmer's season-best
  time, which needs every row in the group).

Every derived cell is stamped ``DERIVED``; a row the formula can't compute is
*flagged* (with a reason), never silently zeroed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from mediahub.ai_core import ask  # raises ProviderNotConfigured / ProviderError — honest
from mediahub.athletes.registry import initials_of

from ._aiutil import parse_json_object
from .models import DataCell, DataColumn, DataTable, Provenance


# ---------------------------------------------------------------------------
# Derivation registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Derivation:
    id: str
    title: str
    description: str
    output_type: str
    scope: str  # "row" | "table"
    params: tuple[str, ...]  # param keys the caller must supply
    compute: Callable  # row: fn(cells, params)->DataCell ; table: fn(table, params)->list[DataCell]


_REGISTRY: dict[str, Derivation] = {}


def register(d: Derivation) -> None:
    _REGISTRY[d.id] = d


def list_derivations() -> list[dict]:
    return [
        {
            "id": d.id,
            "title": d.title,
            "description": d.description,
            "output_type": d.output_type,
            "scope": d.scope,
            "params": list(d.params),
        }
        for d in _REGISTRY.values()
    ]


def get_derivation(derivation_id: str) -> Optional[Derivation]:
    return _REGISTRY.get(derivation_id)


# ---------------------------------------------------------------------------
# Cell helpers
# ---------------------------------------------------------------------------


def _derived(value, display: str = "") -> DataCell:
    return DataCell(
        value=value,
        display=display if display else ("" if value is None else str(value)),
        provenance=Provenance.DERIVED,
    )


def _flagged(note: str) -> DataCell:
    return DataCell(value=None, display="", provenance=Provenance.DERIVED, flagged=True, note=note)


def _raw(cells: dict, key: str) -> str:
    c = cells.get(key)
    if c is None:
        return ""
    if isinstance(c, DataCell):
        return c.display or ("" if c.value is None else str(c.value))
    return str(c)


def _num(cells: dict, key: str) -> Optional[float]:
    c = cells.get(key)
    if isinstance(c, DataCell) and isinstance(c.value, (int, float)) and not isinstance(c.value, bool):
        return float(c.value)
    txt = _raw(cells, key).replace(",", "").strip()
    try:
        return float(txt)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Built-in derivations
# ---------------------------------------------------------------------------


def _full_name(cells: dict, params: dict) -> DataCell:
    first = _raw(cells, params.get("first", "first"))
    last = _raw(cells, params.get("last", "last"))
    name = f"{first} {last}".strip()
    return _derived(name) if name else _flagged("No first/last name to combine.")


def _initials(cells: dict, params: dict) -> DataCell:
    name = _raw(cells, params.get("name", "name"))
    return _derived(initials_of(name)) if name else _flagged("No name to take initials from.")


def _age_from_birth_year(cells: dict, params: dict) -> DataCell:
    by = _num(cells, params.get("birth_year", "birth_year"))
    if by is None:
        return _flagged("Birth year isn't a number.")
    ref = int(params.get("ref_year") or datetime.now(timezone.utc).year)
    age = ref - int(by)
    if age < 0 or age > 120:
        return _flagged(f"Computed age {age} is out of range.")
    return _derived(age, str(age))


def _age_group_band(cells: dict, params: dict) -> DataCell:
    age = _num(cells, params.get("age", "age"))
    if age is None:
        return _flagged("Age isn't a number.")
    a = int(age)
    if a <= 10:
        band = "10 & under"
    elif a >= 19:
        band = "Open"
    else:
        low = a - (a % 2 == 0)  # 11→11, 12→11, 13→13, 14→13 ...
        band = f"{low}-{low + 1}"
    return _derived(band)


def _sum(cells: dict, params: dict) -> DataCell:
    keys = params.get("columns") or []
    total = 0.0
    seen = False
    for k in keys:
        v = _num(cells, k)
        if v is not None:
            total += v
            seen = True
    if not seen:
        return _flagged("No numbers to add.")
    out = int(total) if total.is_integer() else round(total, 4)
    return _derived(out, str(out))


def _difference(cells: dict, params: dict) -> DataCell:
    a = _num(cells, params.get("a", "a"))
    b = _num(cells, params.get("b", "b"))
    if a is None or b is None:
        return _flagged("Both columns must be numbers to subtract.")
    diff = a - b
    out = int(diff) if float(diff).is_integer() else round(diff, 4)
    return _derived(out, str(out))


def _concat(cells: dict, params: dict) -> DataCell:
    keys = params.get("columns") or []
    sep = str(params.get("sep", " "))
    parts = [_raw(cells, k) for k in keys]
    parts = [p for p in parts if p]
    return _derived(sep.join(parts)) if parts else _flagged("Nothing to join.")


def _season_best(table: DataTable, params: dict) -> list[DataCell]:
    """Best value within each group (e.g. each swimmer's fastest time)."""
    group_key = params.get("group", "")
    value_key = params.get("value", "")
    lower_is_better = bool(params.get("lower_is_better", True))
    col = table.column(value_key)
    is_time = bool(col and col.type == "time")

    def _val(cell: DataCell) -> Optional[float]:
        if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
            return float(cell.value)
        return None

    # First pass: best per group.
    best: dict[str, float] = {}
    for row in table.rows:
        g = table_cell(row, group_key).display
        v = _val(table_cell(row, value_key))
        if v is None:
            continue
        if g not in best:
            best[g] = v
        else:
            best[g] = min(best[g], v) if lower_is_better else max(best[g], v)

    out: list[DataCell] = []
    for row in table.rows:
        g = table_cell(row, group_key).display
        if g in best:
            bv = best[g]
            if is_time:
                from mediahub.club_records.store import format_time_cs

                out.append(_derived(int(bv), format_time_cs(int(bv))))
            else:
                disp = str(int(bv)) if float(bv).is_integer() else str(bv)
                out.append(_derived(bv, disp))
        else:
            out.append(_flagged("No value to compare in this group."))
    return out


def table_cell(row: dict, key: str) -> DataCell:
    c = row.get(key)
    if isinstance(c, DataCell):
        return c
    if c is None:
        return DataCell()
    return DataCell.from_dict(c)


register(Derivation("full_name", "Full name", "Join a first-name and last-name column.", "text", "row", ("first", "last"), _full_name))
register(Derivation("initials", "Initials", "Turn a name into initials (e.g. M.P.).", "text", "row", ("name",), _initials))
register(Derivation("age_from_birth_year", "Age", "Work out an age from a birth year.", "int", "row", ("birth_year",), _age_from_birth_year))
register(Derivation("age_group_band", "Age group", "Put an age into a 2-year band (11-12, 13-14, …).", "text", "row", ("age",), _age_group_band))
register(Derivation("sum", "Sum", "Add several number columns together.", "number", "row", ("columns",), _sum))
register(Derivation("difference", "Difference", "Subtract one number column from another (a − b).", "number", "row", ("a", "b"), _difference))
register(Derivation("concat", "Joined text", "Join several columns into one text column.", "text", "row", ("columns",), _concat))
register(Derivation("season_best", "Season best", "Each group's best value (e.g. a swimmer's fastest time).", "time", "table", ("group", "value"), _season_best))


# ---------------------------------------------------------------------------
# Apply a derivation to a table (pure — returns the same table, mutated)
# ---------------------------------------------------------------------------


def apply_derivation(
    table: DataTable,
    output_key: str,
    output_title: str,
    derivation_id: str,
    params: dict,
) -> DataTable:
    """Add/replace a derived column on ``table`` and compute every cell.

    Raises ``KeyError`` for an unknown derivation id. Per-row failures become
    flagged cells (with a reason), never silent values.
    """
    d = _REGISTRY.get(derivation_id)
    if d is None:
        raise KeyError(f"Unknown derivation: {derivation_id}")

    # Upsert the column definition.
    existing = table.column(output_key)
    col = DataColumn(
        key=output_key,
        title=output_title or output_key,
        type=d.output_type,
        derived=True,
        derivation=derivation_id,
    )
    if existing is None:
        table.columns.append(col)
    else:
        table.columns[table.columns.index(existing)] = col

    if d.scope == "table":
        cells = d.compute(table, params)
        for i, row in enumerate(table.rows):
            row[output_key] = cells[i] if i < len(cells) else _flagged("Not computed.")
    else:
        for row in table.rows:
            try:
                row[output_key] = d.compute(row, params)
            except Exception as exc:  # noqa: BLE001 — a bad row is flagged, never fatal
                row[output_key] = _flagged(f"Could not compute: {exc}")
    return table


# ---------------------------------------------------------------------------
# AI *suggestion* (human-confirmed) — never computes
# ---------------------------------------------------------------------------


@dataclass
class DerivationSuggestion:
    ok: bool
    derivation_id: str = ""
    output_title: str = ""
    params: dict = field(default_factory=dict)
    rationale: str = ""
    reason: str = ""  # why a suggestion couldn't be made (when ok is False)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "derivation_id": self.derivation_id,
            "output_title": self.output_title,
            "params": self.params,
            "rationale": self.rationale,
            "reason": self.reason,
        }


def suggest_derivation(table: DataTable, prompt: str) -> DerivationSuggestion:
    """Ask the AI which registered derivation fits ``prompt`` (human confirms).

    Returns a *proposal* only — the caller shows it for confirmation and then
    calls :func:`apply_derivation`. Raises ``ProviderNotConfigured`` /
    ``ProviderError`` when no AI provider is configured (honest error, never a
    fabricated formula).
    """
    cols_desc = "\n".join(f"- {c.key} ({c.type}): {c.title}" for c in table.columns)
    derivs_desc = "\n".join(
        f"- {d.id}: {d.description} [params: {', '.join(d.params)}]" for d in _REGISTRY.values()
    )
    system = (
        "You map a club's plain-English request to ONE registered, deterministic "
        "derivation. You never compute values yourself. Reply with a single JSON "
        "object: {\"derivation_id\": str, \"output_title\": str, \"params\": object, "
        "\"rationale\": str}. params must reference column keys that exist. If no "
        "derivation fits, reply {\"derivation_id\": \"\", \"reason\": str}."
    )
    user = (
        f"Table columns:\n{cols_desc}\n\n"
        f"Available derivations:\n{derivs_desc}\n\n"
        f"Request: {prompt}"
    )
    reply = ask(system, user, max_tokens=400)
    obj = parse_json_object(reply)
    if not obj:
        return DerivationSuggestion(False, reason="The AI reply could not be understood.")
    did = str(obj.get("derivation_id") or "").strip()
    if not did:
        return DerivationSuggestion(False, reason=str(obj.get("reason") or "No derivation fits."))
    if did not in _REGISTRY:
        return DerivationSuggestion(False, reason=f"Suggested an unknown derivation: {did!r}.")
    params = obj.get("params") if isinstance(obj.get("params"), dict) else {}
    # Validate referenced columns exist (single-key and list params).
    valid_keys = set(table.column_keys)
    for k, v in list(params.items()):
        if isinstance(v, str) and v and v not in valid_keys and k not in ("sep", "ref_year"):
            return DerivationSuggestion(
                False, reason=f"Referenced a column that doesn't exist: {v!r}."
            )
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str) and item not in valid_keys:
                    return DerivationSuggestion(
                        False, reason=f"Referenced a column that doesn't exist: {item!r}."
                    )
    return DerivationSuggestion(
        True,
        derivation_id=did,
        output_title=str(obj.get("output_title") or _REGISTRY[did].title),
        params=params,
        rationale=str(obj.get("rationale") or ""),
    )


__all__ = [
    "Derivation",
    "DerivationSuggestion",
    "register",
    "list_derivations",
    "get_derivation",
    "apply_derivation",
    "suggest_derivation",
]
