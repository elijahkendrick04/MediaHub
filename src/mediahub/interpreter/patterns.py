"""
patterns.py — load and extend data/patterns.jsonl.

Patterns are language-agnostic regex/heuristic records persisted as
newline-delimited JSON.  No domain vocabulary literals here.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import uuid
from typing import Any

log = logging.getLogger(__name__)


def _default_patterns_path() -> pathlib.Path:
    """Writable patterns file, derived from DATA_DIR (never the read-only
    package tree). DATA_DIR defaults to src/mediahub in dev and is the mounted
    disk on the hosted deployment, so provisional patterns persist to a
    writable location instead of ``/app/src/mediahub/data`` (read-only →
    Permission denied on flush).
    """
    env = os.environ.get("DATA_DIR")
    base = pathlib.Path(env) if env else pathlib.Path(__file__).resolve().parents[1]
    return base / "data" / "patterns.jsonl"


class PatternStore:
    """
    In-memory store backed by a JSONL file on disk.

    Each record:
        id          str   — unique pattern identifier
        type        str   — category label (e.g. "event_header", "time_value")
        pattern     str   — regex string
        description str   — human-readable note
        provisional bool  — True = awaiting human confirmation
        fires       int   — number of times matched (runtime counter, not persisted unless flush called)
    """

    def __init__(self, path: pathlib.Path | str | None = None) -> None:
        self._path = pathlib.Path(path) if path else _default_patterns_path()
        self._records: dict[str, dict] = {}
        self._compiled: dict[str, re.Pattern] = {}
        self._load()

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            log.info("No patterns file at %s — starting empty.", self._path)
            return
        with self._path.open(encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                    pid = rec.get("id") or str(uuid.uuid4())
                    rec.setdefault("id", pid)
                    rec.setdefault("fires", 0)
                    rec.setdefault("provisional", False)
                    self._records[pid] = rec
                    try:
                        self._compiled[pid] = re.compile(rec["pattern"], re.IGNORECASE)
                    except re.error as exc:
                        log.warning("Bad regex in pattern %s (line %d): %s", pid, line_no, exc)
                except json.JSONDecodeError as exc:
                    log.warning("Malformed JSON in patterns.jsonl line %d: %s", line_no, exc)

    def flush(self) -> None:
        """Persist current records back to disk.

        Best-effort: provisional-pattern learning must never abort the parse
        that triggered it, so a write failure (read-only fs, full disk) is
        logged and swallowed rather than propagated.
        """
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("w", encoding="utf-8") as fh:
                for rec in self._records.values():
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning("Could not flush patterns to %s: %s", self._path, exc)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def by_type(self, type_name: str) -> list[dict]:
        return [r for r in self._records.values() if r.get("type") == type_name]

    def compiled(self, pid: str) -> re.Pattern | None:
        return self._compiled.get(pid)

    def all_records(self) -> list[dict]:
        return list(self._records.values())

    def ids_for_type(self, type_name: str) -> list[str]:
        return [r["id"] for r in self.by_type(type_name)]

    # ------------------------------------------------------------------
    # Match helpers
    # ------------------------------------------------------------------

    def match_first(self, type_name: str, text: str) -> tuple[re.Match | None, str | None]:
        """
        Try each pattern of *type_name* against *text*.
        Returns (match, pattern_id) for the first hit, or (None, None).
        """
        for rec in self.by_type(type_name):
            pid = rec["id"]
            pat = self._compiled.get(pid)
            if pat is None:
                continue
            m = pat.search(text)
            if m:
                rec["fires"] = rec.get("fires", 0) + 1
                return m, pid
        return None, None

    def match_all(self, type_name: str, text: str) -> list[tuple[re.Match, str]]:
        """Return all matches across all patterns of *type_name*."""
        hits: list[tuple[re.Match, str]] = []
        for rec in self.by_type(type_name):
            pid = rec["id"]
            pat = self._compiled.get(pid)
            if pat is None:
                continue
            for m in pat.finditer(text):
                rec["fires"] = rec.get("fires", 0) + 1
                hits.append((m, pid))
        return hits

    # ------------------------------------------------------------------
    # Add new patterns
    # ------------------------------------------------------------------

    def add(
        self,
        pattern: str,
        type_name: str,
        description: str = "",
        provisional: bool = True,
        extra: dict[str, Any] | None = None,
    ) -> str:
        """Add a new pattern; returns its id.  Skips exact regex duplicates."""
        for rec in self._records.values():
            if rec["pattern"] == pattern and rec["type"] == type_name:
                return rec["id"]
        pid = str(uuid.uuid4())[:8]
        rec: dict[str, Any] = {
            "id": pid,
            "type": type_name,
            "pattern": pattern,
            "description": description,
            "provisional": provisional,
            "fires": 0,
        }
        if extra:
            rec.update(extra)
        self._records[pid] = rec
        try:
            self._compiled[pid] = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            log.warning("Could not compile new pattern %s: %s", pid, exc)
        return pid
