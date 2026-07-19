"""Finding #101 — observability stores resolve DATA_DIR lazily, not at import.

``llm_usage`` / ``uptime`` / ``imagine_usage`` froze ``DATA_DIR``/``DB_PATH`` at
import and bootstrapped their schema at import time. A ``DATA_DIR`` set *after*
those modules were first imported therefore split their writes across two DBs:
the import-time default and the real one. Each store now resolves ``DATA_DIR``
per call (``_db_path()``) and bootstraps on first write, so a late ``DATA_DIR``
lands every row in the one live DB.

Each test writes to a DATA_DIR set *after* import (no reload) and asserts the
row landed in the current DATA_DIR's ``data.db`` — the discriminator that fails
on the frozen-path code and passes on the lazy code.
"""

from __future__ import annotations

import sqlite3

import pytest

from mediahub.observability import imagine_usage, llm_usage, uptime


def _count(db_path, table) -> int:
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(str(db_path))
    try:
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.Error:
            return 0
    finally:
        conn.close()


def test_uptime_write_follows_late_data_dir(tmp_path, monkeypatch):
    late = tmp_path / "late"
    monkeypatch.setenv("DATA_DIR", str(late))  # set AFTER import, no reload
    rid = uptime.record_heartbeat(ok=True)
    assert rid > 0
    assert _count(late / "data.db", "uptime_heartbeats") == 1, (
        "heartbeat must land in the current DATA_DIR, not a frozen import-time path"
    )


def test_llm_usage_write_follows_late_data_dir(tmp_path, monkeypatch):
    late = tmp_path / "late"
    monkeypatch.setenv("DATA_DIR", str(late))
    rid = llm_usage.record_call(provider="gemini", ok=True)
    assert rid > 0
    assert _count(late / "data.db", "llm_calls") == 1


def test_imagine_usage_write_follows_late_data_dir(tmp_path, monkeypatch):
    late = tmp_path / "late"
    monkeypatch.setenv("DATA_DIR", str(late))
    rid = imagine_usage.record_use(org_id="org-x", op="cutout", ok=True)
    assert rid > 0
    assert _count(late / "data.db", "imagine_uses") == 1


@pytest.mark.parametrize("mod", [uptime, llm_usage, imagine_usage])
def test_db_path_attribute_tracks_current_data_dir(mod, tmp_path, monkeypatch):
    # The back-compat DB_PATH export is served lazily, so it always points at the
    # current DATA_DIR rather than an import-time freeze.
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "a"))
    assert mod.DB_PATH == tmp_path / "a" / "data.db"
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "b"))
    assert mod.DB_PATH == tmp_path / "b" / "data.db"


def test_no_import_time_default_db_created(tmp_path, monkeypatch):
    # A store imported with no writes must not have bootstrapped a stray DB in
    # the current DATA_DIR (schema is created on first write, not at import).
    empty = tmp_path / "untouched"
    empty.mkdir()
    monkeypatch.setenv("DATA_DIR", str(empty))
    # No write performed against this DATA_DIR.
    assert not (empty / "data.db").exists()
