# build_reports

The working logs and evidence reports the autonomous engines keep while they
build and check MediaHub. In plain words: this folder is the engines' shared
notebook — each one writes down what it just did and what to do next, so the
next run (or a human) can pick up where it left off.

What lives here now:

- [`AUTOBUILD_LOG.md`](AUTOBUILD_LOG.md) — the autonomous build engine's
  append-only cycle log and latest handoff.
- [`STRATEGY_LOG.md`](STRATEGY_LOG.md) — the strategy/roadmap engine's log; it
  maintains [`../ROADMAP.md`](../ROADMAP.md).
- [`USABILITY_LOG.md`](USABILITY_LOG.md) and
  [`USABILITY_REGISTER.md`](USABILITY_REGISTER.md) — the daily production
  usability/QA run: the narrative log and the slow-moving register of core
  journeys, defects, and proposals.
- [`GEN_ENGINE_LOG.md`](GEN_ENGINE_LOG.md),
  [`GEN_QUALITY_BASELINE.md`](GEN_QUALITY_BASELINE.md),
  [`SEQ_SPINE_2026-06-10.md`](SEQ_SPINE_2026-06-10.md) — the generation-engine
  v2 build evidence cited by [`../ROADMAP.md`](../ROADMAP.md),
  [`../GENERATION.md`](../GENERATION.md), and ADR-0001.
- [`BLUEPRINT.md`](BLUEPRINT.md) — the original content-engine design
  blueprint; the live V5 detectors in `legacy/` still cite its principles.

Historical one-off build specs and reports (the V2–V9 era, the export
handoffs, the one-time migration audits) were removed in June 2026 — they
described work that shipped long ago. If you ever need one, it's in git
history.
