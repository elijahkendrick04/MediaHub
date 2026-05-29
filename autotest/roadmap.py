"""Read docs/ROADMAP.md → structured items, and pick the next thing to build.

The repo already has the *write* side of the roadmap: a push to `main` whose
commit message carries a ``roadmap: <ID> <status>`` trailer flips the status
badge on the matching heading (scripts/roadmap_autoupdate.py + the
roadmap-autoupdate workflow). This module is the *read + select* side the
builder needs, plus a helper to emit that same trailer — so "autonomously
update the roadmap" reuses the existing, tested machinery instead of a new one.

IDs and statuses match the existing directive convention:
  IDs:      PAR-N · SEQ-N · Step N · phase number (1.6, 2.1)
  statuses: done | wip | blocked | todo   (badges ✅ 🔵 ⚠️ ❌)
"""
from __future__ import annotations

import dataclasses
import os
import re
from pathlib import Path

ROADMAP_PATH = Path(__file__).resolve().parent.parent / "docs" / "ROADMAP.md"

_HEADING = re.compile(r"^(#{2,4})\s+(.*)$")
# An ID at/near the start of a heading: PAR-1, SEQ-0, Step 7, or a phase 1.6.
_ID = re.compile(r"\b(PAR-\d+|SEQ-\d+|Step\s+\d+)\b|^(\d+\.\d+)\b", re.IGNORECASE)

_STATUS_BY_BADGE = [
    ("✅", "done"),
    ("\U0001F535", "wip"),     # 🔵
    ("⚠️", "partial"),
    ("❌", "todo"),
]


@dataclasses.dataclass
class RoadmapItem:
    id: str            # normalised, e.g. "SEQ-1", "Step 7", "1.6"
    title: str
    status: str        # done | wip | partial | todo | deferred
    line: int          # 1-based heading line in ROADMAP.md
    body: str          # the section text under this heading (until the next heading)

    @property
    def actionable(self) -> bool:
        return self.status in ("todo", "wip", "partial")


def _norm_id(raw: str) -> str:
    raw = raw.strip()
    m = re.match(r"step\s+(\d+)", raw, re.IGNORECASE)
    if m:
        return f"Step {m.group(1)}"
    return raw.upper() if raw[:3].upper() in ("PAR", "SEQ") else raw


def _status_for(heading: str) -> str:
    for badge, status in _STATUS_BY_BADGE:
        if badge in heading:
            if status == "todo" and "DEFERRED" in heading.upper():
                return "deferred"
            return status
    return "todo"  # no badge → not started


def parse_items(path: Path | None = None) -> list[RoadmapItem]:
    text = (path or ROADMAP_PATH).read_text(encoding="utf-8")
    lines = text.splitlines()
    # find heading line indices first so we can slice bodies
    heads: list[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        if _HEADING.match(ln):
            heads.append((i, ln))
    items: list[RoadmapItem] = []
    for idx, (i, ln) in enumerate(heads):
        m = _ID.search(_HEADING.match(ln).group(2))
        if not m:
            continue
        rid = _norm_id(m.group(1) or m.group(2))
        title = _HEADING.match(ln).group(2)
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        body = "\n".join(lines[i + 1:end]).strip()
        items.append(RoadmapItem(id=rid, title=title.strip(), status=_status_for(title),
                                 line=i + 1, body=body))
    return items


def _priority(item: RoadmapItem) -> tuple[int, int]:
    """Sort key: SEQ (sequential/foundational) first, then PAR (isolated, low
    risk), then Step, each by their number; partial before todo."""
    kind, num = 9, 9999
    m = re.match(r"(SEQ|PAR)-(\d+)", item.id, re.IGNORECASE)
    if m:
        kind = 0 if m.group(1).upper() == "SEQ" else 1
        num = int(m.group(2))
    elif item.id.lower().startswith("step"):
        kind = 2
        num = int(item.id.split()[1])
    status_rank = {"partial": 0, "wip": 1, "todo": 2}.get(item.status, 3)
    return (kind, num if kind != 9 else status_rank * 1000 + num)


def next_item(path: Path | None = None) -> RoadmapItem | None:
    """The next thing to build. AUTOTEST_BUILD_ITEM forces a specific id."""
    items = parse_items(path)
    forced = os.environ.get("AUTOTEST_BUILD_ITEM", "").strip()
    if forced:
        for it in items:
            if it.id.lower() == forced.lower():
                return it
        return None
    candidates = [it for it in items if it.actionable]
    candidates.sort(key=_priority)
    return candidates[0] if candidates else None


def directive(item_id: str, status: str) -> str:
    """The commit-message trailer the existing autoupdate reads on push to main."""
    return f"roadmap: {item_id} {status}"
