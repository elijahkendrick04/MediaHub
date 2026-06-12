# Seasonal qualifying-time packs (W.4)

**In plain words.** Each season, counties / regions / national bodies publish
qualifying times ("QTs") as public PDFs. This folder holds those tables as
small JSON files, one folder per season, so "Qualified for Counties!" cards
can fire with a named, dated source. Times are facts; every table cites the
PDF it was copied from and when.

## Layout

```
data/standards/
  README.md                ← this runbook
  2026-27/
    _template.example.json ← copy this to start a new table (never loaded)
    <body>_<comp>.json     ← one curated table per competition
```

Files ending `.example.json` are templates and are **never loaded**.
Everything else under a season folder is loaded by
`mediahub.standards.load_standard_packs()` and merged with the legacy
`data/quals.json` registry (duplicate ids: first one wins, quals.json first).

## Schema

Identical to `data/quals.json` — `{"version": 1, "standards": [...]}` where
each standard carries: `id` (stable, e.g. `WALES_LC_2026_27_NATIONALS`),
`competition`, `body`, `level` (`county` / `regional` / `national` /
`university`), `course` (`LC`/`SC`), `season`, `window_start`/`window_end`
(when the time must have been swum), `venue`, `event_dates`, **`source_url`
(the published PDF — required)**, **`retrieved_at` (curation date —
required)**, `confidence`, `importance_score`, `relevance_clubs` (`["*"]`
for everyone), `notes`, and `times`
(`[{"event": "100_FR", "gender": "F", "ct": "1:10.00"}, ...]`).

## Seasonal refresh runbook

1. When a body publishes next season's QTs (usually a PDF), download it and
   note the URL.
2. Copy `_template.example.json` to `<season>/<body>_<competition>.json`.
3. Transcribe the times **exactly** — never round, never infer a missing
   event. If a cell is unreadable, omit that event and say so in `notes`.
4. Fill `source_url` + `retrieved_at` (today, ISO). These are what the card's
   provenance line shows; a table without them must not ship.
5. `python -m pytest tests/test_standards_packs.py -q` — the loader test
   validates the file parses and ids don't collide.
6. Clubs then tick the new standards in **Organisation → Qualifying
   standards**; nothing is auto-enabled.

Standards older than 60 days re-surface as "stale" through the existing
freshness logic (`quals_registry.FRESHNESS_DAYS`) — that's the prompt to
re-verify against the source each season, not an error.

US expansion note: USA Swimming motivational times are official free PDFs on
a fixed 4-year cycle — same schema, same runbook, when that market opens.
