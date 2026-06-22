"""collab/revisions.py — design-spec version history, diff & restore (roadmap 1.18).

Every copilot edit and every regenerate already persists a *new*
``CreativeBrief`` JSON at ``RUNS_DIR/<run_id>/briefs/cb_<id>.json`` (the patch
applier mints a fresh id rather than mutating in place), so a card's design
versions already accumulate on disk — what was missing is a human-facing way to
*see* them, *compare* them, and *roll back*. This module provides exactly that,
read-mostly over those existing files:

  - ``list_revisions`` — every brief for a card, oldest→newest, with the latest
    flagged as current (latest = newest mtime, matching the renderer's pick);
  - ``diff_revisions`` — a field-level before/after between two versions;
  - ``restore_revision`` — re-issue a chosen prior version as a fresh brief so it
    becomes current *without* discarding the in-between versions (reversible).

No AI, no engine maths — just careful bookkeeping over the brief files.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional

# The brief fields worth surfacing in a diff — the design decisions a reviewer
# cares about. Nested dicts (text layers, colour roles) are flattened to dotted
# keys. Everything else (ids, signatures, timestamps) is bookkeeping, not design.
_DIFF_FIELDS: tuple[str, ...] = (
    "primary_hook",
    "layout_template",
    "tone",
    "mood",
    "accent_style",
    "background_style",
    "composition",
    "photo_treatment",
    "typography_pair",
    "motion_intent",
    "confidence_label",
)
_DIFF_DICT_FIELDS: tuple[str, ...] = (
    "text_layers",
    "colour_role_assignment",
    "text_effects",
)


def _runs_dir(runs_dir: Optional[Path] = None) -> Path:
    if runs_dir is not None:
        return Path(runs_dir)
    env = os.environ.get("RUNS_DIR")
    if env:
        return Path(env)
    data = os.environ.get("DATA_DIR")
    if data:
        return Path(data) / "runs_v4"
    return Path(__file__).resolve().parents[1] / "runs_v4"


def _briefs_dir(run_id: str, runs_dir: Optional[Path] = None) -> Path:
    return _runs_dir(runs_dir) / run_id / "briefs"


def _short_label(brief: dict) -> str:
    """A one-line description of a version for the history list."""
    tl = brief.get("text_layers") or {}
    head = (tl.get("headline_line1") or brief.get("primary_hook") or "").strip()
    arch = (brief.get("layout_template") or "").strip()
    if head and arch:
        return f"{head} · {arch}"
    return head or arch or (brief.get("id") or "version")


def _iter_card_briefs(run_id: str, card_id: str, runs_dir: Optional[Path] = None):
    """Yield (mtime, path, brief_dict) for each brief belonging to the card."""
    bdir = _briefs_dir(run_id, runs_dir)
    if not bdir.exists() or not card_id:
        return
    for p in bdir.glob("cb_*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if str(data.get("content_item_id") or "") != str(card_id):
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0.0
        yield mtime, p, data


def list_revisions(run_id: str, card_id: str, *, runs_dir: Optional[Path] = None) -> list[dict]:
    """Every version of a card's design, oldest→newest, latest flagged current."""
    rows = sorted(_iter_card_briefs(run_id, card_id, runs_dir), key=lambda kv: kv[0])
    out: list[dict] = []
    for mtime, _p, brief in rows:
        out.append(
            {
                "brief_id": brief.get("id") or "",
                "mtime": mtime,
                "created_at": brief.get("created_at") or "",
                "label": _short_label(brief),
                "ai_directed": bool(brief.get("ai_directed")),
                "is_current": False,
            }
        )
    if out:
        out[-1]["is_current"] = True  # newest mtime is what the renderer uses
    return out


def get_brief(
    run_id: str, card_id: str, brief_id: str, *, runs_dir: Optional[Path] = None
) -> Optional[dict]:
    """Load one brief by id, but only if it belongs to ``card_id`` (isolation)."""
    brief_id = (brief_id or "").strip()
    if not brief_id:
        return None
    for _mtime, _p, brief in _iter_card_briefs(run_id, card_id, runs_dir):
        if (brief.get("id") or "") == brief_id:
            return brief
    return None


def _flatten_for_diff(brief: dict) -> dict:
    flat: dict[str, str] = {}
    for f in _DIFF_FIELDS:
        v = brief.get(f)
        if v not in (None, "", [], {}):
            flat[f] = str(v)
    for f in _DIFF_DICT_FIELDS:
        d = brief.get(f) or {}
        if isinstance(d, dict):
            for k, v in d.items():
                if v not in (None, "", [], {}):
                    flat[f"{f}.{k}"] = str(v)
    return flat


def diff_revisions(
    run_id: str,
    card_id: str,
    brief_a_id: str,
    brief_b_id: str,
    *,
    runs_dir: Optional[Path] = None,
) -> Optional[list[dict]]:
    """Field-level before/after between two versions of a card's design.

    ``a`` is the older/base, ``b`` the newer/compared. Returns a list of
    ``{field, before, after}`` for every field that differs, or ``None`` when
    either brief can't be found for this card.
    """
    a = get_brief(run_id, card_id, brief_a_id, runs_dir=runs_dir)
    b = get_brief(run_id, card_id, brief_b_id, runs_dir=runs_dir)
    if a is None or b is None:
        return None
    fa, fb = _flatten_for_diff(a), _flatten_for_diff(b)
    keys = sorted(set(fa) | set(fb))
    diff: list[dict] = []
    for k in keys:
        before, after = fa.get(k, ""), fb.get(k, "")
        if before != after:
            diff.append({"field": k, "before": before, "after": after})
    return diff


def restore_revision(
    run_id: str,
    card_id: str,
    brief_id: str,
    *,
    runs_dir: Optional[Path] = None,
) -> Optional[dict]:
    """Re-issue a prior version as a fresh brief so it becomes current.

    Writes a copy of the chosen brief with a new id and a bumped timestamp, so
    it sorts newest (the renderer picks it up) while every in-between version
    stays on disk — restore is itself reversible. Returns the new brief dict, or
    ``None`` when the chosen version can't be found for this card.
    """
    chosen = get_brief(run_id, card_id, brief_id, runs_dir=runs_dir)
    if chosen is None:
        return None
    new = dict(chosen)
    new["id"] = "cb_" + uuid.uuid4().hex[:12]
    new["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    new["restored_from"] = brief_id
    bdir = _briefs_dir(run_id, runs_dir)
    bdir.mkdir(parents=True, exist_ok=True)
    path = bdir / f"{new['id']}.json"
    path.write_text(json.dumps(new, indent=2), encoding="utf-8")
    # Nudge mtime to now so it sorts last even on a coarse filesystem clock.
    try:
        now = time.time()
        os.utime(path, (now, now))
    except OSError:
        pass
    return new


def count_revisions(run_id: str, card_id: str, *, runs_dir: Optional[Path] = None) -> int:
    return sum(1 for _ in _iter_card_briefs(run_id, card_id, runs_dir))


__all__ = [
    "list_revisions",
    "get_brief",
    "diff_revisions",
    "restore_revision",
    "count_revisions",
]
