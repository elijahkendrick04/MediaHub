"""Tests for mediahub.memory.store — the sqlite-vec vector store.

Uses the real sqlite-vec extension (a declared dependency; no network), against
a temp memory.db per test. Verifies the council's hard requirements: tenant
isolation, embedding-model isolation, idempotent upsert, and that the extension
loads at all (the council's "prove it first" gate, as a regression test).
"""
from __future__ import annotations

import pytest

from mediahub.memory import store


@pytest.fixture(autouse=True)
def tmp_memory_db(tmp_path, monkeypatch):
    # The store resolves DATA_DIR/memory.db per call now, so point DATA_DIR here.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    yield


def _vec(*xs):
    return [float(x) for x in xs]


def test_sqlite_vec_loads():
    # The council's do-first gate, pinned as a regression test.
    assert store.is_available() is True


def test_upsert_and_query_knn():
    store.upsert(tenant_id="clubA", entry_id="c1", vector=_vec(0.1, 0.1, 0.1, 0.1),
                 model_id="m1", caption="cap A1", event_context="50 free PB")
    store.upsert(tenant_id="clubA", entry_id="c2", vector=_vec(0.9, 0.9, 0.9, 0.9),
                 model_id="m1", caption="cap A2", event_context="200 fly")
    hits = store.query(tenant_id="clubA", vector=_vec(0.1, 0.1, 0.1, 0.1), model_id="m1", k=2)
    assert len(hits) == 2
    assert hits[0].caption == "cap A1"  # nearest
    assert hits[0].event_context == "50 free PB"
    assert hits[0].distance <= hits[1].distance


def test_tenant_isolation():
    store.upsert(tenant_id="clubA", entry_id="a", vector=_vec(0.1, 0.1, 0.1, 0.1),
                 model_id="m1", caption="A", event_context="x")
    store.upsert(tenant_id="clubB", entry_id="b", vector=_vec(0.1, 0.1, 0.1, 0.1),
                 model_id="m1", caption="B", event_context="x")
    hits = store.query(tenant_id="clubA", vector=_vec(0.1, 0.1, 0.1, 0.1), model_id="m1", k=5)
    assert [h.caption for h in hits] == ["A"]  # clubB never compared


def test_model_isolation():
    store.upsert(tenant_id="clubA", entry_id="a", vector=_vec(0.1, 0.1, 0.1, 0.1),
                 model_id="m1", caption="m1cap", event_context="x")
    store.upsert(tenant_id="clubA", entry_id="b", vector=_vec(0.1, 0.1, 0.1, 0.1),
                 model_id="m2", caption="m2cap", event_context="x")
    hits = store.query(tenant_id="clubA", vector=_vec(0.1, 0.1, 0.1, 0.1), model_id="m1", k=5)
    assert [h.caption for h in hits] == ["m1cap"]  # m2 vectors never mixed in


def test_idempotent_upsert_dedup():
    store.upsert(tenant_id="clubA", entry_id="c1", vector=_vec(0.1, 0.1, 0.1, 0.1),
                 model_id="m1", caption="v1", event_context="x")
    store.upsert(tenant_id="clubA", entry_id="c1", vector=_vec(0.1, 0.1, 0.1, 0.1),
                 model_id="m1", caption="v2", event_context="x")
    assert store.count(tenant_id="clubA") == 1
    hits = store.query(tenant_id="clubA", vector=_vec(0.1, 0.1, 0.1, 0.1), model_id="m1", k=5)
    assert hits[0].caption == "v2"


def test_count_and_clear():
    store.upsert(tenant_id="clubA", entry_id="a", vector=_vec(1, 0, 0, 0),
                 model_id="m1", caption="A", event_context="x")
    store.upsert(tenant_id="clubA", entry_id="b", vector=_vec(0, 1, 0, 0),
                 model_id="m1", caption="B", event_context="x")
    assert store.count(tenant_id="clubA") == 2
    assert store.count(tenant_id="clubA", model_id="m1") == 2
    assert store.count(tenant_id="clubA", model_id="other") == 0
    store.clear(tenant_id="clubA")
    assert store.count(tenant_id="clubA") == 0


def test_query_empty_store_returns_empty():
    assert store.query(tenant_id="clubA", vector=_vec(0.1, 0.1, 0.1, 0.1), model_id="m1", k=3) == []


def test_per_dim_tables_coexist():
    store.upsert(tenant_id="clubA", entry_id="d4", vector=_vec(0.1, 0.1, 0.1, 0.1),
                 model_id="m1", caption="dim4", event_context="x")
    store.upsert(tenant_id="clubA", entry_id="d3", vector=_vec(0.1, 0.1, 0.1),
                 model_id="m1", caption="dim3", event_context="x")
    assert store.count(tenant_id="clubA") == 2
    h4 = store.query(tenant_id="clubA", vector=_vec(0.1, 0.1, 0.1, 0.1), model_id="m1", k=5)
    h3 = store.query(tenant_id="clubA", vector=_vec(0.1, 0.1, 0.1), model_id="m1", k=5)
    assert [h.caption for h in h4] == ["dim4"]
    assert [h.caption for h in h3] == ["dim3"]


def test_empty_vector_rejected():
    with pytest.raises(ValueError):
        store.upsert(tenant_id="clubA", entry_id="x", vector=[],
                     model_id="m1", caption="c", event_context="x")
