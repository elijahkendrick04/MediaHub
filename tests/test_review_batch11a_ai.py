"""Regression tests for deep-review batch 11a (AI-layer robustness, module-local).

#44 media_ai.llm._safe_int/_safe_float fall back instead of crashing at import.
#46 media_ai.llm.generate_json returns the fallback (not a silent {}) when the
    provider answers with unparseable output.
#48 memory.store._db_path resolves DATA_DIR per call (not frozen at import).

(#42 learned-authority attempt floor is covered by test_deep_research.py;
 #45 anthropic retry and #47 embedder alignment are covered by their module
 suites.)
"""

from __future__ import annotations


def test_safe_int_float_fall_back_on_bad_values():
    # The import-time env parses (breaker threshold/cooldown) live in the
    # shared Gemini transport now (finding #43); the #44 guarantee — a bad
    # env value coerces to the default instead of raising at import time
    # and taking down every importer — must hold there.
    from mediahub.ai_core import gemini_transport as t

    assert t._safe_int("not-an-int", 45) == 45
    assert t._safe_int("50", 45) == 50
    assert t._safe_int(None, 45) == 45
    assert t._safe_float("4x.5", 60.0) == 60.0
    assert t._safe_float("1.5", 60.0) == 1.5


def test_generate_json_returns_fallback_on_unparseable(monkeypatch):
    from mediahub.media_ai import llm

    # Provider answered, but not with JSON — must return the caller's fallback,
    # not mask it, and never raise.
    monkeypatch.setattr(llm, "generate", lambda *a, **k: "this is prose, not json")
    assert llm.generate_json("p", fallback={"x": 1}) == {"x": 1}
    assert llm.generate_json("p") == {}  # default fallback


def test_memory_db_path_reads_data_dir_per_call(monkeypatch, tmp_path):
    from mediahub.memory import store

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert store._db_path() == tmp_path / "memory.db"
    # Resolved per call, so a later DATA_DIR is honoured (was frozen at import).
    other = tmp_path / "other"
    monkeypatch.setenv("DATA_DIR", str(other))
    assert store._db_path() == other / "memory.db"
