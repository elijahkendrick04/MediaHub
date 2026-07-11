"""Chat session persistence for the free-text iterative brief loop.

A chat session is a list of (role, content) messages plus an optional
draft brief the assistant has proposed. Sessions live as JSON files under
``DATA_DIR/free_text_chats/<chat_id>.json`` so they survive page reloads
and process restarts.

The conversation protocol (see agent.py) lets the LLM either ask a
clarifying question, run a web-research lookup, or propose a brief. The
user accepts or declines the brief; on accept, the session's brief is
the input to caption/image/motion generators.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _data_dir() -> Path:
    env = os.environ.get("DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "data"


def _sessions_dir() -> Path:
    d = _data_dir() / "free_text_chats"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ChatSession:
    chat_id: str
    created_at: str
    updated_at: str
    title: str = ""
    # Owning organisation/profile id — tenant isolation. "" on legacy chats
    # created before scoping existed (tolerated like ownerless runs).
    profile_id: str = ""
    # messages = [{role: "user"|"assistant"|"system_note", content: str, ts: iso}]
    messages: list[dict] = field(default_factory=list)
    # Latest brief the assistant has proposed, awaiting user accept/decline.
    pending_brief: Optional[dict] = None
    # The brief the user accepted (frozen — used by content generators).
    accepted_brief: Optional[dict] = None
    # Research evidence gathered across the conversation, keyed by query.
    research_log: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "chat_id": self.chat_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "title": self.title,
            "profile_id": self.profile_id,
            "messages": list(self.messages),
            "pending_brief": self.pending_brief,
            "accepted_brief": self.accepted_brief,
            "research_log": list(self.research_log),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChatSession":
        return cls(
            chat_id=d.get("chat_id", ""),
            created_at=d.get("created_at", _now_iso()),
            updated_at=d.get("updated_at", _now_iso()),
            title=d.get("title", "") or "",
            profile_id=d.get("profile_id", "") or "",
            messages=list(d.get("messages") or []),
            pending_brief=d.get("pending_brief"),
            accepted_brief=d.get("accepted_brief"),
            research_log=list(d.get("research_log") or []),
        )

    def add_user_message(self, text: str) -> None:
        self.messages.append(
            {
                "role": "user",
                "content": text,
                "ts": _now_iso(),
            }
        )
        if not self.title and text.strip():
            self.title = text.strip()[:80]
        self.updated_at = _now_iso()

    def add_assistant_message(self, text: str, meta: Optional[dict] = None) -> None:
        msg: dict[str, Any] = {
            "role": "assistant",
            "content": text,
            "ts": _now_iso(),
        }
        if meta:
            msg["meta"] = meta
        self.messages.append(msg)
        self.updated_at = _now_iso()


def create_session(profile_id: str = "") -> ChatSession:
    """Create and persist a new chat, stamped with its owning profile.

    Callers with an active organisation (the web routes) pass its
    profile id so the chat is tenant-scoped from birth; "" keeps the
    legacy ownerless behaviour for pre-org sandboxes.
    """
    s = ChatSession(
        chat_id=uuid.uuid4().hex[:12],
        created_at=_now_iso(),
        updated_at=_now_iso(),
        profile_id=(profile_id or "").strip(),
    )
    save_session(s)
    return s


def can_access_session(s: Optional[ChatSession], active_pid: Optional[str]) -> bool:
    """Tenant isolation guard — mirrors web.py's ``_can_access_run`` rules.

    A chat that records an owning ``profile_id`` is only accessible to
    that organisation's session. Legacy ownerless chats (created before
    scoping existed) stay readable so historical conversations aren't
    orphaned. ``active_pid`` of ``None`` means no organisations are
    configured at all — a single-tenant sandbox with nothing to isolate.
    """
    if s is None:
        return False
    if active_pid is None:
        return True
    owner = (s.profile_id or "").strip()
    if not owner:
        return True
    return owner == active_pid


def save_session(s: ChatSession) -> None:
    path = _sessions_dir() / f"{s.chat_id}.json"
    # Write atomically (same-dir temp + os.replace) so a crash or an
    # overlapping write mid-serialisation can't truncate the file and lose
    # the whole conversation — the chat is the only record of the brief.
    # Mirrors stub_pack_store._atomic_write.
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(s.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_session(chat_id: str) -> Optional[ChatSession]:
    if not chat_id or not chat_id.replace("-", "").isalnum():
        return None
    path = _sessions_dir() / f"{chat_id}.json"
    if not path.exists():
        return None
    try:
        return ChatSession.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return None


def list_sessions(limit: int = 50, profile_id: Optional[str] = None) -> list[dict]:
    """List chats, newest first.

    ``profile_id=None`` keeps the historical unscoped listing (pre-org
    sandboxes / direct unit calls). When a profile id is given, only that
    organisation's chats — plus legacy ownerless ones, mirroring
    :func:`can_access_session` — are returned; transcripts can carry
    athlete names and briefs, so they must not list across workspaces.
    """
    rows: list[dict] = []
    for p in _sessions_dir().glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            owner = (d.get("profile_id") or "").strip()
            if profile_id is not None and owner and owner != profile_id:
                continue
            rows.append(
                {
                    "chat_id": d.get("chat_id", p.stem),
                    "title": d.get("title", "") or "Untitled",
                    "created_at": d.get("created_at", ""),
                    "updated_at": d.get("updated_at", ""),
                    "profile_id": owner,
                    "n_messages": len(d.get("messages") or []),
                    "accepted": bool(d.get("accepted_brief")),
                }
            )
        except (OSError, json.JSONDecodeError):
            continue
    rows.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
    return rows[:limit]


def delete_session(chat_id: str) -> bool:
    if not chat_id or not chat_id.replace("-", "").isalnum():
        return False
    p = _sessions_dir() / f"{chat_id}.json"
    if not p.exists():
        return False
    try:
        p.unlink()
        return True
    except OSError:
        return False
