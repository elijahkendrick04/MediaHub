"""mediahub/log_sentinel/state.py — sentinel persistence under DATA_DIR.

Everything the sentinel remembers lives in ``DATA_DIR/log_sentinel/``:

* ``state.json``   — the log cursor, per-issue notify/action timestamps, and the
                     daily action counter (survives restarts on the persistent disk,
                     so a sentinel-triggered restart can't forget its own caps).
* ``audit.jsonl``  — append-only ledger: every finding, every notification, every
                     action attempt with its outcome. The explainability trail.
* ``status.json``  — last-poll snapshot consumed by ``/healthz/sentinel`` and the
                     CLI ``status`` command.
* ``leader.json``  — heartbeat lockfile so exactly one gunicorn worker polls.

Plain JSON on purpose: tiny write volume, human-inspectable, no schema to migrate.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

AUDIT_MAX_BYTES = 5 * 1024 * 1024  # rotate to .1 beyond this; two files max


def state_dir(data_dir: Optional[str] = None) -> Path:
    base = Path(data_dir) if data_dir is not None else Path(os.environ.get("DATA_DIR", "data"))
    p = base / "log_sentinel"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- state (cursor + memory + caps) ------------------------------------------


def load_state(data_dir: Optional[str] = None) -> dict:
    return _read_json(state_dir(data_dir) / "state.json")


def save_state(state: dict, data_dir: Optional[str] = None) -> None:
    _write_json(state_dir(data_dir) / "state.json", state)


def issue_memory(state: dict, issue_id: str) -> dict:
    return dict((state.get("issues") or {}).get(issue_id) or {})


def remember_issue(state: dict, issue_id: str, **fields) -> None:
    issues = state.setdefault("issues", {})
    mem = issues.setdefault(issue_id, {})
    mem.update(fields)


def actions_today(state: dict) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rec = state.get("actions") or {}
    return int(rec.get("count") or 0) if rec.get("date") == today else 0


def record_action(state: dict) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rec = state.get("actions") or {}
    count = int(rec.get("count") or 0) if rec.get("date") == today else 0
    state["actions"] = {"date": today, "count": count + 1}


# --- audit ledger -------------------------------------------------------------


def append_audit(entry: dict, data_dir: Optional[str] = None) -> None:
    """Append one audit line; rotate once at AUDIT_MAX_BYTES (keep .1).

    Best-effort: a failed audit write — e.g. ``ENOSPC``, which happens exactly
    when the ``disk_full`` detector fires — must NOT abort the sentinel cycle
    before the operator notification is sent, so write failures are swallowed and
    logged rather than raised.
    """
    try:
        path = state_dir(data_dir) / "audit.jsonl"
        if path.exists() and path.stat().st_size > AUDIT_MAX_BYTES:
            path.replace(path.with_suffix(".jsonl.1"))
        record = {"ts": _utc_now_iso(), **entry}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError as exc:
        log.warning("log_sentinel: audit write failed (%s); continuing to notify", exc)


def read_audit_tail(n: int = 50, data_dir: Optional[str] = None) -> list[dict]:
    path = state_dir(data_dir) / "audit.jsonl"
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[-max(1, n) :]:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        return []
    return out


# --- status snapshot ------------------------------------------------------------


def write_status(snapshot: dict, data_dir: Optional[str] = None) -> None:
    _write_json(state_dir(data_dir) / "status.json", {"ts": _utc_now_iso(), **snapshot})


def read_status(data_dir: Optional[str] = None) -> dict:
    return _read_json(state_dir(data_dir) / "status.json")


# --- leader lock (one poller across gunicorn workers) ---------------------------


def acquire_leader(worker_id: str, ttl: float, data_dir: Optional[str] = None) -> bool:
    """Take or refresh the leader lock. True iff this worker is the leader.

    The lock is a heartbeat file: the holder rewrites it each tick; any other
    worker may take over once the heartbeat is older than ``ttl`` (covers the
    holder dying mid-flight, e.g. gunicorn max-requests recycling)."""
    from mediahub._atomic_io import cross_process_lock  # noqa: PLC0415

    d = state_dir(data_dir)
    path = d / "leader.json"
    now = time.time()
    # Hold a cross-process lock across the whole read→decide→write so two workers
    # can't interleave and BOTH pass the read-back for one tick (duplicate polls /
    # notifications). Falls back to the write+read-back on a non-POSIX box.
    with cross_process_lock(d / "leader.lock"):
        current = _read_json(path)
        holder = str(current.get("worker") or "")
        beat = float(current.get("ts") or 0.0)
        if holder and holder != worker_id and (now - beat) < ttl:
            return False
        _write_json(path, {"worker": worker_id, "ts": now})
        # Read-back still settles near-simultaneous claims on a box without
        # fcntl (where the lock is a no-op): last writer wins, the loser stands
        # down until the next tick.
        return str(_read_json(path).get("worker") or "") == worker_id


def release_leader(worker_id: str, data_dir: Optional[str] = None) -> None:
    path = state_dir(data_dir) / "leader.json"
    if str(_read_json(path).get("worker") or "") == worker_id:
        try:
            path.unlink()
        except Exception:
            pass


__all__ = [
    "state_dir",
    "load_state",
    "save_state",
    "issue_memory",
    "remember_issue",
    "actions_today",
    "record_action",
    "append_audit",
    "read_audit_tail",
    "write_status",
    "read_status",
    "acquire_leader",
    "release_leader",
]
