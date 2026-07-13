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
      "last_changed_at": "2026-05-10T11:00:00Z",
      "actor": "member@club" | "api-token:mht_…" | null
    },
    ...
  }
"""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from .._atomic_io import atomic_write_json, cross_process_lock
from .status import CardStatus, CardWorkflowState

log = logging.getLogger(__name__)


def _preserve_corrupt(path: Path, exc: Exception) -> None:
    """Copy a corrupt sidecar aside (once) and log, so its decisions can be
    recovered instead of being silently overwritten by the next mutator."""
    bad = path.with_name(path.name + ".corrupt")
    try:
        if not bad.exists():
            shutil.copy2(path, bad)
        log.error(
            "workflow sidecar %s is corrupt (%s); preserved a copy at %s", path.name, exc, bad.name
        )
    except OSError:
        log.error("workflow sidecar %s is corrupt (%s); could not preserve it", path.name, exc)


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

    @contextlib.contextmanager
    def _locked(self, run_id: str) -> Iterator[None]:
        """Serialise a load -> mutate -> save both in-process and across workers.

        The in-process ``threading.Lock`` guards threads within one gunicorn
        worker; the ``flock`` on a per-run lock file guards the *other* workers
        (the app runs ``--workers 2`` on a shared disk), which the thread lock
        alone cannot — without it two workers can each persist a different card
        and lose one another's approval decision.
        """
        with self._lock:
            with cross_process_lock(self._path(run_id).with_suffix(".lock")):
                yield

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
        except (json.JSONDecodeError, OSError, ValueError, AttributeError) as exc:
            # Never silently return {} on a corrupt sidecar — the next mutator
            # would persist a single card over it, wiping prior approve/reject
            # decisions. Atomic writes make torn reads impossible, so reaching
            # here means genuine on-disk corruption: surface it and keep a copy.
            _preserve_corrupt(path, exc)
            return {}

    def _save(self, run_id: str, states: dict[str, CardWorkflowState]) -> None:
        """Persist the states dict to disk atomically. Caller holds the lock."""
        atomic_write_json(
            self._path(run_id),
            {card_id: s.to_dict() for card_id, s in states.items()},
        )

    def set_status(
        self,
        run_id: str,
        card_id: str,
        status: CardStatus,
        notes: Optional[str] = None,
        posted_at: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> None:
        """Set the status of a card, preserving existing edits.

        ``actor`` (finding #116) records who/what made the change so the audit
        trail distinguishes a human from an agent — a member's email for a web
        approval, ``api-token:<token_id>`` for a public-API/MCP one. Omitted
        (``None``) leaves the prior actor untouched."""
        now = datetime.now(timezone.utc).isoformat()
        with self._locked(run_id):
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
            if actor is not None:
                existing.actor = actor

            states[card_id] = existing
            self._save(run_id, states)

    def set_edits(
        self,
        run_id: str,
        card_id: str,
        edits: dict[str, str],
        actor: Optional[str] = None,
    ) -> None:
        """
        Persist user caption overrides for a card.
        Keys are '{tone_str}_{slot}', e.g. 'warm-club_headline'.
        Status is set to EDITED if currently QUEUE.
        ``actor`` (finding #116) records who/what made the edit, as in
        :meth:`set_status`.

        H-10: overwriting a caption slot stashes the value it replaces under
        a reserved ``prev.<key>`` slot in the same bag, so the review drawer
        can offer a one-step "Restore previous caption" (a restore save swaps
        the pair back). ``insp.*`` inspector overrides and the ``prev.*``
        slots themselves are never stashed. The dotted ``prev.`` prefix keeps
        the pack builder's ``tone_slot`` caption parser skipping these cleanly,
        exactly like ``insp.*``.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._locked(run_id):
            states = self.load(run_id)
            existing = states.get(card_id, CardWorkflowState(card_id=card_id))

            merged = {**(existing.edited_captions or {})}
            for key, val in edits.items():
                old = merged.get(key)
                if (
                    not key.startswith(("insp.", "prev."))
                    and isinstance(old, str)
                    and old
                    and old != val
                ):
                    merged["prev." + key] = old
                merged[key] = val
            existing.edited_captions = merged
            existing.last_changed_at = now
            if existing.status == CardStatus.QUEUE:
                existing.status = CardStatus.EDITED
            if actor is not None:
                existing.actor = actor

            states[card_id] = existing
            self._save(run_id, states)

    def set_translation(
        self,
        run_id: str,
        card_id: str,
        language: str,
        variant: dict,
    ) -> None:
        """Store a translated variant for a card, keyed by target language.

        1.24 localisation: the variant rides with the card, so approving the
        card approves the language pair as one decision. Re-translating the same
        language overwrites that slot; other languages are preserved. This is a
        non-destructive add — it never changes the card's status (translation
        is not an edit or an approval), so a queued card stays queued.
        """
        now = datetime.now(timezone.utc).isoformat()
        lang = (language or "").strip()
        if not lang:
            return
        with self._locked(run_id):
            states = self.load(run_id)
            existing = states.get(card_id, CardWorkflowState(card_id=card_id))
            existing.translations = {**(existing.translations or {}), lang: variant}
            existing.last_changed_at = now
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

    def mark_all_posted(self, run_id: str) -> int:
        """Mark all approved cards as posted. Returns count of cards updated."""
        now = datetime.now(timezone.utc).isoformat()
        updated = 0
        with self._locked(run_id):
            states = self.load(run_id)
            for card_id, s in states.items():
                if s.status == CardStatus.APPROVED:
                    s.status = CardStatus.POSTED
                    s.posted_at = now
                    s.last_changed_at = now
                    updated += 1
            self._save(run_id, states)
        return updated
