"""Loop sweep-env cadences: fuzz every Nth sweep, opt-in variety rotation every
Vth sweep (AUTOTEST_VARIETY_EVERY), and pool refresh logging that never counts
discovered URLs as downloaded files."""
from __future__ import annotations

from pathlib import Path

import pytest

from autotest import loop


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("AUTOTEST_INPUT", "AUTOTEST_FUZZ_EVERY", "AUTOTEST_VARIETY_EVERY",
                "AUTOTEST_REFRESH_EVERY"):
        monkeypatch.delenv(var, raising=False)


def test_variety_pass_off_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr(loop.acquire, "next_input",
                        lambda sweep: calls.append(sweep) or Path("/x/rotated.pdf"))
    monkeypatch.setenv("AUTOTEST_FUZZ_EVERY", "0")
    env = loop._sweep_env(3)
    assert "AUTOTEST_INPUT" not in env
    assert calls == []


def test_variety_pass_sets_input_from_pool_on_nth_sweep(monkeypatch):
    calls = []
    monkeypatch.setattr(loop.acquire, "next_input",
                        lambda sweep: calls.append(sweep) or Path("/x/rotated.pdf"))
    monkeypatch.setenv("AUTOTEST_FUZZ_EVERY", "0")
    monkeypatch.setenv("AUTOTEST_VARIETY_EVERY", "3")
    env = loop._sweep_env(3)
    assert env["AUTOTEST_INPUT"] == str(Path("/x/rotated.pdf"))
    assert calls == [3]
    # off-cadence sweep: no rotated input
    assert "AUTOTEST_INPUT" not in loop._sweep_env(4)
    # sweep 0 never rotates (matches the fuzz cadence)
    assert "AUTOTEST_INPUT" not in loop._sweep_env(0)


def test_variety_pass_empty_pool_leaves_input_unset(monkeypatch):
    monkeypatch.setattr(loop.acquire, "next_input", lambda sweep: None)
    monkeypatch.setenv("AUTOTEST_FUZZ_EVERY", "0")
    monkeypatch.setenv("AUTOTEST_VARIETY_EVERY", "2")
    assert "AUTOTEST_INPUT" not in loop._sweep_env(2)


def test_fuzz_wins_over_variety_on_shared_cadence(monkeypatch, tmp_path):
    monkeypatch.setattr(loop, "FUZZ_DIR", tmp_path)
    monkeypatch.setattr(loop.acquire, "fuzz_input",
                        lambda kind, d: d / f"{kind}.pdf")
    monkeypatch.setattr(loop.acquire, "next_input",
                        lambda sweep: pytest.fail("variety must not run on a fuzz sweep"))
    monkeypatch.setenv("AUTOTEST_FUZZ_EVERY", "5")
    monkeypatch.setenv("AUTOTEST_VARIETY_EVERY", "5")
    env = loop._sweep_env(5)
    assert env["AUTOTEST_INPUT"].endswith(".pdf")


def test_refresh_logs_discovered_urls_as_sources_not_files(monkeypatch, capsys):
    monkeypatch.setattr(loop.acquire, "download_sources", lambda: [])
    monkeypatch.setattr(loop.acquire, "discover_online",
                        lambda: ["https://example.org/a.pdf", "https://example.org/b.pdf"])
    monkeypatch.setenv("AUTOTEST_REFRESH_EVERY", "10")
    loop._maybe_refresh_pool(10)
    out = capsys.readouterr().out
    assert "discovered +2 sources" in out
    assert "files" not in out  # URLs are not counted as downloaded files


def test_refresh_logs_downloaded_files_separately(monkeypatch, capsys):
    monkeypatch.setattr(loop.acquire, "download_sources",
                        lambda: [Path("/x/a.pdf")])
    monkeypatch.setattr(loop.acquire, "discover_online", lambda: [])
    monkeypatch.setenv("AUTOTEST_REFRESH_EVERY", "10")
    loop._maybe_refresh_pool(10)
    out = capsys.readouterr().out
    assert "+1 files" in out
    assert "sources" not in out
