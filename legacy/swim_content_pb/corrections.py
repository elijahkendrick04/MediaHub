"""
swim_content_pb/corrections.py
Per-meet override store.

Corrections are stored in runs_v4/<run_id>__corrections.json.
NO automatic merging across runs. A separate save_to_persistent_mappings()
is stubbed for future work but NOT exposed in the UI.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

_RUNS_DIR = Path(__file__).resolve().parent.parent / "runs_v4"
_LOCK = threading.Lock()


def _corrections_path(run_id: str) -> Path:
    """Return the path for a run's corrections JSON file."""
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    # Sanitise run_id for filesystem safety
    safe = "".join(c for c in run_id if c.isalnum() or c in "-_.")
    return _RUNS_DIR / f"{safe}__corrections.json"


def _load(run_id: str) -> dict:
    p = _corrections_path(run_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(run_id: str, data: dict) -> None:
    p = _corrections_path(run_id)
    try:
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


class CorrectionsStore:
    """Per-meet manual override store.

    hy3_swimmer_key = original_asa_id or 'name:LASTNAME, FIRSTNAME'
    """

    def get_override(self, run_id: str, hy3_swimmer_key: str) -> Optional[dict]:
        """Look up override for a HY3 swimmer in this run."""
        with _LOCK:
            data = _load(run_id)
        return data.get(hy3_swimmer_key)

    def has_override(self, run_id: str, hy3_swimmer_key: str) -> bool:
        return self.get_override(run_id, hy3_swimmer_key) is not None

    def set_override_asa_id(
        self,
        run_id: str,
        hy3_swimmer_key: str,
        new_asa_id: str,
        note: str = "",
    ) -> None:
        """User says: this swimmer's correct ASA number for this meet is X."""
        with _LOCK:
            data = _load(run_id)
            data[hy3_swimmer_key] = {
                "action": "override_asa_id",
                "new_asa_id": new_asa_id,
                "note": note,
                "original_key": hy3_swimmer_key,
            }
            _save(run_id, data)

    def set_ignore_pb(
        self,
        run_id: str,
        hy3_swimmer_key: str,
        reason: str = "",
    ) -> None:
        """User says: don't run PB detection for this swimmer in this meet."""
        with _LOCK:
            data = _load(run_id)
            data[hy3_swimmer_key] = {
                "action": "ignore_pb",
                "reason": reason,
                "original_key": hy3_swimmer_key,
            }
            _save(run_id, data)

    def remove_override(self, run_id: str, hy3_swimmer_key: str) -> None:
        """Remove an override (undo)."""
        with _LOCK:
            data = _load(run_id)
            data.pop(hy3_swimmer_key, None)
            _save(run_id, data)

    def all_for_run(self, run_id: str) -> list[dict]:
        """For UI display — all overrides in this run."""
        with _LOCK:
            data = _load(run_id)
        result = []
        for key, val in data.items():
            result.append({"swimmer_key": key, **val})
        return result

    def save_to_persistent_mappings(
        self,
        run_id: str,
        hy3_swimmer_key: str,
    ) -> None:
        """STUB — future work. Permanently save a mapping for future runs.
        Not exposed in the UI yet per spec.
        """
        # TODO: implement persistent cross-run mapping store
        pass
