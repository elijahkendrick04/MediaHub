"""Roadmap 1.18 build 3 — the collab.locks element-lock registry."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.collab import locks as lk


@pytest.fixture
def db(tmp_path):
    return tmp_path / "data.db"


def test_set_and_read_lock(db):
    assert lk.set_lock("run1", "card1", "sponsor", True, by="owner@c", db_path=db) is True
    assert lk.locked_elements("run1", "card1", db_path=db) == {"sponsor"}
    assert lk.is_locked("run1", "card1", "sponsor", db_path=db) is True
    assert lk.is_locked("run1", "card1", "headline", db_path=db) is False


def test_unlock(db):
    lk.set_lock("run1", "card1", "headline", True, db_path=db)
    lk.set_lock("run1", "card1", "headline", False, db_path=db)
    assert lk.locked_elements("run1", "card1", db_path=db) == set()


def test_locks_are_per_card(db):
    lk.set_lock("run1", "cardA", "photo", True, db_path=db)
    assert lk.locked_elements("run1", "cardB", db_path=db) == set()


def test_unknown_element_rejected(db):
    with pytest.raises(lk.LockError):
        lk.set_lock("run1", "card1", "not-an-element", True, db_path=db)
    # is_locked tolerates an unknown element (returns False, never raises)
    assert lk.is_locked("run1", "card1", "bogus", db_path=db) is False


def test_list_locks_metadata(db):
    lk.set_lock("run1", "card1", "palette", True, by="chair@c", db_path=db)
    rows = lk.list_locks("run1", "card1", db_path=db)
    assert len(rows) == 1
    assert rows[0]["element"] == "palette"
    assert rows[0]["locked_by"] == "chair@c"


def test_delete_for_run(db):
    lk.set_lock("run1", "card1", "sponsor", True, db_path=db)
    lk.set_lock("run1", "card2", "photo", True, db_path=db)
    lk.set_lock("run2", "card1", "headline", True, db_path=db)
    assert lk.delete_for_run("run1", db_path=db) == 2
    assert lk.locked_elements("run1", "card1", db_path=db) == set()
    assert lk.locked_elements("run2", "card1", db_path=db) == {"headline"}


def test_lockable_vocabulary_covers_sponsor_and_photo(db):
    assert "sponsor" in lk.LOCKABLE_ELEMENTS
    assert "photo" in lk.LOCKABLE_ELEMENTS
    assert "headline" in lk.LOCKABLE_ELEMENTS
