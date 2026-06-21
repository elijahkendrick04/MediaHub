"""data_hub — the club's data as browsable, editable tables (roadmap 1.13).

MediaHub is structured-data-first: the canonical results store *is* the
spreadsheet. This package turns that store — plus the club's own tables — into a
user-facing **data hub**:

* :mod:`~mediahub.data_hub.models`      — the table/column/cell shape, with
  per-cell *provenance* (parsed vs typed-in vs derived vs imported).
* :mod:`~mediahub.data_hub.tables`      — read-only views over the engine's
  stores (athletes, results, records, swimmers, clubs, meets).
* :mod:`~mediahub.data_hub.store`       — the club's own editable tables
  (rosters, sponsor facts, custom sheets), org-scoped in SQLite.
* :mod:`~mediahub.data_hub.portability` — deterministic CSV/XLSX import/export
  round-trip, with ambiguity flagging.
* :mod:`~mediahub.data_hub.derive`      — deterministic derived columns, with
  AI only *suggesting* a definition (a human confirms; never auto-computes).
* :mod:`~mediahub.data_hub.scaffold`    — "a sheet from a prompt": AI proposes
  columns + kinds for a new org table (honest-errors with no provider).
* :mod:`~mediahub.data_hub.connectors`  — pull adapters that sync club-relevant
  sources on a schedule, normalised to the canonical shape with trust metadata.

The rule that governs everything here: **facts are exact, judgement is AI, and
errors are honest.** Importing, deriving and exporting are deterministic; the AI
only ever *suggests* (a derivation, a schema) for a human to confirm.
"""

from __future__ import annotations

from .models import (
    COLUMN_TYPES,
    TABLE_KINDS,
    DataCell,
    DataColumn,
    DataTable,
    DataWarning,
    Provenance,
    text_cell,
)
from .portability import ImportResult, export_csv, export_xlsx, import_bytes
from .tables import (
    get_canonical_table,
    list_canonical_tables,
)

__all__ = [
    "Provenance",
    "COLUMN_TYPES",
    "TABLE_KINDS",
    "DataCell",
    "DataColumn",
    "DataTable",
    "DataWarning",
    "text_cell",
    "ImportResult",
    "import_bytes",
    "export_csv",
    "export_xlsx",
    "get_canonical_table",
    "list_canonical_tables",
]
