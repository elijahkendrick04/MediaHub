"""season_wrap/drafts.py — wrap draft packs + DATA_DIR persistence (W.8).

Builds the "month in numbers" / season-wrap draft record from
``aggregate.aggregate_window`` and persists it under
``DATA_DIR/season_wraps/<profile_id>/<id>.json``.

Deliberately caption-free: drafts carry only deterministic facts. Captions
are generated later, at the review surface, through the existing
``media_ai.llm`` seams — never here.
"""

from __future__ import annotations

import calendar
import json
import os
import re
from pathlib import Path
from typing import Optional

from mediahub.season_wrap.aggregate import aggregate_window

_HIGHLIGHTS_CAP = 8
_SLUG_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _slug(value: str) -> str:
    """Filesystem-safe id/profile slug — blocks path traversal."""
    return _SLUG_RE.sub("-", str(value or "")).strip("-") or "unknown"


def _wraps_dir(profile_id: str, data_dir: Optional[Path] = None) -> Path:
    base = Path(data_dir) if data_dir is not None else Path(os.environ.get("DATA_DIR", "data"))
    return base / "season_wraps" / _slug(profile_id)


def _draft_from_stats(stats, *, draft_id: str, title: str) -> dict:
    highlights = [
        {
            "swimmer": a["swimmer"],
            "event": a["event"],
            "headline": a["headline"],
            "type": a["type"],
            "time": a.get("time", ""),
        }
        for a in stats.top_achievements[:_HIGHLIGHTS_CAP]
    ]
    return {
        "id": draft_id,
        "title": title,
        "window": {"start": stats.start, "end": stats.end},
        "stats": stats.to_dict(),
        "stat_chips": [list(chip) for chip in stats.headline_stats()],
        "highlights": highlights,
    }


def build_monthly_draft(profile_id: str, runs_dir: Path, *, year: int, month: int) -> dict:
    """The 'June 2026 in numbers' draft pack for one calendar month."""
    last_day = calendar.monthrange(year, month)[1]
    start = f"{year:04d}-{month:02d}-01"
    end = f"{year:04d}-{month:02d}-{last_day:02d}"
    stats = aggregate_window(profile_id, Path(runs_dir), start=start, end=end)
    return _draft_from_stats(
        stats,
        draft_id=f"monthly-{year:04d}-{month:02d}",
        title=f"{calendar.month_name[month]} {year} in numbers",
    )


def build_season_draft(
    profile_id: str, runs_dir: Path, *, season_start: str, season_end: str
) -> dict:
    """The configurable season-end wrap over [season_start, season_end].

    The id is keyed to the season *start* only, so re-drafting the same season
    (the web action re-runs it with today's moving end date) overwrites one
    stable file instead of spawning a new draft every day it is clicked.
    """
    stats = aggregate_window(profile_id, Path(runs_dir), start=season_start, end=season_end)
    return _draft_from_stats(
        stats,
        draft_id=f"season-{stats.start}",
        title=f"Season wrap {stats.start} to {stats.end}",
    )


def save_draft(profile_id: str, draft: dict, data_dir: Optional[Path] = None) -> Path:
    """Persist a draft (idempotent — same id overwrites). Returns the path."""
    d = _wraps_dir(profile_id, data_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{_slug(draft.get('id') or 'draft')}.json"
    path.write_text(json.dumps(draft, indent=2, sort_keys=True), encoding="utf-8")
    return path


def list_drafts(profile_id: str, data_dir: Optional[Path] = None) -> list[dict]:
    """Every saved draft for the org, in stable filename order."""
    d = _wraps_dir(profile_id, data_dir)
    if not d.exists():
        return []
    out: list[dict] = []
    for p in sorted(d.glob("*.json")):
        try:
            draft = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(draft, dict):
            out.append(draft)
    return out


def load_draft(profile_id: str, draft_id: str, data_dir: Optional[Path] = None) -> Optional[dict]:
    """One saved draft by id, or None when absent/unreadable."""
    path = _wraps_dir(profile_id, data_dir) / f"{_slug(draft_id)}.json"
    if not path.exists():
        return None
    try:
        draft = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return draft if isinstance(draft, dict) else None


__all__ = [
    "build_monthly_draft",
    "build_season_draft",
    "save_draft",
    "list_drafts",
    "load_draft",
]
