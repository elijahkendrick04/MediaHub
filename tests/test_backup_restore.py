"""PC.14 — the backup + restore drill, rehearsed on every test run.

An unrestored backup is a hypothesis: this suite creates real stores,
backs them up, restores into a FRESH directory and verifies the contents
— the automated half of docs/SUPPORT_INCIDENT_RUNBOOK.md §4.
"""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from mediahub import backup as bk


@pytest.fixture
def data_world(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.delenv("MEDIAHUB_BACKUP_DIR", raising=False)
    monkeypatch.delenv("MEDIAHUB_BACKUP_UPLOAD_URL", raising=False)

    # A live SQLite DB…
    conn = sqlite3.connect(data / "data.db")
    conn.execute("CREATE TABLE runs (id TEXT PRIMARY KEY, profile_id TEXT)")
    conn.execute("INSERT INTO runs VALUES ('run-1', 'org-a')")
    conn.commit()
    conn.close()
    # …root ledgers…
    (data / "users.jsonl").write_text(json.dumps({"email": "a@b.co"}) + "\n")
    (data / "memberships.jsonl").write_text(json.dumps({"email": "a@b.co"}) + "\n")
    # …directory sections…
    (data / "club_profiles").mkdir()
    (data / "club_profiles" / "org-a.json").write_text(json.dumps({"profile_id": "org-a"}))
    (data / "commercial").mkdir()
    (data / "commercial" / "wtp_quotes.jsonl").write_text("{}\n")
    # …runs + workflow sidecars, plus things that must be EXCLUDED.
    runs = data / "runs_v4"
    runs.mkdir()
    (runs / "run-1.json").write_text(json.dumps({"run_id": "run-1"}))
    (runs / "run-1__workflow.json").write_text("{}")
    heavy = runs / "run-1"
    heavy.mkdir()
    (heavy / "render.png").write_bytes(b"\x89PNG heavy")
    (data / "motion_cache").mkdir()
    (data / "motion_cache" / "x.mp4").write_bytes(b"mp4")
    return data


def test_backup_create_contents_and_exclusions(data_world):
    report = bk.create_backup()
    archive = Path(report["archive"])
    assert archive.exists()
    assert archive.parent == data_world / "backups"  # default target
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        for expected in (
            "data.db",
            "users.jsonl",
            "memberships.jsonl",
            "club_profiles/org-a.json",
            "commercial/wtp_quotes.jsonl",
            "runs_v4/run-1.json",
            "runs_v4/run-1__workflow.json",
            "backup_manifest.json",
        ):
            assert expected in names, f"backup missing {expected}: {sorted(names)}"
        # Re-derivable heavyweight state stays out.
        assert not any("render.png" in n for n in names)
        assert not any("motion_cache" in n for n in names)
        # The DB snapshot is a working database with the row intact.
        manifest = json.loads(zf.read("backup_manifest.json"))
        assert "data.db" in manifest["databases"]


def test_restore_drill_round_trip(data_world, tmp_path):
    report = bk.create_backup()
    fresh = tmp_path / "restored"
    result = bk.restore_backup(Path(report["archive"]), fresh)
    assert result["files_restored"] >= 6

    conn = sqlite3.connect(fresh / "data.db")
    rows = conn.execute("SELECT id, profile_id FROM runs").fetchall()
    conn.close()
    assert rows == [("run-1", "org-a")]
    assert json.loads((fresh / "club_profiles" / "org-a.json").read_text()) == {
        "profile_id": "org-a"
    }
    assert (fresh / "users.jsonl").read_text().strip() == json.dumps({"email": "a@b.co"})
    assert (fresh / "runs_v4" / "run-1.json").exists()


def test_restore_refuses_non_empty_target_without_force(data_world, tmp_path):
    report = bk.create_backup()
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "something.txt").write_text("live data")
    with pytest.raises(RuntimeError):
        bk.restore_backup(Path(report["archive"]), occupied)
    # force=True restores over it deliberately.
    result = bk.restore_backup(Path(report["archive"]), occupied, force=True)
    assert result["files_restored"] >= 6


def test_restore_blocks_path_traversal(data_world, tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../outside.txt", "escape")
    with pytest.raises(RuntimeError):
        bk.restore_backup(evil, tmp_path / "victim")
    assert not (tmp_path / "outside.txt").exists()


def test_prune_keeps_newest(data_world, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_BACKUP_KEEP", "2")
    out = bk.backup_dir()
    out.mkdir(parents=True, exist_ok=True)
    for stamp in ("20260101-000000", "20260102-000000", "20260103-000000"):
        (out / f"mediahub-backup-{stamp}.zip").write_bytes(b"old")
    report = bk.create_backup()
    archives = sorted(p.name for p in out.glob("mediahub-backup-*.zip"))
    assert len(archives) == 2
    assert Path(report["archive"]).name in archives


def test_sweep_honest_noop_when_unconfigured(data_world):
    assert bk.backup_enabled() is False
    assert bk.sweep() == {"enabled": False}
    assert bk.last_backup_state() is None


def test_sweep_records_state_when_configured(data_world, tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_BACKUP_DIR", str(tmp_path / "offsite"))
    result = bk.sweep()
    assert result["enabled"] is True
    state = bk.last_backup_state()
    assert state and state["archive"].startswith(str(tmp_path / "offsite"))
    assert state["uploaded"] is False  # no upload URL configured


def test_offsite_upload_put(data_world, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_BACKUP_UPLOAD_URL", "https://backup-host.example/mh/")
    monkeypatch.setenv("MEDIAHUB_BACKUP_UPLOAD_TOKEN", "tok-1")
    captured = {}

    class _Resp:
        status_code = 200

    def fake_put(url, data=None, headers=None, timeout=None):
        captured["url"] = url
        captured["auth"] = headers.get("Authorization")
        return _Resp()

    monkeypatch.setattr("requests.put", fake_put)
    report = bk.create_backup()
    assert report["uploaded"] is True
    assert captured["url"].startswith("https://backup-host.example/mh/mediahub-backup-")
    assert captured["auth"] == "Bearer tok-1"
