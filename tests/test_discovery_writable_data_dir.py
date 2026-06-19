"""Regression for the hosted failure where running a meet pack through the meet
recap tool surfaced, on the UI:

    Club discovery store warning: [Errno 13] Permission denied: '/app/src/mediahub/data'
    PB lookup error for <name>: [Errno 13] Permission denied: '/app/src/mediahub/data'

Both came from modules that hardcoded a package-relative ``data/`` path
(``Path(__file__)…/"data"``) and eagerly ``mkdir``'d it, instead of deriving
from the writable ``DATA_DIR`` disk. On the hosted deployment the package tree
(``/app/src/mediahub``) is read-only, so the mkdir raised PermissionError.

The fix: both derive from ``DATA_DIR`` (the same ``discovered/`` tree the PB
caches use) and fail soft — a read-only store is a best-effort enrichment miss,
never a crash that aborts the recap.
"""

from __future__ import annotations

import pytest

from mediahub.context_engine import trust
from mediahub.web import club_discovery


# ── Club discovery store ────────────────────────────────────────────────────


def test_clubs_root_derives_from_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    root = club_discovery._clubs_root()
    assert root == tmp_path / "discovered" / "clubs"
    assert "src/mediahub/data" not in str(root)


def test_record_clubs_writes_under_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    written = club_discovery.record_clubs(["City of Test Aquatics"], run_id="run-1")
    assert written, "expected the club to be recorded"
    for p in written:
        assert str(tmp_path) in str(p)
        assert "src/mediahub/data" not in str(p)
        assert p.exists()
    names = club_discovery.list_discovered_club_names()
    assert "City of Test Aquatics" in names


def test_record_clubs_raises_on_readonly_so_caller_can_surface(monkeypatch, tmp_path):
    """A storage failure must PROPAGATE, not be swallowed: pipeline_v4 wraps the
    call in a try/except that surfaces it as a (developer-visible) "Club
    discovery store warning" progress line. Swallowing it here would hide a
    genuine infrastructure fault — exactly the silent-fail the operator does
    not want."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    def _boom(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("pathlib.Path.mkdir", _boom)
    with pytest.raises(OSError):
        club_discovery.record_clubs(["Anything SC"], run_id="run-2")


def test_list_discovered_clubs_empty_when_root_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "does-not-exist"))
    # No store yet → empty list, never an error.
    assert club_discovery.list_discovered_clubs() == []


# ── PB trust ledger ─────────────────────────────────────────────────────────


def test_ledger_path_derives_from_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    p = trust._ledger_path()
    assert p == tmp_path / "discovered" / "discovered_sources.jsonl"
    assert "src/mediahub/data" not in str(p)


def test_record_attempt_writes_under_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    trust.record_attempt("example.org", success=True, purpose="swimmer_pbs")
    assert trust._ledger_path().exists()
    # A 1/1 success lifts the domain above the 0.5 neutral prior.
    assert trust.score_domain("example.org") > 0.5


def test_trust_failsoft_on_readonly(monkeypatch, tmp_path):
    """A read-only ledger dir must not raise from PB ranking — the bug aborted
    every swimmer's lookup. Ranking simply degrades to the neutral prior."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    def _boom(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("pathlib.Path.mkdir", _boom)
    # None of these may raise.
    trust.record_attempt("example.com", success=True, purpose="swimmer_pbs")
    assert trust.score_domain("example.com") == pytest.approx(0.5)
    assert trust.rank_candidates(
        ["https://a.example/x", "https://b.example/y"]
    ) == ["https://a.example/x", "https://b.example/y"]
