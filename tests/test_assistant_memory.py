"""P6.2 — org assistant preference memory (assistant/memory.py)."""

from __future__ import annotations

from mediahub.assistant import memory as mem


def test_remember_list_and_org_scoping(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    a = mem.remember("club-a", "Never show times for 8-and-unders")
    assert a is not None and a.id
    mem.remember("club-a", "Lead with the first name")
    mem.remember("club-b", "Use formal tone")
    assert {i.text for i in mem.list_items("club-a")} == {
        "Never show times for 8-and-unders",
        "Lead with the first name",
    }
    # org isolation
    assert [i.text for i in mem.list_items("club-b")] == ["Use formal tone"]


def test_remember_empty_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert mem.remember("club", "   ") is None
    assert mem.list_items("club") == []


def test_dedupes_case_insensitively(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    mem.remember("club", "Lead with the first name")
    mem.remember("club", "lead with the FIRST name")
    assert len(mem.list_items("club")) == 1


def test_forget_and_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    a = mem.remember("club", "rule one")
    mem.remember("club", "rule two")
    assert mem.forget("club", a.id) is True
    assert mem.forget("club", "nonexistent") is False
    assert len(mem.list_items("club")) == 1
    assert mem.clear("club") == 1
    assert mem.list_items("club") == []


def test_recall_prefers_keyword_overlap(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    mem.remember("club", "Never show times for 8-and-unders")
    mem.remember("club", "Always tag the head coach")
    hits = mem.recall("club", "can you hide the times please", k=1)
    assert hits and "times" in hits[0].text


def test_recall_without_context_returns_recent(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    mem.remember("club", "older")
    mem.remember("club", "newer")
    hits = mem.recall("club", "", k=5)  # no context → most recent
    assert hits[0].text == "newer"


def test_prompt_block_renders_or_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert mem.as_prompt_block("club") == ""
    mem.remember("club", "Never show times for 8-and-unders")
    block = mem.as_prompt_block("club", "times")
    assert "standing preferences" in block and "8-and-unders" in block
