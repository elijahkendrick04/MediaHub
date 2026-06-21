# Data hub + bulk personalisation (roadmap 1.13)

**Date:** 2026-06-21 · **Scope:** new `data_hub/` + `bulk/` packages, the
`/data-hub` web surface, connector framework · **Status:** shipped in three
sub-builds on one branch → one PR.

## What 1.13 is

MediaHub is structured-data-first — the canonical results store *is* the
spreadsheet. 1.13 turns that store (and the club's own tables) into a
user-facing **data hub** with per-cell provenance, a CSV/XLSX round-trip,
deterministic derived columns, and **review-queued bulk generation**
("certificates for all 47 PB swimmers"). It maps the Canva *Sheets / Sheets AI /
Magic Formulas / Bulk Create / Magic Studio at Scale / Data Connectors* cluster
onto MediaHub's thesis (data in → exact, branded, **approval-gated** content
out) — see `docs/CREATIVE_SUITE_PARITY.md` §1.13.

## How it was built (three sub-builds, one branch)

1. **Data hub core** — `data_hub/models.py` (provenance-stamped table/column/cell),
   `tables.py` (read-only canonical views over the athlete registry, club
   records, and each run's canonical `Meet`), `store.py` (editable org tables,
   org-scoped in SQLite), `portability.py` (deterministic CSV/XLSX import+export
   with ambiguity flagging).
2. **Intelligence** — `derive.py` (registered deterministic derivations +
   `suggest_derivation` that only *proposes* a formula for a human to confirm),
   `scaffold.py` ("a sheet from a prompt" — AI proposes columns, never rows),
   and the `bulk/` package (`bulk_generate` → queues each card into
   `CardStatus.QUEUE`, best-effort renders the format artifact, never approves).
3. **Surface** — the `/data-hub` grid UI (sort/filter/freeze/format, provenance
   badges, import/export, bulk launcher), the JSON API, and the
   `data_hub/connectors/` pull-adapter framework (trust metadata, scheduled
   refresh, a working in-house CSV connector + the flag-gated Swim England
   seam).

## The rules it respects

- **Facts are code; judgement is AI; errors are honest.** Import, derive and
  export are deterministic. The AI only ever *suggests* a derivation or a schema;
  with no provider configured the suggestion surfaces honest
  `ProviderNotConfigured`, never a fabricated column.
- **Flag, never guess.** A cell that doesn't fit its kind is flagged for review
  (the "flag ambiguous rows" rule, made visible as a provenance badge).
- **A human approves before any content is used.** Bulk generation queues every
  card for review; it never approves, posts, or clobbers an existing decision.
- **Multi-tenant isolation.** Every table, job and connector is scoped by
  `profile_id`; one club can never read another's.
- **Deterministic engine untouched.** Parsers/detectors/ranker/colour-science
  are read from, never modified; bulk targets are resolved by fixed filters.

## Tests

89 new tests across `tests/test_data_hub_*.py` and `tests/test_bulk_generate.py`
(models, store + isolation, portability round-trip + flagging, canonical views,
derivations + AI suggest, scaffold, bulk queueing + no-clobber + honest
failures, connectors, and the full web surface). XLSX paths self-skip when
`openpyxl` is absent; AI paths assert the honest-error contract.

## Deferred (by design, with a home)

- **Per-org/per-feature quotas** on bulk → roadmap 1.23 (a safety cap holds now).
- **Insights/analysis** over tables → roadmap 1.11 (charts).
- **Live external connectors** (Swim England Rankings) → founder task F.5; the
  seam is shipped and flag-gated.
- **PDF table print** → rides 1.15's document/PDF suite.
