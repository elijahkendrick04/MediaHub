"""data_hub.connectors — pull adapters, trust, refresh, honest errors (1.13)."""

from __future__ import annotations

import pytest

from mediahub.data_hub import connectors, store
from mediahub.data_hub.connectors.base import ConnectorNotConfigured
from mediahub.data_hub.connectors.builtin import CsvUrlConnector
from mediahub.data_hub.models import Provenance


def test_builtins_registered():
    ids = {c["connector_id"] for c in connectors.list_connectors()}
    assert {"csv_url", "swim_england_rankings"} <= ids


def test_csv_url_connector_offline_fetch():
    conn = CsvUrlConnector(fetcher=lambda url: b"Swimmer,PBs\nMaya,3\nSam,2\n")
    table = connectors.run_connector(
        "club-a", "csv_url", params={"url": "https://x/feed.csv", "source": "Club feed"}, connector=conn
    )
    assert table.row_count == 2
    # Synced cells are CONNECTOR provenance, carry the source, and are read-only.
    cell = table.cell(0, "swimmer")
    assert cell.provenance == Provenance.CONNECTOR
    assert "feed.csv" in cell.source
    assert table.editable is False


def test_sync_into_org_table_and_refresh(tmp_path):
    db = tmp_path / "data.db"
    conn = CsvUrlConnector(fetcher=lambda url: b"Swimmer,PBs\nMaya,3\n")
    tid = connectors.sync_connector("club-a", "csv_url", params={"url": "x"}, connector=conn, db_path=db)
    t = store.get_org_table("club-a", tid, db_path=db)
    assert t.row_count == 1

    # A refresh replaces the rows in the same table.
    conn2 = CsvUrlConnector(fetcher=lambda url: b"Swimmer,PBs\nMaya,4\nSam,1\n")
    connectors.sync_connector("club-a", "csv_url", params={"url": "x"}, connector=conn2, table_id=tid, db_path=db)
    t2 = store.get_org_table("club-a", tid, db_path=db)
    assert t2.row_count == 2


def test_csv_url_honest_error_without_url():
    with pytest.raises(ConnectorNotConfigured):
        connectors.run_connector("club-a", "csv_url", params={})


def test_swim_england_seam_is_flag_gated(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_SWIM_ENGLAND_API_KEY", raising=False)
    with pytest.raises(ConnectorNotConfigured):
        connectors.run_connector("club-a", "swim_england_rankings", params={})


def test_unknown_connector_raises():
    with pytest.raises(KeyError):
        connectors.run_connector("club-a", "no_such_connector")


def test_register_refresh_task_is_safe():
    # Idempotent + never raises even if the scheduler isn't importable.
    connectors.register_refresh_task()
    connectors.register_refresh_task()
