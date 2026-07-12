"""First-party performance metrics store — the analytics loop's memory (1.14).

The performance loop closes the engine: a club posts an approved card by hand,
then records how it did, and that evidence flows back into the planner's ranking
("spotlights have outperformed recaps for this club — rank more of them"). This
module is the store of those per-post metrics, one JSON file per org under
``DATA_DIR/analytics/<org>.json``.

**Why manual entry (for now).** MediaHub never auto-publishes (standing rule), so
there is no machine path that *posts* a card — and therefore none that could pull
its metrics back automatically. Auto-ingest from the platform APIs is a Phase-4
concern, gated on the publish adapters that do not exist yet. Until then the
honest path is operator entry (``source="manual"``); the ``source`` field and
:func:`record_metric`'s ``source`` argument are the seam an API ingest would use
later. Nothing here fabricates a number.

First-party by construction: no third-party analytics aggregator is involved —
the club owns its numbers, stored beside the rest of its data and tenant-isolated.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from mediahub._atomic_io import atomic_write_text, cross_process_lock

# The engagement signals we track. Deliberately a small, universal set — every
# platform reports some subset; absent ones are simply 0.
METRIC_KEYS = ("impressions", "likes", "comments", "shares", "saves")
MAX_POSTS = 2000

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")
_LOCK = threading.Lock()


@dataclass
class PostMetric:
    """One posted card's measured performance (manually recorded, by default)."""

    id: str
    post_type: str  # canonical post-type slug (what was posted)
    posted_date: str  # ISO YYYY-MM-DD the club posted it
    metrics: dict = field(default_factory=dict)  # subset of METRIC_KEYS → int
    posted_hour: Optional[int] = None  # 0-23 local hour, when known
    archetype: str = ""  # optional design archetype, for finer attribution
    pack_id: str = ""  # optional link back to the draft
    platform: str = ""  # optional platform label
    source: str = "manual"  # "manual" today; "api" is the post-P4 seam
    recorded_at: str = ""

    def dow(self) -> Optional[int]:
        """Day of week (0=Mon … 6=Sun) of the post, or None if the date is bad."""
        try:
            return date.fromisoformat(self.posted_date).weekday()
        except (ValueError, TypeError):
            return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "post_type": self.post_type,
            "posted_date": self.posted_date,
            "metrics": dict(self.metrics),
            "posted_hour": self.posted_hour,
            "archetype": self.archetype,
            "pack_id": self.pack_id,
            "platform": self.platform,
            "source": self.source,
            "recorded_at": self.recorded_at,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sanitise_org(org_id: str) -> str:
    s = _SAFE.sub("_", (org_id or "unknown").strip()) or "unknown"
    return s[:120]


def _path(org_id: str, data_dir: Optional[Path] = None) -> Path:
    base = Path(data_dir) if data_dir is not None else Path(os.environ.get("DATA_DIR", "."))
    d = base / "analytics"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{_sanitise_org(org_id)}.json"


def _clean_metrics(raw: object) -> dict:
    out: dict[str, int] = {}
    if isinstance(raw, dict):
        for k in METRIC_KEYS:
            try:
                v = int(raw.get(k, 0) or 0)
            except (TypeError, ValueError):
                v = 0
            if v < 0:
                v = 0
            if v:
                out[k] = v
    return out


def _clean_date(value: object) -> Optional[str]:
    s = str(value or "").strip()[:10]
    try:
        date.fromisoformat(s)
        return s
    except (ValueError, TypeError):
        return None


def _clean_post(raw: object) -> Optional[PostMetric]:
    if not isinstance(raw, dict):
        return None
    from mediahub.club_platform.post_types import canonical_slug

    slug = canonical_slug(raw.get("post_type"))
    when = _clean_date(raw.get("posted_date"))
    if not slug or not when:
        return None
    hour = raw.get("posted_hour")
    try:
        hour = int(hour) if hour is not None and str(hour) != "" else None
        if hour is not None and not (0 <= hour <= 23):
            hour = None
    except (TypeError, ValueError):
        hour = None
    return PostMetric(
        id=str(raw.get("id") or uuid.uuid4().hex[:12]),
        post_type=slug,
        posted_date=when,
        metrics=_clean_metrics(raw.get("metrics")),
        posted_hour=hour,
        archetype=str(raw.get("archetype") or "").strip()[:60],
        pack_id=str(raw.get("pack_id") or "").strip()[:40],
        platform=str(raw.get("platform") or "").strip()[:40],
        source=str(raw.get("source") or "manual").strip()[:20] or "manual",
        recorded_at=str(raw.get("recorded_at") or ""),
    )


def load_metrics(org_id: str, *, data_dir: Optional[Path] = None) -> list[PostMetric]:
    """Every recorded post metric for the org (missing/corrupt loads empty)."""
    path = _path(org_id, data_dir)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # "missing/corrupt loads empty" (per the module docstring). ValueError
        # covers both json.JSONDecodeError (malformed JSON) and UnicodeDecodeError
        # (a non-UTF-8 file on the durable disk) — both are ValueError subclasses,
        # neither is an OSError, so the narrower (OSError, JSONDecodeError) used to
        # let a non-UTF-8 metrics file escape and 500 /plan/analytics and every
        # analytics API (QA-016; matches inputs.py / planner.py).
        return []
    posts = raw.get("posts") if isinstance(raw, dict) else None
    if not isinstance(posts, list):
        return []
    return [p for p in map(_clean_post, posts) if p]


def _save(org_id: str, posts: list[PostMetric], *, data_dir: Optional[Path] = None) -> None:
    # Atomic write; the caller (record_metric / delete_metric) holds the lock
    # across the whole load -> modify -> save. A non-atomic write here could tear
    # the file, after which load_metrics() returns [] and the next record would
    # overwrite the org's entire metrics history with a single record.
    path = _path(org_id, data_dir)
    payload = json.dumps({"posts": [p.to_dict() for p in posts]}, indent=2, ensure_ascii=False)
    atomic_write_text(path, payload)


def _lock_path(org_id: str, data_dir: Optional[Path] = None) -> Path:
    return _path(org_id, data_dir).with_suffix(".lock")


def record_metric(
    org_id: str,
    post_type: str,
    posted_date: str,
    metrics: dict,
    *,
    posted_hour: Optional[int] = None,
    archetype: str = "",
    pack_id: str = "",
    platform: str = "",
    source: str = "manual",
    data_dir: Optional[Path] = None,
) -> Optional[PostMetric]:
    """Record one post's measured performance. None when the post type/date are
    invalid or the store is full (honest cap, never a silent drop)."""
    rec = _clean_post(
        {
            "post_type": post_type,
            "posted_date": posted_date,
            "metrics": metrics,
            "posted_hour": posted_hour,
            "archetype": archetype,
            "pack_id": pack_id,
            "platform": platform,
            "source": source,
        }
    )
    if rec is None:
        return None
    with _LOCK, cross_process_lock(_lock_path(org_id, data_dir)):
        posts = load_metrics(org_id, data_dir=data_dir)
        if len(posts) >= MAX_POSTS:
            return None
        rec.recorded_at = _now()
        posts.append(rec)
        _save(org_id, posts, data_dir=data_dir)
    return rec


def delete_metric(org_id: str, metric_id: str, *, data_dir: Optional[Path] = None) -> bool:
    with _LOCK, cross_process_lock(_lock_path(org_id, data_dir)):
        posts = load_metrics(org_id, data_dir=data_dir)
        kept = [p for p in posts if p.id != metric_id]
        if len(kept) == len(posts):
            return False
        _save(org_id, kept, data_dir=data_dir)
    return True


def engagement_score(metrics: dict) -> int:
    """A single deterministic engagement number from a metrics dict. Fixed
    weights — comments/shares/saves count for more than a like, impressions are
    reach not engagement and are excluded. Same inputs → same score."""
    m = metrics or {}

    def g(k: str) -> int:
        try:
            return max(0, int(m.get(k, 0) or 0))
        except (TypeError, ValueError):
            return 0

    return g("likes") + 2 * g("comments") + 3 * g("shares") + 2 * g("saves")


__all__ = [
    "PostMetric",
    "METRIC_KEYS",
    "MAX_POSTS",
    "load_metrics",
    "record_metric",
    "delete_metric",
    "engagement_score",
]
