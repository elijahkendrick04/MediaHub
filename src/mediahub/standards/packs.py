"""Loader for the seasonal standards packs (W.4).

A pack is a JSON file in ``data/standards/<season>/`` with the exact
schema of ``data/quals.json`` (``{"version": 1, "standards": [...]}``).
Files ending ``.example.json`` are templates and never loaded. The
merged view is the legacy ``quals.json`` registry plus every pack, with
later duplicates (same standard id) dropped so a pack can be superseded
by republishing under the same id in a newer season directory.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


def _standards_dirs() -> list[Path]:
    """Candidate roots, in load order: repo data/, then DATA_DIR/data/."""
    dirs: list[Path] = []
    repo_root = Path(__file__).resolve().parents[3]
    dirs.append(repo_root / "data" / "standards")
    env = os.environ.get("DATA_DIR")
    if env:
        dirs.append(Path(env) / "data" / "standards")
    return dirs


def load_standard_packs() -> list:
    """Every Standard from every season pack file, in deterministic order."""
    from swim_content.quals_registry import load_registry

    out: list = []
    seen_files: set[Path] = set()
    for root in _standards_dirs():
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*/*.json")):
            if path.name.endswith(".example.json") or path in seen_files:
                continue
            seen_files.add(path)
            try:
                out.extend(load_registry(path))
            except Exception:
                log.warning("standards pack unreadable, skipped: %s", path, exc_info=True)
    return out


def all_standards() -> list:
    """quals.json registry + season packs, deduped by standard id."""
    from swim_content.quals_registry import load_registry

    merged: list = []
    seen: set[str] = set()
    try:
        base = load_registry()
    except Exception:
        base = []
    for s in list(base) + load_standard_packs():
        sid = getattr(s, "standard_id", "")
        if sid and sid in seen:
            continue
        seen.add(sid)
        merged.append(s)
    return merged


def standards_for_profile(profile=None) -> list:
    """The standards the detector should run for this workspace.

    With ``profile.important_standards`` set, only those ids run (the club
    picked its county/region); otherwise every loaded standard runs — the
    pre-W.4 behaviour.
    """
    standards = all_standards()
    wanted = list(getattr(profile, "important_standards", None) or [])
    if not wanted:
        return standards
    wanted_set = {w.strip() for w in wanted if w and w.strip()}
    picked = [s for s in standards if getattr(s, "standard_id", "") in wanted_set]
    return picked or standards


def available_standards_summary() -> list[dict]:
    """Settings-picker rows: id, label, level, season, source."""
    rows = []
    for s in all_standards():
        rows.append(
            {
                "id": getattr(s, "standard_id", ""),
                "competition": getattr(s, "competition", ""),
                "body": getattr(s, "body", ""),
                "level": getattr(s, "level", ""),
                "season": getattr(s, "season", ""),
                "course": getattr(s, "course", ""),
                "source_url": getattr(s, "source_url", ""),
            }
        )
    rows.sort(key=lambda r: (r["season"], r["competition"]))
    return rows
