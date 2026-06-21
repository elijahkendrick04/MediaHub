"""bulk.store — persist bulk-generation jobs under DATA_DIR (roadmap 1.13).

Jobs are small JSON records kept under ``DATA_DIR/bulk_jobs/``. Each carries its
owning ``profile_id``, and every read is access-checked against the caller's org
so one club can never see another's job (the tenant rule).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .models import BulkJob


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))


def _jobs_dir(jobs_dir: Optional[Path] = None) -> Path:
    if jobs_dir is not None:
        return Path(jobs_dir)
    return _data_dir() / "bulk_jobs"


def save_job(job: BulkJob, *, jobs_dir: Optional[Path] = None) -> None:
    base = _jobs_dir(jobs_dir)
    base.mkdir(parents=True, exist_ok=True)
    job.touch()
    (base / f"{job.job_id}.json").write_text(json.dumps(job.to_dict(), indent=2), encoding="utf-8")


def load_job(profile_id: str, job_id: str, *, jobs_dir: Optional[Path] = None) -> Optional[BulkJob]:
    path = _jobs_dir(jobs_dir) / f"{job_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    job = BulkJob.from_dict(data)
    if profile_id and job.profile_id and job.profile_id != profile_id:
        return None  # tenant isolation
    return job


def list_jobs(profile_id: str, *, jobs_dir: Optional[Path] = None, limit: int = 50) -> list[dict]:
    base = _jobs_dir(jobs_dir)
    if not base.exists():
        return []
    files = sorted(base.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict] = []
    for p in files:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("profile_id") != profile_id:
            continue
        job = BulkJob.from_dict(data)
        out.append(
            {
                "job_id": job.job_id,
                "title": job.title,
                "run_id": job.run_id,
                "format_slug": job.format_slug,
                "status": job.status,
                "created_at": job.created_at,
                **job.progress(),
            }
        )
        if len(out) >= limit:
            break
    return out


def delete_job(profile_id: str, job_id: str, *, jobs_dir: Optional[Path] = None) -> bool:
    job = load_job(profile_id, job_id, jobs_dir=jobs_dir)
    if job is None:
        return False
    try:
        (_jobs_dir(jobs_dir) / f"{job_id}.json").unlink()
        return True
    except OSError:
        return False


__all__ = ["save_job", "load_job", "list_jobs", "delete_job"]
