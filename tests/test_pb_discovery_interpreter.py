"""Regression tests for the interpreter-backed PB extraction path.

`_interpreter_extract_pbs` was doubly broken: it called a bare `interpreter.`
name (only `mediahub` was imported -> NameError), and it treated the
`InterpretedMeet` dataclass returned by `interpret_document` as a dict
(`result.get("pbs")`). A bare `except Exception` swallowed both, so the path
silently produced nothing and always fell back to the heuristic extractor.

These tests pin the fixed behaviour: the interpreter result is walked
(events -> swims) into PBRows, and the path still degrades gracefully when the
interpreter package is unavailable.
"""
from __future__ import annotations

import builtins

import pytest

from mediahub.pb_discovery.fetch_profile import ProfilePage
from mediahub.pb_discovery.parse_pbs import (
    PBRow,
    _interpreter_extract_pbs,
    parse_pbs_from_page,
)

# A minimal results-style page the interpreter can parse into events + swims.
_PAGE_TEXT = (
    "Jane Smith — Personal Bests\n"
    "Event 1 Girls 100m Freestyle\n"
    "1 Smith, Jane 2008 Swansea 1:02.34\n"
    "Event 2 Girls 200m Backstroke\n"
    "1 Smith, Jane 2008 Swansea 2:18.90\n"
)


def _page(text: str = _PAGE_TEXT) -> ProfilePage:
    return ProfilePage(
        url="http://example.test/jane",
        fetched_at="2026-01-01T00:00:00Z",
        text=text,
        tables=[],
        fetch_success=True,
    )


def test_interpreter_path_extracts_pbrows():
    rows, conf = _interpreter_extract_pbs(_page())
    assert rows, "interpreter path should now produce PBRows (regression: it returned [] )"
    assert all(isinstance(r, PBRow) for r in rows)

    by_event = {r.event: r for r in rows}
    assert "100m Freestyle" in by_event
    assert "200m Backstroke" in by_event

    free = by_event["100m Freestyle"]
    assert free.time_canonical == "1:02.34"
    assert free.course in ("LC", "SC")          # resolved, not crashed
    assert free.rank == 1
    assert free.raw.get("source") == "interpreter"
    assert 0.0 <= conf <= 1.0


def test_no_bare_interpreter_nameerror():
    # The original bug raised NameError('interpreter') which the bare except
    # masked as []. Assert we get real rows, proving the name resolves.
    rows, _ = _interpreter_extract_pbs(_page())
    assert len(rows) >= 2


def test_parse_pbs_prefers_interpreter_then_falls_back():
    # End-to-end: interpreter-first wins when it yields rows.
    rows, conf = parse_pbs_from_page(_page(), use_interpreter=True)
    assert rows
    assert rows[0].raw.get("source") == "interpreter"


def test_graceful_fallback_when_interpreter_unavailable(monkeypatch):
    # Simulate the interpreter package not being importable: the extractor must
    # raise ImportError (so the caller falls back), and parse_pbs_from_page must
    # still return heuristic rows rather than crashing.
    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "mediahub.interpreter" or name.startswith("mediahub.interpreter."):
            raise ImportError("simulated: interpreter not built")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    with pytest.raises(ImportError):
        _interpreter_extract_pbs(_page())

    # The public entry point swallows the ImportError and uses the heuristic.
    rows, conf = parse_pbs_from_page(_page(), use_interpreter=True)
    assert all(r.raw.get("source") in ("table_heuristic", "text_heuristic") for r in rows)
