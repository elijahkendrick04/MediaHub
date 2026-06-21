"""data_hub.scaffold — "a sheet from a prompt" (roadmap 1.13)."""

from __future__ import annotations

import pytest

from mediahub.ai_core import ProviderNotConfigured
from mediahub.data_hub import scaffold


def test_scaffold_honest_error(monkeypatch):
    def _boom(*a, **k):
        raise ProviderNotConfigured("no key")

    monkeypatch.setattr(scaffold, "ask", _boom)
    with pytest.raises(ProviderNotConfigured):
        scaffold.scaffold_table("a sign-up sheet for the gala")


def test_scaffold_success(monkeypatch):
    reply = (
        '{"title":"Gala sign-up","columns":['
        '{"title":"Swimmer","type":"text"},'
        '{"title":"Event","type":"text"},'
        '{"title":"Entry time","type":"time"},'
        '{"title":"Paid","type":"bool"}'
        '],"rationale":"basic sign-up"}'
    )
    monkeypatch.setattr(scaffold, "ask", lambda s, u, **k: reply)
    res = scaffold.scaffold_table("a gala sign-up sheet")
    assert res.ok is True
    assert res.title == "Gala sign-up"
    assert [c.title for c in res.columns] == ["Swimmer", "Event", "Entry time", "Paid"]
    assert [c.type for c in res.columns] == ["text", "text", "time", "bool"]
    # Keys are unique snake_case and columns are editable (no rows invented).
    assert res.columns[0].key == "swimmer"
    assert all(c.editable for c in res.columns)


def test_scaffold_dedupes_keys_and_clamps_type(monkeypatch):
    reply = (
        '{"title":"X","columns":['
        '{"title":"Name","type":"weird"},'
        '{"title":"Name","type":"text"}'
        ']}'
    )
    monkeypatch.setattr(scaffold, "ask", lambda s, u, **k: reply)
    res = scaffold.scaffold_table("two name columns")
    assert res.ok is True
    keys = [c.key for c in res.columns]
    assert keys == ["name", "name_2"]  # unique
    assert res.columns[0].type == "text"  # unknown type clamped


def test_scaffold_no_columns_is_not_ok(monkeypatch):
    monkeypatch.setattr(scaffold, "ask", lambda s, u, **k: '{"title":"X","columns":[]}')
    res = scaffold.scaffold_table("nothing useful")
    assert res.ok is False
    assert res.reason


def test_scaffold_unparseable_reply(monkeypatch):
    monkeypatch.setattr(scaffold, "ask", lambda s, u, **k: "sorry, I can't help")
    res = scaffold.scaffold_table("???")
    assert res.ok is False
