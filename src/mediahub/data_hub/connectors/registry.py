"""data_hub.connectors.registry — register, run and schedule connectors (1.13).

The registry is the single place routes and the scheduler reach for a connector.
``run_connector`` fetches and normalises into a :class:`DataTable` with every
cell stamped ``CONNECTOR`` and the source's trust recorded; ``sync_connector``
upserts that into a club-owned org table so it stays browsable and refreshable.
The scheduled-refresh seam registers a scheduler task type so a connector can be
re-pulled on a cadence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .. import store as _store
from ..models import DataCell, DataTable, Provenance
from .base import Connector, ConnectorResult, SourceTrust
from .builtin import CsvUrlConnector, SwimEnglandRankingsConnector

_REGISTRY: dict[str, Connector] = {}


def register(connector: Connector) -> None:
    _REGISTRY[connector.connector_id] = connector


def get(connector_id: str) -> Optional[Connector]:
    return _REGISTRY.get(connector_id)


def list_connectors() -> list[dict]:
    return [c.meta() for c in _REGISTRY.values()]


# Register the shipped connectors.
register(CsvUrlConnector())
register(SwimEnglandRankingsConnector())


def _stamp(result: ConnectorResult) -> list[dict]:
    """Re-stamp every cell with CONNECTOR provenance + the source trust."""
    trust = result.trust
    rows: list[dict] = []
    for row in result.rows:
        out: dict[str, DataCell] = {}
        for key, cell in row.items():
            c = cell if isinstance(cell, DataCell) else DataCell.from_dict(cell)
            c.provenance = Provenance.CONNECTOR
            c.source = trust.source_url or trust.source
            if not c.confidence:
                c.confidence = trust.confidence
            out[key] = c
        rows.append(out)
    return rows


def run_connector(
    profile_id: str,
    connector_id: str,
    *,
    params: Optional[dict] = None,
    connector: Optional[Connector] = None,
    title: str = "",
) -> DataTable:
    """Fetch via a connector and return a normalised, provenance-stamped table.

    Raises ``KeyError`` for an unknown connector; the connector may raise
    ``ConnectorNotConfigured`` (honest error) if it isn't ready.
    """
    c = connector or _REGISTRY.get(connector_id)
    if c is None:
        raise KeyError(f"Unknown connector: {connector_id}")
    result = c.fetch(profile_id, params or {})
    table = DataTable(
        table_id=f"connector:{connector_id}",
        title=title or c.title,
        kind="org",
        profile_id=profile_id,
        columns=result.columns,
        rows=_stamp(result),
        editable=False,  # synced data is read-only; edits would be overwritten on refresh
        source=result.trust.source,
        description=result.trust.note,
        warnings=result.warnings,
    )
    return table


def sync_connector(
    profile_id: str,
    connector_id: str,
    *,
    params: Optional[dict] = None,
    connector: Optional[Connector] = None,
    table_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> str:
    """Fetch and persist into a club-owned org table; return its ``table_id``.

    If ``table_id`` is given the rows are replaced in place (a refresh);
    otherwise a new org table is created.
    """
    table = run_connector(profile_id, connector_id, params=params, connector=connector)
    if table_id is None:
        table_id = _store.create_table(
            profile_id,
            table.title,
            table.columns,
            description=table.description,
            db_path=db_path,
        )
    else:
        _store.set_columns(profile_id, table_id, table.columns, db_path=db_path)
        # Replace existing rows with the fresh pull.
        existing = _store.get_org_table(profile_id, table_id, db_path=db_path)
        if existing is not None:
            for rid in _store.row_ids_for(existing):
                _store.delete_row(profile_id, table_id, rid, db_path=db_path)
    for row in table.rows:
        _store.upsert_row(profile_id, table_id, row, db_path=db_path)
    return table_id


# ---------------------------------------------------------------------------
# Scheduled refresh seam
# ---------------------------------------------------------------------------


def _refresh_handler(params: dict) -> None:
    """Scheduler handler: refresh one connector-backed table (idempotent)."""
    profile_id = params.get("profile_id", "")
    connector_id = params.get("connector_id", "")
    table_id = params.get("table_id")
    conn_params = params.get("params") or {}
    if not profile_id or not connector_id or not table_id:
        return
    try:
        sync_connector(
            profile_id, connector_id, params=conn_params, table_id=table_id
        )
    except Exception:  # noqa: BLE001 — a failed refresh must not crash the scheduler
        pass


def register_refresh_task() -> None:
    """Register the connector-refresh task type with the scheduler (idempotent)."""
    try:
        from mediahub.scheduler import register_task_type

        register_task_type("data_hub_connector_refresh", _refresh_handler)
    except Exception:  # noqa: BLE001 — scheduler optional; never block import
        pass


__all__ = [
    "register",
    "get",
    "list_connectors",
    "run_connector",
    "sync_connector",
    "register_refresh_task",
    "SourceTrust",
]
