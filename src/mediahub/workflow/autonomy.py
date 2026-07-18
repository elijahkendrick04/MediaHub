"""mediahub/workflow/autonomy.py — append-only audit ledger for the autonomy runner.

The bounded autonomy runner can take several steps on a club's behalf before a
human sees anything, so the council made an immutable, per-organisation audit
trail a first-class requirement: a committee member must be able to reconstruct
exactly what the system did to their content. Every session start, every tool
call (and every BLOCKED call), and the final summary are appended here — one
JSON object per line, never mutated or deleted.

Storage is a per-org JSONL file under ``DATA_DIR/autonomy_audit/<org>.jsonl``.
The org id is sanitised to a safe filename (it is operator/club data, never a
path), so it can never escape the audit directory.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")
_LOCK = threading.Lock()
_MAX_FIELD = 2000  # cap any single recorded value so the log can't balloon


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_org(org_id: str) -> str:
    """Sanitise an org id into a filename that cannot escape the audit dir."""
    s = _SAFE.sub("_", (org_id or "unknown").strip()) or "unknown"
    return s[:120]


def _audit_dir() -> Path:
    # Resolved per call (not frozen at import) so the ledger always follows
    # the live DATA_DIR — the audit trail must land where the data lives.
    base = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))
    d = base / "autonomy_audit"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _truncate(value):
    """Bound recorded values; coerce non-JSON-able args to a short repr."""
    try:
        s = value if isinstance(value, str) else json.dumps(value, default=str)
    except Exception:
        s = str(value)
    return s if len(s) <= _MAX_FIELD else s[:_MAX_FIELD] + "…"


def _safe_args(args: Optional[dict]):
    """Args exactly when their JSON form fits the cap; a marker dict otherwise.

    Truncating the *serialised* JSON and re-parsing it (the previous approach)
    raised on any oversized payload — which would have crashed the very
    operation being audited — and could write an unparseable line. Here the
    audit line is always valid JSON and assembling it can never raise.
    """
    if not args:
        return {}
    try:
        s = json.dumps(args, default=str)
    except Exception:
        return {"_unserialisable": str(args)[:_MAX_FIELD]}
    if len(s) <= _MAX_FIELD:
        try:
            return json.loads(s)  # normalised copy (default=str applied)
        except Exception:  # pragma: no cover - dumps output always parses
            return {"_unserialisable": s[:_MAX_FIELD]}
    return {"_truncated": s[:_MAX_FIELD] + "…"}


class AuditLog:
    """Append-only, per-org JSONL audit trail. Best-effort: a logging failure
    must never break (or, worse, silently abort) the runner — but a write that
    DOES happen is immutable."""

    def __init__(self, base_dir: Optional[Path] = None):
        self._dir = Path(base_dir) if base_dir is not None else None

    def _path(self, org_id: str) -> Path:
        base = self._dir if self._dir is not None else _audit_dir()
        base.mkdir(parents=True, exist_ok=True)
        return base / f"{_safe_org(org_id)}.jsonl"

    def record(
        self,
        org_id: str,
        session_id: str,
        kind: str,
        *,
        tool: str = "",
        args: Optional[dict] = None,
        result: str = "",
        level: Optional[int] = None,
    ) -> None:
        """Append one immutable audit line. ``kind`` is e.g. ``session_start`` |
        ``tool_call`` | ``blocked`` | ``summary`` | ``error``."""
        entry = {
            "ts": _now(),
            "org_id": org_id,
            "session_id": session_id,
            "kind": kind,
            "tool": tool,
            "args": _safe_args(args),
            "result": _truncate(result),
        }
        if level is not None:
            entry["level"] = int(level)
        try:
            line = json.dumps(entry, default=str)
        except Exception:
            line = json.dumps(
                {"ts": _now(), "org_id": org_id, "session_id": session_id, "kind": "error"}
            )
        try:
            with _LOCK:
                with open(self._path(org_id), "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except Exception as exc:
            # Never let auditing break the run — but a lost audit write (read-only
            # FS / full disk) must not be fully silent, or the "immutable audit
            # trail" degrades with no signal.
            log.warning("autonomy audit write failed for org %s: %s", org_id, exc)

    def read(self, org_id: str, *, limit: int = 200) -> list[dict]:
        """Read recent audit entries for an org (oldest→newest within the tail)."""
        # limit<=0 means "no rows"; guard before the slice so limit=0 doesn't
        # become lines[0:] (everything) — the opposite of the intent.
        if limit <= 0:
            return []
        path = self._path(org_id)
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
        out = []
        for ln in lines[-int(limit) :]:
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
        return out


__all__ = ["AuditLog"]
