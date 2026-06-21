"""Deterministic attribution over recorded post metrics (roadmap 1.14).

Turns the raw per-post metrics (``analytics.store``) into the club's performance
picture: which **post types** earn the most engagement, and **when** posts do
best (hour of day / day of week). This is the deterministic half of the
performance loop — fixed weights, plain arithmetic, **no LLM** (CLAUDE.md keeps
scoring deterministic). The planner reads the per-type index from here as another
source-grounded signal; the optional AI *digest* (``analytics.digest``) only
phrases these same computed numbers.

Same metrics in → same table out, so a plan built from it stays reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from mediahub.analytics.store import PostMetric, engagement_score

# A type needs at least this many posts before its index is trusted enough to
# move the plan — one viral post shouldn't rewrite the ranking.
MIN_SAMPLES = 2

_DOW_LABELS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass
class TypePerformance:
    """One post type's measured performance, relative to the org's own average."""

    post_type: str
    n: int
    avg_engagement: float
    index: float  # avg_engagement / overall mean (1.0 = average; >1 outperforms)

    def to_dict(self) -> dict:
        return {
            "post_type": self.post_type,
            "n": self.n,
            "avg_engagement": round(self.avg_engagement, 1),
            "index": round(self.index, 2),
        }


@dataclass
class Attribution:
    """The whole performance picture for one org."""

    n_posts: int
    overall_mean: float
    by_type: list[TypePerformance] = field(default_factory=list)
    best_hour: Optional[int] = None
    best_dow: Optional[int] = None

    def type_index(self) -> dict[str, TypePerformance]:
        return {t.post_type: t for t in self.by_type}

    def best_dow_label(self) -> str:
        return _DOW_LABELS[self.best_dow] if self.best_dow is not None else ""

    def to_dict(self) -> dict:
        return {
            "n_posts": self.n_posts,
            "overall_mean": round(self.overall_mean, 1),
            "by_type": [t.to_dict() for t in self.by_type],
            "best_hour": self.best_hour,
            "best_dow": self.best_dow,
            "best_dow_label": self.best_dow_label(),
        }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def attribute(metrics: list[PostMetric]) -> Attribution:
    """Aggregate per-post metrics into the deterministic performance picture."""
    posts = [m for m in metrics if m is not None]
    if not posts:
        return Attribution(n_posts=0, overall_mean=0.0)

    scores = [engagement_score(m.metrics) for m in posts]
    overall_mean = _mean(scores)

    # Per type — average engagement and an index vs the org's overall mean.
    by_type_scores: dict[str, list[float]] = {}
    for m, s in zip(posts, scores):
        by_type_scores.setdefault(m.post_type, []).append(s)
    by_type: list[TypePerformance] = []
    for slug, vals in by_type_scores.items():
        avg = _mean(vals)
        idx = (avg / overall_mean) if overall_mean > 0 else 1.0
        by_type.append(TypePerformance(post_type=slug, n=len(vals), avg_engagement=avg, index=idx))
    # Highest index first; ties broken by sample count then slug for stability.
    by_type.sort(key=lambda t: (-t.index, -t.n, t.post_type))

    # Best hour / day of week — only from posts that carry the timing, and only
    # when there is a real sample (else honest None, no fabricated "best time").
    best_hour = _best_bucket([(m.posted_hour, s) for m, s in zip(posts, scores)])
    best_dow = _best_bucket([(m.dow(), s) for m, s in zip(posts, scores)])

    return Attribution(
        n_posts=len(posts),
        overall_mean=overall_mean,
        by_type=by_type,
        best_hour=best_hour,
        best_dow=best_dow,
    )


def _best_bucket(pairs: list[tuple[Optional[int], float]]) -> Optional[int]:
    """The bucket key (hour or dow) with the highest mean score, or None when no
    post carries that timing. Deterministic tie-break: lowest key wins."""
    buckets: dict[int, list[float]] = {}
    for key, score in pairs:
        if key is None:
            continue
        buckets.setdefault(int(key), []).append(score)
    if not buckets:
        return None
    return min(buckets, key=lambda k: (-_mean(buckets[k]), k))


__all__ = [
    "Attribution",
    "TypePerformance",
    "MIN_SAMPLES",
    "attribute",
]
