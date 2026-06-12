"""Retention enforcement — scheduled deletion of expired runs and uploads.

``MEDIAHUB_RETENTION_DAYS`` (unset or 0 = disabled) is the deployment-wide
retention period for runs, their uploads and generated packs. When enabled,
a daily scheduler task deletes anything older than the period **through the
run-deletion path**, so the full erasure cascade (PB caches, caption memory,
posting-log excerpts, motion cache) applies to every aged-out run — exactly
what the Privacy Notice §8 promises.

Ages are measured from the run JSON's file mtime (robust to DB drift and
covers runs whose DB row was lost); loose upload files age the same way.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)


def retention_days() -> int:
    """The configured retention period in days; 0 = retention disabled."""
    raw = (os.environ.get("MEDIAHUB_RETENTION_DAYS") or "").strip()
    try:
        return max(0, int(raw)) if raw else 0
    except ValueError:
        return 0


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "data"))


def sweep_expired(delete_run: Callable[[str], bool], *, now: float | None = None) -> dict:
    """Delete runs and upload files older than the retention period.

    ``delete_run`` is web.py's ``_delete_run`` (DB row + files + cascade).
    Returns counts; never raises — one bad file must not stop the sweep.
    """
    days = retention_days()
    report = {"enabled": days > 0, "days": days, "runs_deleted": 0, "uploads_deleted": 0}
    if days <= 0:
        return report
    cutoff = (now if now is not None else time.time()) - days * 86400

    runs_dir = _data_dir() / "runs_v4"
    if runs_dir.exists():
        for run_file in sorted(runs_dir.glob("*.json")):
            # Workflow sidecars (<id>__workflow.json) ride along with their run.
            if "__" in run_file.stem:
                continue
            try:
                if run_file.stat().st_mtime >= cutoff:
                    continue
            except OSError:
                continue
            run_id = run_file.stem
            try:
                delete_run(run_id)
                report["runs_deleted"] += 1
            except Exception:
                log.warning("retention: failed to delete run %s", run_id, exc_info=True)

    uploads_dir = _data_dir() / "uploads_v4"
    if uploads_dir.exists():
        for item in uploads_dir.iterdir():
            try:
                if item.stat().st_mtime >= cutoff:
                    continue
                if item.is_file():
                    item.unlink()
                    report["uploads_deleted"] += 1
                elif item.is_dir():
                    import shutil

                    shutil.rmtree(item, ignore_errors=True)
                    report["uploads_deleted"] += 1
            except OSError:
                continue

    if report["runs_deleted"] or report["uploads_deleted"]:
        log.info(
            "retention sweep: deleted %d run(s), %d upload(s) older than %d days",
            report["runs_deleted"],
            report["uploads_deleted"],
            days,
        )
    return report


__all__ = ["retention_days", "sweep_expired"]
