"""brand/resweep.py — kit-edit → re-render sweep over persisted briefs (1.12).

Canva's "replace logo/colours across designs in a few clicks" — MediaHub's
data-driven equivalent. Because every card is generated from a persisted
:class:`~mediahub.creative_brief.generator.CreativeBrief` (nothing is
hand-placed), applying a brand kit across a club's whole back-catalogue is just:
walk the briefs, re-resolve their colour roles under the new kit, and re-render
the ones that change.

This module is the deterministic core:

* :func:`iter_profile_briefs` enumerates every persisted brief for a profile's
  runs.
* :func:`preview_kit_change` computes, **without rendering**, which cards would
  change and exactly which ``--mh-*`` role tokens differ (the diff preview).
* :func:`apply_kit_change` orchestrates the actual re-render through an injected
  ``render_card`` callback (the web route supplies one that renders + persists +
  flags the card for re-review), so this stays pure and Playwright-free.

Approval-first: applying never publishes. The caller's callback re-queues each
re-rendered card for human re-approval — a kit change can't silently alter
already-approved content.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Optional


@dataclass
class CardDiff:
    run_id: str
    card_id: str
    brief_id: str
    before: dict = field(default_factory=dict)  # resolved --mh-* role vars (current)
    after: dict = field(default_factory=dict)  # resolved --mh-* role vars (under new kit)

    @property
    def changed_roles(self) -> list[str]:
        keys = set(self.before) | set(self.after)
        return sorted(k for k in keys if self.before.get(k) != self.after.get(k))

    @property
    def changed(self) -> bool:
        return bool(self.changed_roles)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "card_id": self.card_id,
            "brief_id": self.brief_id,
            "changed": self.changed,
            "changed_roles": self.changed_roles,
            "before": {k: self.before.get(k) for k in self.changed_roles},
            "after": {k: self.after.get(k) for k in self.changed_roles},
        }


@dataclass
class SweepPreview:
    kit_id: str
    diffs: list[CardDiff] = field(default_factory=list)

    @property
    def affected(self) -> list[CardDiff]:
        return [d for d in self.diffs if d.changed]

    def to_dict(self) -> dict:
        affected = self.affected
        return {
            "kit_id": self.kit_id,
            "n_scanned": len(self.diffs),
            "n_affected": len(affected),
            "affected": [d.to_dict() for d in affected],
        }


@dataclass
class SweepResult:
    kit_id: str
    rendered: list[str] = field(default_factory=list)  # "run_id::card_id"
    skipped: list[str] = field(default_factory=list)
    remaining: int = 0  # affected cards left when a limit truncates the run

    def to_dict(self) -> dict:
        return {
            "kit_id": self.kit_id,
            "n_rendered": len(self.rendered),
            "n_skipped": len(self.skipped),
            "rendered": self.rendered,
            "skipped": self.skipped,
            "remaining": self.remaining,
        }


# --------------------------------------------------------------------------
# Enumeration
# --------------------------------------------------------------------------


def _run_ids_for_profile(profile_id: str, runs_dir: Path) -> list[str]:
    out: list[str] = []
    for p in sorted(runs_dir.glob("*.json")):
        name = p.name
        # skip the sidecars that share the runs dir
        if name.endswith("__workflow.json") or name.endswith("__approvals.json"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if (data.get("profile_id") or "") == profile_id:
            out.append(p.stem)
    return out


def iter_profile_briefs(profile_id: str, *, runs_dir: Path) -> Iterator[tuple[str, str, dict]]:
    """Yield ``(run_id, card_id, brief_dict)`` for every persisted brief whose
    run belongs to ``profile_id``. The latest brief per card wins (a card can be
    regenerated several times)."""
    runs_dir = Path(runs_dir)
    for run_id in _run_ids_for_profile(profile_id, runs_dir):
        bdir = runs_dir / run_id / "briefs"
        if not bdir.exists():
            continue
        latest: dict[str, tuple[float, dict]] = {}
        for bp in bdir.glob("cb_*.json"):
            try:
                data = json.loads(bp.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            card_id = str(data.get("content_item_id") or "")
            if not card_id:
                continue
            try:
                mtime = bp.stat().st_mtime
            except OSError:
                mtime = 0.0
            if card_id not in latest or mtime > latest[card_id][0]:
                latest[card_id] = (mtime, data)
        for card_id, (_mtime, data) in latest.items():
            yield run_id, card_id, data


# --------------------------------------------------------------------------
# Preview (deterministic — no rendering)
# --------------------------------------------------------------------------


def preview_kit_change(profile, kit, *, runs_dir: Path) -> SweepPreview:
    """Diff every persisted brief's resolved colour roles, current vs. ``kit``.

    ``before`` is how the card resolves today (its own stored palette);
    ``after`` is with the kit's brand applied. No pixels are produced — this is
    the cheap, deterministic preview the UI shows before an apply.
    """
    from mediahub.brand.kits import brand_kit_from_ref
    from mediahub.creative_brief.generator import CreativeBrief
    from mediahub.graphic_renderer.render import resolved_role_vars_for_brief

    brand_kit_new = brand_kit_from_ref(profile, kit)
    diffs: list[CardDiff] = []
    for run_id, card_id, brief_dict in iter_profile_briefs(profile.profile_id, runs_dir=runs_dir):
        brief = CreativeBrief.from_dict(brief_dict)
        if brief is None:
            continue
        try:
            before = resolved_role_vars_for_brief(brief, None)
            after = resolved_role_vars_for_brief(brief, brand_kit_new)
        except Exception:
            continue
        diffs.append(
            CardDiff(
                run_id=run_id,
                card_id=card_id,
                brief_id=str(brief_dict.get("id") or ""),
                before=before,
                after=after,
            )
        )
    return SweepPreview(kit_id=getattr(kit, "kit_id", ""), diffs=diffs)


# --------------------------------------------------------------------------
# Apply (re-render via an injected callback — approval-gated)
# --------------------------------------------------------------------------


def apply_kit_change(
    profile,
    kit,
    *,
    runs_dir: Path,
    render_card: Callable[[str, str, dict], bool],
    limit: Optional[int] = None,
) -> SweepResult:
    """Re-render the cards a kit change would alter, newest-affected first.

    ``render_card(run_id, card_id, brief_dict) -> bool`` does the actual
    render + persist + re-review flag and returns True if it rendered (False to
    skip, e.g. a rejected card). ``limit`` caps the work per call so a huge
    back-catalogue doesn't block one request; ``remaining`` reports the rest.
    """
    preview = preview_kit_change(profile, kit, runs_dir=runs_dir)
    affected = preview.affected
    result = SweepResult(kit_id=getattr(kit, "kit_id", ""))
    budget = len(affected) if limit is None else max(0, limit)
    for i, diff in enumerate(affected):
        if i >= budget:
            result.remaining = len(affected) - i
            break
        tag = f"{diff.run_id}::{diff.card_id}"
        try:
            did = render_card(diff.run_id, diff.card_id, _brief_for(diff, runs_dir))
        except Exception:
            did = False
        (result.rendered if did else result.skipped).append(tag)
    return result


def _brief_for(diff: CardDiff, runs_dir: Path) -> dict:
    """Reload the brief dict for a diff (kept tiny so apply stays memory-light)."""
    bp = Path(runs_dir) / diff.run_id / "briefs" / f"{diff.brief_id}.json"
    try:
        return json.loads(bp.read_text(encoding="utf-8"))
    except Exception:
        return {}


__all__ = [
    "CardDiff",
    "SweepPreview",
    "SweepResult",
    "iter_profile_briefs",
    "preview_kit_change",
    "apply_kit_change",
]
