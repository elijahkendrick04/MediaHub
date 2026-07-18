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
    # Full per-run sidecar family (approvals ledger carries approver EMAILS,
    # incl. its .lock/.corrupt companions) + one orphan sidecar whose parent
    # run predates the family sweep — the wipe must erase every one of these.
    (data / "runs_v4" / "r1__workflow.json").write_text("{}")
    (data / "runs_v4" / "r1__approvals.json").write_text('{"emails":["a@b.c"]}')
    (data / "runs_v4" / "r1__approvals.json.corrupt").write_text('{"emails":["a@b.c"]}')
    (data / "runs_v4" / "r1__approvals.lock").write_text("")
    (data / "runs_v4" / "r1__pronunciations.json").write_text('{"Aoife":"EE-fa"}')
    (data / "runs_v4" / "ghost__approvals.json").write_text('{"emails":["x@y.z"]}')
    (data / "uploads_v4" / "meet.hy3").write_text("x")
    (data / "brand_kits" / "orgA.json").write_text("brand")  # must survive
    conn = sqlite3.connect(str(data / "data.db"))
    conn.execute("CREATE TABLE runs(id TEXT, profile_id TEXT, status TEXT)")
    conn.execute("CREATE TABLE card_reactions(run_id TEXT)")
    conn.execute("INSERT INTO runs VALUES('r1','orgA','done')")
    # Same shape as content_pack_visual.visual_index.ensure_schema — the app's
    # _delete_run cascades this table, so the wipe's DB sweep must clear it too.
    conn.execute(
        "CREATE TABLE visual_index(vid TEXT PRIMARY KEY, run_id TEXT NOT NULL, "
        "brief_id TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO visual_index VALUES('vid-abc','r1','b1')")
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


def test_refuses_src_mediahub(monkeypatch):
    # web.py's *actual* fallback when DATA_DIR is unset is src/mediahub (the
    # package dir), so dev runtime data accumulates there — the guard must
    # refuse it, not just the repo root and src/.
    monkeypatch.setenv("DATA_DIR", str(_REPO / "src" / "mediahub"))
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
    conn = sqlite3.connect(str(data / "data.db"))
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM visual_index").fetchone()[0] == 1
    conn.close()


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
    conn = sqlite3.connect(str(data / "data.db"))
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    # vid→run_id index rows must not survive the wipe (parity with the app's
    # _delete_run cascade, which also clears visual_index).
    assert conn.execute("SELECT count(*) FROM visual_index").fetchone()[0] == 0
    conn.close()
    # org/brand config preserved
    assert (data / "brand_kits" / "orgA.json").read_text() == "brand"


def test_sidecars_never_enumerated_and_fully_wiped(tmp_path, monkeypatch, capsys):
    """Sidecar files must not inflate the run count as phantom run ids, and
    the wipe must leave runs_v4 with no <id>__* file at all — the whole
    family (.lock/.corrupt included) plus orphans from pre-sweep deletions."""
    data = tmp_path / "data"
    _seed(data)
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.delenv("RUNS_DIR", raising=False)
    monkeypatch.delenv("UPLOADS_DIR", raising=False)
    assert _load().main(["--yes"]) == 0
    out = capsys.readouterr().out
    assert "runs found  : 1 " in out  # r1 only; sidecars are not phantom runs
    assert "removed 1 run(s)" in out
    assert list((data / "runs_v4").glob("*__*")) == []
    assert list((data / "runs_v4").glob("*")) == []


def test_keep_uploads_flag(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _seed(data)
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.delenv("RUNS_DIR", raising=False)
    monkeypatch.delenv("UPLOADS_DIR", raising=False)
    assert _load().main(["--yes", "--keep-uploads"]) == 0
    assert (data / "uploads_v4" / "meet.hy3").exists()  # preserved
    assert list((data / "runs_v4").glob("*")) == []  # runs still gone


def test_preflight_refuses_wrong_data_dir(tmp_path, monkeypatch, capsys):
    # Reproduce the real footgun: DATA_DIR points somewhere with no data.db,
    # while RUNS_DIR still points at the disk that holds the runs. The wipe
    # must REFUSE rather than delete the run files and orphan the DB.
    real = tmp_path / "real"
    _seed(real)  # data.db + runs live here
    wrong = tmp_path / "wrong"
    wrong.mkdir()
    monkeypatch.setenv("DATA_DIR", str(wrong))  # no data.db here
    monkeypatch.setenv("RUNS_DIR", str(real / "runs_v4"))  # runs still reachable
    monkeypatch.delenv("UPLOADS_DIR", raising=False)
    rc = _load().main(["--yes"])
    assert rc == 2, "must refuse a DATA_DIR with no data.db"
    assert "Refusing to run" in capsys.readouterr().out
    # Nothing deleted: the real run files survive the refusal.
    assert (real / "runs_v4" / "r1.json").exists()


def test_force_overrides_preflight(tmp_path, monkeypatch):
    real = tmp_path / "real"
    _seed(real)
    wrong = tmp_path / "wrong"
    wrong.mkdir()
    monkeypatch.setenv("DATA_DIR", str(wrong))
    monkeypatch.setenv("RUNS_DIR", str(real / "runs_v4"))
    monkeypatch.delenv("UPLOADS_DIR", raising=False)
    # --force overrides the refusal and proceeds (exit is not the refuse-2),
    # deleting the reachable run files.
    rc = _load().main(["--yes", "--force"])
    assert rc != 2
    assert not (real / "runs_v4" / "r1.json").exists()


def test_dry_run_flags_preflight_issue(tmp_path, monkeypatch):
    wrong = tmp_path / "wrong"
    wrong.mkdir()  # writable but no data.db
    monkeypatch.setenv("DATA_DIR", str(wrong))
    monkeypatch.setenv("RUNS_DIR", str(wrong / "runs_v4"))
    monkeypatch.delenv("UPLOADS_DIR", raising=False)
    assert _load().main([]) == 2  # dry run surfaces the blocking issue


if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))
