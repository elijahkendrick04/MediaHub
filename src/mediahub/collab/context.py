"""collab/context.py — Team Context (roadmap 1.18).

The same org context the AI copilot reads — brand voice, palette/tone, the
workspace's standing preferences (the assistant memory the copilot honours), and
recent content — assembled into one read-only view *for humans too*. So a new
committee member can see "this is who we are and what we've decided" in the same
place the assistant does, rather than it being implicit AI-only state.

Read-only and best-effort: every source is wrapped so a missing one degrades to
empty rather than raising. Lazy imports keep ``collab`` from pulling the brand /
assistant / web stacks in at import time.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))


def _brand_block(profile_id: str) -> dict:
    try:
        from mediahub.web.club_profile import load_profile

        prof = load_profile(profile_id)
        if prof is None:
            return {}
        palette: dict = {}
        tone = ""
        try:
            kit = prof.get_brand_kit()
            palette = dict(getattr(kit, "palette", {}) or {})
            tone = getattr(kit, "tone", "") or ""
        except Exception:
            pass
        return {
            "display_name": getattr(prof, "display_name", "") or profile_id,
            "voice_summary": getattr(prof, "brand_voice_summary", "") or "",
            "tone": tone,
            "palette": palette,
        }
    except Exception:
        return {}


def _preferences(profile_id: str) -> list[str]:
    """The org's standing preferences the copilot respects — surfaced verbatim."""
    try:
        from mediahub.assistant import memory as _memory

        return [it.text for it in _memory.recall(profile_id, "", k=12) if it.text]
    except Exception:
        return []


def _recent_runs(profile_id: str, *, limit: int = 6) -> list[dict]:
    """The org's most recent finished runs, straight from the runs table."""
    db = _data_dir() / "data.db"
    if not db.exists():
        return []
    try:
        conn = sqlite3.connect(str(db), timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT id, meet_name, created_at FROM runs "
                "WHERE profile_id=? ORDER BY created_at DESC LIMIT ?",
                ((profile_id or "").strip(), int(limit)),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    return [
        {
            "run_id": r["id"],
            "meet_name": r["meet_name"] or "",
            "created_at": r["created_at"] or "",
        }
        for r in rows
    ]


def team_context(profile_id: str, *, recent_limit: int = 6) -> dict:
    """Assemble the org's Team Context: brand, standing preferences, recent runs.

    Never raises; any unavailable source degrades to empty.
    """
    pid = (profile_id or "").strip()
    if not pid:
        return {"brand": {}, "preferences": [], "recent": []}
    return {
        "brand": _brand_block(pid),
        "preferences": _preferences(pid),
        "recent": _recent_runs(pid, limit=recent_limit),
    }


__all__ = ["team_context"]
