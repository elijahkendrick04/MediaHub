# 25. Accumulating PB-history baseline (the scalable "is this a PB?" source)

- **Status:** Accepted (maintainer directive, 2026-06-19).
- **Date:** 2026-06-19
- **Deciders:** MediaHub maintainer. Explicit directives, in order: *"improve the
  speed and efficiency of the PB finder by ten fold … the results also have to
  improve"*; *"it found 0 pbs, which isnt true"*; *"I dont want it to find pbs
  from seed times ever … make sure that the pb lookup actually works … super
  powerful and accurate"*; *"will this work [at] scale [for] anyone … whenever
  they like"*; *"Dont build in a paid version api"*.

## Context

The PB finder reported **0 PBs** for meets full of them, and was slow. Root
cause: "is this a PB?" depended entirely on a **per-swimmer live web lookup**
(`pb_discovery`). In production the free search backend is throttled to zero, so
there was no prior-best baseline → every swim failed PB detection while still
spending the network time.

Two rejected stop-gaps:

1. **Infer PBs from the file's entry/seed time** (a swim faster than its seed).
   Tried on this branch, then **rejected by the maintainer**: seed times are
   unreliable (soft / converted / "NT" entries), so this risks *false* PBs — and
   a wrong PB is worse than a missing one. The seed-based `PBLikelyDetector` was
   removed from the V5 registry.
2. **Self-host SearXNG** for search. Rejected for a public product: SearXNG is a
   scraping *proxy* with no index of its own; at "anyone-anytime" volume it gets
   rate-limited/blocked by the upstream engines it scrapes — it relocates the
   "returns 0" wall onto infra we operate. (See research: Brave killed its free
   API tier Feb 2026; Google CSE is closed to new customers.)

## Decision

Make the **club's own accumulating results history** the primary PB baseline.

- Every uploaded results file feeds a per-tenant best-times store
  (`src/mediahub/pb_history/`, SQLite at `DATA_DIR/pb_history.db`). "Is this a
  PB?" becomes a **local lookup against the swimmer's real earlier swims** —
  deterministic, instant, network-free, and more accurate every upload. Returning
  swimmers never touch the web, so it scales to a public product. This is **not**
  seed-time inference: every stored time is a real swum result.
- The store builds the existing `BridgedSnapshot` shape, so the unchanged
  deterministic detectors (`pb_confirmed` / `official_pb_confirmed`) fire from
  it. Correctness invariants: fastest-within-a-meet kept; the current meet is
  **excluded** from its own baseline; re-uploads are idempotent; every row and
  query is **tenant-scoped** (no cross-club leakage).
- Cross-upload **swimmer identity** is conservative — normalised name + club +
  year of birth; when uncertain, a swimmer is treated as new (a missed PB, never
  a wrong one).
- **Web discovery becomes a cold-start bootstrap only** — run for swimmers with
  no local history yet, via **free** search backends. Per the maintainer, **no
  paid search API is integrated.** Recommended free default for the bootstrap is
  a pluggable provider (e.g. TinyFish's free tier) with DuckDuckGo/SearXNG
  fallback; that wiring is a separate, follow-up increment.

## Consequences

- **Speed:** the slow per-swimmer web phase stops being the bottleneck; for
  returning swimmers PBs are computed in the normal recognition pass with no
  network. The cold-start research set shrinks toward zero as history fills in.
- **Accuracy / honesty:** PBs are asserted only against real prior results. A
  brand-new club's *first* upload still shows no PBs until the bootstrap (or the
  second upload) provides a baseline — which is the honest answer.
- **Data model:** a new per-tenant store under `DATA_DIR`. Multi-tenant isolation
  and audit (date + meet of each stored best) are first-class, matching the
  data-model direction in `CLAUDE.md`. It participates in the existing
  `DATA_DIR` backup/retention story.
- **Privacy:** the store holds the same athlete result data already processed per
  run, scoped per tenant; it is covered by the existing retention/erasure paths
  for `DATA_DIR` data.
