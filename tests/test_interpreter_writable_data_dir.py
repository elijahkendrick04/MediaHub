"""The interpreter's self-learning side-effects (validation corpus + provisional
patterns) must write under DATA_DIR, never the read-only package source tree,
and must never abort the deterministic parse when the filesystem refuses a write.

Regression for the hosted failure where a parsed results ZIP surfaced
``Parser error: [Errno 13] Permission denied: '/app/src/mediahub/data'`` because
``save_corpus_section`` / ``PatternStore.flush`` mkdir'd into the package tree
(``src/mediahub/data``) instead of the mounted DATA_DIR disk.
"""

from __future__ import annotations

import importlib

import pytest


def _reload(monkeypatch, data_dir):
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    import mediahub.interpreter.hypothesis as hyp
    import mediahub.interpreter.patterns as pat

    importlib.reload(pat)
    importlib.reload(hyp)
    return hyp, pat


def test_corpus_dir_derives_from_data_dir(monkeypatch, tmp_path):
    hyp, _ = _reload(monkeypatch, tmp_path)
    expected = tmp_path / "data" / "patterns_validation_corpus"
    assert hyp._default_corpus_dir() == expected


def test_patterns_path_derives_from_data_dir(monkeypatch, tmp_path):
    _, pat = _reload(monkeypatch, tmp_path)
    assert pat._default_patterns_path() == tmp_path / "data" / "patterns.jsonl"
    # A store built with no explicit path uses the DATA_DIR location.
    store = pat.PatternStore()
    assert store._path == tmp_path / "data" / "patterns.jsonl"


def test_save_corpus_section_writes_under_data_dir(monkeypatch, tmp_path):
    hyp, _ = _reload(monkeypatch, tmp_path)
    dest = hyp.save_corpus_section("a parsed section", label="success")
    assert dest is not None
    assert dest.exists()
    # Lands under DATA_DIR, NEVER the package source tree.
    assert str(tmp_path) in str(dest)
    assert "src/mediahub/data" not in str(dest)


def test_save_corpus_section_failsoft_on_readonly(monkeypatch, tmp_path):
    """A write failure is best-effort: it returns None, never raises, so the
    deterministic parse that triggered it still completes."""
    hyp, _ = _reload(monkeypatch, tmp_path)

    def _boom(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("pathlib.Path.mkdir", _boom)
    # Must not raise.
    assert hyp.save_corpus_section("text", label="success") is None


def test_pattern_flush_failsoft_on_readonly(monkeypatch, tmp_path):
    _, pat = _reload(monkeypatch, tmp_path)
    store = pat.PatternStore()

    def _boom(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("pathlib.Path.mkdir", _boom)
    # Must not raise even though the backing dir can't be created.
    store.flush()


def test_parse_succeeds_when_corpus_write_blocked(monkeypatch, tmp_path):
    """End-to-end guard: an unwritable data dir must not turn a good parse into
    a 'no results / Permission denied' failure."""
    _reload(monkeypatch, tmp_path)
    from mediahub.interpreter import interpret_document

    def _boom(self, *a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("pathlib.Path.mkdir", _boom)

    html = (
        b"<!DOCTYPE html><html><body>"
        b"<h2>Event 1: Female 50m Freestyle</h2><table>"
        b"<tr><th>Place</th><th>Name</th><th>YOB</th><th>Club</th><th>Time</th></tr>"
        b"<tr><td>1</td><td>Alpha Beta</td><td>2010</td><td>Test SC</td><td>28.45</td></tr>"
        b"<tr><td>2</td><td>Gamma Delta</td><td>2010</td><td>Other SC</td><td>29.12</td></tr>"
        b"<tr><td>3</td><td>Epsilon Zeta</td><td>2011</td><td>Test SC</td><td>30.55</td></tr>"
        b"<tr><td>4</td><td>Eta Theta</td><td>2010</td><td>Third SC</td><td>31.01</td></tr>"
        b"</table></body></html>"
    )
    # Should return parsed swims, not raise PermissionError.
    result = interpret_document(html, hint="html")
    total = sum(len(e.swims) for e in result.events)
    assert total >= 4
