"""workflow/approvals.py — per-card approval-votes ledger (roadmap 1.12).

Group-approver rules (``workflow.governance``) need to remember *who* has
approved each card so far. Rather than widen ``CardWorkflowState`` (and the
persisted workflow JSON shape), this is a separate, additive sidecar — exactly
like the workflow store sits beside the run JSON:

    DATA_DIR/runs_v4/<run_id>__approvals.json
    { "<card_id>": [ {"email": "a@club", "at": "<iso>"}, ... ], ... }

Votes are distinct per (card, email). Re-queueing or rejecting a card clears
its votes so a fresh approval round starts clean.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ApprovalLedger:
    def __init__(self, runs_dir: Path):
        self.runs_dir = Path(runs_dir)
        self._lock = threading.Lock()

    def _path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}__approvals.json"

    def _load(self, run_id: str) -> dict:
        p = self._path(run_id)
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save(self, run_id: str, data: dict) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._path(run_id).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def record(self, run_id: str, card_id: str, email: str) -> list[str]:
        """Record a distinct approval vote; return the card's approver emails."""
        email = (email or "").strip().lower()
        with self._lock:
            data = self._load(run_id)
            votes = data.get(card_id) or []
            if email and not any((v.get("email") or "").lower() == email for v in votes):
                votes.append({"email": email, "at": _now_iso()})
                data[card_id] = votes
                self._save(run_id, data)
            return [v.get("email", "") for v in votes]

    def approvers_for(self, run_id: str, card_id: str) -> list[str]:
        votes = self._load(run_id).get(card_id) or []
        return [v.get("email", "") for v in votes if v.get("email")]

    def clear(self, run_id: str, card_id: str) -> None:
        """Drop a card's votes (on reject / re-queue) so approval restarts clean."""
        with self._lock:
            data = self._load(run_id)
            if card_id in data:
                del data[card_id]
                self._save(run_id, data)


__all__ = ["ApprovalLedger"]
