"""Scheduled DATA_DIR backup + rehearsed restore (PC.14).

An unrestored backup is a hypothesis — this module is both halves:

- :func:`create_backup` zips the stores a recovery actually needs (the
  SQLite databases via the online backup API for a consistent snapshot,
  every root JSONL ledger, club profiles + logos, the commercial ledgers,
  sponsor + autonomy-audit ledgers, and the runs' JSON + workflow states)
  into ``mediahub-backup-<utc>.zip`` under the backup directory, prunes old
  archives, and optionally pushes the archive off-site with a plain HTTP
  PUT.
- :func:`restore_backup` rebuilds a DATA_DIR from such an archive — the
  drill rehearsed by ``tests/test_backup_restore.py`` on every run and by
  ``python -m mediahub.backup restore`` for a human.

Deliberately excluded (recorded in each archive's manifest): rendered
outputs and caches (motion cache, visuals — re-derivable from runs),
upload temp files, and the demo sandbox. The Render disk snapshot covers
whole-disk recovery; this archive is the *portable, off-site* layer.

Configuration (all optional — unconfigured = feature off, honestly):

    MEDIAHUB_BACKUP_DIR          where archives land (default DATA_DIR/backups
                                 — set a mounted/remote path for true off-site)
    MEDIAHUB_BACKUP_KEEP         archives to keep locally (default 14)
    MEDIAHUB_BACKUP_UPLOAD_URL   optional HTTP(S) endpoint; each archive is
                                 PUT there as application/zip
    MEDIAHUB_BACKUP_UPLOAD_TOKEN optional Bearer token for the PUT
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

DEFAULT_KEEP = 14

# Directories copied wholesale (relative to DATA_DIR).
_DIR_SECTIONS = (
    "club_profiles",
    "club_logos",
    "commercial",
    "sponsors",
    "autonomy_audit",
)

# SQLite databases snapshotted via the online backup API.
_DB_FILES = ("data.db", "memory.db")


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "data"))


def backup_dir() -> Path:
    raw = (os.environ.get("MEDIAHUB_BACKUP_DIR") or "").strip()
    return Path(raw) if raw else _data_dir() / "backups"


def backup_enabled() -> bool:
    """The scheduled sweep runs only when the operator opted in by setting
    a backup directory or an off-site upload URL."""
    return bool(
        (os.environ.get("MEDIAHUB_BACKUP_DIR") or "").strip()
        or (os.environ.get("MEDIAHUB_BACKUP_UPLOAD_URL") or "").strip()
    )


def _keep() -> int:
    raw = (os.environ.get("MEDIAHUB_BACKUP_KEEP") or "").strip()
    try:
        return max(1, int(raw)) if raw else DEFAULT_KEEP
    except ValueError:
        return DEFAULT_KEEP


def _snapshot_sqlite(src: Path, dest: Path) -> bool:
    """Copy a SQLite DB consistently even while the app writes to it."""
    try:
        with sqlite3.connect(str(src), timeout=10.0) as conn, sqlite3.connect(
            str(dest)
        ) as out:
            conn.backup(out)
        return True
    except sqlite3.Error as exc:
        log.warning("backup: sqlite snapshot of %s failed: %s", src.name, exc)
        return False


def create_backup(dest_dir: Optional[Path] = None) -> dict:
    """Write one backup archive. Returns a report incl. the archive path."""
    data_dir = _data_dir()
    out_dir = Path(dest_dir) if dest_dir is not None else backup_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive = out_dir / f"mediahub-backup-{stamp}.zip"

    manifest: dict = {
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "data_dir": str(data_dir),
        "databases": [],
        "ledgers": [],
        "dirs": {},
        "runs_files": 0,
        "excluded": [
            "rendered outputs and caches (motion_cache, visuals — re-derivable)",
            "uploads_v4 temp files",
            "demo_try sandbox state",
            "backups/ itself",
        ],
    }

    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1. Consistent SQLite snapshots.
        for db_name in _DB_FILES:
            src = data_dir / db_name
            if not src.exists():
                continue
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                if _snapshot_sqlite(src, tmp_path):
                    zf.write(tmp_path, db_name)
                    manifest["databases"].append(db_name)
            finally:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

        # 2. Root JSONL ledgers (users, memberships, legal acceptances, …).
        for ledger in sorted(data_dir.glob("*.jsonl")):
            try:
                zf.write(ledger, ledger.name)
                manifest["ledgers"].append(ledger.name)
            except OSError:
                continue

        # 3. Whole directories of small, precious state.
        for section in _DIR_SECTIONS:
            d = data_dir / section
            if not d.is_dir():
                continue
            count = 0
            for f in sorted(d.rglob("*")):
                if not f.is_file():
                    continue
                try:
                    zf.write(f, str(f.relative_to(data_dir)))
                    count += 1
                except OSError:
                    continue
            if count:
                manifest["dirs"][section] = count

        # 4. Runs: the JSON + workflow states (renders re-derive from these).
        runs_dir = data_dir / "runs_v4"
        if runs_dir.is_dir():
            for f in sorted(runs_dir.glob("*.json")):
                try:
                    zf.write(f, f"runs_v4/{f.name}")
                    manifest["runs_files"] += 1
                except OSError:
                    continue

        zf.writestr("backup_manifest.json", json.dumps(manifest, indent=2))

    report = {
        "archive": str(archive),
        "bytes": archive.stat().st_size,
        "manifest": manifest,
        "pruned": _prune(out_dir),
        "uploaded": False,
        "upload_error": "",
    }

    # 5. Optional off-site push.
    url = (os.environ.get("MEDIAHUB_BACKUP_UPLOAD_URL") or "").strip()
    if url:
        ok, err = _upload(archive, url)
        report["uploaded"] = ok
        report["upload_error"] = err
    return report


def _prune(out_dir: Path) -> int:
    archives = sorted(out_dir.glob("mediahub-backup-*.zip"))
    excess = len(archives) - _keep()
    removed = 0
    for old in archives[: max(0, excess)]:
        try:
            old.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def _upload(archive: Path, url: str) -> tuple[bool, str]:
    """PUT the archive off-site. Honest result, no silent retries."""
    headers = {"Content-Type": "application/zip"}
    token = (os.environ.get("MEDIAHUB_BACKUP_UPLOAD_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    target = url.rstrip("/") + "/" + archive.name if not url.endswith(".zip") else url
    try:
        import requests  # noqa: PLC0415

        with archive.open("rb") as fh:
            r = requests.put(target, data=fh, headers=headers, timeout=120)
        if r.status_code >= 300:
            return False, f"upload returned HTTP {r.status_code}"
        return True, ""
    except Exception as exc:
        log.warning("backup: off-site upload failed: %s", exc)
        return False, str(exc)


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


def restore_backup(archive: Path, data_dir: Optional[Path] = None, *, force: bool = False) -> dict:
    """Rebuild a DATA_DIR from a backup archive.

    Refuses a non-empty target unless ``force`` — restoring over live data
    is a deliberate act. Zip members are path-checked so a crafted archive
    cannot escape the target directory.
    """
    archive = Path(archive)
    target = Path(data_dir) if data_dir is not None else _data_dir()
    target.mkdir(parents=True, exist_ok=True)
    existing = [p for p in target.iterdir() if p.name != "backups"]
    if existing and not force:
        raise RuntimeError(
            f"restore target {target} is not empty ({len(existing)} entries) — "
            "pass force=True / --force to restore over it"
        )
    restored = 0
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            name = member.filename
            if member.is_dir():
                continue
            dest = (target / name).resolve()
            if not str(dest).startswith(str(target.resolve())):
                raise RuntimeError(f"archive member escapes the target: {name!r}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, dest.open("wb") as out:
                out.write(src.read())
            restored += 1
    return {"archive": str(archive), "target": str(target), "files_restored": restored}


# ---------------------------------------------------------------------------
# Scheduler + state
# ---------------------------------------------------------------------------


def sweep(_params: Optional[dict] = None) -> dict:
    """The daily scheduler handler. No-ops (honestly logged) when the
    operator hasn't configured a backup target."""
    if not backup_enabled():
        log.info("backup sweep skipped: no MEDIAHUB_BACKUP_DIR / upload URL configured")
        return {"enabled": False}
    report = create_backup()
    _record_state(report)
    log.info(
        "backup sweep: wrote %s (%d bytes), uploaded=%s",
        report["archive"],
        report["bytes"],
        report["uploaded"],
    )
    return {"enabled": True, **report}


def _state_path() -> Path:
    return _data_dir() / "backup_state.json"


def _record_state(report: dict) -> None:
    try:
        _state_path().write_text(
            json.dumps(
                {
                    "last_backup_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "archive": report.get("archive", ""),
                    "bytes": report.get("bytes", 0),
                    "uploaded": report.get("uploaded", False),
                    "upload_error": report.get("upload_error", ""),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        log.warning("backup: could not record state", exc_info=True)


def last_backup_state() -> Optional[dict]:
    p = _state_path()
    if not p.exists():
        return None
    try:
        loaded = json.loads(p.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


__all__ = [
    "backup_dir",
    "backup_enabled",
    "create_backup",
    "last_backup_state",
    "restore_backup",
    "sweep",
]
