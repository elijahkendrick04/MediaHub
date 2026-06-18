"""Copilot session store (P6.2) — the conversation + edit history.

One :class:`AssistantSession` per (run, card): the chat transcript plus an
**edit log** recording every patch turn (the ops applied, the ops rejected and
why, and the brief id before/after). That log is what makes the assistant
auditable and reversible — each turn is a new brief version, and the prior brief
id is kept so a caller can revert.

Persisted as JSON under
``DATA_DIR/assistant_sessions/<run_id>/<card_id>/<session_id>.json``; multi-tenant
isolation rides the run/card path (the web routes gate access to the run).
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AssistantSession:
    session_id: str
    run_id: str
    card_id: str
    profile_id: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    # chat turns: {"role": "user"|"assistant", "content": str, "ts": str}
    messages: list[dict] = field(default_factory=list)
    # edit turns: {"ts", "applied": [op_dict...], "rejected": [[op_dict, reason]...],
    #              "brief_before": str, "brief_after": str}
    edits: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "card_id": self.card_id,
            "profile_id": self.profile_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": self.messages,
            "edits": self.edits,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Optional["AssistantSession"]:
        if not isinstance(d, dict) or not d.get("session_id"):
            return None
        return cls(
            session_id=str(d["session_id"]),
            run_id=str(d.get("run_id", "")),
            card_id=str(d.get("card_id", "")),
            profile_id=str(d.get("profile_id", "")),
            created_at=str(d.get("created_at") or _now()),
            updated_at=str(d.get("updated_at") or _now()),
            messages=list(d.get("messages") or []),
            edits=list(d.get("edits") or []),
        )

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content, "ts": _now()})
        self.updated_at = _now()

    def add_edit(self, *, applied, rejected, brief_before: str, brief_after: str) -> None:
        self.edits.append(
            {
                "ts": _now(),
                "applied": [op.to_dict() for op in applied],
                "rejected": [[op.to_dict(), reason] for op, reason in rejected],
                "brief_before": brief_before,
                "brief_after": brief_after,
            }
        )
        self.updated_at = _now()

    def recent_chat(self, n: int = 8) -> list[dict]:
        return self.messages[-n:]


def _safe(part: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(part or ""))


def _base_dir() -> Path:
    env = os.environ.get("DATA_DIR")
    root = Path(env) if env else Path(__file__).resolve().parents[1]
    return root / "assistant_sessions"


def _card_dir(run_id: str, card_id: str) -> Path:
    return _base_dir() / _safe(run_id) / _safe(card_id)


def create_session(run_id: str, card_id: str, *, profile_id: str = "") -> AssistantSession:
    s = AssistantSession(
        session_id=uuid.uuid4().hex[:12],
        run_id=str(run_id),
        card_id=str(card_id),
        profile_id=str(profile_id),
    )
    save_session(s)
    return s


def save_session(s: AssistantSession) -> Path:
    d = _card_dir(s.run_id, s.card_id)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{s.session_id}.json"
    p.write_text(json.dumps(s.to_dict(), indent=2, default=str), encoding="utf-8")
    return p


def load_session(run_id: str, card_id: str, session_id: str) -> Optional[AssistantSession]:
    p = _card_dir(run_id, card_id) / f"{_safe(session_id)}.json"
    if not p.exists():
        return None
    try:
        return AssistantSession.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return None


def latest_session(run_id: str, card_id: str) -> Optional[AssistantSession]:
    """The most recently updated session for a card, or None."""
    d = _card_dir(run_id, card_id)
    if not d.exists():
        return None
    best: Optional[AssistantSession] = None
    for f in d.glob("*.json"):
        try:
            s = AssistantSession.from_dict(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
        if s is None:
            continue
        if best is None or s.updated_at > best.updated_at:
            best = s
    return best


def get_or_create(
    run_id: str, card_id: str, session_id: str = "", *, profile_id: str = ""
) -> AssistantSession:
    """Load ``session_id`` if given and present, else start a fresh session."""
    if session_id:
        existing = load_session(run_id, card_id, session_id)
        if existing is not None:
            return existing
    return create_session(run_id, card_id, profile_id=profile_id)


__all__ = [
    "AssistantSession",
    "create_session",
    "save_session",
    "load_session",
    "latest_session",
    "get_or_create",
]
