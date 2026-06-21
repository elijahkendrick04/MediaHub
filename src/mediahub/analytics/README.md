# analytics

The **performance loop** that closes MediaHub's engine (roadmap **1.14**). A club
posts an approved card by hand, records how it did, and that evidence flows back
into the planner's ranking — *"spotlights have outperformed recaps for this club,
so rank more of them"*. The data advantage compounds: the more a club logs, the
sharper its plan.

First-party and honest:

- **The club owns its numbers.** No third-party analytics aggregator — the
  metrics live beside the rest of the club's data, tenant-isolated.
- **Manual entry, for now.** MediaHub never auto-publishes (standing rule), so
  nothing *posts* a card — and nothing can pull its metrics back automatically.
  Auto-ingest from the platform APIs is a **post-P4** concern, gated on the
  publish adapters that don't exist yet. The `source` field is the seam an API
  ingest would use later. Nothing here fabricates a number.

## Files

- `store.py` — per-org metric records under `DATA_DIR/analytics/<org>.json`:
  `record_metric` / `load_metrics` / `delete_metric`, and `engagement_score`
  (fixed weights: `likes + 2·comments + 3·shares + 2·saves`; impressions are
  reach, not engagement).
- `attribution.py` — **deterministic** aggregation (`attribute`): per-type
  average engagement + an index vs the club's own average, plus best day/hour.
  No LLM — same metrics in → same table out, so plans stay reproducible.
- `digest.py` — an **optional** AI gloss (`performance_digest`) that only
  *phrases* the numbers `attribution` already computed: number-guarded (a
  smuggled-in stat is dropped) and honest-errors with `ClaudeUnavailableError`
  when no provider is set. The loop works without it — the planner reads the
  deterministic numbers directly.

## How it feeds the plan

`content_engine.signals.gather_performance_signals` turns each well-sampled
type's index into a source-grounded **own** signal, and the planner applies a
small, bounded, explained nudge (`+8 / −6` max) — fully deterministic, with a
reason line that quotes the numbers. A type needs ≥ `MIN_SAMPLES` posts before it
can move the ranking (one viral post shouldn't rewrite the plan).

Surface: **Plan → Performance** (`/plan/analytics`). Tests:
`tests/test_performance_analytics.py`.
