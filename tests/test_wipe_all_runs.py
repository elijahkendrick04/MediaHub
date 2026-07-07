"""Guards + behaviour for scripts/wipe_all_runs.py (all-org run wipe).

The script is destructive by design, so the tests pin the safety rails
(dry-run is a no-op, refuses the source tree / unset DATA_DIR) and confirm a
real wipe removes run data while leaving org/brand config alone.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "wipe_all_runs.py"


def _load():
    spec = importlib.util.spec_from_file_location("wipe_all_runs", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed(data: Path) -> None:
    (data / "runs_v4").mkdir(parents=True)
    (data / "uploads_v4").mkdir(parents=True)
    (data / "brand_kits").mkdir(parents=True)
    (data / "runs_v4" / "r1.json").write_text('{"profile_id":"orgA","status":"done"}')
    (data / "runs_v4" / "r1").mkdir()
    (data / "runs_v4" / "r1" / "card.png").write_text("png")
    (data / "uploads_v4" / "meet.hy3").write_text("x")
    (data / "brand_kits" / "orgA.json").write_text("brand")  # must survive
    conn = sqlite3.connect(str(data / "data.db"))
    conn.execute("CREATE TABLE runs(id TEXT, profile_id TEXT, status TEXT)")
    conn.execute("CREATE TABLE card_reactions(run_id TEXT)")
    conn.execute("INSERT INTO runs VALUES('r1','orgA','done')")
    conn.commit()
    conn.close()


def test_refuses_unset_data_dir(monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    mod = _load()
    with pytest.raises(SystemExit):
        mod.main([])


def test_refuses_source_tree(monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(_REPO / "src"))
    mod = _load()
    with pytest.raises(SystemExit):
        mod.main([])


def test_dry_run_deletes_nothing(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _seed(data)
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.delenv("RUNS_DIR", raising=False)
    monkeypatch.delenv("UPLOADS_DIR", raising=False)
    assert _load().main([]) == 0
    assert (data / "runs_v4" / "r1.json").exists()
    n = sqlite3.connect(str(data / "data.db")).execute("SELECT count(*) FROM runs").fetchone()[0]
    assert n == 1


def test_yes_wipes_runs_but_keeps_brand(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _seed(data)
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.delenv("RUNS_DIR", raising=False)
    monkeypatch.delenv("UPLOADS_DIR", raising=False)
    assert _load().main(["--yes"]) == 0
    # run data gone
    assert list((data / "runs_v4").glob("*")) == []
    assert list((data / "uploads_v4").glob("*")) == []
    n = sqlite3.connect(str(data / "data.db")).execute("SELECT count(*) FROM runs").fetchone()[0]
    assert n == 0
    # org/brand config preserved
    assert (data / "brand_kits" / "orgA.json").read_text() == "brand"


def test_keep_uploads_flag(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _seed(data)
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.delenv("RUNS_DIR", raising=False)
    monkeypatch.delenv("UPLOADS_DIR", raising=False)
    assert _load().main(["--yes", "--keep-uploads"]) == 0
    assert (data / "uploads_v4" / "meet.hy3").exists()  # preserved
    assert list((data / "runs_v4").glob("*")) == []  # runs still gone


if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))
