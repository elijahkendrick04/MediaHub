# V7.5 — Interpreter Hardening (round 2)

## Context
Round 1 interpreter passes synthetic fixtures (7/7 tests). Real-world corpus eval (44 captured docs) shows 75% recovery — below the ≥90% target. Specific failure modes surfaced:

- **HTML framesets** (3 docs): SPORTSYSTEMS / `RG*.HTM` style — `results.html` is just a `<frameset>` shell pointing at `before.htm` / `main.htm` / per-event `RG*.HTM`. The interpreter has to **follow framesets** or **aggregate sibling HTML files** in the same directory.
- **Hytek-style PDFs** (5+ docs, including the Swansea Aquatics May LC 2025 our user cares about): row data is split across **multiple visual lines**. Place+name on line N, split times on lines N+1..N+3. Currently each visual line is treated as a separate row, so column induction misses everything.
- **Bristol L1 / L3 / NDA Sprint / Sasa North R1 / UoA Autumn**: events detected (~85-289) but 0 swims — the column-header row isn't being found because column headers may be far from event header, or layout is multi-column in a way the current schema-induction doesn't handle.

## Eval report
`/home/user/workspace/swim-content/samples/learning_corpus/EVAL_REPORT.csv` — 44 rows with per-doc events/swims/confidence/error.

## Goal
Get the corpus eval to **≥90% recovery** (≥40/44 docs producing ≥1 swim) and **mean confidence ≥0.65**, without losing any current passes.

## Required fixes

### 1. Frameset follow-through (HTML)
In `interpreter/ingest.py`, when extracting HTML:
- If the document is a `<frameset>` with no body content, parse `<frame src="...">` URLs.
- If those URLs are relative (e.g. `before.htm`), check the **same directory** as the input file. If we don't know the input file path (bytes-only API), we can't follow — so introduce a NEW optional parameter `source_path: Path | None = None` on `interpret_document()` that lets callers pass the file path. When provided AND the HTML is a frameset, recursively load each sibling HTML file referenced by the frameset, concatenate the streams.
- Even better: when given a directory path or a `results.html` that's a frameset, **also automatically include sibling `*.htm`/`*.HTM` files** that look like SPORTSYSTEMS event pages (heuristic: filename matches `^[A-Z]+\d+H?\d*\.HTM$` or contains `<title>...Female|Male...m...</title>`).

### 2. Multi-line row grouping (PDFs)
In `interpreter/rows.py`, before extracting rows:
- Detect the "Hytek printout" pattern: a line with a place number and almost no other content, followed by 1+ lines containing only time-shaped tokens at numeric x-positions.
- **Group these lines into one logical row**. The place number anchors the row; subsequent split-time lines attach to it.
- Also handle the case where the swimmer name wraps: place + name + age + club on row 1, time on row 2.

Strategy: introduce a **row-grouping pass** between ingest and schema-induction. Group consecutive lines whose y-positions are close AND whose first non-blank token isn't a new place number / event header / blank. The grouped block becomes a single "logical line" for downstream stages.

### 3. Header row detection robustness
In `interpreter/schema_induce.py`:
- The current `_find_best_header_row()` works on synthetic data but fails on real PDFs where:
  - Event header and column header are on adjacent lines and confusable
  - Column header line has trailing whitespace columns that match nothing
  - Column header words are split across multiple lines (e.g., "Finals\nTime")
- Improvements:
  - Allow column-header detection to span 2 consecutive lines (look at concat of line N + line N+1).
  - Don't require ALL columns to be present in headers — accept partial header matches and infer remaining columns from the data rows themselves (regex-family detection on actual data).
  - When header detection fails entirely, **fall back to header-less mode**: detect columns purely from the data (regex families per column position).

### 4. Pure-data column detection (header-less mode)
Add a fallback in `schema_induce.py`:
- If header-row confidence < 0.4, induce columns purely from data rows.
- For each candidate row, tokenise into runs of non-whitespace characters with their x-positions.
- Cluster x-positions across rows; each cluster is a column.
- Identify column type by majority regex-family vote across the rows.

This unlocks PDFs where the column header is missing or unrecognisable.

### 5. Tests
Update `tests_v75/test_interpreter_smoke.py` (or add `test_interpreter_corpus.py`):
- Add 3 new synthetic fixtures:
  - Hytek-style multi-line row PDF
  - Frameset HTML pointing to siblings
  - Column-header-less PDF with pure-data column detection
- All must pass.

Add `tests_v75/test_corpus_recovery.py`:
- Read `samples/learning_corpus/INDEX.csv`, run interpreter on all `status=captured` rows.
- Assert: ≥90% docs yield ≥1 swim, mean confidence ≥0.65, total swims ≥30000 (currently 24763).
- Skip docs with format `none` or `image`-only.

Run `python3 scripts/eval_corpus.py` after changes; aim to beat the current numbers.

### 6. Pattern persistence
When the new strategies (multi-line grouping, header-less mode, frameset follow) succeed, persist the pattern shape to `data/patterns.jsonl` so future docs of the same shape parse faster.

## Constraints
- Keep existing 217 tests passing.
- ZERO hardcoded swim vocabulary in interpreter/*.py — all new vocabulary still goes in `data/ontology/*.json`.
- ZERO hardcoded source domains.
- Anti-shortcut: do NOT special-case Hytek or SPORTSYSTEMS by name. Use shape detection (e.g., "this looks like a frameset" or "rows have only place + split times") not brand detection.

## Deliverable
- Updated `interpreter/` with fixes
- New tests passing
- `python3 scripts/eval_corpus.py` reaches ≥90% recovery, mean conf ≥0.65
- Updated `INTERPRETER_BUILD_REPORT.md` with the new corpus numbers
