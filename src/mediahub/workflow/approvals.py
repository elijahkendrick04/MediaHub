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

import contextlib
import json
import logging
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .._atomic_io import atomic_write_json, cross_process_lock

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ApprovalLedger:
    def __init__(self, runs_dir: Path):
        self.runs_dir = Path(runs_dir)
        self._lock = threading.Lock()

    def _path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}__approvals.json"

    @contextlib.contextmanager
    def _locked(self, run_id: str) -> Iterator[None]:
        """Serialise a load -> mutate -> save in-process and across gunicorn
        workers — concurrent votes on the same run are the expected workload, so
        without the cross-process ``flock`` one vote is silently dropped."""
        with self._lock:
            with cross_process_lock(self._path(run_id).with_suffix(".lock")):
                yield

    def _load(self, run_id: str) -> dict:
        p = self._path(run_id)
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            # Preserve a corrupt ledger instead of silently zeroing every vote.
            bad = p.with_name(p.name + ".corrupt")
            try:
                if not bad.exists():
                    shutil.copy2(p, bad)
            except OSError:
                pass
            log.error("approvals ledger %s is corrupt (%s); votes not counted", p.name, exc)
            return {}

    def _save(self, run_id: str, data: dict) -> None:
        atomic_write_json(self._path(run_id), data)

    def record(
        self, run_id: str, card_id: str, email: str, *, actor_kind: str = "human"
    ) -> list[str]:
        """Record a distinct approval vote; return the card's approver emails.

        ``actor_kind`` (finding #116) marks *how* the vote arrived: ``"human"``
        (a member in the app) is the default and stays byte-identical on disk;
        anything else — e.g. ``"api_token"`` for a public-API/MCP approval — is
        stamped onto the stored vote so a group-approval trail can tell an agent
        from a person. Counting/dedup stay keyed on ``email`` and are unchanged.
        """
        email = (email or "").strip().lower()
        with self._locked(run_id):
            data = self._load(run_id)
            votes = data.get(card_id) or []
            if email and not any((v.get("email") or "").lower() == email for v in votes):
                vote = {"email": email, "at": _now_iso()}
                if actor_kind and actor_kind != "human":
                    vote["actor_kind"] = actor_kind
                votes.append(vote)
                data[card_id] = votes
                self._save(run_id, data)
            return [v.get("email", "") for v in votes]

    def approvers_for(self, run_id: str, card_id: str) -> list[str]:
        votes = self._load(run_id).get(card_id) or []
        return [v.get("email", "") for v in votes if v.get("email")]

    def clear(self, run_id: str, card_id: str) -> None:
        """Drop a card's votes (on reject / re-queue) so approval restarts clean."""
        with self._locked(run_id):
            data = self._load(run_id)
            if card_id in data:
                del data[card_id]
                self._save(run_id, data)


__all__ = ["ApprovalLedger"]
