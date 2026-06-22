"""Roadmap 1.18 build 4 — the collab.share_tokens ledger."""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.collab import share_tokens as st


@pytest.fixture
def db(tmp_path):
    return tmp_path / "data.db"


def test_create_and_resolve(db):
    s = st.create_share("run1", card_id="card1", perm="comment", created_by="o@c", db_path=db)
    assert len(s.token) >= 24
    assert s.perm == "comment"
    assert s.expires_at > time.time()
    got = st.resolve(s.token, db_path=db)
    assert got is not None and got.run_id == "run1" and got.card_id == "card1"


def test_bad_perm_rejected(db):
    with pytest.raises(st.ShareTokenError):
        st.create_share("run1", perm="admin", db_path=db)


def test_ttl_clamped(db):
    s = st.create_share("run1", ttl_days=9999, db_path=db)
    # capped at MAX_TTL_DAYS
    assert s.expires_at <= time.time() + st.MAX_TTL_DAYS * 86400 + 5
    s2 = st.create_share("run1", ttl_days=0, db_path=db)
    assert s2.expires_at > time.time()  # floored to >=1 day


def test_resolve_none_when_revoked(db):
    s = st.create_share("run1", db_path=db)
    assert st.revoke(s.token, run_id="run1", db_path=db) is True
    assert st.resolve(s.token, db_path=db) is None


def test_revoke_scoped_to_run(db):
    s = st.create_share("run1", db_path=db)
    # revoke under the wrong run is a no-op
    assert st.revoke(s.token, run_id="run2", db_path=db) is False
    assert st.resolve(s.token, db_path=db) is not None


def test_resolve_none_when_expired(db):
    s = st.create_share("run1", db_path=db)
    conn = sqlite3.connect(str(db))
    conn.execute(
        "UPDATE collab_share_tokens SET expires_at=? WHERE token=?",
        (time.time() - 10, s.token),
    )
    conn.commit()
    conn.close()
    assert st.resolve(s.token, db_path=db) is None


def test_list_for_run_excludes_revoked_by_default(db):
    a = st.create_share("run1", db_path=db)
    st.create_share("run1", db_path=db)
    st.revoke(a.token, run_id="run1", db_path=db)
    assert len(st.list_for_run("run1", db_path=db)) == 1
    assert len(st.list_for_run("run1", include_revoked=True, db_path=db)) == 2


def test_unknown_token_resolves_none(db):
    assert st.resolve("nope", db_path=db) is None
    assert st.resolve("", db_path=db) is None


def test_delete_for_run(db):
    st.create_share("run1", db_path=db)
    st.create_share("run1", db_path=db)
    st.create_share("run2", db_path=db)
    assert st.delete_for_run("run1", db_path=db) == 2
    assert st.list_for_run("run1", db_path=db) == []
    assert len(st.list_for_run("run2", db_path=db)) == 1
