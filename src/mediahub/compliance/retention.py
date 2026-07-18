"""Retention schedule + purge job (storage limitation, Art 5(1)(e)).

In plain words: nothing should live forever by accident. Every artifact
class has a retention window — configurable globally by env var and
per tenant on the club profile — and a daily scheduled job deletes what
has aged out, reporting what it removed.

Artifact classes and defaults (conservative; sign-off tracked as Q8 in
docs/compliance/OPEN_LEGAL_QUESTIONS.md):

| class          | what                                              | env var                              | default |
|----------------|---------------------------------------------------|--------------------------------------|---------|
| ``raw_uploads``| original uploaded results files                   | MEDIAHUB_RETENTION_RAW_UPLOAD_DAYS   | 180     |
| ``runs``       | parsed runs + rendered cards + workflow + packs   | MEDIAHUB_RETENTION_RUN_DAYS          | 730     |
| ``pb_caches``  | PB lookup caches incl. raw search HTML            | MEDIAHUB_RETENTION_PB_CACHE_DAYS     | 30      |
| ``security_log``| security/accountability events                   | MEDIAHUB_RETENTION_SECURITY_LOG_DAYS | 365     |

Deliberately NOT purged: the complaints/incidents/DSR/consent ledgers and
the autonomy audit ledger — they are accountability records (Art 5(2),
Art 33(5)); their retention is a legal-judgment question, not a default.

A value of ``0`` disables purging for that class (keep forever) — explicit,
visible in config, never silent.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from mediahub._atomic_io import atomic_write_text

log = logging.getLogger(__name__)

DEFAULTS = {
    "raw_uploads": 180,
    "runs": 730,
    "pb_caches": 30,
    "security_log": 365,
}

_ENV_VARS = {
    "raw_uploads": "MEDIAHUB_RETENTION_RAW_UPLOAD_DAYS",
    "runs": "MEDIAHUB_RETENTION_RUN_DAYS",
    "pb_caches": "MEDIAHUB_RETENTION_PB_CACHE_DAYS",
    "security_log": "MEDIAHUB_RETENTION_SECURITY_LOG_DAYS",
}


def _data_dir() -> Path:
    src_root = Path(__file__).resolve().parents[1]
    return Path(os.environ.get("DATA_DIR", str(src_root)))


def _runs_dir() -> Path:
    return Path(os.environ.get("RUNS_DIR", str(_data_dir() / "runs_v4")))


def _uploads_dir() -> Path:
    return Path(os.environ.get("UPLOADS_DIR", str(_data_dir() / "uploads_v4")))


def global_days(artifact_class: str) -> int:
    """Deployment-wide retention window in days (0 = keep forever)."""
    default = DEFAULTS[artifact_class]
    raw = os.environ.get(_ENV_VARS[artifact_class], "").strip()
    try:
        days = int(raw) if raw else default
    except ValueError:
        days = default
    days = max(0, days)
    # The UK-legal baseline's single global window (MEDIAHUB_RETENTION_DAYS,
    # mediahub.privacy.retention) acts as a CEILING for the data-bearing
    # classes — whichever window is shorter wins, so the setting shown on
    # the Privacy page is always honoured.
    if artifact_class in ("runs", "raw_uploads"):
        legacy_raw = os.environ.get("MEDIAHUB_RETENTION_DAYS", "").strip()
        try:
            legacy = max(0, int(legacy_raw)) if legacy_raw else 0
        except ValueError:
            legacy = 0
        if legacy:
            days = min(days, legacy) if days else legacy
    return days


def effective_days(artifact_class: str, profile_id: str = "") -> int:
    """Tenant override wins when present and SHORTER (a club can tighten
    retention, never extend it past the deployment ceiling)."""
    base = global_days(artifact_class)
    if not profile_id:
        return base
    try:
        from mediahub.web.club_profile import load_profile

        profile = load_profile(profile_id)
        overrides = getattr(profile, "retention_overrides", None) or {}
        raw = overrides.get(artifact_class)
        if raw is None or str(raw).strip() == "":
            return base
        days = max(0, int(raw))
        if base == 0:
            return days
        return min(days, base) if days else base
    except Exception:
        return base


def _age_cutoff(days: int, now: datetime) -> Optional[datetime]:
    if days <= 0:
        return None
    return now - timedelta(days=days)


def _run_timestamp(path: Path, run: dict) -> datetime:
    for key in ("finished_at", "created_at"):
        raw = run.get(key) or ""
        if raw:
            try:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def run_purge(
    delete_run: Optional[Callable[[str], None]] = None,
    *,
    now: Optional[datetime] = None,
) -> dict:
    """Apply the retention schedule once. Idempotent; returns a report.

    ``delete_run`` is web.py's ``_delete_run`` (cascades run JSON, sidecar
    visuals, workflow, packs, DB row, in-memory cache). Without it, runs
    are purged with a filesystem-level fallback covering the same stores.
    """
    now = now or datetime.now(timezone.utc)
    report: dict = {
        "ran_at": now.replace(microsecond=0).isoformat(),
        "runs_deleted": [],
        "upload_dirs_deleted": [],
        "upload_files_deleted": 0,
        "pb_cache_files_deleted": 0,
        "security_log_lines_dropped": 0,
        "errors": [],
    }

    # 1. Runs (per-tenant windows).
    runs_dir = _runs_dir()
    if runs_dir.exists():
        for path in sorted(runs_dir.glob("*.json")):
            if "__" in path.name:
                # Per-run sidecar files (<run_id>__workflow.json, __approvals.json,
                # __pronunciations.json, ...) are swept with their run below and
                # must never be parsed as run files of their own.
                continue
            try:
                run = json.loads(path.read_text())
            except Exception:
                continue
            run_id = str(run.get("run_id") or path.stem)
            days = effective_days("runs", str(run.get("profile_id") or ""))
            cutoff = _age_cutoff(days, now)
            if cutoff is None or _run_timestamp(path, run) >= cutoff:
                continue
            try:
                if delete_run is not None:
                    delete_run(run_id)
                else:
                    _delete_run_fallback(run_id, path)
                report["runs_deleted"].append(run_id)
            except Exception as e:
                report["errors"].append(f"run {run_id}: {e}")

    # 2. Raw uploads (shorter window; also catches dirs orphaned of their run).
    uploads = _uploads_dir()
    if uploads.exists():
        for d in sorted(uploads.iterdir()):
            if d.name == "media_library":
                continue
            if not d.is_dir():
                # Loose transient files written straight into uploads_v4
                # (legacy path) carry no run or tenant hint — age them on
                # the global raw-uploads window.
                cutoff = _age_cutoff(global_days("raw_uploads"), now)
                if cutoff is None:
                    continue
                try:
                    if datetime.fromtimestamp(d.stat().st_mtime, tz=timezone.utc) < cutoff:
                        d.unlink()
                        report["upload_files_deleted"] += 1
                except OSError as e:
                    report["errors"].append(f"uploads {d.name}: {e}")
                continue
            profile_id = ""
            run_path = _runs_dir() / f"{d.name}.json"
            if run_path.exists():
                try:
                    profile_id = str(json.loads(run_path.read_text()).get("profile_id") or "")
                except Exception:
                    pass
            days = effective_days("raw_uploads", profile_id)
            cutoff = _age_cutoff(days, now)
            if cutoff is None:
                continue
            newest = max(
                (f.stat().st_mtime for f in d.rglob("*") if f.is_file()),
                default=d.stat().st_mtime,
            )
            if datetime.fromtimestamp(newest, tz=timezone.utc) < cutoff:
                try:
                    shutil.rmtree(d)
                    report["upload_dirs_deleted"].append(d.name)
                except OSError as e:
                    report["errors"].append(f"uploads {d.name}: {e}")

    # 3. PB caches (global window — the warm cache is not tenant-attributable).
    days = global_days("pb_caches")
    cutoff = _age_cutoff(days, now)
    if cutoff is not None:
        roots = [
            _data_dir() / "data" / "discovered",
            _data_dir() / "discovered",
            _data_dir() / ".cache" / "pb_lookup",
            _data_dir() / ".cache" / "swimmingresults",
        ]
        for root in roots:
            if not root.exists():
                continue
            for f in root.rglob("*.json"):
                try:
                    if datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc) < cutoff:
                        f.unlink()
                        report["pb_cache_files_deleted"] += 1
                except OSError:
                    continue

    # 4. Security log (rewrite, dropping aged lines).
    days = global_days("security_log")
    cutoff = _age_cutoff(days, now)
    log_path = _data_dir() / "security_log" / "events.jsonl"
    if cutoff is not None and log_path.exists():
        # Hold the security-log lock across read→filter→write so a concurrent
        # record_event() append isn't dropped, and rewrite atomically so a crash
        # can't lose the whole log. record_event() is called AFTER this block, so
        # holding its (non-reentrant) lock only here can't deadlock.
        from .security_log import _LOCK as _sec_lock  # noqa: PLC0415

        with _sec_lock:
            kept, dropped = [], 0
            for line in log_path.read_text(encoding="utf-8").splitlines():
                try:
                    ts = datetime.fromisoformat(json.loads(line).get("ts", ""))
                    # A naive timestamp is UTC; comparing it to the aware cutoff
                    # must not raise (which used to abort the whole purge) — do the
                    # comparison INSIDE the try so a bad/naive line just survives.
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    aged = ts < cutoff
                except Exception:
                    kept.append(line)
                    continue
                if aged:
                    dropped += 1
                else:
                    kept.append(line)
            if dropped:
                atomic_write_text(log_path, "\n".join(kept) + ("\n" if kept else ""))
                report["security_log_lines_dropped"] = dropped

    try:
        from .security_log import record_event

        record_event(
            "retention_purge",
            detail=(
                f"runs={len(report['runs_deleted'])} uploads={len(report['upload_dirs_deleted'])} "
                f"pb_cache_files={report['pb_cache_files_deleted']} "
                f"log_lines={report['security_log_lines_dropped']} errors={len(report['errors'])}"
            ),
        )
    except Exception:
        pass
    return report


def _delete_run_fallback(run_id: str, json_path: Path) -> None:
    """Filesystem cascade matching web._delete_run for scheduler-only contexts."""
    json_path.unlink(missing_ok=True)
    shutil.rmtree(json_path.parent / run_id, ignore_errors=True)
    # Sweep the whole <run_id>__* sidecar family (workflow store, approvals
    # ledger with approver emails + .lock/.corrupt companions, pronunciation
    # map with athlete names) so no personal data outlives the erasure —
    # mirrors web._delete_run.
    if run_id:
        import glob as _glob  # noqa: PLC0415

        for side in json_path.parent.glob(f"{_glob.escape(run_id)}__*"):
            try:
                side.unlink()
            except OSError:
                pass
    shutil.rmtree(_data_dir() / "turn_into_packs" / run_id, ignore_errors=True)
    shutil.rmtree(_uploads_dir() / run_id, ignore_errors=True)
    try:
        import sqlite3

        db = _data_dir() / "data.db"
        if db.exists():
            conn = sqlite3.connect(db)
            try:
                conn.execute("DELETE FROM runs WHERE id=?", (run_id,))
                conn.commit()
            finally:
                conn.close()
    except Exception:
        pass
