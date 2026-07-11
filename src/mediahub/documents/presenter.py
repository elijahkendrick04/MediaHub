"""documents.presenter — the live presenter session for a deck (roadmap 1.15).

The deck format gets a **presenter surface**: a console with speaker notes and a
timer, an audience full-screen view, autoplay (kiosk mode for a foyer screen), and
**phone-as-remote** pairing. This module is the engine behind it — a small,
multi-worker-safe session store (one JSON file per session under
``DATA_DIR/presenter_sessions``, atomic writes, TTL) and the state machine the web
routes drive. No web code here, so it is unit-testable on its own.

Control model: the owner (the signed-in presenter) creates a session and gets a
short **pairing code**; a phone that knows the code can drive slide changes
(next/prev/goto/blackout). The code is the capability — it is short-lived (TTL) and
unguessable enough for an ephemeral in-room remote; the web layer rate-limits code
entry. Live edits during a talk are handled by ``spec_version``: when the owner
re-saves the deck the version bumps and the audience view reloads.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

# Unambiguous alphabet (no 0/O/1/I/L) for a code read aloud / typed on a phone.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LEN = 6
SESSION_TTL_SECONDS = 6 * 3600  # a presentation sitting; purged after

ACTIONS = ("next", "prev", "goto", "blackout", "timer_reset", "autoplay", "end")


def _now() -> float:
    return time.time()


def _store_dir() -> Path:
    d = Path(os.environ.get("DATA_DIR", ".")).resolve() / "presenter_sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _make_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))


@dataclass
class PresenterSession:
    session_id: str
    doc_id: str
    owner: str  # profile id of the presenter who created it
    total_slides: int
    pairing_code: str
    current: int = 0
    blackout: bool = False
    autoplay: bool = False
    autoplay_seconds: float = 8.0
    spec_version: str = ""  # bumps on a live edit → audience reloads
    timer_started_at: float = 0.0
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    ended: bool = False

    def is_expired(self, *, now: Optional[float] = None) -> bool:
        return (now or _now()) - self.updated_at > SESSION_TTL_SECONDS

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "PresenterSession":
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in raw.items() if k in fields})

    def public_state(self) -> dict:
        """The state the audience / remote polls (no owner id leaked)."""
        elapsed = int(_now() - self.timer_started_at) if self.timer_started_at else 0
        return {
            "session_id": self.session_id,
            "doc_id": self.doc_id,
            "current": self.current,
            "total": self.total_slides,
            "blackout": self.blackout,
            "autoplay": self.autoplay,
            "autoplay_seconds": self.autoplay_seconds,
            "spec_version": self.spec_version,
            "timer_elapsed": elapsed,
            "ended": self.ended,
        }


# ---------------------------------------------------------------------------
# Persistence (atomic, per-session JSON under DATA_DIR)
# ---------------------------------------------------------------------------


def _path(session_id: str) -> Path:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    return _store_dir() / f"{safe}.json"


def _save(session: PresenterSession) -> PresenterSession:
    session.updated_at = _now()
    p = _path(session.session_id)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(session.to_dict()), encoding="utf-8")
    os.replace(tmp, p)
    return session


def get_session(session_id: str) -> Optional[PresenterSession]:
    p = _path(session_id)
    if not p.exists():
        return None
    try:
        s = PresenterSession.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None
    if s.is_expired():
        try:
            p.unlink()
        except OSError:
            pass
        return None
    return s


def get_by_pairing_code(code: str, *, include_ended: bool = False) -> Optional[PresenterSession]:
    """Resolve a live session by its pairing code.

    ``include_ended=True`` also returns a session whose talk has ended (but not
    one that has expired/been purged), so the remote can tell a *finished*
    presentation apart from a *wrong* code — an ended-but-valid code gets a
    friendly "presentation ended" screen instead of "Code not found", and never
    burns the shared-NAT failure budget (E-4).
    """
    code = (code or "").strip().upper()
    if not code:
        return None
    for f in _store_dir().glob("*.json"):
        try:
            s = PresenterSession.from_dict(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            continue
        if s.pairing_code == code and not s.is_expired() and (include_ended or not s.ended):
            return s
    return None


def create_session(
    doc_id: str,
    total_slides: int,
    owner: str,
    *,
    spec_version: str = "",
    autoplay: bool = False,
    autoplay_seconds: float = 8.0,
) -> PresenterSession:
    """Start a presenter session for a deck and mint its pairing code."""
    total = max(1, int(total_slides))
    # Mint a code not currently in use by a live session.
    existing = {
        s.pairing_code
        for s in _iter_live()  # avoid collisions among active sessions
    }
    code = _make_code()
    while code in existing:
        code = _make_code()
    session = PresenterSession(
        session_id="ps_" + secrets.token_hex(8),
        doc_id=str(doc_id),
        owner=str(owner),
        total_slides=total,
        pairing_code=code,
        spec_version=str(spec_version),
        autoplay=bool(autoplay),
        autoplay_seconds=float(autoplay_seconds),
        timer_started_at=_now(),
    )
    return _save(session)


def _iter_live():
    now = _now()
    for f in _store_dir().glob("*.json"):
        try:
            s = PresenterSession.from_dict(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            continue
        if not s.is_expired(now=now):
            yield s


def get_live_for(doc_id: str, owner: str) -> Optional[PresenterSession]:
    """The current live (non-ended, non-expired) session for this deck+owner.

    Lets the console *resume* an existing session on reload instead of minting a
    fresh one every load — a reload used to create a new session with a new
    pairing code, desyncing the already-paired phone and audience projector
    (G-12). Returns the most-recently-updated match, or None to start fresh.
    """
    doc_id, owner = str(doc_id), str(owner)
    best: Optional[PresenterSession] = None
    for s in _iter_live():
        if s.doc_id == doc_id and s.owner == owner and not s.ended:
            if best is None or s.updated_at > best.updated_at:
                best = s
    return best


def apply_action(session_id: str, action: str, value=None) -> Optional[PresenterSession]:
    """Apply a control action (used by the phone remote and the console)."""
    s = get_session(session_id)
    if s is None:
        return None
    if action == "next":
        s.current = min(s.current + 1, s.total_slides - 1)
        s.autoplay = False  # a manual move hands control to the presenter (D-11)
    elif action == "prev":
        s.current = max(s.current - 1, 0)
        s.autoplay = False  # ...so the audience follows the driver, not the kiosk loop
    elif action == "goto":
        try:
            s.current = max(0, min(int(value), s.total_slides - 1))
        except (TypeError, ValueError):
            return s
        s.autoplay = False
    elif action == "blackout":
        s.blackout = (not s.blackout) if value is None else bool(value)
    elif action == "timer_reset":
        s.timer_started_at = _now()
    elif action == "autoplay":
        s.autoplay = (not s.autoplay) if value is None else bool(value)
    elif action == "end":
        s.ended = True
    else:
        return s  # unknown action → no-op (forward-compatible)
    return _save(s)


def update_spec(
    session_id: str, *, total_slides: int, spec_version: str
) -> Optional[PresenterSession]:
    """Reflect a live edit of the deck — bumps the version so the audience reloads."""
    s = get_session(session_id)
    if s is None:
        return None
    s.total_slides = max(1, int(total_slides))
    s.current = min(s.current, s.total_slides - 1)
    s.spec_version = str(spec_version)
    return _save(s)


def end_session(session_id: str) -> None:
    s = get_session(session_id)
    if s is not None:
        s.ended = True
        _save(s)


def purge_expired() -> int:
    """Delete expired session files; returns how many were removed."""
    removed = 0
    now = _now()
    for f in _store_dir().glob("*.json"):
        try:
            s = PresenterSession.from_dict(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
            continue
        if s.is_expired(now=now):
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    return removed


__all__ = [
    "ACTIONS",
    "SESSION_TTL_SECONDS",
    "PresenterSession",
    "create_session",
    "get_session",
    "get_live_for",
    "get_by_pairing_code",
    "apply_action",
    "update_spec",
    "end_session",
    "purge_expired",
]
