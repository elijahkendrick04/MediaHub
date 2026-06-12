"""Append-only JSONL ledgers under ``DATA_DIR/compliance/``.

Mirrors the ``users.jsonl`` pattern (web/auth.py): every write appends one
JSON object per line; reads coalesce to the latest record per key
(last-write-wins). Append-only keeps an accountability trail — a record is
"updated" by appending a superseding line, never by rewriting history.

Files are chmod 0600 like the users ledger: complaint and incident records
carry contact details and incident facts that other processes on a shared
host must not read.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Iterable, Optional

_LOCK = threading.Lock()


def compliance_dir() -> Path:
    """Resolve ``DATA_DIR/compliance`` the same way web.py resolves DATA_DIR."""
    src_root = Path(__file__).resolve().parents[1]
    data_dir = Path(os.environ.get("DATA_DIR", str(src_root)))
    return data_dir / "compliance"


class JsonlLedger:
    """One append-only JSONL file with last-write-wins coalescing by key."""

    def __init__(self, filename: str, key_field: str = "id") -> None:
        self._filename = filename
        self._key_field = key_field

    @property
    def path(self) -> Path:
        return compliance_dir() / self._filename

    def append(self, record: dict) -> None:
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    def _iter_lines(self) -> Iterable[dict]:
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue  # tolerate a torn write; later lines still load

    def all(self) -> list[dict]:
        """Latest record per key, in first-seen order."""
        merged: dict[str, dict] = {}
        for rec in self._iter_lines():
            key = str(rec.get(self._key_field, ""))
            if not key:
                continue
            merged[key] = rec
        return list(merged.values())

    def get(self, key: str) -> Optional[dict]:
        found = None
        for rec in self._iter_lines():
            if str(rec.get(self._key_field, "")) == str(key):
                found = rec
        return found
