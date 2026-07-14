"""tests/test_visual_index.py — the O(1) vid→(run_id, brief_id) index (#17).

``GET /api/visual/<vid>`` and its ``/png/<format>`` sibling used to resolve one
id by nested-walking every run dir under ``RUNS_DIR`` and ``json.loads``-ing
every ``visual.json`` — ``O(all-tenant-runs × visuals-per-run)`` on hot
``<img src>`` routes. These cover the tiny SQLite index that replaces the walk:
``index_visual``/``lookup``/``forget`` round-trip, that ``persist_visual``
stamps it when a visual is written, and that it lands in the same ``data.db``
``web.py`` reads. Route-level fast-path, lazy backfill and erasure-cascade
coverage lives in ``tests/test_cross_tenant_access.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A fresh DATA_DIR so the index writes to an isolated ``tmp/data.db``."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    return tmp_path


def test_index_and_lookup_roundtrip(data_dir):
    from mediahub.content_pack_visual import visual_index as vi

    payload = {"id": "v_primary", "visual_ids": {"v_primary": "feed_portrait",
                                                 "v_square": "feed_square"}}
    vi.index_visual("run-1", "brief-7", payload)

    # Every vid in the payload — the primary id AND every per-format id — must
    # resolve to the same brief dir, because the routes match on either form.
    assert vi.lookup("v_primary") == ("run-1", "brief-7")
    assert vi.lookup("v_square") == ("run-1", "brief-7")
    assert vi.lookup("v_unknown") is None


def test_lookup_empty_and_missing(data_dir):
    from mediahub.content_pack_visual import visual_index as vi

    assert vi.lookup("") is None
    assert vi.lookup("never-indexed") is None


def test_forget_removes_row(data_dir):
    from mediahub.content_pack_visual import visual_index as vi

    vi.index_visual("run-x", "brief-x", {"id": "v_gone", "visual_ids": {}})
    assert vi.lookup("v_gone") == ("run-x", "brief-x")
    vi.forget("v_gone")
    assert vi.lookup("v_gone") is None


def test_reindex_updates_mapping(data_dir):
    """A re-render rewrites the sidecar; INSERT OR REPLACE must repoint the vid."""
    from mediahub.content_pack_visual import visual_index as vi

    vi.index_visual("run-a", "brief-old", {"id": "v_moved", "visual_ids": {}})
    vi.index_visual("run-a", "brief-new", {"id": "v_moved", "visual_ids": {}})
    assert vi.lookup("v_moved") == ("run-a", "brief-new")


def test_index_ignores_empty_ids(data_dir):
    from mediahub.content_pack_visual import visual_index as vi

    # No id and no visual_ids → nothing to index, no row, no crash.
    vi.index_visual("run-0", "brief-0", {"visual_ids": {}})
    vi.index_visual("run-0", "brief-0", {})
    conn = vi._connect()
    try:
        n = conn.execute("SELECT COUNT(*) FROM visual_index").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


class _StubVisual:
    """Minimal stand-in for graphic_renderer.render.GeneratedVisual — just the
    attributes persist_visual reads (``id``/``brief_id``/``file_path`` +
    ``to_dict``)."""

    def __init__(self, vid, brief_id):
        self.id = vid
        self.brief_id = brief_id
        self.file_path = None

    def to_dict(self):
        return {"id": self.id, "content_item_id": "card-1", "format_name": "feed_portrait"}


def test_persist_visual_stamps_index(data_dir):
    """Writing a visual must make it O(1)-resolvable without any walk."""
    from mediahub.content_pack_visual import integration as ig
    from mediahub.content_pack_visual import visual_index as vi

    sidecar = ig.persist_visual(_StubVisual("v_persisted", "brief-99"), run_id="run-9")
    # Sidecar written where the route expects it …
    assert sidecar.exists()
    assert sidecar.parent.name == "brief-99"
    # … and the index points the vid at that run + brief dir.
    assert vi.lookup("v_persisted") == ("run-9", "brief-99")


def test_index_db_is_the_web_data_db(data_dir):
    """The index must land in the exact data.db web.py opens, or the routes
    can't read what persist_visual wrote."""
    from mediahub.content_pack_visual import visual_index as vi

    assert vi._db_path() == data_dir / "data.db"
