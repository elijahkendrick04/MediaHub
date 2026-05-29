"""Handover protocol — the link between the builder loop and the testing loop.

When the builder finishes a roadmap item it writes a handover record. The
constant testing loop reads pending handovers, interprets them *against the
roadmap intent*, tests the change, and resolves each one (done / blocked) with
its verdict. This is the shared context channel the two loops use to stay
coordinated; the records are tracked so they double as an audit trail.

  autotest/handover/pending/<id>-<ts>.json   awaiting test
  autotest/handover/done/<id>-<ts>.json      tested OK → roadmap marked done
  autotest/handover/blocked/<id>-<ts>.json   regressed/failed → reverted/blocked
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

HANDOVER_DIR = Path(__file__).resolve().parent / "handover"
PENDING = HANDOVER_DIR / "pending"
DONE = HANDOVER_DIR / "done"
BLOCKED = HANDOVER_DIR / "blocked"


def _ts() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def write(record: dict[str, Any]) -> Path:
    """Persist a builder→tester handover. ``record`` must include item_id,
    title, intent, summary, files_changed, branch, merge_target,
    acceptance_criteria."""
    PENDING.mkdir(parents=True, exist_ok=True)
    record.setdefault("created_at", _ts())
    record.setdefault("status", "awaiting-test")
    path = PENDING / f"{record['item_id'].replace(' ', '_')}-{record['created_at']}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


def pending() -> list[tuple[Path, dict[str, Any]]]:
    if not PENDING.exists():
        return []
    out = []
    for p in sorted(PENDING.glob("*.json")):
        try:
            out.append((p, json.loads(p.read_text(encoding="utf-8"))))
        except (ValueError, OSError):
            continue
    return out


def resolve(path: Path, verdict: str, details: dict[str, Any]) -> Path:
    """Move a pending handover to done/ or blocked/ with the tester's verdict."""
    dest_dir = DONE if verdict == "done" else BLOCKED
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        record = {}
    record["status"] = verdict
    record["tested_at"] = _ts()
    record["verdict"] = details
    dest = dest_dir / path.name
    dest.write_text(json.dumps(record, indent=2), encoding="utf-8")
    try:
        path.unlink()
    except OSError:
        pass
    return dest
