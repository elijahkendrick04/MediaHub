"""
WorkflowStore — per-run, per-card workflow state.

Storage: runs_v4/<run_id>__workflow.json  (sidecar — never touches main run JSON)

File format:
  {
    "<card_id>": {
      "card_id": "...",
      "status": "queue" | "approved" | "rejected" | "posted" | "edited",
      "edited_captions": {"warm-club_headline": "...", ...} | null,
      "notes": "..." | null,
      "posted_at": "2026-05-10T12:00:00Z" | null,
      "last_changed_at": "2026-05-10T11:00:00Z"
    },
    ...
  }
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .status import CardStatus, CardWorkflowState, ScheduleStatus


class WorkflowStore:
    """
    Thread-safe store for per-card workflow state, persisted as a sidecar JSON
    alongside the main run JSON.
    """

    def __init__(self, runs_dir: Path):
        self.runs_dir = Path(runs_dir)
        self._lock = threading.Lock()

    def _path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}__workflow.json"

    def load(self, run_id: str) -> dict[str, CardWorkflowState]:
        """Return all CardWorkflowState objects for the run, keyed by card_id."""
        path = self._path(run_id)
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text())
            return {
                card_id: CardWorkflowState.from_dict(state_dict)
                for card_id, state_dict in raw.items()
            }
        except Exception:
            return {}

    def _save(self, run_id: str, states: dict[str, CardWorkflowState]) -> None:
        """Persist the states dict to disk. Caller holds lock."""
        path = self._path(run_id)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {card_id: s.to_dict() for card_id, s in states.items()},
                indent=2,
            )
        )

    def set_status(
        self,
        run_id: str,
        card_id: str,
        status: CardStatus,
        notes: Optional[str] = None,
        posted_at: Optional[str] = None,
    ) -> None:
        """Set the status of a card, preserving existing edits."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            states = self.load(run_id)
            existing = states.get(card_id, CardWorkflowState(card_id=card_id))

            # If marking posted, stamp the time
            if status == CardStatus.POSTED and not posted_at:
                posted_at = now

            existing.status = status
            existing.last_changed_at = now
            if notes is not None:
                existing.notes = notes
            if posted_at is not None:
                existing.posted_at = posted_at

            states[card_id] = existing
            self._save(run_id, states)

    def set_edits(
        self,
        run_id: str,
        card_id: str,
        edits: dict[str, str],
    ) -> None:
        """
        Persist user caption overrides for a card.
        Keys are '{tone_str}_{slot}', e.g. 'warm-club_headline'.
        Status is set to EDITED if currently QUEUE.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            states = self.load(run_id)
            existing = states.get(card_id, CardWorkflowState(card_id=card_id))

            existing.edited_captions = {**(existing.edited_captions or {}), **edits}
            existing.last_changed_at = now
            if existing.status == CardStatus.QUEUE:
                existing.status = CardStatus.EDITED

            states[card_id] = existing
            self._save(run_id, states)

    def summary(self, run_id: str) -> dict:
        """Return {queue, approved, rejected, posted, edited, total}."""
        states = self.load(run_id)
        counts: dict[str, int] = {
            "queue": 0,
            "approved": 0,
            "rejected": 0,
            "posted": 0,
            "edited": 0,
        }
        for s in states.values():
            key = s.status.value
            if key in counts:
                counts[key] += 1
        counts["total"] = len(states)
        return counts

    def set_schedule(
        self,
        run_id: str,
        card_id: str,
        schedule_status: ScheduleStatus,
        buffer_update_id: Optional[str] = None,
        scheduled_at: Optional[str] = None,
        schedule_error: Optional[str] = None,
    ) -> CardWorkflowState:
        """Update a card's external-scheduler state.

        Used by the publishing layer (Buffer) to record when a card has
        been queued or scheduled with a third-party service. Returns the
        updated CardWorkflowState.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            states = self.load(run_id)
            existing = states.get(card_id, CardWorkflowState(card_id=card_id))
            existing.schedule_status = schedule_status
            existing.last_changed_at = now
            # Always overwrite the most recent attempt's metadata; explicit
            # None clears prior values so the UI never shows a stale id
            # after a failed re-schedule.
            existing.buffer_update_id = buffer_update_id
            existing.scheduled_at = scheduled_at
            existing.schedule_error = schedule_error
            states[card_id] = existing
            self._save(run_id, states)
            return existing

    def mark_all_posted(self, run_id: str) -> int:
        """Mark all approved cards as posted. Returns count of cards updated."""
        now = datetime.now(timezone.utc).isoformat()
        updated = 0
        with self._lock:
            states = self.load(run_id)
            for card_id, s in states.items():
                if s.status == CardStatus.APPROVED:
                    s.status = CardStatus.POSTED
                    s.posted_at = now
                    s.last_changed_at = now
                    updated += 1
            self._save(run_id, states)
        return updated
