"""analytics — the first-party performance loop (roadmap 1.14).

Closes the engine: a club posts an approved card by hand, records how it did,
and that evidence flows back into the planner's ranking ("spotlights have
outperformed recaps for this club — rank more of them"). All first-party — the
club owns its numbers, no third-party aggregator.

- ``store`` — per-org metric records (``DATA_DIR/analytics/<org>.json``).
  Manual entry today; auto-ingest from the platform APIs is the post-P4 seam
  (MediaHub never auto-publishes, so nothing can pull metrics back yet).
- ``attribution`` — deterministic aggregation: which post types earn the most
  engagement and when posts do best. No LLM — the planner reads this as another
  source-grounded signal, so plans stay reproducible.
- ``digest`` — optional AI gloss that only *phrases* the computed numbers
  (number-guarded, honest-errors without a provider). The loop works without it.
"""

from .attribution import Attribution, TypePerformance, attribute
from .digest import performance_digest
from .store import (
    METRIC_KEYS,
    PostMetric,
    delete_metric,
    engagement_score,
    load_metrics,
    record_metric,
)

__all__ = [
    "Attribution",
    "METRIC_KEYS",
    "PostMetric",
    "TypePerformance",
    "attribute",
    "delete_metric",
    "engagement_score",
    "load_metrics",
    "performance_digest",
    "record_metric",
]
